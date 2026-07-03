"""
Connection hub + camera manager.

Bridges worker THREADS (which call set_frame/publish_event) to asyncio
WebSocket clients. Video is latest-wins per camera; data events are fanned
out to per-connection bounded queues (drop-oldest on overflow so a slow
client never adds latency for others).
"""
from __future__ import annotations

import asyncio
from typing import Any

import store
from detection import Detector
from scene import SceneConfig
from worker import CameraWorker


class Hub:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._frames: dict[str, bytes] = {}
        self._data_queues: set[asyncio.Queue] = set()

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


class CameraManager:
    def __init__(self, hub: Hub, system=None) -> None:
        self.hub = hub
        self.system = system  # SystemState | None
        self._detector: Detector | None = None
        self._workers: dict[str, CameraWorker] = {}

    def _detector_lazy(self) -> Detector:
        if self._detector is None:
            self._detector = Detector()
        return self._detector

    def add(
        self, cam_id: str, source: str | int, *, loop_file: bool = True, intersection_id: str = "1"
    ) -> None:
        if cam_id in self._workers:
            raise ValueError(f"camera '{cam_id}' already exists")
        worker = CameraWorker(
            cam_id, source, self._detector_lazy(), self.hub,
            loop_file=loop_file, intersection_id=intersection_id, system=self.system,
        )
        self._workers[cam_id] = worker
        worker.start()
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
            }
            payload = w.scene.to_payload()
            if payload:
                entry["scene"] = payload
            cams.append(entry)
        store.save({"cameras": cams})

    def restore(self) -> int:
        """Re-create cameras and re-apply scenes from the saved state.
        Returns the number of cameras restored. Never raises on a bad entry."""
        restored = 0
        for entry in store.load().get("cameras", []):
            try:
                cam_id = entry["camera_id"]
                self.add(
                    cam_id,
                    entry["source"],
                    loop_file=entry.get("loop_file", True),
                    intersection_id=str(entry.get("intersection_id", "1")),
                )
                if entry.get("scene"):
                    self.set_scene(cam_id, SceneConfig.from_payload(entry["scene"]))
                restored += 1
            except Exception:  # noqa: BLE001 — one bad entry must not block the rest
                continue
        return restored

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "camera_id": w.cam_id,
                "source": str(w.source),
                "status": w.status,
                "error": w.error,
                "fps": round(w.fps, 1),
                "scene": w.scene.info(),
            }
            for w in self._workers.values()
        ]

    def stop_all(self) -> None:
        for w in list(self._workers.values()):
            w.stop()
        self._workers.clear()
