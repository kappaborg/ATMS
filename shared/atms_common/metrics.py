"""
MetricsRecorder protocol.

A thin abstraction over Prometheus client so the failsafe controller can be
unit-tested with an in-memory recorder, then wired to prometheus_client in
production. Phase B (B2) will extend this with OpenTelemetry-native metrics
where appropriate.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Protocol

Labels = Mapping[str, str]


class MetricsRecorder(Protocol):
    def inc(self, name: str, value: float = 1.0, labels: Labels | None = None) -> None: ...

    def set_gauge(self, name: str, value: float, labels: Labels | None = None) -> None: ...


def _key(labels: Labels | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted(labels.items()))


class InMemoryMetrics:
    """Test double. Records counters and gauges in nested dicts."""

    def __init__(self) -> None:
        self.counters: dict[str, dict[tuple[tuple[str, str], ...], float]] = defaultdict(dict)
        self.gauges: dict[str, dict[tuple[tuple[str, str], ...], float]] = defaultdict(dict)

    def inc(self, name: str, value: float = 1.0, labels: Labels | None = None) -> None:
        k = _key(labels)
        self.counters[name][k] = self.counters[name].get(k, 0.0) + value

    def set_gauge(self, name: str, value: float, labels: Labels | None = None) -> None:
        self.gauges[name][_key(labels)] = value

    def counter(self, name: str, labels: Labels | None = None) -> float:
        return self.counters[name].get(_key(labels), 0.0)

    def gauge(self, name: str, labels: Labels | None = None) -> float:
        return self.gauges[name].get(_key(labels), 0.0)


class PrometheusMetrics:
    """
    Production MetricsRecorder backed by prometheus_client.

    Imported lazily so unit tests do not require the dependency.
    """

    def __init__(self) -> None:
        # Lazy import keeps prometheus_client out of the unit-test dependency set.
        from prometheus_client import (  # noqa: PLC0415
            Counter,
            Gauge,
        )

        self._Counter = Counter
        self._Gauge = Gauge
        self._counters: dict[str, object] = {}
        self._gauges: dict[str, object] = {}

    def _counter_for(self, name: str, labels: Labels | None):
        if name not in self._counters:
            label_names = tuple(sorted((labels or {}).keys()))
            self._counters[name] = self._Counter(name, name, labelnames=label_names)
        return self._counters[name]

    def _gauge_for(self, name: str, labels: Labels | None):
        if name not in self._gauges:
            label_names = tuple(sorted((labels or {}).keys()))
            self._gauges[name] = self._Gauge(name, name, labelnames=label_names)
        return self._gauges[name]

    def inc(self, name: str, value: float = 1.0, labels: Labels | None = None) -> None:
        c = self._counter_for(name, labels)
        if labels:
            c.labels(**labels).inc(value)
        else:
            c.inc(value)

    def set_gauge(self, name: str, value: float, labels: Labels | None = None) -> None:
        g = self._gauge_for(name, labels)
        if labels:
            g.labels(**labels).set(value)
        else:
            g.set(value)
