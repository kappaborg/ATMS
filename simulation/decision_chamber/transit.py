"""Transit Signal Priority — GTFS-realtime subscriber.

Real production:
- The chamber subscribes to the deployment city's GTFS-realtime feed
  (e.g., İBB / IETT in İstanbul, TfL in London, NYC MTA, etc.)
- Polls the feed every ~10 s via HTTP
- Decodes the protobuf, filters for buses approaching THIS intersection
  (geo-fence around intersection lat/lon)
- Computes schedule deviation per bus (current_time - scheduled_arrival)
- If any bus is behind schedule by > `delay_threshold_s`, requests
  priority for the bus's approach direction
- Hands the signal to the chamber's L3 optimization as a SOFT bias
  (smaller than pedestrian or emergency — bus priority is real but
  conditional)

Phase 4 ships the protocol layer + L3 integration. Geo-fence (per-
intersection lat/lon + lane → direction mapping) is a deployment-
specific config; the demo subscribes to a configurable feed URL and
filters by route_id only.

Wire format: GTFS-realtime is a protobuf spec defined at
https://developers.google.com/transit/gtfs-realtime/reference. The
`gtfs-realtime-bindings` Python package compiles the proto for us. We
only consume `vehicle.trip.trip_id`, `vehicle.position`, and
`vehicle.timestamp` — a small slice of the full message.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

log = logging.getLogger("atms.chamber.transit")


class TransitPriorityDetector:
    """Real GTFS-realtime subscriber + per-direction TSP demand signal.

    Returns a per-direction priority dict each tick. The chamber's L3
    optimization adds a small bonus per direction with active TSP demand.
    """

    name = "gtfs_realtime_tsp"

    def __init__(
        self,
        feed_url: str | None = None,
        route_direction_map: dict[str, str] | None = None,
        delay_threshold_s: float = 60.0,
        poll_interval_s: float = 10.0,
        bonus_per_late_bus: float = 0.10,
    ):
        """
        Args:
            feed_url: GTFS-realtime VehiclePositions feed URL. None
                disables polling (returns no demand). Production: point
                at the city's real feed (e.g., IETT, TfL).
            route_direction_map: route_id -> direction name (which of
                our directions does this bus route arrive on). Required
                for the demo to translate "bus on route X is late" to
                "give TSP to direction Y". Production: per-intersection
                geo-fence does this automatically.
            delay_threshold_s: seconds-behind-schedule before requesting
                TSP. 60s = 1 minute behind. Lower = more aggressive TSP.
            poll_interval_s: HTTP poll rate. Most agencies update at
                ~5-30 s; 10 s is a reasonable default.
            bonus_per_late_bus: score added to L3 for the bus's
                direction. 0.10 = modest bias; one late bus alone won't
                override a heavily queued opposing direction.
        """
        self._feed_url = feed_url
        self._route_dir = route_direction_map or {}
        self._delay_threshold = delay_threshold_s
        self._poll_interval = poll_interval_s
        self._bonus = bonus_per_late_bus

        # Cached TSP demand per direction (set of route_ids requesting
        # priority for that direction).
        self._lock = threading.Lock()
        self._tsp_demand: dict[str, set[str]] = {}

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if feed_url is not None:
            self._start_poller()

    def _start_poller(self) -> None:
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        log.info(
            "GTFS-RT TSP detector polling %s every %.1fs",
            self._feed_url, self._poll_interval,
        )

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._fetch_and_update()
            except Exception as e:
                log.warning("TSP poll failed: %s", e)
            self._stop.wait(self._poll_interval)

    def _fetch_and_update(self) -> None:
        try:
            from google.transit import gtfs_realtime_pb2  # noqa: PLC0415
        except ImportError as e:
            log.error("gtfs-realtime-bindings missing: %s — TSP disabled", e)
            return

        req = urllib.request.Request(
            self._feed_url, headers={"User-Agent": "ATMS-DecisionChamber/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read()
        except (urllib.error.URLError, TimeoutError) as e:
            log.debug("TSP feed unreachable: %s", e)
            return

        msg = gtfs_realtime_pb2.FeedMessage()
        try:
            msg.ParseFromString(body)
        except Exception as e:
            log.warning("malformed GTFS-RT feed: %s", e)
            return

        now_ts = time.time()
        demand: dict[str, set[str]] = {}
        for entity in msg.entity:
            if not entity.HasField("vehicle"):
                continue
            vp = entity.vehicle
            if not vp.HasField("trip"):
                continue
            route_id = vp.trip.route_id
            direction = self._route_dir.get(route_id)
            if direction is None:
                continue
            # Approximate schedule deviation: how late is THIS update?
            # GTFS-RT VehiclePosition.timestamp is when the bus reported
            # the position. If the bus is moving "slowly" (poll old), we
            # treat it as a proxy. Real TSP uses trip_update.delay if
            # available.
            vehicle_ts = vp.timestamp if vp.HasField("timestamp") else now_ts
            deviation = now_ts - vehicle_ts
            if deviation >= self._delay_threshold:
                demand.setdefault(direction, set()).add(route_id)

        with self._lock:
            self._tsp_demand = demand

    def get_tsp_bonus_per_direction(self) -> dict[str, float]:
        """Returns {direction: score_bonus} for the chamber's L3 to add.
        Empty when no late buses are detected.
        """
        with self._lock:
            return {
                direction: len(routes) * self._bonus
                for direction, routes in self._tsp_demand.items()
            }

    def get_demand_detail(self) -> dict[str, list[str]]:
        """For the operator console: returns {direction: [route_ids]}."""
        with self._lock:
            return {direction: sorted(routes) for direction, routes in self._tsp_demand.items()}

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
