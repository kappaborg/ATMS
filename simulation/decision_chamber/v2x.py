"""V2X Signal Request Message (SRM) handler.

In production:
- A DSRC or C-V2X Roadside Unit (RSU) decodes J2735 messages from
  approaching emergency / transit / priority vehicles.
- The RSU forwards Signal Request Messages (SRM) over UDP to this
  detector. We decode them, translate the requested NEMA phase to our
  direction nomenclature, and emit an EmergencySignal that the chamber
  treats as Layer-1 preemption input.

In dev:
- `scripts/v2x_srm_sender.py` produces real ASN.1 UPER-encoded packets
  in the same wire format an RSU would emit. The detector doesn't know
  or care about the source — the bytes on the wire are identical.

Wire format:
- SAE J2735 SRM is a large structure; we ship a minimal subset
  (`SimplifiedSrm`) with the fields that matter for priority-request
  semantics. The ASN.1 spec is embedded below and compiled at module
  load time. Phase 3 will swap this for the full J2735-202309 ASN.1
  spec (~3500 lines) which `asn1tools` can load from a .asn file. The
  detector's interface to the rest of the chamber stays identical.
"""

from __future__ import annotations

import logging
import socket
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from simulation.decision_chamber.state import EmergencySignal, EmergencySource

log = logging.getLogger("atms.chamber.v2x")


SIMPLIFIED_SRM_ASN1 = """
SimplifiedSrm DEFINITIONS AUTOMATIC TAGS ::= BEGIN

SimplifiedSrm ::= SEQUENCE {
    msgId          INTEGER (0..255),
    vehicleId      INTEGER (0..16777215),
    requestedPhase INTEGER (1..8),
    requestType    ENUMERATED { priority, preempt, transit },
    timestamp      INTEGER
}

SrmAck ::= SEQUENCE {
    msgId           INTEGER (0..255),
    ackedVehicleId  INTEGER (0..16777215),
    status          ENUMERATED { received, granted, denied, queued },
    chamberTimestamp INTEGER
}

END
"""

# Lazy-compile so import doesn't crash environments without asn1tools.
_codec = None


def _get_codec():
    global _codec
    if _codec is None:
        try:
            import asn1tools  # noqa: PLC0415
        except ImportError as e:
            raise RuntimeError(
                "asn1tools required for V2X SRM. "
                "Install: pip install asn1tools"
            ) from e
        _codec = asn1tools.compile_string(SIMPLIFIED_SRM_ASN1, "uper")
    return _codec


# NEMA phase number -> direction name. Matches the convention in
# controller_bridge.DIRECTION_TO_PHASE so the round-trip is consistent.
NEMA_PHASE_TO_DIRECTION = {
    1: "north_south",
    2: "north_south",
    3: "east_west",
    4: "east_west",
    5: "north_south",
    6: "north_south",
    7: "east_west",
    8: "east_west",
}


def encode_srm(
    msg_id: int,
    vehicle_id: int,
    requested_phase: int,
    request_type: str = "preempt",
    timestamp: int | None = None,
) -> bytes:
    """Build a real UPER-encoded SimplifiedSrm packet. Used by the dev
    sender script + by tests to verify the encoder/decoder round-trips.
    """
    if timestamp is None:
        timestamp = int(datetime.now(timezone.utc).timestamp())
    codec = _get_codec()
    return codec.encode(
        "SimplifiedSrm",
        {
            "msgId": msg_id & 0xFF,
            "vehicleId": vehicle_id & 0xFFFFFF,
            "requestedPhase": requested_phase,
            "requestType": request_type,
            "timestamp": timestamp,
        },
    )


def decode_srm(packet: bytes) -> dict[str, Any]:
    """Decode a UPER SimplifiedSrm packet. Raises on malformed input —
    callers should catch + log."""
    codec = _get_codec()
    decoded = codec.decode("SimplifiedSrm", packet)
    return decoded


def encode_srm_ack(
    msg_id: int,
    acked_vehicle_id: int,
    status: str = "received",
) -> bytes:
    """Encode an SRM acknowledgment. SAE J2735 spec mandates V2X devices
    receive a confirmation within ~100ms of sending a Signal Request
    Message. Status semantics:
    - 'received': chamber got the SRM but hasn't decided yet
    - 'granted': chamber will preempt to the requested phase
    - 'denied': request rejected (e.g., lower priority than active preempt)
    - 'queued': will serve after current preempt completes
    """
    codec = _get_codec()
    return codec.encode(
        "SrmAck",
        {
            "msgId": msg_id & 0xFF,
            "ackedVehicleId": acked_vehicle_id & 0xFFFFFF,
            "status": status,
            "chamberTimestamp": int(datetime.now(timezone.utc).timestamp()),
        },
    )


class V2XSrmDetector:
    """UDP listener that decodes J2735-style SRM packets in a background
    thread. The detector buffers the most recently received signal so
    `poll()` is non-blocking — the chamber tick rate doesn't have to
    match the V2X packet rate.

    Production: bind to the RSU's loopback port; community + auth are
    handled at the RSU edge. Dev: bind to 127.0.0.1 and use
    `scripts/v2x_srm_sender.py` to feed synthetic SRMs.
    """

    name = "v2x_srm"

    def __init__(
        self,
        listen_host: str = "127.0.0.1",
        listen_port: int = 4444,
        signal_ttl_seconds: float = 5.0,
    ):
        self._host = listen_host
        self._port = listen_port
        self._ttl = signal_ttl_seconds
        self._lock = threading.Lock()
        self._recent: list[tuple[datetime, dict[str, Any]]] = []
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._start_listener()

    def _start_listener(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind((self._host, self._port))
            sock.settimeout(0.5)
            self._sock = sock
        except OSError as e:
            log.warning(
                "V2X SRM detector failed to bind %s:%d — %s (running disabled)",
                self._host, self._port, e,
            )
            return
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        log.info("V2X SRM listener bound on UDP %s:%d", self._host, self._port)

    def _listen_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                data, peer = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                decoded = decode_srm(data)
            except Exception as e:
                log.warning("malformed SRM packet (%s); first bytes: %s", e, data[:16].hex())
                continue
            arrival = datetime.now(timezone.utc)
            with self._lock:
                self._recent.append((arrival, decoded))
                # Trim entries older than TTL
                cutoff = arrival - timedelta(seconds=self._ttl)
                self._recent = [(t, d) for (t, d) in self._recent if t >= cutoff]
            # Phase 10.3: synchronous ACK within 100ms per SAE J2735.
            # Status "received" — chamber acknowledges receipt; granted/
            # denied decision is communicated via the eventual phase
            # transition (or lack thereof).
            try:
                ack = encode_srm_ack(
                    msg_id=int(decoded.get("msgId", 0)),
                    acked_vehicle_id=int(decoded.get("vehicleId", 0)),
                    status="received",
                )
                self._sock.sendto(ack, peer)
            except Exception as e:
                log.warning("SRM ACK send failed: %s", e)

    def poll(self, tick_time: datetime, context: dict[str, Any]) -> list[EmergencySignal]:
        with self._lock:
            cutoff = tick_time - timedelta(seconds=self._ttl)
            fresh = [(t, d) for (t, d) in self._recent if t >= cutoff]
        out: list[EmergencySignal] = []
        for arrival, decoded in fresh:
            phase = decoded.get("requestedPhase", 0)
            direction = NEMA_PHASE_TO_DIRECTION.get(phase)
            if direction is None:
                log.warning("SRM phase %d has no direction mapping — skipping", phase)
                continue
            # request_type 'preempt' is a true emergency override; 'priority'
            # and 'transit' are softer (handled at L3 in Phase 3 via the
            # TSP module). For Phase 2 we treat 'preempt' as preemption-
            # eligible only.
            req_type = decoded.get("requestType", "priority")
            if req_type != "preempt":
                continue
            out.append(
                EmergencySignal(
                    source=EmergencySource.V2X_SRM,
                    direction=direction,
                    confidence=0.95,  # V2X is high-trust
                    detected_at=arrival,
                    notes=f"vehicleId={decoded.get('vehicleId')} phase={phase}",
                )
            )
        return out

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            self._sock.close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
