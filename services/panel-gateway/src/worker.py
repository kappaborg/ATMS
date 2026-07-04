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

import math
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
from behavior import DriftDetector, DriverBehavior, ErraticDriving, RedLightDetector  # noqa: E402
from emergency import EmergencyVehicleDetector  # noqa: E402
from emissions import EmissionAccumulator  # noqa: E402
from incidents import IncidentDetector  # noqa: E402
import plates  # noqa: E402
import reid as reid_mod  # noqa: E402
import violations_log  # noqa: E402
from report import SessionReport  # noqa: E402
from scene import SceneConfig  # noqa: E402

HISTORY_FLUSH_S = float(os.getenv("PANEL_HISTORY_FLUSH_S", "60"))
# Unattended monitoring: keep the full pipeline (detection/decision/history)
# running even with no operator watching, throttled to PANEL_RECORD_FPS and
# skipping video encoding. Off by default (idle at ~0% CPU); a government
# deployment turns this on so history/alerts never have gaps.
ALWAYS_RECORD = os.getenv("PANEL_ALWAYS_RECORD", "").lower() in ("1", "true", "yes")
RECORD_FPS = float(os.getenv("PANEL_RECORD_FPS", "5"))


def _snapshot_dir() -> str:
    d = os.getenv("PANEL_VIOLATIONS_DIR")
    if not d:
        state = os.getenv("PANEL_STATE_FILE")
        base = os.path.dirname(os.path.abspath(state)) if state else "."
        d = os.path.join(base or ".", "violation_snaps")
    os.makedirs(d, exist_ok=True)
    return d

_INFER_LOCK = threading.Lock()


def _open_capture(source: str | int) -> cv2.VideoCapture:
    """Open a capture for an RTSP/HTTP URL, file path, or USB index.

    FFmpeg timeouts are passed at open time for network sources (setting them
    afterwards is silently ignored)."""
    if isinstance(source, int) or (isinstance(source, str) and source.isdigit()):
        return cv2.VideoCapture(int(source))
    if isinstance(source, str) and source.lower().startswith(("rtsp://", "http://", "https://")):
        url = source
        # Web-page live streams (YouTube Live etc.): resolve to the underlying
        # HLS manifest NOW — resolved URLs expire, so doing this per-open makes
        # a 24/7 live camera self-healing across reconnects.
        import streams

        if streams.is_web_page_stream(source):
            resolved = streams.resolve_stream_url(source)
            if resolved:
                url = resolved
            # else: fall through; the open will fail -> worker retries/backoff
        cap = cv2.VideoCapture(
            url,
            cv2.CAP_FFMPEG,
            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 15000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000],
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
        sahi: bool = False,
    ):
        self.cam_id = cam_id
        self.source = source
        self.detector = detector
        self.hub = hub
        self.loop_file = loop_file
        self.intersection_id = intersection_id
        self.system = system  # SystemState | None
        # Per-camera SAHI: sliced inference for aerial/small-object views
        # (slower); toggled at runtime via POST /cameras/{id}/sahi.
        self.sahi_enabled = sahi
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
        self.drift = DriftDetector()
        self.emergency = EmergencyVehicleDetector()
        self.plate_reader = plates.PlateReader() if plates.enabled() else None
        self._logged_viol: set[tuple[int, str]] = set()  # (track_id, type) already logged
        # Teleport gate: last center + time per track, to catch identity
        # glitches (occlusion box-jumps, ID switches) before they poison the
        # trajectory detectors (fake speeding/reckless/red-light).
        self._tp_last: dict[int, tuple[float, float, float]] = {}
        # Deep ReID: raw tracker id -> canonical (possibly recovered) id.
        self.reid = reid_mod.DeepReID() if reid_mod.enabled() else None
        self._alias: dict[int, int] = {}
        self._raw_age: dict[int, int] = {}  # raw tracker id -> frames seen
        self._pending_forget: dict[int, float] = {}  # lost cid -> t_lost
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

    def _forget_identity(self, tid: int) -> None:
        """Forget identity-bound state (plate, violation dedup) for a vehicle
        that is truly gone (or whose identity is no longer trustworthy)."""
        if self.plate_reader is not None:
            self.plate_reader.remove(tid)
        for _vt in ("stopped_vehicle", "speeding", "wrong_way", "red_light", "reckless", "drift"):
            self._logged_viol.discard((tid, _vt))

    def _reset_track(self, tid: int, scene) -> None:
        """Wipe all per-track state after a teleport (identity glitch): the
        'vehicle' at this id may be a different physical vehicle now."""
        if scene.speed is not None:
            scene.speed.remove(tid)
        self.incidents.remove(tid)
        self.behavior.remove(tid)
        self.redlight.remove(tid)
        self.erratic.remove(tid)
        self.drift.remove(tid)
        self.emergency.remove(tid)
        if self.reid is not None:
            self.reid.remove(tid)  # fingerprint no longer trustworthy either
        self._forget_identity(tid)  # cached plate may belong to the old vehicle

    def _teleport_gate(self, vehicles: list, t_now: float, scene) -> None:
        """Detect implausible per-frame jumps and reset those tracks.

        Scale-aware: a vehicle plausibly moves a few times its own size per
        frame; the allowance grows with dt (slow FPS = bigger legit steps)."""
        live: set[int] = set()
        for d in vehicles:
            tid = d.track_id
            live.add(tid)
            cx, cy = d.center
            prev = self._tp_last.get(tid)
            self._tp_last[tid] = (cx, cy, t_now)
            if prev is None:
                continue
            px, py, pt = prev
            dt = max(t_now - pt, 1e-3)
            diag = math.hypot(d.bbox[2] - d.bbox[0], d.bbox[3] - d.bbox[1]) or 40.0
            limit = max(2.5 * diag, 80.0) * max(1.0, dt / 0.12)
            if math.hypot(cx - px, cy - py) > limit:
                self._reset_track(tid, scene)
        for tid in list(self._tp_last):
            if tid not in live:
                self._tp_last.pop(tid, None)

    def _log_violation(self, viol: dict, bbox, frame, t_now: float) -> None:
        """Persist one violation to the evidence log with a cropped snapshot."""
        snap_path = None
        try:
            if bbox is not None:
                h, w = frame.shape[:2]
                pad = 24
                x1, y1 = max(0, int(bbox[0]) - pad), max(0, int(bbox[1]) - pad)
                x2, y2 = min(w, int(bbox[2]) + pad), min(h, int(bbox[3]) + pad)
                crop = frame[y1:y2, x1:x2]
                if crop.size:
                    fn = f"{int(t_now)}_{self.cam_id}_{viol['track_id']}_{viol['type']}.jpg"
                    snap_path = os.path.join(_snapshot_dir(), fn)
                    cv2.imwrite(snap_path, crop)
        except Exception:  # noqa: BLE001 — snapshot is best-effort
            snap_path = None
        detail = {k: v for k, v in viol.items() if k not in ("type", "track_id", "plate")}
        try:
            violations_log.get_log().record(
                int(t_now), self.cam_id, self.intersection_id, viol["track_id"],
                viol["type"], viol.get("plate"), detail, snap_path,
            )
        except Exception:  # noqa: BLE001 — logging must never break the loop
            pass

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
                raw = self.detector.infer(frame, use_sahi=self.sahi_enabled)
            tracked = self.tracker.update(to_tracker_input(raw))
            result = summarize(tracked)

            # Deep ReID: restore identity across occlusions BEFORE anything
            # consumes track ids. A re-born track that matches a recently-lost
            # vehicle's appearance fingerprint gets its OLD id back (plate
            # cache, violation dedup and history stay attached to the vehicle).
            if self.reid is not None:
                fdiag = math.hypot(frame.shape[1], frame.shape[0])
                recover_budget = 2  # at most N recovery embeds per frame (CPU)
                for d in result.detections:
                    if not d.is_vehicle:
                        continue
                    raw_id = d.track_id
                    age = self._raw_age.get(raw_id, 0) + 1
                    self._raw_age[raw_id] = age
                    cid = self._alias.get(raw_id)
                    if cid is None:
                        cid = raw_id
                        # Defer recovery to the 2nd sighting: 1-frame flicker
                        # tracks never cost an embedding.
                        if age >= 2:
                            if recover_budget > 0:
                                recover_budget -= 1
                                rec = self.reid.recover(frame, d.bbox, d.center, t_now, fdiag)
                                if rec is not None:
                                    cid = rec
                                    self._pending_forget.pop(rec, None)  # it came back
                            self._alias[raw_id] = cid
                    d.track_id = cid
                    self.reid.note_seen(cid, frame, d.bbox, d.center)

            scene = self.scene
            w = frame.shape[1]
            # Per-direction aggregates fed to the decision engine.
            ns = {"vehicle_count": 0, "average_emission": 0.0, "average_waiting_time": 0.0,
                  "average_velocity": 0.0, "environmental_impact_score": 0.0,
                  "transit_present": False}
            ew = dict(ns)
            ns_speeds: list[float] = []
            ew_speeds: list[float] = []

            # Identity-glitch gate FIRST: a track whose box teleported gets its
            # per-track state wiped before any estimator consumes the jump.
            self._teleport_gate([d for d in result.detections if d.is_vehicle], t_now, scene)

            ped_present = False  # a pedestrian in the roadway (crossing)
            dir_by_id: dict[int, str] = {}  # track -> "ns"|"ew" (for alerts)
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
                    dir_by_id[d.track_id] = "ns" if direction == "ns" else "ew"
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
            # With ReID, identity may come back: motion state resets immediately
            # (continuity is broken anyway), but the plate cache and violation
            # dedup are KEPT for the recovery window and forgotten only if the
            # vehicle never returns.
            for raw_rid in getattr(self.tracker, "last_removed_ids", []):
                self._raw_age.pop(raw_rid, None)
                rid = self._alias.pop(raw_rid, raw_rid)  # canonical id
                if scene.speed is not None:
                    scene.speed.remove(rid)
                self.incidents.remove(rid)
                self.behavior.remove(rid)
                self.redlight.remove(rid)
                self.erratic.remove(rid)
                self.drift.remove(rid)
                self.emergency.remove(rid)
                if self.reid is not None:
                    self.reid.note_lost(rid, t_now)  # fingerprint -> recovery gallery
                    self._pending_forget[rid] = t_now
                else:
                    self._forget_identity(rid)

            # Identities that never came back within the recovery window.
            if self.reid is not None and self._pending_forget:
                ttl = self.reid.ttl_s + 2.0
                for rid in [r for r, tl in self._pending_forget.items() if t_now - tl > ttl]:
                    self._pending_forget.pop(rid, None)
                    self.reid.remove(rid)
                    self._forget_identity(rid)

            # Unified violation detection: stopped (incident) + speeding +
            # wrong-way, all flagged on the detections and merged into one list
            # so the frame overlay, the WS flags, and the aggregate agree.
            vehicles = [d for d in result.detections if d.is_vehicle]
            # With zones drawn, only stops INSIDE the roadway can be incidents
            # (a car standing in a parking bay is parked, not stalled).
            roadway_ids = (
                {d.track_id for d in vehicles if d.approach is not None}
                if scene.zones is not None else None
            )
            incidents, stopped_ids = self.incidents.update(
                vehicles, t_now, roadway_ids=roadway_ids
            )
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
            # Emergency vehicle: flashing blue/red light bar on a tracked
            # vehicle. An ALERT for the operator (one-click preempt), never an
            # automatic preemption — a colour heuristic must not move signals.
            emergency_ids = self.emergency.update(frame, vehicles, t_now)
            # Drift / loss-of-control (lateral-G) — needs calibration for
            # real speed + world-metre curvature.
            dviol, drift_ids = [], set()
            if scene.calibration is not None:
                world = [(d.track_id, *scene.calibration.to_ground(*d.center)) for d in vehicles]
                dviol, drift_ids = self.drift.update(world, t_now)
            emergency_dir = None  # which approach the emergency vehicle is on
            for d in result.detections:
                d.stopped = d.track_id in stopped_ids
                d.speeding = d.track_id in speeding_ids
                d.wrong_way = d.track_id in wrong_ids
                d.red_light = d.track_id in redlight_ids
                d.reckless = d.track_id in reckless_ids
                d.drift = d.track_id in drift_ids
                d.emergency = d.track_id in emergency_ids
                if d.emergency and emergency_dir is None:
                    emergency_dir = (
                        "east_west" if dir_by_id.get(d.track_id) == "ew" else "north_south"
                    )
            violations = [
                {"type": "stopped_vehicle", "track_id": i["track_id"], "seconds": i["seconds"]}
                for i in incidents
            ] + bviol + rlviol + eviol + dviol

            bbox_by_id = {d.track_id: d.bbox for d in result.detections} if violations else {}

            # License-plate capture for flagged violators (enforcement evidence).
            # Only for moving-vehicle violations (not stalls); capped + cached.
            if self.plate_reader is not None and violations:
                self.plate_reader.begin_frame()
                for viol in violations:
                    if viol["type"] == "stopped_vehicle":
                        continue
                    tid = viol["track_id"]
                    plate = self.plate_reader.cached(tid)
                    if plate is None and tid in bbox_by_id:
                        plate = self.plate_reader.read(frame, bbox_by_id[tid], tid)
                    if plate:
                        viol["plate"] = plate

            # Evidence log: persist each DISTINCT violation once (with a snapshot).
            for viol in violations:
                key = (viol["track_id"], viol["type"])
                if key in self._logged_viol:
                    continue
                self._logged_viol.add(key)
                self._log_violation(viol, bbox_by_id.get(viol["track_id"]), frame, t_now)

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
                    # Flashing-light emergency vehicle detected (operator alert;
                    # direction suggests which approach to preempt).
                    "emergency_vehicle": (
                        {"direction": emergency_dir, "count": len(emergency_ids)}
                        if emergency_ids else None
                    ),
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
