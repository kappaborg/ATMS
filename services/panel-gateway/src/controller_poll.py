"""
Poll traffic-controller /health endpoints for the failsafe mode.

Each ATMS intersection runs a traffic-controller whose /health endpoint
(unauthenticated) returns its current failsafe mode. The gateway polls the
configured controllers and feeds the mode into SystemState.

Config: PANEL_CONTROLLER_URLS = "1=http://host:8010,2=http://host2:8010"
(intersection_id=base_url, comma-separated). A bare URL maps to intersection
"1". Poll interval: PANEL_CONTROLLER_POLL_S (default 2).

Uses stdlib urllib in a thread executor — no extra dependency.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.request

log = logging.getLogger("panel.controller")


def parse_mapping(spec: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        if "=" in part:
            iid, url = part.split("=", 1)
            mapping[iid.strip()] = url.strip().rstrip("/")
        else:
            mapping["1"] = part.rstrip("/")
    return mapping


def _fetch_mode(url: str, timeout: float = 3.0) -> str | None:
    with urllib.request.urlopen(f"{url}/health", timeout=timeout) as r:  # noqa: S310 (fixed scheme)
        data = json.loads(r.read().decode("utf-8"))
    mode = data.get("mode")
    return str(mode) if mode is not None else None


async def run_controller_poller(
    mapping: dict[str, str], system, stop: asyncio.Event, interval: float = 2.0
) -> None:
    loop = asyncio.get_running_loop()
    log.info("polling %d controller(s) for failsafe mode", len(mapping))
    while not stop.is_set():
        for iid, url in mapping.items():
            try:
                mode = await loop.run_in_executor(None, _fetch_mode, url)
                system.set_mode(iid, mode, reachable=True)
            except Exception as e:  # noqa: BLE001 — controller may be down
                system.set_mode(iid, None, reachable=False)
                log.debug("controller %s (%s) unreachable: %s", iid, url, e)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
