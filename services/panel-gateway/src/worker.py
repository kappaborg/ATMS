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
from scene import SceneConfig  # noqa: E402

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
        self.engine = AIDecisionEngine()
        self.scene = SceneConfig()  # calibration/zones applied at runtime
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
            # Idle when no client is watching: keep the capture warm (read and
            # discard a frame at a low rate) but skip the expensive YOLO
            # pipeline. A newly-connecting viewer resumes full processing within
            # a frame. This makes an always-on gateway cheap.
            if self.hub.viewer_count() == 0:
                self.status = "idle"
                cap.read()
                time.sleep(0.25)
                continue
            if self.status == "idle":
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
                  "average_velocity": 0.0, "environmental_impact_score": 0.0}
            ew = dict(ns)
            ns_speeds: list[float] = []
            ew_speeds: list[float] = []

            for d in result.detections:
                cx, cy = d.center
                # Real speed from ground-plane calibration, when available.
                if scene.speed is not None:
                    d.speed_kmh = scene.speed.update(d.track_id, cx, cy, t_now)
                # Approach from operator zones, else left/right-of-centre fallback.
                if scene.zones is not None:
                    d.approach = scene.zones.classify(cx, cy)
                    direction = scene.directions.get(d.approach or "", "")
                else:
                    direction = "ns" if cx < w / 2 else "ew"
                    d.approach = direction
                bucket, speeds = (ns, ns_speeds) if direction == "ns" else (ew, ew_speeds)
                bucket["vehicle_count"] += 1
                if d.speed_kmh is not None:
                    speeds.append(d.speed_kmh)

            for bucket, speeds in ((ns, ns_speeds), (ew, ew_speeds)):
                if speeds:
                    bucket["average_velocity"] = sum(speeds) / len(speeds)

            # Release speed-history for tracks the tracker expired this frame.
            if scene.speed is not None:
                for rid in getattr(self.tracker, "last_removed_ids", []):
                    scene.speed.remove(rid)

            decision = self.engine.make_decision(ns, ew)
            self.engine.execute_decision(decision)

            # fps
            fps_n += 1
            if time.time() - fps_t0 >= 1.0:
                self.fps = fps_n / (time.time() - fps_t0)
                fps_t0, fps_n = time.time(), 0

            annotated = annotate(frame, result, decision.recommended_phase.value, self.fps)
            ok_enc, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
            latency_ms = (time.time() - t_cap) * 1000.0

            if ok_enc:
                self.hub.set_frame(self.cam_id, buf.tobytes())
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
                    "decision": {
                        "phase": decision.recommended_phase.value,
                        "active_direction": self.engine.active_direction,
                        "priority": decision.priority.value,
                        "confidence": round(decision.confidence, 3),
                        "reason": decision.reason,
                    },
                    # Real controller decision from the ATMS `decisions` topic,
                    # when the gateway is connected to a running system.
                    "intersection_id": self.intersection_id,
                    "system": self.system.get(self.intersection_id) if self.system else None,
                }
            )
