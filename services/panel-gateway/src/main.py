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
from typing import Literal

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
from pydantic import BaseModel, Field

# A client closing mid-send makes send_bytes/send_json raise the underlying
# websockets ConnectionClosed (not WebSocketDisconnect) — treat both as a
# normal disconnect so a routine close doesn't log an ASGI traceback.
try:
    from websockets.exceptions import ConnectionClosed as _WSClosed

    _WS_DISCONNECTS: tuple = (WebSocketDisconnect, _WSClosed)
except Exception:  # noqa: BLE001
    _WS_DISCONNECTS = (WebSocketDisconnect,)

from hub import CameraManager, Hub
from limits import RateLimiter, WSLimiter, max_cameras
from panel_auth import Principal, auth_enabled, authenticate, issue_token, principal_from_token
from scene import SceneConfig
from security import SourceRejected, validate_source
from system_state import SystemState

VIDEO_FPS = float(os.getenv("PANEL_VIDEO_FPS", "20"))
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
CONTROLLER_URLS = os.getenv("PANEL_CONTROLLER_URLS", "")
CONTROLLER_POLL_S = float(os.getenv("PANEL_CONTROLLER_POLL_S", "2"))

hub = Hub()
system = SystemState()
manager = CameraManager(hub, system=system)
rate_limiter = RateLimiter()
# Dedicated, much stricter budget for /auth/login (brute-force defence), keyed
# by IP+username. Configurable via PANEL_LOGIN_RATE (default 5 attempts / 60s).
login_limiter = RateLimiter(os.getenv("PANEL_LOGIN_RATE", "5/60"))
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
    # camera_id/intersection_id are used to build filesystem paths (snapshot
    # filenames) and route paths — constrain them to a safe charset so a value
    # like "../../etc" cannot traverse out of the snapshot directory.
    camera_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    source: str  # "rtsp://...", "http://...", "0" (USB), or a file path
    loop_file: bool = True
    intersection_id: str = Field(default="1", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    # Which arm of the junction the camera watches. Display metadata: it is what
    # distinguishes two cameras on the same junction in the UI.
    approach: Literal["north", "south", "east", "west"] | None = None
    sahi: bool = False  # sliced inference for aerial/small-object views (slower)
    min_confidence: float | None = Field(default=None, ge=0.05, le=0.95)


class JunctionIn(BaseModel):
    # Free text, unlike the ids above: never used to build a path, and rendered
    # as text content (Svelte escapes it), so it is not a traversal or XSS
    # vector. Length-capped to keep the map legible and the state file bounded.
    name: str = Field(default="", max_length=64)
    city: str = Field(default="", max_length=64)


def _resolve_principal(authorization: str | None, token: str | None) -> Principal | None:
    """Bearer header (or ?token= for WebSockets) -> Principal. When auth is
    disabled (no users / no API token configured) everything runs as a local
    admin so the desktop dev flow needs no login."""
    if not auth_enabled():
        return Principal(sub="local", role="admin")
    tok = None
    if authorization and authorization.lower().startswith("bearer "):
        tok = authorization[7:].strip()
    elif token:
        tok = token
    return principal_from_token(tok)


def require_role(minimum: str):
    """Dependency factory: require an authenticated principal with >= role."""

    async def dep(
        authorization: str | None = Header(default=None),
        token: str | None = Query(default=None),
    ) -> Principal:
        p = _resolve_principal(authorization, token)
        if p is None:
            raise HTTPException(status_code=401, detail="authentication required")
        if not p.has_role(minimum):
            raise HTTPException(status_code=403, detail=f"requires '{minimum}' role")
        return p

    return dep


async def rate_limit(request: Request) -> None:
    """Per-client-IP sliding-window limit on mutating requests."""
    key = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(key):
        raise HTTPException(status_code=429, detail="rate limit exceeded")


def _audit(p: Principal, action: str, detail: str = "") -> None:
    """Append-only operator audit line — who did what (accountability)."""
    import logging

    logging.getLogger("panel.audit").info(
        "AUDIT user=%s role=%s action=%s %s", p.sub, p.role, action, detail
    )


_VIEWER = Depends(require_role("viewer"))
_OPERATOR = Depends(require_role("operator"))
_RATE = Depends(rate_limit)


@app.on_event("startup")
async def _startup() -> None:
    import logging

    log = logging.getLogger("uvicorn")
    host = os.getenv("PANEL_HOST", "127.0.0.1")
    loopback = host in ("127.0.0.1", "localhost", "::1")
    insecure_ok = os.getenv("PANEL_ALLOW_INSECURE_BIND", "").lower() in ("1", "true", "yes")
    if not loopback and not auth_enabled():
        if not insecure_ok:
            # Fail closed: refuse to expose an unauthenticated gateway on the
            # network. Every mutating endpoint (add-camera → SSRF, preempt,
            # plate query, CSV export) would otherwise be open to anyone who can
            # reach it.
            raise RuntimeError(
                f"Refusing to start: PANEL_HOST={host} is not loopback but no auth "
                "is configured. Set PANEL_USERS (multi-operator RBAC) or "
                "PANEL_API_TOKEN, or bind to 127.0.0.1. To override at your own "
                "risk, set PANEL_ALLOW_INSECURE_BIND=1."
            )
        log.warning(
            "⚠ Panel gateway bound to %s with NO auth (PANEL_ALLOW_INSECURE_BIND "
            "set) — reachable and UNAUTHENTICATED on the network.", host,
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

    # Violation-evidence retention: enforce PANEL_VIOLATION_RETENTION_DAYS
    # (rows + snapshot files) at startup and every 6 hours. 0/unset = keep.
    retention_days = float(os.getenv("PANEL_VIOLATION_RETENTION_DAYS", "0"))
    if retention_days > 0:
        async def _retention_loop() -> None:
            import time as _time

            import violations_log

            while not _stop.is_set():
                try:
                    n = await asyncio.get_running_loop().run_in_executor(
                        None, violations_log.get_log().sweep, retention_days, _time.time()
                    )
                    if n:
                        log.info("retention: pruned %d violation(s) older than %.0f days", n, retention_days)
                except Exception as e:  # noqa: BLE001 — retention must never kill the gateway
                    log.warning("retention sweep failed: %s", e)
                try:
                    await asyncio.wait_for(_stop.wait(), timeout=6 * 3600)
                except asyncio.TimeoutError:
                    pass

        asyncio.create_task(_retention_loop())


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
        "auth_enabled": auth_enabled(),
        "limits": {"max_cameras": max_cameras(), "ws_clients": ws_limiter.count},
        "system_stream": {"enabled": bool(KAFKA_BOOTSTRAP), "connected": system.connected},
    }


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
async def login(body: LoginIn, request: Request, __: None = _RATE) -> dict:
    """Exchange operator credentials for a signed session token."""
    ip = request.client.host if request.client else "unknown"
    # Strict per-(IP, username) throttle so credential stuffing can't ride the
    # looser mutating-request budget.
    if not login_limiter.allow(f"{ip}:{body.username}"):
        raise HTTPException(status_code=429, detail="too many login attempts — try again shortly")
    p = authenticate(body.username, body.password)
    if p is None:
        import logging

        logging.getLogger("panel.audit").warning(
            "AUDIT login-failed user=%s ip=%s", body.username, ip
        )
        raise HTTPException(status_code=401, detail="invalid credentials")
    token, exp = issue_token(p)
    _audit(p, "login")
    return {"token": token, "username": p.sub, "role": p.role, "expires_epoch": exp}


@app.get("/auth/me")
async def whoami(p: Principal = _VIEWER) -> dict:
    """Resolve the caller's identity/role (frontend uses this to validate a
    stored token and tailor the UI)."""
    return {"username": p.sub, "role": p.role}


@app.get("/cameras")
async def list_cameras(_: Principal = _VIEWER) -> list[dict]:
    return manager.list()


@app.get("/devices")
async def list_devices(_: Principal = _VIEWER) -> list[dict]:
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
async def add_camera(cam: CameraIn, p: Principal = _OPERATOR, __: None = _RATE) -> dict:
    if len(manager.list()) >= max_cameras():
        raise HTTPException(status_code=429, detail=f"camera limit reached ({max_cameras()})")
    try:
        safe_source = validate_source(cam.source)
    except SourceRejected as e:
        raise HTTPException(status_code=400, detail=f"rejected source: {e}")
    try:
        manager.add(
            cam.camera_id, safe_source, loop_file=cam.loop_file,
            intersection_id=cam.intersection_id, sahi=cam.sahi,
            min_confidence=cam.min_confidence, approach=cam.approach,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _audit(p, "add_camera", f"id={cam.camera_id}")
    return {"status": "added", "camera_id": cam.camera_id}


class SahiIn(BaseModel):
    enabled: bool


@app.post("/cameras/{camera_id}/sahi")
async def set_camera_sahi(camera_id: str, body: SahiIn, p: Principal = _OPERATOR, __: None = _RATE) -> dict:
    """Toggle SAHI sliced inference for one camera (aerial/small-object views).
    Slower per frame — enable only where objects are too small for whole-frame."""
    try:
        manager.set_sahi(camera_id, body.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail="camera not found")
    _audit(p, "set_sahi", f"id={camera_id} enabled={body.enabled}")
    return {"status": "ok", "camera_id": camera_id, "sahi": body.enabled}


class ConfidenceIn(BaseModel):
    min_confidence: float = Field(ge=0.05, le=0.95)


@app.post("/cameras/{camera_id}/confidence")
async def set_camera_confidence(camera_id: str, body: ConfidenceIn, p: Principal = _OPERATOR, __: None = _RATE) -> dict:
    """Set a camera's detection-confidence floor. Raise it to remove wrong
    boxes on noisy scenes (water/reflections/foliage); lower it for recall."""
    try:
        manager.set_min_confidence(camera_id, body.min_confidence)
    except KeyError:
        raise HTTPException(status_code=404, detail="camera not found")
    _audit(p, "set_confidence", f"id={camera_id} min={body.min_confidence}")
    return {"status": "ok", "camera_id": camera_id, "min_confidence": body.min_confidence}


@app.delete("/cameras/{camera_id}")
async def remove_camera(camera_id: str, p: Principal = _OPERATOR, __: None = _RATE) -> dict:
    try:
        manager.remove(camera_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="camera not found")
    _audit(p, "remove_camera", f"id={camera_id}")
    return {"status": "removed", "camera_id": camera_id}


@app.get("/cameras/{camera_id}/report")
async def camera_report(camera_id: str, format: str = "csv", _: Principal = _VIEWER):
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


@app.get("/violations")
async def list_violations(
    hours: float = 24.0, camera_id: str | None = None, type: str | None = None,
    plate: str | None = None, limit: int = 500, p: Principal = _VIEWER,
) -> dict:
    """The persisted violation evidence log (type, plate, detail, snapshot).
    `plate` filter supports data-subject access requests (DSAR)."""
    import time as _time

    import violations_log

    # A targeted plate lookup is a DSAR-grade query over personal data — require
    # operator, and audit it (least privilege for PII; plain browsing stays viewer).
    if plate:
        if not p.has_role("operator"):
            raise HTTPException(status_code=403, detail="plate lookup requires 'operator' role")
        _audit(p, "violations_plate_lookup", f"plate={plate}")

    hours = max(0.0, min(hours, 24 * 366))
    now = int(_time.time())
    rows = violations_log.get_log().query(
        now - int(hours * 3600), now, camera_id, type,
        min(max(limit, 1), 2000), plate=plate,
    )
    return {"violations": rows}


@app.delete("/violations/{vid}")
async def delete_violation(vid: int, p: Principal = _OPERATOR, __: None = _RATE) -> dict:
    """Erase one violation record + its snapshot (DSAR erasure / correction).
    Audited."""
    import violations_log

    path = violations_log.get_log().snapshot_path(vid)
    n = violations_log.get_log().delete(vid)
    if n == 0:
        raise HTTPException(status_code=404, detail="violation not found")
    if path:
        try:
            Path(path).unlink()
        except OSError:
            pass
    _audit(p, "delete_violation", f"id={vid}")
    return {"status": "deleted", "id": vid}


@app.get("/violations/{vid}/snapshot")
async def violation_snapshot(vid: int, _: Principal = _VIEWER):
    """The evidence snapshot image for a violation."""
    import violations_log

    path = violations_log.get_log().snapshot_path(vid)
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="no snapshot")
    return Response(content=Path(path).read_bytes(), media_type="image/jpeg")


@app.get("/violations/export")
async def export_violations(hours: float = 168.0, p: Principal = _OPERATOR, __: None = _RATE):
    """CSV export of the violation log (for enforcement / audit). Bulk PII
    export — restricted to operators and audited."""
    import csv
    import io
    import time as _time

    import violations_log

    _audit(p, "violations_export", f"hours={hours}")
    hours = max(0.0, min(hours, 24 * 366))
    now = int(_time.time())
    rows = violations_log.get_log().query(now - int(hours * 3600), now, None, None, 5000)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "timestamp_epoch", "camera_id", "intersection_id", "track_id",
                "type", "plate", "detail", "has_snapshot"])
    for r in rows:
        w.writerow([r["id"], r["ts"], r["camera_id"], r["intersection_id"], r["track_id"],
                    r["type"], r["plate"] or "", r["detail"], r["has_snapshot"]])
    return Response(content=out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="atms-violations.csv"'})


@app.put("/intersections/{iid}")
async def set_junction(
    iid: str, body: JunctionIn, p: Principal = _OPERATOR, __: None = _RATE
) -> dict:
    """Name a junction (e.g. city "Sarajevo", name "Marijin Dvor") so the map
    reads as places rather than ids. Sending both fields empty clears the name."""
    try:
        meta = manager.set_junction(iid, body.name, body.city)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _audit(p, "set_junction", f"id={iid}")
    return {"intersection_id": iid, **meta}


@app.get("/intersections")
async def list_intersections(_: Principal = _VIEWER) -> list[dict]:
    """Network overview: every intersection with its cameras and the
    authoritative controller/failsafe state (from the ATMS decisions topic +
    controller polling, when connected)."""
    out = []
    for grp in manager.intersections():
        out.append({
            **grp,
            "system": system.get(grp["intersection_id"]) if system else None,
        })
    return out


@app.get("/corridors")
async def list_corridors(_: Principal = _VIEWER) -> list[dict]:
    """Green-wave corridors with their computed offset schedule, green bands
    and design-speed trajectory (for the time-space diagram)."""
    return manager.list_corridors()


@app.post("/corridors")
async def add_corridor(payload: dict, p: Principal = _OPERATOR, __: None = _RATE) -> dict:
    """Define a corridor and coordinate its intersections into a green wave.
    Body: {corridor_id, direction?, design_speed_kmh?, cycle_s?, green_s?,
           stops:[{intersection_id, distance_m}]}."""
    try:
        result = manager.add_corridor(payload)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"invalid corridor: {e}")
    _audit(p, "add_corridor", f"id={payload.get('corridor_id')}")
    return result


@app.delete("/corridors/{corridor_id}")
async def remove_corridor(corridor_id: str, p: Principal = _OPERATOR, __: None = _RATE) -> dict:
    try:
        manager.remove_corridor(corridor_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="corridor not found")
    _audit(p, "remove_corridor", f"id={corridor_id}")
    return {"status": "removed", "corridor_id": corridor_id}


@app.get("/history")
async def history_range(
    hours: float = 24.0,
    bucket_min: float = 60.0,
    camera_id: str | None = None,
    _: Principal = _VIEWER,
) -> dict:
    """Long-horizon totals + time-bucketed series over the last `hours`
    (persisted across restarts). Optionally scoped to one camera."""
    import time as _time

    import history

    # Clamp inputs: guard against a 0/negative bucket (SQL divide-by-zero) and
    # absurd ranges from a malformed client.
    hours = max(0.0, min(hours, 24 * 366))          # <= ~1 year
    bucket_min = min(max(bucket_min, 1.0), 24 * 60)  # 1 min .. 1 day
    now = int(_time.time())
    since = now - int(hours * 3600)
    store = history.get_store()
    return {
        "since_epoch": since,
        "until_epoch": now,
        "totals": store.totals(since, now, camera_id),
        "series": store.series(since, now, int(bucket_min * 60), camera_id),
    }


class PreemptIn(BaseModel):
    direction: str  # "north_south" | "east_west"
    active: bool = True
    hold_s: float | None = None  # auto-clear after N seconds; None = hold


@app.post("/cameras/{camera_id}/preempt")
async def preempt(camera_id: str, body: PreemptIn, p: Principal = _OPERATOR, __: None = _RATE) -> dict:
    """Emergency-vehicle preemption — force an approach to green for an
    approaching ambulance/fire/police, then release. Operator-triggered here;
    production integrates dispatch/V2X (Opticom-style)."""
    try:
        manager.preempt(camera_id, body.direction, body.active, body.hold_s)
    except KeyError:
        raise HTTPException(status_code=404, detail="camera not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _audit(p, "preempt", f"id={camera_id} dir={body.direction} active={body.active}")
    return {"status": "ok", "preemption": body.direction if body.active else None}


@app.post("/cameras/{camera_id}/scene")
async def set_scene(camera_id: str, payload: dict, p: Principal = _OPERATOR, __: None = _RATE) -> dict:
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
        result = manager.set_scene(camera_id, scene)
    except KeyError:
        raise HTTPException(status_code=404, detail="camera not found")
    _audit(p, "set_scene", f"id={camera_id}")
    return result


def _ws_authorized(ws: WebSocket, token: str | None) -> bool:
    p = _resolve_principal(ws.headers.get("authorization"), token)
    return p is not None and p.has_role("viewer")


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
    except _WS_DISCONNECTS:
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
    except _WS_DISCONNECTS:
        pass
    finally:
        hub.remove_video_viewer()
        ws_limiter.release()
