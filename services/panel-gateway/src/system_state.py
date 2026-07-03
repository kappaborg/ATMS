"""
Real ATMS controller state, consumed from the `decisions` Kafka topic.

The panel normally shows a per-camera *local* decision estimate. When the
gateway is connected to a running ATMS (KAFKA_BOOTSTRAP_SERVERS set), it also
consumes the actual decision-engine output so operators see what the real
system is commanding — and, via staleness, when that stream has gone silent
(a signal the controller has fallen back to fixed-time).
"""
from __future__ import annotations

import threading
import time


class SystemState:
    def __init__(self, staleness_s: float = 5.0) -> None:
        self._lock = threading.Lock()
        self._by_intersection: dict[str, dict] = {}
        self.staleness_s = staleness_s
        self.connected = False  # Kafka bridge running

    def on_decision(self, msg: dict) -> None:
        iid = str(msg.get("intersection_id", "1"))
        record = {
            "intersection_id": iid,
            "commanded_phase": msg.get("commanded_phase"),
            "recommended_phase": msg.get("recommended_phase"),
            "priority": msg.get("priority"),
            "confidence": msg.get("confidence"),
            "reason": msg.get("reason"),
            "ts": time.time(),
        }
        with self._lock:
            self._by_intersection[iid] = record

    def get(self, intersection_id: str = "1") -> dict | None:
        with self._lock:
            d = self._by_intersection.get(str(intersection_id))
        if d is None:
            return None
        age = time.time() - d["ts"]
        return {
            **{k: v for k, v in d.items() if k != "ts"},
            "age_s": round(age, 1),
            "stale": age > self.staleness_s,
            "source": "decision-engine",
        }
