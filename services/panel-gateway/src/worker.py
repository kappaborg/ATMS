"""
Per-camera processing worker.

Each camera runs one worker thread: capture -> detect -> track -> decide ->
annotate -> publish. Design for responsiveness:
  * Video frames are published latest-wins (stale frames dropped), so the
    panel always shows the freshest frame with no growing queue latency.
  * Small data events (detections/decision/metrics) are pushed to the hub
    immediately and broadcast to clients.
  * YOLO inference is serialized under a shared lock (ultralytics is not
    thread-safe); fine for 1-4 cameras.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import cv2

_ROOT = Path(__file__).resolve().parents[3]
# Reuse the FIXED components rather than duplicating them:
#   - SimpleByteTracker (lost-track carry-over fix) from ai-perception
#   - AIDecisionEngine (real phase state machine) from repo root
# TODO: promote these into shared/ to drop the path inserts.
sys.path.insert(0, str(_ROOT / "services" / "ai-perception" / "src"))
sys.path.insert(0, str(_ROOT))
from tracking.bytetrack_simple import SimpleByteTracker  # noqa: E402
from ai_decision_system import AIDecisionEngine  # noqa: E402

from detection import Detector, annotate, summarize, to_tracker_input  # noqa: E402
import history  # noqa: E402
from behavior import DriverBehavior, ErraticDriving, RedLightDetector  # noqa: E402
from emissions import EmissionAccumulator  # noqa: E402
from incidents import IncidentDetector  # noqa: E402
from report import SessionReport  # noqa: E402
from scene import SceneConfig  # noqa: E402

HISTORY_FLUSH_S = float(os.getenv("PANEL_HISTORY_FLUSH_S", "60"))
# Unattended monitoring: keep the full pipeline (detection/decision/history)
# running even with no operator watching, throttled to PANEL_RECORD_FPS and
# skipping video encoding. Off by default (idle at ~0% CPU); a government
# deployment turns this on so history/alerts never have gaps.
ALWAYS_RECORD = os.getenv("PANEL_ALWAYS_RECORD", "").lower() in ("1", "true", "yes")
RECORD_FPS = float(os.getenv("PANEL_RECORD_FPS", "5"))

_INFER_LOCK = threading.Lock()


def _open_capture(source: str | int) -> cv2.VideoCapture:
    """Open a capture for an RTSP/HTTP URL, file path, or USB index.

    FFmpeg timeouts are passed at open time for network sources (setting them
    afterwards is silently ignored)."""
    if isinstance(source, int) or (isinstance(source, str) and source.isdigit()):
        return cv2.VideoCapture(int(source))
    if isinstance(source, str) and source.lower().startswith(("rtsp://", "http://", "https://")):
        cap = cv2.VideoCapture(
            source,
            cv2.CAP_FFMPEG,
            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000],
        )
        # Keep the internal buffer tiny so we decode the freshest frame.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap
    return cv2.VideoCapture(str(source))


class CameraWorker:
    def __init__(
        self,
        cam_id: str,
        source: str | int,
        detector: Detector,
        hub,
        *,
        loop_file=True,
        intersection_id: str = "1",
        system=None,
    ):
        self.cam_id = cam_id
        self.source = source
        self.detector = detector
        self.hub = hub
        self.loop_file = loop_file
        self.intersection_id = intersection_id
        self.system = system  # SystemState | None
        self.tracker = SimpleByteTracker()
        # Predictive congestion on: the panel's per-camera decision reason
        # then shows "Congestion forecast …" (disable with ATMS_USE_PREDICTIONS=0).
        self.engine = AIDecisionEngine(
            use_predictions=os.getenv("ATMS_USE_PREDICTIONS", "1").lower() in ("1", "true", "yes")
        )
        self.scene = SceneConfig()  # calibration/zones applied at runtime
        self.incidents = IncidentDetector()
        self.behavior = DriverBehavior()
        self.redlight = RedLightDetector()
        self.erratic = ErraticDriving()
        self.emissions = EmissionAccumulator()
        self.report = SessionReport(cam_id)
        self._prev_t: float | None = None
        # Distinct vehicle track-ids seen in the CURRENT history interval
        # (cleared on each flush → bounded memory over a long session).
        self._interval_veh_ids: set[int] = set()
        # History flush: last-flushed cumulative CO2 counters, to persist deltas.
        self._hist_t: float | None = None
        self._hist_prev = {"co2_g": 0.0, "saved_g": 0.0, "incidents": 0}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.status = "starting"
        self.error: str | None = None
        self.fps = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"cam-{self.cam_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _flush_history(self, t_now: float) -> None:
        """Every HISTORY_FLUSH_S, persist the metrics accrued in the interval
        (deltas vs the last flush) so long-horizon totals survive restarts."""
        def cum_snapshot() -> dict:
            c = self.emissions.cumulative()
            return {"co2_g": c["co2_g"], "saved_g": c["saved_g"],
                    "incidents": self.report.incident_count}

        if self._hist_t is None:
            self._hist_t = t_now
            self._hist_prev = cum_snapshot()
            self._interval_veh_ids.clear()
            return
        if t_now - self._hist_t < HISTORY_FLUSH_S:
            return
        cur = cum_snapshot()
        d_veh = len(self._interval_veh_ids)  # distinct vehicles this interval
        d_co2 = max(0.0, cur["co2_g"] - self._hist_prev["co2_g"]) / 1000.0
        d_saved = max(0.0, cur["saved_g"] - self._hist_prev["saved_g"]) / 1000.0
        d_inc = max(0, cur["incidents"] - self._hist_prev["incidents"])
        try:
            history.get_store().record_interval(
                self.cam_id, int(t_now), d_veh, d_co2, d_saved, d_inc
            )
        except Exception:  # noqa: BLE001 — history is best-effort, never break the loop
            pass
        self._hist_prev = cur
        self._hist_t = t_now
        self._interval_veh_ids.clear()  # bound memory: only one interval retained

    def _run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            cap = _open_capture(self.source)
            if not cap.isOpened():
                self.status, self.error = "reconnecting", "cannot open source"
                time.sleep(min(backoff, 5.0))
                backoff = min(backoff * 2, 5.0)
                continue
            backoff = 0.5
            self.status, self.error = "live", None
            self._loop(cap)
            cap.release()
        self.status = "stopped"

    def _loop(self, cap: cv2.VideoCapture) -> None:
        frame_idx = 0
        fps_t0, fps_n = time.time(), 0
        while not self._stop.is_set():
            # No viewer: by default idle (keep the capture warm, skip the
            # expensive YOLO pipeline) so an always-on gateway is cheap. With
            # PANEL_ALWAYS_RECORD, instead keep monitoring/history alive but
            # throttled to RECORD_FPS and without video encoding.
            viewers = self.hub.viewer_count()
            if viewers == 0 and not ALWAYS_RECORD:
                self.status = "idle"
                cap.read()
                time.sleep(0.25)
                continue
            if viewers == 0:
                self.status = "recording"
                time.sleep(1.0 / max(RECORD_FPS, 0.1))
            elif self.status in ("idle", "recording"):
                self.status = "live"

            t_cap = time.time()
            ok, frame = cap.read()
            if not ok:
                # File source: loop; live source: break out to reconnect.
                if self.loop_file and not str(self.source).lower().startswith(
                    ("rtsp://", "http://", "https://")
                ) and not str(self.source).isdigit():
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                self.status = "reconnecting"
                return

            frame_idx += 1
            t_now = time.time()
            with _INFER_LOCK:
                raw = self.detector.infer(frame)
            tracked = self.tracker.update(to_tracker_input(raw))
            result = summarize(tracked)

            scene = self.scene
            w = frame.shape[1]
            # Per-direction aggregates fed to the decision engine.
            ns = {"vehicle_count": 0, "average_emission": 0.0, "average_waiting_time": 0.0,
                  "average_velocity": 0.0, "environmental_impact_score": 0.0,
                  "transit_present": False}
            ew = dict(ns)
            ns_speeds: list[float] = []
            ew_speeds: list[float] = []

            ped_present = False  # a pedestrian in the roadway (crossing)
            for d in result.detections:
                cx, cy = d.center
                # Approach from operator zones, else left/right-of-centre fallback.
                if scene.zones is not None:
                    d.approach = scene.zones.classify(cx, cy)
                    direction = scene.directions.get(d.approach or "", "")
                else:
                    direction = "ns" if cx < w / 2 else "ew"
                    d.approach = direction

                if d.is_vehicle:
                    # Real speed from ground-plane calibration, when available.
                    if scene.speed is not None:
                        d.speed_kmh = scene.speed.update(d.track_id, cx, cy, t_now)
                    bucket, speeds = (ns, ns_speeds) if direction == "ns" else (ew, ew_speeds)
                    bucket["vehicle_count"] += 1
                    self._interval_veh_ids.add(d.track_id)
                    if d.label == "bus":
                        bucket["transit_present"] = True  # transit signal priority
                    if d.speed_kmh is not None:
                        speeds.append(d.speed_kmh)
                elif d.label == "person":
                    # In the roadway = inside an approach zone (calibrated). Without
                    # zones, any detected person counts — safety-conservative (better
                    # to over-hold clearance than strand someone; bounded in engine).
                    if scene.zones is None or d.approach is not None:
                        ped_present = True

            for bucket, speeds in ((ns, ns_speeds), (ew, ew_speeds)):
                if speeds:
                    bucket["average_velocity"] = sum(speeds) / len(speeds)

            # Release per-track state for tracks the tracker expired this frame.
            for rid in getattr(self.tracker, "last_removed_ids", []):
                if scene.speed is not None:
                    scene.speed.remove(rid)
                self.incidents.remove(rid)
                self.behavior.remove(rid)
                self.redlight.remove(rid)
                self.erratic.remove(rid)

            # Unified violation detection: stopped (incident) + speeding +
            # wrong-way, all flagged on the detections and merged into one list
            # so the frame overlay, the WS flags, and the aggregate agree.
            vehicles = [d for d in result.detections if d.is_vehicle]
            incidents, stopped_ids = self.incidents.update(vehicles, t_now)
            # Wrong-way needs real approach zones (calibrated) — the crude
            # left/right split isn't per-approach flow and would false-positive.
            bviol, speeding_ids, wrong_ids = self.behavior.update(
                vehicles, t_now, wrong_way=scene.zones is not None
            )
            # Red-light running: crossing a stop-line while that approach is red.
            # Uses the CURRENT signal state (before this frame's decision).
            rlviol, redlight_ids = [], set()
            if scene.stop_lines:
                cur_phase = self.engine.current_phase.value
                active = self.engine.active_direction

                def _is_red(appr: str) -> bool:
                    d = "north_south" if appr == "ns" else "east_west"
                    return not (active == d and cur_phase in ("GREEN", "YELLOW"))

                rlviol, redlight_ids = self.redlight.update(
                    vehicles, t_now, scene.stop_lines, _is_red
                )
            # Reckless/erratic (weaving) — trajectory-based, advisory.
            eviol, reckless_ids = self.erratic.update(vehicles, t_now)
            for d in result.detections:
                d.stopped = d.track_id in stopped_ids
                d.speeding = d.track_id in speeding_ids
                d.wrong_way = d.track_id in wrong_ids
                d.red_light = d.track_id in redlight_ids
                d.reckless = d.track_id in reckless_ids
            violations = [
                {"type": "stopped_vehicle", "track_id": i["track_id"], "seconds": i["seconds"]}
                for i in incidents
            ] + bviol + rlviol + eviol

            # Carbon: accumulate real CO2 from measured speed (needs calibration).
            dt = (t_now - self._prev_t) if self._prev_t is not None else 0.0
            self._prev_t = t_now
            for d in vehicles:
                if d.speed_kmh is not None:
                    self.emissions.add(d.track_id, d.label, d.speed_kmh, dt, t_now)

            # Accumulate session KPIs for the exportable report.
            self.report.record(
                result.vehicle_count,
                result.pedestrian_count,
                [i["track_id"] for i in incidents],
                self.emissions.stats(t_now),
                t_now,
            )

            # Persist per-interval deltas to the long-horizon history store.
            self._flush_history(t_now)

            decision = self.engine.make_decision(ns, ew, pedestrian_present=ped_present)
            self.engine.execute_decision(decision)

            # fps
            fps_n += 1
            if time.time() - fps_t0 >= 1.0:
                self.fps = fps_n / (time.time() - fps_t0)
                fps_t0, fps_n = time.time(), 0

            # Video encoding is only worth it when someone is watching; in
            # record-only mode we skip it and just publish the data event
            # (which feeds decisions, the network overview, and history).
            if viewers > 0:
                annotated = annotate(frame, result, decision.recommended_phase.value, self.fps)
                # Draw stop-lines, coloured by the current signal for their approach.
                for sl in scene.stop_lines:
                    d = "north_south" if sl["approach"] == "ns" else "east_west"
                    red = not (
                        self.engine.active_direction == d
                        and decision.recommended_phase.value in ("GREEN", "YELLOW")
                    )
                    (sx1, sy1), (sx2, sy2) = sl["points"]
                    cv2.line(annotated, (int(sx1), int(sy1)), (int(sx2), int(sy2)),
                             (0, 0, 255) if red else (0, 200, 0), 2)
                ok_enc, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok_enc:
                    self.hub.set_frame(self.cam_id, buf.tobytes())
            latency_ms = (time.time() - t_cap) * 1000.0

            self.hub.publish_event(
                {
                    "type": "frame",
                    "camera_id": self.cam_id,
                    "frame": frame_idx,
                    "ts": time.time(),
                    "pipeline_latency_ms": round(latency_ms, 1),
                    "fps": round(self.fps, 1),
                    "counts": {
                        "vehicles": result.vehicle_count,
                        "pedestrians": result.pedestrian_count,
                    },
                    "detections": [
                        {
                            "track_id": d.track_id,
                            "label": d.label,
                            "confidence": round(d.confidence, 3),
                            "bbox": [round(v, 1) for v in d.bbox],
                            "speed_kmh": d.speed_kmh,
                            "approach": d.approach,
                        }
                        for d in result.detections
                    ],
                    "approaches": {
                        "ns": {"vehicles": ns["vehicle_count"], "avg_speed_kmh": round(ns["average_velocity"], 1)},
                        "ew": {"vehicles": ew["vehicle_count"], "avg_speed_kmh": round(ew["average_velocity"], 1)},
                    },
                    "calibrated": self.scene.calibration is not None,
                    # Unified driver/vehicle violations (stopped, speeding,
                    # wrong-way). `incidents` kept as the stopped-only subset
                    # for backward compatibility.
                    "violations": violations,
                    "incidents": incidents,
                    "emissions": self.emissions.stats(t_now),
                    "preemption": self.engine._preemption_active(),
                    "transit": {"ns": ns["transit_present"], "ew": ew["transit_present"]},
                    "pedestrian": {"present": ped_present, "clearance_hold": self.engine._ped_hold_active},
                    "decision": {
                        "phase": decision.recommended_phase.value,
                        "active_direction": self.engine.active_direction,
                        "priority": decision.priority.value,
                        "confidence": round(decision.confidence, 3),
                        "reason": decision.reason,
                        # Short-horizon congestion forecast (per direction, 0..1).
                        "predicted_congestion": self.engine._last_prediction,
                    },
                    # Real controller decision from the ATMS `decisions` topic,
                    # when the gateway is connected to a running system.
                    "intersection_id": self.intersection_id,
                    "system": self.system.get(self.intersection_id) if self.system else None,
                }
            )
