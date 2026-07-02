"""NTCIP-1202 over SNMPv3 — production secure controller bridge.

Phase 6 production-grade upgrade from the Phase 2 SNMPv1 bridge.
SNMPv3 adds:

- **User-based Security Model (USM)** — per-user credentials, not a
  community string shared across an entire ops network.
- **Authentication** — HMAC-SHA1 message digest. Detects packet
  tampering. Required by KJP ops; SNMPv1 community auth is not
  acceptable for production.
- **Encryption** — AES-CFB-128. Protects phase commands from
  passive snooping on the operations LAN.

Three security levels (RFC 3414 §1.2):

| Level | Auth | Priv | When |
|---|---|---|---|
| `noAuthNoPriv` | none | none | dev only — same security as v1 |
| `authNoPriv` | HMAC-SHA1 | none | trusted physical network, tampering protection |
| `authPriv` | HMAC-SHA1 | AES-CFB-128 | production — pilot deployment default |

Engine discovery: SNMPv3 requires the client to discover the
remote engine's ID, boot count, and time before sending an
authenticated request. puresnmp handles this transparently on the
first call.

Wire compatibility: any NTCIP-1202 controller speaking SNMPv3 USM
accepts these packets (Swarco MX-PRO, Yunex Sitraffic sX, McCain ATC).
Older legacy controllers (Marvell) may not support v3 — they need
firmware upgrade or replacement before pilot deployment.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Protocol

from simulation.decision_chamber.controller_bridge import (
    DIRECTION_TO_PHASE,
    NTCIP_PHASE_FORCE_OFF_BASE,
    NTCIP_PHASE_STATUS_GREEN,
    ControllerBridge,
)
from simulation.decision_chamber.state import ChamberOutput

log = logging.getLogger("atms.chamber.ntcip_v3")


class NtcipV3ControllerBridge:
    """Real NTCIP-1202 over SNMPv3 USM. Used in production where SNMPv1
    community-string auth is not acceptable (most municipal pilots,
    including Sarajevo KJP).

    Same `send_phase_request()` + `get_actual_phase()` interface as
    `NtcipControllerBridge` — drop-in replacement when the site
    config specifies SNMPv3 credentials.

    `auth_passphrase` and `priv_passphrase` are usernames/keys derived
    per RFC 3414 §A.2. Operations team stores these in a secrets
    manager (Vault, AWS Secrets Manager, KJP's internal HSM) and
    references them via env var in the site YAML.
    """

    name = "ntcip_1202_snmpv3"

    def __init__(
        self,
        controller_host: str = "127.0.0.1",
        controller_port: int = 161,
        username: str = "atms-chamber",
        auth_passphrase: str | None = None,
        priv_passphrase: str | None = None,
        security_level: str = "authPriv",  # 'noAuthNoPriv' | 'authNoPriv' | 'authPriv'
        timeout_seconds: float = 1.0,
        closed_loop_poll_interval_s: float = 2.0,
    ):
        try:
            import puresnmp  # noqa: F401, PLC0415
            from puresnmp.credentials import V3, Auth, Priv  # noqa: PLC0415
        except ImportError as e:
            raise RuntimeError(
                "puresnmp required for SNMPv3 NTCIP. "
                "Install: pip install 'puresnmp[crypto]'"
            ) from e

        self._host = controller_host
        self._port = controller_port
        self._username = username
        self._timeout = timeout_seconds
        self._poll_interval = closed_loop_poll_interval_s

        # Build the credentials object matching the requested security level
        auth_obj = None
        priv_obj = None
        if security_level == "authPriv":
            if not auth_passphrase or not priv_passphrase:
                raise ValueError(
                    "authPriv requires both auth_passphrase and priv_passphrase"
                )
            auth_obj = Auth(auth_passphrase.encode("utf-8"), method="sha1")
            priv_obj = Priv(priv_passphrase.encode("utf-8"), method="aes")
        elif security_level == "authNoPriv":
            if not auth_passphrase:
                raise ValueError("authNoPriv requires auth_passphrase")
            auth_obj = Auth(auth_passphrase.encode("utf-8"), method="sha1")
        elif security_level == "noAuthNoPriv":
            pass
        else:
            raise ValueError(
                f"unknown security_level {security_level!r}; "
                "expected noAuthNoPriv | authNoPriv | authPriv"
            )

        self._credentials = V3(username=username, auth=auth_obj, priv=priv_obj)
        self._security_level = security_level

        # Closed-loop status read-back cache (mirrors v1 bridge pattern)
        self._status_lock = threading.Lock()
        self._last_actual_phase: dict | None = None
        self._poll_thread: threading.Thread | None = None
        self._stop = threading.Event()
        if closed_loop_poll_interval_s > 0:
            self._start_status_poller()

        log.info(
            "SNMPv3 bridge target: %s:%d  user=%s  level=%s  closed-loop=%s",
            controller_host, controller_port, username, security_level,
            "on" if closed_loop_poll_interval_s > 0 else "off",
        )

    # ---------------------------------------------------------------
    # ControllerBridge protocol
    # ---------------------------------------------------------------

    def send_phase_request(self, output: ChamberOutput) -> None:
        direction = output.commanded_phase
        if direction.endswith("_green"):
            direction = direction[: -len("_green")]
        target_phase = DIRECTION_TO_PHASE.get(direction)
        if target_phase is None:
            log.warning(
                "no NEMA phase mapping for direction %s — skipping SNMPv3 send",
                direction,
            )
            return

        # Same NEMA TS 4 semantic as v1 bridge: force-off the other
        # phase so the target phase gets served.
        other_phases = [p for p in DIRECTION_TO_PHASE.values() if p != target_phase]
        for phase_to_terminate in other_phases:
            oid = f"{NTCIP_PHASE_FORCE_OFF_BASE}.{phase_to_terminate}"
            try:
                asyncio.run(self._async_set(oid, 1))
                log.debug(
                    "NTCIPv3 set %s = 1 (force-off phase %d so phase %d / %s gets served)",
                    oid, phase_to_terminate, target_phase, direction,
                )
            except Exception as e:
                log.warning(
                    "NTCIPv3 SET to %s:%d failed: %s",
                    self._host, self._port, e,
                )

    def get_actual_phase(self) -> dict | None:
        with self._status_lock:
            return dict(self._last_actual_phase) if self._last_actual_phase else None

    def close(self) -> None:
        self._stop.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)

    # ---------------------------------------------------------------
    # Async puresnmp glue (SNMPv3 client is async)
    # ---------------------------------------------------------------

    async def _async_set(self, oid: str, value: int) -> None:
        from puresnmp import Client  # noqa: PLC0415
        from x690.types import Integer  # noqa: PLC0415

        # Engine discovery happens automatically on first call.
        client = Client(self._host, self._credentials, port=self._port)
        await asyncio.wait_for(
            client.set(oid, Integer(value)), timeout=self._timeout,
        )

    async def _async_get_int(self, oid: str) -> int | None:
        from puresnmp import Client  # noqa: PLC0415

        client = Client(self._host, self._credentials, port=self._port)
        try:
            result = await asyncio.wait_for(
                client.get(oid), timeout=self._timeout,
            )
            return int(result) if result is not None else None
        except (TimeoutError, Exception) as e:
            log.debug("v3 GET %s failed: %s", oid, e)
            return None

    # ---------------------------------------------------------------
    # Closed-loop status poller (mirrors v1)
    # ---------------------------------------------------------------

    def _start_status_poller(self) -> None:
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                actual = asyncio.run(self._poll_once())
                if actual is not None:
                    with self._status_lock:
                        self._last_actual_phase = actual
            except Exception as e:
                log.debug("SNMPv3 status poll failed: %s", e)
            self._stop.wait(self._poll_interval)

    async def _poll_once(self) -> dict | None:
        value = await self._async_get_int(NTCIP_PHASE_STATUS_GREEN + ".0")
        if value is None:
            return None
        active_phases = [i + 1 for i in range(16) if value & (1 << i)]
        phase_to_dir = {v: k for k, v in DIRECTION_TO_PHASE.items()}
        active_directions = sorted({phase_to_dir.get(p) for p in active_phases if p in phase_to_dir})
        active_directions = [d for d in active_directions if d]
        return {
            "phase_greens_bitmask": value,
            "active_phases": active_phases,
            "active_directions": active_directions,
            "read_at": datetime.now(timezone.utc).isoformat(),
        }


def _check_bridge_protocol() -> None:
    """Type-check stub: confirms NtcipV3ControllerBridge satisfies the
    ControllerBridge protocol at module load time. No runtime cost.
    """
    bridge: ControllerBridge = NtcipV3ControllerBridge.__new__(NtcipV3ControllerBridge)
    _ = bridge
