"""
Per-camera session report — the exportable summary a city attaches to a
grant application or compliance filing.

Accumulates KPIs since the camera started (unique vehicles, peak load,
incidents, measured CO2 + estimated savings) plus a per-minute time-series.
This is a SESSION report (in-memory, since the gateway/camera started); long-
horizon reporting belongs in the TimescaleDB store the full stack provides.
"""
from __future__ import annotations

import csv
import io
from collections import deque


class SessionReport:
    def __init__(self, camera_id: str, snapshot_interval_s: float = 60.0, max_snapshots: int = 1440):
        self.camera_id = camera_id
        self.snapshot_interval_s = snapshot_interval_s
        self.start: float | None = None
        self.peak_vehicles = 0
        self._incident_ids: set[int] = set()
        self._snapshots: deque = deque(maxlen=max_snapshots)
        self._last_snap: float | None = None

    def record(
        self,
        vehicles_in_frame: int,
        pedestrians_in_frame: int,
        incident_ids: list[int],
        emissions: dict | None,
        t: float,
    ) -> None:
        if self.start is None:
            self.start = t
            self._last_snap = t
        self.peak_vehicles = max(self.peak_vehicles, vehicles_in_frame)
        self._incident_ids.update(int(i) for i in incident_ids)
        if self._last_snap is not None and t - self._last_snap >= self.snapshot_interval_s:
            self._last_snap = t
            self._snapshots.append(
                {
                    "timestamp_epoch": round(t),
                    "vehicles": vehicles_in_frame,
                    "pedestrians": pedestrians_in_frame,
                    "total_co2_kg": emissions["total_co2_kg"] if emissions else "",
                    "rate_kg_h": emissions["rate_kg_h"] if emissions else "",
                }
            )

    def summary(self, emissions: dict | None, now: float) -> dict:
        dur = round(now - self.start) if self.start is not None else 0
        e = emissions or {}
        return {
            "camera_id": self.camera_id,
            "session_start_epoch": round(self.start) if self.start is not None else "",
            "duration_s": dur,
            "unique_vehicles": e.get("vehicles", 0),
            "peak_vehicles_in_frame": self.peak_vehicles,
            "incidents_total": len(self._incident_ids),
            "measured_co2_kg": e.get("total_co2_kg", 0.0),
            "idle_co2_kg": e.get("idle_co2_kg", 0.0),
            "estimated_saved_kg": e.get("est_saved_kg", 0.0),
            "avg_intensity_g_per_km": e.get("avg_g_per_km", 0.0),
            "savings_ratio": e.get("savings_ratio", ""),
        }

    def to_csv(self, emissions: dict | None, now: float) -> str:
        out = io.StringIO()
        out.write(f"# ATMS Panel session report — camera {self.camera_id}\n")
        out.write("# Measured values are real; estimated_saved_kg is a model "
                  "(idle CO2 x savings_ratio), not a raw measurement.\n\n")
        w = csv.writer(out)
        w.writerow(["metric", "value"])
        for k, v in self.summary(emissions, now).items():
            w.writerow([k, v])
        snaps = list(self._snapshots)
        if snaps:
            out.write("\n")
            cols = list(snaps[0].keys())
            w.writerow(cols)
            for s in snaps:
                w.writerow([s[c] for c in cols])
        return out.getvalue()
