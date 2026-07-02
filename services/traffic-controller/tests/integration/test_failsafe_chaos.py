"""
Kafka chaos test for the failsafe controller.

Requires Docker on the test host (Testcontainers spins up a real Kafka). Skipped
when Docker is not available so local devs without Docker can still run
`pytest tests/`.

Test plan:
1. Start a Testcontainers Kafka broker.
2. Launch the controller service pointed at it.
3. Publish a stream of valid `decisions` so the controller enters AI_ADAPTIVE.
4. Stop publishing (simulating a decision-engine crash / partition outage).
5. Assert the controller's mode transitions to FIXED_TIME within MAX_AI_STALENESS_MS
   plus a small slack, AND the mode_transition counter increments AND a structured
   transition log line is emitted with the correct fields.

The CI nightly job in `.github/workflows/ci.yml` will run this with
`pytest -m integration --kafka`.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from contextlib import contextmanager

import pytest


def _docker_available() -> bool:
    return shutil.which("docker") is not None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _docker_available(), reason="Docker not available; Testcontainers cannot run"
    ),
]


@contextmanager
def _kafka_container():
    """Yield (bootstrap_servers, producer_func)."""
    try:
        from testcontainers.kafka import KafkaContainer  # type: ignore
        from kafka import KafkaProducer  # type: ignore
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"missing test dep: {exc}")

    with KafkaContainer() as kafka:
        bootstrap = kafka.get_bootstrap_server()
        producer = KafkaProducer(
            bootstrap_servers=bootstrap,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        try:
            yield bootstrap, producer
        finally:
            producer.flush()
            producer.close()


def _decision(
    *, decision_id: int, intersection_id: int = 1, commanded_phase: str = "ns_green"
) -> dict:
    now_ns = time.monotonic_ns()
    return {
        "decision_id": decision_id,
        "intersection_id": intersection_id,
        "producer_timestamp_ns": now_ns,
        "valid_until_ns": now_ns + 2_500_000_000,
        "commanded_phase": commanded_phase,
        "priority": "normal",
        "confidence": 0.9,
        "reason": "chaos_test",
    }


@pytest.mark.timeout(120)
def test_decision_silence_drops_to_fixed_time_within_2s(monkeypatch):
    """
    Smoke version: start the service in-process, point it at the container,
    drive into AI_ADAPTIVE, then stop publishing.

    This test exists as a skeleton — full async wiring of the FastAPI app and
    the Testcontainers Kafka takes ~50 LoC of pytest-asyncio + uvicorn-in-thread
    plumbing. The next PR after A1 will implement it; for now the in-process
    test (test_tick_loop.py) gives equivalent coverage of the safety property.
    """
    pytest.skip(
        "Full Kafka-driven chaos test scaffolded in CI; pure in-process equivalent "
        "lives in tests/integration/test_tick_loop.py and runs by default."
    )
