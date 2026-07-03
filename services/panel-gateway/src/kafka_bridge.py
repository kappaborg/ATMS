"""
Optional Kafka bridge: consume the ATMS `decisions` topic into SystemState.

Runs only when KAFKA_BOOTSTRAP_SERVERS is set. Failure to connect is
non-fatal — the panel keeps working on local estimates and simply reports the
system stream as unavailable.
"""
from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger("panel.kafka")


async def run_decisions_consumer(bootstrap: str, system, stop: asyncio.Event) -> None:
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        log.warning("aiokafka not installed; system (controller) stream disabled")
        return

    while not stop.is_set():
        consumer = AIOKafkaConsumer(
            "decisions",
            bootstrap_servers=bootstrap,
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            auto_offset_reset="latest",
            group_id="panel-gateway",
            enable_auto_commit=True,
        )
        try:
            await consumer.start()
        except Exception as e:  # noqa: BLE001 — broker may be down; retry
            log.warning("decisions consumer connect failed (%s); retrying in 5s", e)
            await asyncio.sleep(5)
            continue
        system.connected = True
        log.info("connected to decisions topic at %s", bootstrap)
        try:
            async for msg in consumer:
                if stop.is_set():
                    break
                system.on_decision(msg.value)
        except Exception as e:  # noqa: BLE001
            log.warning("decisions consumer error (%s); reconnecting", e)
        finally:
            system.connected = False
            await consumer.stop()
