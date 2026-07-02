"""Prometheus metrics exporter — production observability.

Background HTTP server on a configurable port exposes the chamber's
decision metrics in standard Prometheus text format. Any Prometheus
instance (or compatible scraper: VictoriaMetrics, Mimir, Cortex) can
add a scrape job:

    scrape_configs:
      - job_name: 'atms-decision-chamber'
        scrape_interval: 15s
        static_configs:
          - targets: ['intersection-001.atms.city:9090', ...]

From there: Grafana dashboards, alerting, A/B comparison, long-term
storage — all standard ops tooling.

Metrics exposed (per ATMS naming convention `atms_chamber_<metric>`):

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| atms_chamber_decisions_total | counter | intersection, mode, dominant | every chamber decision |
| atms_chamber_phase_transitions_total | counter | intersection, from, to | phase changes |
| atms_chamber_preemptions_total | counter | intersection, source | emergency preempts |
| atms_chamber_pedestrian_phases_total | counter | intersection, direction | served ped phases |
| atms_chamber_seconds_in_phase | gauge | intersection, phase | current phase elapsed |
| atms_chamber_priority_score | gauge | intersection, direction | last L3 score per direction |
| atms_chamber_emission_g_per_min | gauge | intersection, direction | instantaneous CO2 rate |
| atms_chamber_vehicle_count | gauge | intersection, direction | queue size |
| atms_chamber_tick_duration_seconds | histogram | intersection | tick processing time |

For Phase 3 MVP we implement the counters + gauges. Histogram is
Phase 4 (requires careful bucket selection per deployment).
"""

from __future__ import annotations

import http.server
import logging
import socket
import threading
from collections import defaultdict
from typing import Any

log = logging.getLogger("atms.chamber.metrics")


class PrometheusMetrics:
    """Thread-safe metric collector + HTTP exposition. Drop-in for any
    Prometheus-compatible scraper. Designed to coexist with the
    operator-console state JSON — both are consumers of the same
    decision stream, neither is the source of truth (the audit log is).
    """

    def __init__(
        self,
        intersection_id: str,
        listen_host: str = "0.0.0.0",
        listen_port: int = 9090,
    ):
        self._intersection = intersection_id
        self._lock = threading.Lock()
        # counters: {(metric_name, label_tuple): float}
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = (
            defaultdict(float)
        )
        # gauges: {(metric_name, label_tuple): float}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._port = listen_port
        self._host = listen_host
        self._server: http.server.HTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._start_server()

    # ------------- Public metric APIs --------------------------------

    def increment(self, name: str, **labels: str) -> None:
        labels.setdefault("intersection", self._intersection)
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            self._counters[key] += 1.0

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        labels.setdefault("intersection", self._intersection)
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            self._gauges[key] = value

    # ------------- HTTP server ---------------------------------------

    def _render(self) -> bytes:
        with self._lock:
            counters = list(self._counters.items())
            gauges = list(self._gauges.items())

        lines: list[str] = [
            "# ATMS Decision Chamber metrics",
            "# https://prometheus.io/docs/instrumenting/exposition_formats/",
            "",
        ]
        # Group by metric name so each gets a single HELP + TYPE
        by_name_counter: dict[str, list[tuple[tuple, float]]] = defaultdict(list)
        for (name, labels), val in counters:
            by_name_counter[name].append((labels, val))
        for name, samples in sorted(by_name_counter.items()):
            lines.append(f"# HELP {name} {name.replace('_', ' ').strip()}")
            lines.append(f"# TYPE {name} counter")
            for labels, val in samples:
                lines.append(f"{name}{_fmt_labels(labels)} {val}")

        by_name_gauge: dict[str, list[tuple[tuple, float]]] = defaultdict(list)
        for (name, labels), val in gauges:
            by_name_gauge[name].append((labels, val))
        for name, samples in sorted(by_name_gauge.items()):
            lines.append(f"# HELP {name} {name.replace('_', ' ').strip()}")
            lines.append(f"# TYPE {name} gauge")
            for labels, val in samples:
                lines.append(f"{name}{_fmt_labels(labels)} {val}")

        return ("\n".join(lines) + "\n").encode("utf-8")

    def _start_server(self) -> None:
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (HTTP convention)
                if self.path != "/metrics":
                    self.send_response(404)
                    self.end_headers()
                    return
                body = owner._render()
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "text/plain; version=0.0.4; charset=utf-8",
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                # Quiet — we don't want every scrape in stderr.
                pass

        try:
            server = http.server.HTTPServer((self._host, self._port), Handler)
        except OSError as e:
            log.warning(
                "metrics server failed to bind %s:%d — %s (metrics disabled)",
                self._host, self._port, e,
            )
            return
        self._server = server
        self._server_thread = threading.Thread(
            target=server.serve_forever, daemon=True
        )
        self._server_thread.start()
        log.info(
            "metrics exposed at http://%s:%d/metrics",
            self._host, self._port,
        )

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()


def _fmt_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    parts = [f'{k}="{_escape(str(v))}"' for k, v in labels]
    return "{" + ",".join(parts) + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def find_free_port(start: int = 9090, attempts: int = 10) -> int:
    """Helper for dev environments — if 9090 is taken, look for a higher one."""
    for offset in range(attempts):
        port = start + offset
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            s.close()
            continue
    return start
