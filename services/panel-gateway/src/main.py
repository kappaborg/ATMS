"""
ATMS Panel Gateway.

A self-contained FastAPI service that ingests 1-4 cameras (RTSP / HTTP-MJPEG /
USB index / local file), runs the ATMS perception + decision pipeline per
camera, and serves a desktop panel:

  REST
    GET    /health
    GET    /cameras
    POST   /cameras                {camera_id, source, loop_file?}
    DELETE /cameras/{camera_id}
  WebSocket
    /ws/data                       JSON events (detections, decision, metrics)
    /ws/video/{camera_id}          binary JPEG frames (latest-wins)

The panel is a MONITORING surface only — it is never in the safety-critical
control loop (the traffic-controller failsafe owns that).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from hub import CameraManager, Hub

VIDEO_FPS = float(os.getenv("PANEL_VIDEO_FPS", "20"))

hub = Hub()
manager = CameraManager(hub)
app = FastAPI(title="ATMS Panel Gateway", version="1.0.0")

# Tauri dev server / localhost origins. Pin via PANEL_CORS_ORIGINS in prod.
_origins = [o for o in os.getenv("PANEL_CORS_ORIGINS", "http://localhost:1420,tauri://localhost").split(",") if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CameraIn(BaseModel):
    camera_id: str
    source: str  # "rtsp://...", "http://...", "0" (USB), or a file path
    loop_file: bool = True


@app.on_event("startup")
async def _startup() -> None:
    hub.bind_loop(asyncio.get_running_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    manager.stop_all()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "cameras": len(manager.list())}


@app.get("/cameras")
async def list_cameras() -> list[dict]:
    return manager.list()


@app.post("/cameras")
async def add_camera(cam: CameraIn) -> dict:
    try:
        manager.add(cam.camera_id, cam.source, loop_file=cam.loop_file)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "added", "camera_id": cam.camera_id}


@app.delete("/cameras/{camera_id}")
async def remove_camera(camera_id: str) -> dict:
    try:
        manager.remove(camera_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="camera not found")
    return {"status": "removed", "camera_id": camera_id}


@app.websocket("/ws/data")
async def ws_data(ws: WebSocket) -> None:
    await ws.accept()
    q = hub.register_data_client()
    try:
        while True:
            event = await q.get()
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister_data_client(q)


@app.websocket("/ws/video/{camera_id}")
async def ws_video(ws: WebSocket, camera_id: str) -> None:
    await ws.accept()
    interval = 1.0 / max(VIDEO_FPS, 1.0)
    last_sent: int | None = None
    try:
        while True:
            frame = hub.latest_frame(camera_id)
            # Only send when the frame actually changed (id-based), so a paused
            # or slow camera doesn't waste bandwidth re-sending the same image.
            fid = id(frame)
            if frame is not None and fid != last_sent:
                await ws.send_bytes(frame)
                last_sent = fid
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass
