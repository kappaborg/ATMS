#!/usr/bin/env python3
"""Serve a real GTFS-realtime VehiclePositions feed over HTTP.

Same wire format any transit agency publishes (protobuf per
google.transit.gtfs_realtime). Used for dev testing the
TransitPriorityDetector without depending on an external agency feed.

The "delay" is simulated by setting `vehicle.timestamp` in the past —
the detector treats `now - vehicle.timestamp` as schedule deviation.
Real production: connect to the city's actual feed (e.g., IETT, TfL).

Run from repo root:
    python3 scripts/gtfs_synthetic_feed.py --port 5050 --delay 90
    # Then point the chamber at http://127.0.0.1:5050/feed

Operator/dev can tune the delay flag while the script is running by
sending SIGUSR1 (Phase 5 enhancement; for now restart with new --delay).
"""

from __future__ import annotations

import argparse
import http.server
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gtfs_synth")


def build_feed(delay_seconds: int) -> bytes:
    """Build a GTFS-realtime FeedMessage with two buses on routes
    'metrobus-34' and 'metrobus-500T', both delayed `delay_seconds`
    behind schedule.
    """
    from google.transit import gtfs_realtime_pb2  # noqa: PLC0415

    msg = gtfs_realtime_pb2.FeedMessage()
    msg.header.gtfs_realtime_version = "2.0"
    msg.header.timestamp = int(time.time())

    now = int(time.time())
    for vehicle_id, route_id in [("BUS-34-001", "metrobus-34"),
                                  ("BUS-500T-007", "metrobus-500T")]:
        e = msg.entity.add()
        e.id = vehicle_id
        v = e.vehicle
        v.vehicle.id = vehicle_id
        v.trip.trip_id = f"trip-{vehicle_id}"
        v.trip.route_id = route_id
        v.timestamp = now - delay_seconds
        # Synthetic position around İstanbul Metrobüs corridor
        v.position.latitude = 41.0455
        v.position.longitude = 28.9870

    return msg.SerializeToString()


def main() -> int:
    p = argparse.ArgumentParser(prog="gtfs_synthetic_feed.py")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5050)
    p.add_argument(
        "--delay",
        type=int,
        default=120,
        help="simulated schedule deviation per bus (seconds; 0 = on-time)",
    )
    args = p.parse_args()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path not in ("/feed", "/"):
                self.send_response(404)
                self.end_headers()
                return
            body = build_feed(args.delay)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    try:
        server = http.server.HTTPServer((args.host, args.port), Handler)
    except OSError as e:
        log.error("bind to %s:%d failed: %s", args.host, args.port, e)
        return 1

    log.info(
        "GTFS-RT synthetic feed listening on http://%s:%d/feed "
        "(simulated delay: %d s)",
        args.host, args.port, args.delay,
    )
    log.info("Stop with Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
