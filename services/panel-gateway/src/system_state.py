"""
Real ATMS controller state for the panel.

Two sources, both optional:
  * `decisions` Kafka topic (decision-engine) -> the commanded phase.
  * the traffic-controller's /health endpoint (HTTP poll) -> the failsafe
    MODE (ai_adaptive / fixed_time / all_red_flash) — the single most
    important safety signal: it tells an operator when the system has
    degraded to fixed-time or escalated to all-red-flash.

Both are per-intersection. get() merges them and reports staleness /
reachability so the panel can warn when a stream goes silent.
"""
from __future__ import annotations

import threading
import time


class SystemState:
    def __init__(self, staleness_s: float = 5.0, mode_staleness_s: float = 8.0) -> None:
        self._lock = threading.Lock()
        self._decisions: dict[str, dict] = {}
        self._modes: dict[str, dict] = {}
        self.staleness_s = staleness_s
        self.mode_staleness_s = mode_staleness_s
        self.connected = False  # Kafka bridge running

    # --- decisions (Kafka) ---
    def on_decision(self, msg: dict) -> None:
        iid = str(msg.get("intersection_id", "1"))
        record = {
            "commanded_phase": msg.get("commanded_phase"),
            "recommended_phase": msg.get("recommended_phase"),
            "priority": msg.get("priority"),
            "confidence": msg.get("confidence"),
            "reason": msg.get("reason"),
            "ts": time.time(),
        }
        with self._lock:
            self._decisions[iid] = record

    # --- failsafe mode (HTTP poll of the controller /health) ---
    def set_mode(self, intersection_id: str, mode: str | None, reachable: bool) -> None:
        with self._lock:
            self._modes[str(intersection_id)] = {
                "mode": mode,
                "reachable": reachable,
                "ts": time.time(),
            }

    def get(self, intersection_id: str = "1") -> dict | None:
        iid = str(intersection_id)
        now = time.time()
        with self._lock:
            dec = self._decisions.get(iid)
            mode = self._modes.get(iid)
        if dec is None and mode is None:
            return None

        out: dict = {"intersection_id": iid, "source": "atms-controller"}
        if dec is not None:
            age = now - dec["ts"]
            out.update(
                {
                    "commanded_phase": dec["commanded_phase"],
                    "recommended_phase": dec["recommended_phase"],
                    "priority": dec["priority"],
                    "confidence": dec["confidence"],
                    "reason": dec["reason"],
                    "age_s": round(age, 1),
                    "stale": age > self.staleness_s,
                }
            )
        else:
            out.update({"commanded_phase": None, "stale": True, "age_s": None})

        if mode is not None:
            fresh = (now - mode["ts"]) <= self.mode_staleness_s
            out["mode"] = mode["mode"] if (mode["reachable"] and fresh) else None
            out["mode_reachable"] = bool(mode["reachable"] and fresh)
        else:
            out["mode"] = None
            out["mode_reachable"] = False
        return out
