"""
Connection hub + camera manager.

Bridges worker THREADS (which call set_frame/publish_event) to asyncio
WebSocket clients. Video is latest-wins per camera; data events are fanned
out to per-connection bounded queues (drop-oldest on overflow so a slow
client never adds latency for others).
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import store
from corridor import build_corridor
from detection import Detector
from scene import SceneConfig
from security import is_live_source, source_kind, validate_source
from worker import CameraWorker


class Hub:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._frames: dict[str, bytes] = {}
        self._data_queues: set[asyncio.Queue] = set()
        self._video_viewers = 0

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # --- called from worker threads ---
    def set_frame(self, cam_id: str, jpeg: bytes) -> None:
        self._frames[cam_id] = jpeg  # atomic dict assignment; latest-wins

    def publish_event(self, event: dict[str, Any]) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._fanout, event)

    def _fanout(self, event: dict[str, Any]) -> None:
        for q in list(self._data_queues):
            if q.full():
                try:
                    q.get_nowait()  # drop oldest
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(event)

    # --- consumed by WS endpoints ---
    def latest_frame(self, cam_id: str) -> bytes | None:
        return self._frames.get(cam_id)

    def register_data_client(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._data_queues.add(q)
        return q

    def unregister_data_client(self, q: asyncio.Queue) -> None:
        self._data_queues.discard(q)

    def add_video_viewer(self) -> None:
        self._video_viewers += 1

    def remove_video_viewer(self) -> None:
        self._video_viewers = max(0, self._video_viewers - 1)

    def viewer_count(self) -> int:
        """Total connected clients (data + video). Workers idle when zero."""
        return len(self._data_queues) + self._video_viewers


class CameraManager:
    def __init__(self, hub: Hub, system=None) -> None:
        self.hub = hub
        self.system = system  # SystemState | None
        self._detector: Detector | None = None
        self._workers: dict[str, CameraWorker] = {}
        self._corridors: dict = {}  # corridor_id -> Corridor
        # Junction display names, keyed by intersection_id: {"name", "city"}.
        # Kept here rather than on the cameras: a junction's name belongs to the
        # junction, and duplicating it per-camera lets two cameras on the same
        # junction disagree about where they are. Entries are independent of
        # cameras, so naming a junction survives its cameras being swapped out.
        self._junctions: dict[str, dict[str, str]] = {}

    def _detector_lazy(self) -> Detector:
        if self._detector is None:
            self._detector = Detector()
        return self._detector

    _ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

    APPROACHES = ("north", "south", "east", "west")

    def add(
        self, cam_id: str, source: str | int, *,
        loop_file: bool = True, intersection_id: str = "1", sahi: bool = False,
        min_confidence: float | None = None, approach: str | None = None,
    ) -> None:
        # Single chokepoint (API + restore): ids build filesystem/route paths,
        # so reject anything outside a safe charset (path-traversal defence).
        if not self._ID_RE.match(str(cam_id)):
            raise ValueError(f"invalid camera_id '{cam_id}'")
        if not self._ID_RE.match(str(intersection_id)):
            raise ValueError(f"invalid intersection_id '{intersection_id}'")
        if cam_id in self._workers:
            raise ValueError(f"camera '{cam_id}' already exists")
        if approach is not None and approach not in self.APPROACHES:
            raise ValueError(f"invalid approach '{approach}'")
        worker = CameraWorker(
            cam_id, source, self._detector_lazy(), self.hub,
            loop_file=loop_file, intersection_id=intersection_id, system=self.system,
            sahi=sahi, min_confidence=min_confidence, approach=approach,
        )
        self._workers[cam_id] = worker
        worker.start()
        self._persist()

    def set_sahi(self, cam_id: str, enabled: bool) -> None:
        worker = self._workers.get(cam_id)
        if worker is None:
            raise KeyError(cam_id)
        worker.sahi_enabled = bool(enabled)  # atomic; worker reads it each frame
        self._persist()

    def set_min_confidence(self, cam_id: str, value: float) -> None:
        worker = self._workers.get(cam_id)
        if worker is None:
            raise KeyError(cam_id)
        worker.min_confidence = max(0.05, min(0.95, float(value)))  # atomic
        self._persist()

    def remove(self, cam_id: str) -> None:
        worker = self._workers.pop(cam_id, None)
        if worker is None:
            raise KeyError(cam_id)
        worker.stop()
        self.hub._frames.pop(cam_id, None)
        self._persist()

    def set_scene(self, cam_id: str, scene) -> dict:
        worker = self._workers.get(cam_id)
        if worker is None:
            raise KeyError(cam_id)
        worker.scene = scene  # atomic reference swap; worker reads it each frame
        self._persist()
        return scene.info()

    # --- durability ---
    def _persist(self) -> None:
        cams = []
        for w in self._workers.values():
            entry = {
                "camera_id": w.cam_id,
                "source": str(w.source),
                "loop_file": w.loop_file,
                "intersection_id": w.intersection_id,
                "sahi": w.sahi_enabled,
                "min_confidence": w.min_confidence,
            }
            if w.approach:
                entry["approach"] = w.approach
            payload = w.scene.to_payload()
            if payload:
                entry["scene"] = payload
            cams.append(entry)
        store.save({
            "cameras": cams,
            "junctions": self._junctions,
            "corridors": [c.to_payload() for c in self._corridors.values()],
        })

    def restore(self) -> int:
        """Re-create cameras and re-apply scenes from the saved state.
        Returns the number of cameras restored. Never raises on a bad entry."""
        restored = 0
        saved = store.load()
        # Junctions first: cameras restored below are grouped under them, and a
        # camera that fails to restore must not take its junction's name with it.
        for iid, meta in (saved.get("junctions") or {}).items():
            if isinstance(meta, dict):
                self._junctions[str(iid)] = {
                    "name": str(meta.get("name", ""))[:64],
                    "city": str(meta.get("city", ""))[:64],
                }
        for entry in saved.get("cameras", []):
            try:
                cam_id = entry["camera_id"]
                safe = validate_source(entry["source"])  # re-vet on load (tamper defence)
                self.add(
                    cam_id,
                    safe,
                    loop_file=entry.get("loop_file", True),
                    intersection_id=str(entry.get("intersection_id", "1")),
                    sahi=bool(entry.get("sahi", False)),
                    min_confidence=entry.get("min_confidence"),
                    approach=entry.get("approach"),
                )
                if entry.get("scene"):
                    self.set_scene(cam_id, SceneConfig.from_payload(entry["scene"]))
                restored += 1
            except Exception as e:  # noqa: BLE001 — one bad entry must not block the rest
                import logging
                logging.getLogger("panel.hub").warning(
                    "restore skipped camera %s: %s", entry.get("camera_id"), e
                )
                continue
        # Corridors last: _apply_coordination matches stops against live workers,
        # so restoring a corridor before its cameras exist would silently push the
        # green-wave offset onto nothing.
        for entry in saved.get("corridors", []):
            try:
                corr = build_corridor(entry)  # re-validates (>=2 stops, positive speed/cycle/green)
                self._corridors[corr.corridor_id] = corr
                self._apply_coordination(corr)
            except Exception as e:  # noqa: BLE001 — one bad corridor must not block the rest
                import logging
                logging.getLogger("panel.hub").warning(
                    "restore skipped corridor %s: %s", entry.get("corridor_id"), e
                )
                continue
        return restored

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "camera_id": w.cam_id,
                "source": str(w.source),
                "kind": source_kind(w.source),
                "live": is_live_source(w.source),
                "intersection_id": w.intersection_id,
                "approach": w.approach,
                "sahi": w.sahi_enabled,
                "min_confidence": round(w.min_confidence, 2),
                "status": w.status,
                "error": w.error,
                "fps": round(w.fps, 1),
                "scene": w.scene.info(),
            }
            for w in self._workers.values()
        ]

    def _apply_coordination(self, corr, clear: bool = False) -> None:
        """Push (or clear) the green-wave offset onto every camera engine at
        each of the corridor's intersections."""
        for stop in corr.stops:
            hint = corr.coordination_for(stop.intersection_id, corr.direction)
            for w in self._workers.values():
                if w.intersection_id != stop.intersection_id:
                    continue
                if clear:
                    w.engine.clear_coordination()
                elif hint:
                    w.engine.set_coordination(
                        hint["offset_s"], hint["cycle_s"], hint["green_s"], hint["direction"]
                    )

    def add_corridor(self, payload: dict) -> dict:
        corr = build_corridor(payload)
        self._corridors[corr.corridor_id] = corr
        self._apply_coordination(corr)
        self._persist()
        return corr.to_dict()

    def remove_corridor(self, corridor_id: str) -> None:
        corr = self._corridors.pop(corridor_id, None)
        if corr is None:
            raise KeyError(corridor_id)
        self._apply_coordination(corr, clear=True)
        self._persist()

    def list_corridors(self) -> list[dict]:
        return [c.to_dict() for c in self._corridors.values()]

    def set_junction(self, iid: str, name: str, city: str) -> dict[str, str]:
        """Name a junction. Accepts an id with no cameras yet — an operator can
        name the site before pointing a camera at it."""
        if not self._ID_RE.match(str(iid)):
            raise ValueError(f"invalid intersection_id '{iid}'")
        meta = {"name": name.strip()[:64], "city": city.strip()[:64]}
        if not meta["name"] and not meta["city"]:
            self._junctions.pop(str(iid), None)  # cleared -> fall back to the id
        else:
            self._junctions[str(iid)] = meta
        self._persist()
        return meta

    def intersections(self) -> list[dict[str, Any]]:
        """Group cameras by intersection for the network overview console."""
        groups: dict[str, list[str]] = {}
        for w in self._workers.values():
            groups.setdefault(w.intersection_id, []).append(w.cam_id)
        # A named junction with no cameras still belongs on the map — otherwise
        # naming a site then losing its camera would silently erase it.
        for iid in self._junctions:
            groups.setdefault(iid, [])
        return [
            {
                "intersection_id": iid,
                "cameras": sorted(cams),
                "name": self._junctions.get(iid, {}).get("name") or None,
                "city": self._junctions.get(iid, {}).get("city") or None,
            }
            for iid, cams in sorted(groups.items())
        ]

    def preempt(self, cam_id: str, direction: str, active: bool, hold_s: float | None = None) -> None:
        w = self._workers.get(cam_id)
        if w is None:
            raise KeyError(cam_id)
        if active:
            w.engine.request_preemption(direction, hold_s)
        else:
            w.engine.clear_preemption()

    def report_csv(self, cam_id: str) -> str:
        import time

        import history

        w = self._workers.get(cam_id)
        if w is None:
            raise KeyError(cam_id)
        now = time.time()
        store = history.get_store()
        now_i = int(now)
        hist = {
            "last_24h": store.totals(now_i - 24 * 3600, now_i, cam_id),
            "last_7d": store.totals(now_i - 7 * 24 * 3600, now_i, cam_id),
            "last_30d": store.totals(now_i - 30 * 24 * 3600, now_i, cam_id),
        }
        return w.report.to_csv(w.emissions.stats(now), now, history_totals=hist)

    def report_json(self, cam_id: str) -> dict:
        import time

        w = self._workers.get(cam_id)
        if w is None:
            raise KeyError(cam_id)
        now = time.time()
        return {
            "summary": w.report.summary(w.emissions.stats(now), now),
            "timeseries": w.report.snapshots(),
        }

    def stop_all(self) -> None:
        for w in list(self._workers.values()):
            w.stop()
        self._workers.clear()
