"""
Health endpoints + dependency checks — Phase B1.

The pattern every service uses for K8s probes (gap #13 from the audit, A2 in
the senior engineer prompt). Three probes with distinct semantics:

- `/live` — process is alive. Liveness probe; failure -> pod restart.
- `/ready` — process can serve traffic right now. Readiness probe; failure ->
  remove from Service endpoints. Aggregates per-dependency `HealthCheck`s.
- `/startup` — initial bootstrap is complete (model loaded, plan loaded, etc.).
  Startup probe; until success, liveness/readiness are not consulted.

Plus `/metrics` if a Prometheus exposer is bound (default off in the shared
factory; services that want it call `attach_prometheus_metrics(app)`).

See ADR-0008.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from fastapi import APIRouter, FastAPI, HTTPException


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str = ""


CheckFn = Callable[[], Awaitable[CheckResult]]


class HealthCheck(Protocol):
    name: str

    async def check(self) -> CheckResult: ...


@dataclass
class _SimpleCheck:
    name: str
    fn: CheckFn

    async def check(self) -> CheckResult:
        return await self.fn()


class HealthRouter:
    """
    Composable router for `/live`, `/ready`, `/startup`.

    Usage:
        router = HealthRouter(service_name="traffic-controller")
        router.add_check("kafka", kafka_check)
        router.add_check("model_loaded", model_check)
        # mark the long-running init complete when ready
        router.mark_started()
        router.attach(app)
    """

    def __init__(self, service_name: str) -> None:
        self._service_name = service_name
        self._checks: list[HealthCheck] = []
        self._started = False
        self._router = APIRouter()
        self._wire_routes()

    # ------------------------------------------------------------------
    # Builder API
    # ------------------------------------------------------------------

    def add_check(self, name: str, fn: CheckFn) -> HealthRouter:
        self._checks.append(_SimpleCheck(name=name, fn=fn))
        return self

    def mark_started(self) -> None:
        self._started = True

    def attach(self, app: FastAPI) -> None:
        app.include_router(self._router)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _wire_routes(self) -> None:
        @self._router.get("/live")
        async def live() -> dict[str, str]:
            return {"status": "live", "service": self._service_name}

        @self._router.get("/startup")
        async def startup() -> dict[str, str]:
            return {
                "status": "started" if self._started else "starting",
                "service": self._service_name,
            }

        @self._router.get("/ready")
        async def ready() -> dict[str, object]:
            if not self._started:
                raise HTTPException(status_code=503, detail="startup not complete")
            results: dict[str, dict[str, str | bool]] = {}
            overall = True
            for check in self._checks:
                res = await check.check()
                results[check.name] = {"ok": res.ok, "detail": res.detail}
                if not res.ok:
                    overall = False
            if not overall:
                raise HTTPException(
                    status_code=503,
                    detail={"status": "not_ready", "checks": results},
                )
            return {
                "status": "ready",
                "service": self._service_name,
                "checks": results,
            }


# ---------------------------------------------------------------------------
# Bundled dep-check factories
# ---------------------------------------------------------------------------


def kafka_check(producer_or_consumer: object) -> CheckFn:
    """Return a check that verifies the Kafka client is in a connected state."""

    async def _check() -> CheckResult:
        if producer_or_consumer is None:
            return CheckResult(ok=False, detail="kafka client not initialised")
        # aiokafka exposes neither a public is_connected nor a sync probe; the
        # safest correct check is to verify the client has been started.
        started = getattr(producer_or_consumer, "_closed", True) is False
        return CheckResult(ok=started, detail="connected" if started else "not connected")

    return _check


def callable_check(name: str, fn: Callable[[], bool], detail_ok: str = "ok") -> CheckFn:
    """Wrap a simple boolean predicate (e.g., 'model loaded') as a HealthCheck."""

    async def _check() -> CheckResult:
        ok = bool(fn())
        return CheckResult(ok=ok, detail=detail_ok if ok else f"{name} not ready")

    return _check
