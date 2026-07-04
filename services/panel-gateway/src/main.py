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

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from hub import CameraManager, Hub
from limits import RateLimiter, WSLimiter, max_cameras
from scene import SceneConfig
from security import SourceRejected, api_token, check_token, validate_source
from system_state import SystemState

VIDEO_FPS = float(os.getenv("PANEL_VIDEO_FPS", "20"))
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
CONTROLLER_URLS = os.getenv("PANEL_CONTROLLER_URLS", "")
CONTROLLER_POLL_S = float(os.getenv("PANEL_CONTROLLER_POLL_S", "2"))

hub = Hub()
system = SystemState()
manager = CameraManager(hub, system=system)
rate_limiter = RateLimiter()
ws_limiter = WSLimiter()
_stop = asyncio.Event()
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
    intersection_id: str = "1"  # which ATMS intersection this camera watches


async def require_auth(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    """REST guard — no-op unless PANEL_API_TOKEN is set."""
    check_token(authorization, token)


async def rate_limit(request: Request) -> None:
    """Per-client-IP sliding-window limit on mutating requests."""
    key = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(key):
        raise HTTPException(status_code=429, detail="rate limit exceeded")


_AUTH = Depends(require_auth)
_RATE = Depends(rate_limit)


@app.on_event("startup")
async def _startup() -> None:
    import logging

    log = logging.getLogger("uvicorn")
    host = os.getenv("PANEL_HOST", "127.0.0.1")
    loopback = host in ("127.0.0.1", "localhost", "::1")
    if not loopback and not api_token():
        log.warning(
            "⚠ Panel gateway bound to %s WITHOUT PANEL_API_TOKEN — it is "
            "reachable on the network and UNAUTHENTICATED. Set PANEL_API_TOKEN "
            "or bind to 127.0.0.1.",
            host,
        )
    hub.bind_loop(asyncio.get_running_loop())
    n = manager.restore()
    if n:
        log.info("restored %d camera(s) from saved state", n)
    if KAFKA_BOOTSTRAP:
        from kafka_bridge import run_decisions_consumer

        asyncio.create_task(run_decisions_consumer(KAFKA_BOOTSTRAP, system, _stop))
    if CONTROLLER_URLS:
        from controller_poll import parse_mapping, run_controller_poller

        mapping = parse_mapping(CONTROLLER_URLS)
        asyncio.create_task(run_controller_poller(mapping, system, _stop, CONTROLLER_POLL_S))


@app.on_event("shutdown")
async def _shutdown() -> None:
    _stop.set()
    manager.stop_all()


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "cameras": len(manager.list()),
        "strict_live": os.getenv("ATMS_STRICT_LIVE", "").lower() in ("1", "true", "yes"),
        "limits": {"max_cameras": max_cameras(), "ws_clients": ws_limiter.count},
        "system_stream": {"enabled": bool(KAFKA_BOOTSTRAP), "connected": system.connected},
    }


@app.get("/cameras")
async def list_cameras(_: None = _AUTH) -> list[dict]:
    return manager.list()


@app.get("/devices")
async def list_devices(_: None = _AUTH) -> list[dict]:
    """Probe local video device indices (USB webcams, macOS Continuity Camera
    for iPhone). Returns the indices that open, with their frame size. On
    macOS the first probe triggers a camera-permission prompt for the process
    running the gateway."""
    import cv2

    def probe() -> list[dict]:
        found = []
        for i in range(4):
            cap = cv2.VideoCapture(i)
            try:
                if cap.isOpened():
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        found.append(
                            {"index": i, "width": int(frame.shape[1]), "height": int(frame.shape[0])}
                        )
            finally:
                cap.release()
        return found

    return await asyncio.get_running_loop().run_in_executor(None, probe)


@app.post("/cameras")
async def add_camera(cam: CameraIn, _: None = _AUTH, __: None = _RATE) -> dict:
    if len(manager.list()) >= max_cameras():
        raise HTTPException(status_code=429, detail=f"camera limit reached ({max_cameras()})")
    try:
        safe_source = validate_source(cam.source)
    except SourceRejected as e:
        raise HTTPException(status_code=400, detail=f"rejected source: {e}")
    try:
        manager.add(
            cam.camera_id, safe_source, loop_file=cam.loop_file, intersection_id=cam.intersection_id
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "added", "camera_id": cam.camera_id}


@app.delete("/cameras/{camera_id}")
async def remove_camera(camera_id: str, _: None = _AUTH, __: None = _RATE) -> dict:
    try:
        manager.remove(camera_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="camera not found")
    return {"status": "removed", "camera_id": camera_id}


@app.get("/cameras/{camera_id}/report")
async def camera_report(camera_id: str, format: str = "csv", _: None = _AUTH):
    """Session KPI report (vehicles, incidents, measured CO2 + estimated
    savings, per-minute time-series). format=csv (default, downloadable) or json."""
    try:
        if format == "json":
            return manager.report_json(camera_id)
        csv_text = manager.report_csv(camera_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="camera not found")
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="atms-report-{camera_id}.csv"'},
    )


@app.post("/cameras/{camera_id}/scene")
async def set_scene(camera_id: str, payload: dict, _: None = _AUTH, __: None = _RATE) -> dict:
    """Set calibration and/or approach zones for a camera.

    Body: {
      "calibration": {"image_points": [[x,y],...], "world_points_m": [[X,Y],...]},
      "zones": {"north": [[x,y],...], ...},
      "zone_directions": {"north": "ns", "east": "ew", ...}
    }
    All fields optional. Returns the applied scene info (incl. reprojection error).
    """
    try:
        scene = SceneConfig.from_payload(payload)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"invalid scene: {e}")
    try:
        return manager.set_scene(camera_id, scene)
    except KeyError:
        raise HTTPException(status_code=404, detail="camera not found")


def _ws_authorized(ws: WebSocket, token: str | None) -> bool:
    try:
        check_token(ws.headers.get("authorization"), token)
        return True
    except HTTPException:
        return False


@app.websocket("/ws/data")
async def ws_data(ws: WebSocket, token: str | None = Query(default=None)) -> None:
    if not _ws_authorized(ws, token):
        await ws.close(code=1008)  # policy violation
        return
    if not ws_limiter.acquire():
        await ws.close(code=1013)  # try again later
        return
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
        ws_limiter.release()


@app.websocket("/ws/video/{camera_id}")
async def ws_video(ws: WebSocket, camera_id: str, token: str | None = Query(default=None)) -> None:
    if not _ws_authorized(ws, token):
        await ws.close(code=1008)
        return
    if not ws_limiter.acquire():
        await ws.close(code=1013)
        return
    await ws.accept()
    hub.add_video_viewer()
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
    finally:
        hub.remove_video_viewer()
        ws_limiter.release()
