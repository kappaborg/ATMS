"""
Kafka producer + consumer wrappers — Phase B1.

Replaces the bespoke `start_kafka` / `stop_kafka` / `consume_messages`
patterns in each service with a consistent shape:

    producer = AtmsKafkaProducer(bootstrap_servers="localhost:9092")
    await producer.start()
    await producer.send("decisions", value={"decision_id": 1, ...})
    await producer.stop()

    consumer = AtmsKafkaConsumer(
        bootstrap_servers="localhost:9092",
        topics=("decisions",),
        group_id="traffic-controller",
        handler=on_decision,                # async (msg_value) -> None
        dlq_topic="decisions.dlq",
    )
    await consumer.start()
    await consumer.run_forever()

Defaults:
- Producer: idempotent (`enable_idempotence=True`), waits for all-replica ack.
- Consumer: manual offset commit AFTER successful handler, dead-letter on
  persistent handler failure.

Real circuit-breaker + retries-with-backoff are Phase B4. This module surfaces
the failure types so B4 has a clean injection point.

See ADR-0008.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from shared.atms_common.errors import KafkaError
from shared.atms_common.resilience import (
    CircuitBreaker,
    Retry,
    with_timeout,
)
from shared.atms_common.tracing import (
    extract_kafka_headers,
    inject_kafka_headers,
    start_span,
)

try:
    from opentelemetry import context as otel_context

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    otel_context = None

try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    from aiokafka.errors import KafkaError as _AioKafkaError

    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    AIOKafkaConsumer = None
    AIOKafkaProducer = None
    _AioKafkaError = Exception


log = logging.getLogger(__name__)


# Handler signature: receive the deserialised value and a metadata dict.
# Return None on success. Raise anything else to trigger DLQ (or retry).
HandlerFn = Callable[[Any], Awaitable[None]]


def _require_kafka() -> None:
    if not KAFKA_AVAILABLE:
        raise KafkaError("aiokafka is not installed in this environment")


class AtmsKafkaProducer:
    """
    Idempotent JSON producer. Async lifecycle (`start` / `stop`).
    """

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        client_id: str = "atms",
        request_timeout_ms: int = 5_000,
        send_timeout_s: float = 2.0,
        breaker: CircuitBreaker | None = None,
        retry: Retry | None = None,
    ) -> None:
        _require_kafka()
        self._bootstrap = bootstrap_servers
        self._client_id = client_id
        self._request_timeout_ms = request_timeout_ms
        self._send_timeout_s = send_timeout_s
        # Phase B4: hardened send composition. Defaults bound the producer
        # to the failsafe staleness budget. Operators can inject custom
        # breakers / retries for tests or non-default behaviour.
        self._breaker = breaker or CircuitBreaker(
            name=f"kafka_send.{client_id}",
            failure_threshold=5,
            reset_timeout_s=30,
        )
        self._retry = retry or Retry(
            name=f"kafka_send.{client_id}",
            attempts=3,
            base_delay_s=0.1,
            max_delay_s=1.0,
            retry_on=(KafkaError,),
        )
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap,
            client_id=self._client_id,
            request_timeout_ms=self._request_timeout_ms,
            enable_idempotence=True,
            acks="all",
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda v: None if v is None else str(v).encode("utf-8"),
        )
        await self._producer.start()
        log.info("AtmsKafkaProducer started", extra={"bootstrap": self._bootstrap})

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def send(self, topic: str, *, value: Any, key: str | None = None) -> None:
        producer = self._producer
        if producer is None:
            raise KafkaError("producer not started")

        # Phase B2: inject the current trace context into Kafka headers so the
        # consumer can continue the trace.
        headers = inject_kafka_headers()

        async def _do_send() -> None:
            try:
                with start_span(
                    f"kafka.send.{topic}",
                    attributes={
                        "messaging.system": "kafka",
                        "messaging.destination": topic,
                        "messaging.kafka.message_key": str(key) if key else "",
                    },
                ):
                    await with_timeout(
                        producer.send_and_wait(topic, value=value, key=key, headers=headers),
                        timeout_s=self._send_timeout_s,
                        name=f"kafka_send.{topic}",
                    )
            except _AioKafkaError as e:
                raise KafkaError(f"send to {topic} failed: {e}") from e

        await self._breaker.call(lambda: self._retry.call(_do_send))

    @property
    def underlying(self) -> AIOKafkaProducer | None:
        """Escape hatch for the health-check or a B4 circuit breaker."""
        return self._producer


class AtmsKafkaConsumer:
    """
    Consumer with manual offset commit and dead-letter on persistent failure.
    """

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        topics: Iterable[str],
        group_id: str,
        handler: HandlerFn,
        dlq_topic: str | None = None,
        auto_offset_reset: str = "latest",
        retry_attempts: int = 3,
    ) -> None:
        _require_kafka()
        self._bootstrap = bootstrap_servers
        self._topics = tuple(topics)
        self._group_id = group_id
        self._handler = handler
        self._dlq_topic = dlq_topic
        self._auto_offset_reset = auto_offset_reset
        self._retry_attempts = retry_attempts
        self._consumer: AIOKafkaConsumer | None = None
        self._dlq_producer: AtmsKafkaProducer | None = None
        self._run_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._bootstrap,
            group_id=self._group_id,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset=self._auto_offset_reset,
            enable_auto_commit=False,
        )
        await self._consumer.start()
        if self._dlq_topic is not None:
            self._dlq_producer = AtmsKafkaProducer(
                bootstrap_servers=self._bootstrap, client_id=f"{self._group_id}-dlq"
            )
            await self._dlq_producer.start()
        log.info(
            "AtmsKafkaConsumer started",
            extra={"topics": self._topics, "group_id": self._group_id},
        )

    async def stop(self) -> None:
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()
            try:
                await self._run_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None
        if self._dlq_producer is not None:
            await self._dlq_producer.stop()
            self._dlq_producer = None

    async def run_forever(self) -> None:
        """Consume messages until cancelled. Internally retries handler errors."""
        if self._consumer is None:
            raise KafkaError("consumer not started")
        async for msg in self._consumer:
            # Phase B2: extract parent trace context from message headers and
            # run the handler inside a child span.
            parent_ctx = extract_kafka_headers(getattr(msg, "headers", None))
            token = (
                otel_context.attach(parent_ctx)
                if OTEL_AVAILABLE and otel_context is not None
                else None
            )
            try:
                with start_span(
                    f"kafka.consume.{msg.topic}",
                    attributes={
                        "messaging.system": "kafka",
                        "messaging.destination": msg.topic,
                        "messaging.kafka.partition": getattr(msg, "partition", -1),
                        "messaging.kafka.offset": getattr(msg, "offset", -1),
                    },
                ):
                    handled = await self._handle_with_retry(msg.value, msg.topic)
            finally:
                if token is not None and otel_context is not None:
                    otel_context.detach(token)
            if handled:
                await self._consumer.commit()
            elif self._dlq_topic is not None and self._dlq_producer is not None:
                # Persistent failure: dead-letter, then commit so we don't loop.
                try:
                    await self._dlq_producer.send(
                        self._dlq_topic,
                        value={
                            "original_topic": msg.topic,
                            "original_value": msg.value,
                            "partition": msg.partition,
                            "offset": msg.offset,
                        },
                        key=str(msg.offset),
                    )
                    await self._consumer.commit()
                except KafkaError as e:
                    log.error("DLQ send failed; leaving offset un-committed: %s", e)
                    # Block here — operator must intervene.
                    raise
            else:
                # No DLQ configured and handler still failing.
                # Leave the offset un-committed so the next consumer poll re-reads.
                # The error is logged; operator must intervene.
                log.error("handler persistently failing with no DLQ; leaving offset uncommitted")
                return

    @property
    def underlying(self) -> AIOKafkaConsumer | None:
        return self._consumer

    # ------------------------------------------------------------------

    async def _handle_with_retry(self, value: Any, topic: str) -> bool:
        """True if handler succeeded; False after retries exhausted.

        Phase B4: use the shared Retry primitive — proper exponential backoff
        + jitter instead of the original tight-loop retry.
        """
        retry = Retry(
            name=f"kafka_handler.{topic}",
            attempts=self._retry_attempts,
            base_delay_s=0.1,
            max_delay_s=2.0,
            retry_on=(Exception,),
        )
        try:
            await retry.call(self._handler, value)
            return True
        # Boundary case (errors.py): consumer loops are one of the few
        # legitimate places a bare Exception is caught — we route the
        # failure to retry / DLQ rather than crashing the loop.
        except Exception as e:
            log.warning("handler exhausted retries on topic=%s: %s", topic, e)
            return False
