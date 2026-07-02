"""Layer 5 output — bridges the chamber's advisory phase request to the
signal controller.

In production:
- The signal controller is an NTCIP-1202 compliant device (e.g., Econolite
  ASC/3, Siemens m50, McCain ATC). It is SIL-rated; it owns the actual
  signal-light commands and the safety failsafe.
- The chamber sends ADVISORY phase requests via SNMP (NTCIP transports SNMP
  over UDP). The controller decides whether to honour, modify, or reject.
- If the chamber crashes or sends invalid requests, the controller falls
  back to its own fixed-time plan via watchdog.

In dev:
- The same SNMP code talks to a local UDP emulator
  (`scripts/ntcip_emulator.py`) that pretends to be a controller. The
  emulator validates the OID + value shape and logs received requests so
  we can verify the chamber output is wire-compatible.

Wire format (NTCIP 1202 §4):
- OID 1.3.6.1.4.1.1206.4.2.1.1.5.1 — phaseStatusGroupRedStatus
- OID 1.3.6.1.4.1.1206.4.2.1.1.5.2 — phaseStatusGroupYellowStatus
- OID 1.3.6.1.4.1.1206.4.2.1.1.5.3 — phaseStatusGroupGreenStatus
- OID 1.3.6.1.4.1.1206.4.2.1.1.4.1 — phaseControlGroupForceOff (write)

For Phase 2 MVP we implement a minimal subset — enough to demonstrate
the architecture. Production extensions (preempt request, hold,
pedestrian indication) are TODOs left in the code.
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
from datetime import datetime, timezone
from typing import Protocol

from simulation.decision_chamber.state import ChamberMode, ChamberOutput

log = logging.getLogger("atms.chamber.bridge")

# Direction -> NEMA phase mapping. NEMA 8-phase: phases 2+6 typically =
# north-south through; 4+8 = east-west through. The chamber's "_green"
# phase strings map to the through-movement phases.
DIRECTION_TO_PHASE = {
    "north_south": 2,
    "east_west": 4,
}

# NTCIP 1202 OIDs (NEMA TS 4 / NTCIP 1202 §4.6 phase control group)
NTCIP_PHASE_FORCE_OFF_BASE = "1.3.6.1.4.1.1206.4.2.1.1.4.1.1"
NTCIP_PHASE_HOLD_BASE = "1.3.6.1.4.1.1206.4.2.1.1.4.1.2"

# NTCIP 1202 §4.5 phase status group — READ for closed-loop status
NTCIP_PHASE_STATUS_GREEN = "1.3.6.1.4.1.1206.4.2.1.1.5.3"  # phaseStatusGroupGreens
NTCIP_PHASE_STATUS_YELLOW = "1.3.6.1.4.1.1206.4.2.1.1.5.2"  # phaseStatusGroupYellows
NTCIP_PHASE_STATUS_RED = "1.3.6.1.4.1.1206.4.2.1.1.5.1"  # phaseStatusGroupReds


class ControllerBridge(Protocol):
    """Abstracts away whether the controller is a real NTCIP-1202 box, a
    local emulator, or a no-op (logging only). All three are
    interchangeable from the chamber's perspective.
    """

    name: str

    def send_phase_request(self, output: ChamberOutput) -> None:
        """Translate the chamber's advisory output to the appropriate
        controller protocol and send. Must not raise — bridge errors are
        logged + counted as a metric but don't crash the chamber.
        """
        ...

    def get_actual_phase(self) -> dict | None:
        """Return what the controller is ACTUALLY doing right now (read
        back via NTCIP GET). Returns None if read-back isn't available or
        the controller hasn't replied. Used by the chamber for closed-
        loop disagreement detection: if commanded != actual for >N
        ticks, log a divergence alert.
        """
        ...


class StubControllerBridge:
    """No-op bridge: just logs what would be sent. Used when no real
    controller is available — the chamber still produces full output via
    the state JSON.
    """

    name = "stub"

    def send_phase_request(self, output: ChamberOutput) -> None:
        log.info(
            "[stub] commanded_phase=%s mode=%s dominant=%s",
            output.commanded_phase,
            output.mode.value,
            output.dominant_factor,
        )

    def get_actual_phase(self) -> dict | None:
        # No controller to query — return None so the chamber knows
        # closed-loop status isn't available.
        return None


class NtcipControllerBridge:
    """Real NTCIP-1202 over SNMP/UDP. Wire-compatible with any compliant
    signal controller — dev tests against `scripts/ntcip_emulator.py`
    listening on UDP/161; production points at the controller's IP.

    Implementation note: SNMPv1 over UDP/161 is the NTCIP standard
    (NTCIP 1103 §4.2). We send `set` requests with the appropriate OID
    + value. Real installations require community-string auth (default
    'public') and may use SNMPv3 — configurable here.

    Phase 2 implements minimal phase-force-off command. Phase 3 adds:
    - pedestrian-call (NTCIP-1202 §4.7.1)
    - preempt-call (NTCIP-1202 §4.7.4)
    - status polling (chamber reads back actual controller state)
    """

    name = "ntcip_1202"

    def __init__(
        self,
        controller_host: str = "127.0.0.1",
        controller_port: int = 161,
        community: str = "public",
        timeout_seconds: float = 0.5,
        closed_loop_poll_interval_s: float = 2.0,
    ):
        self._host = controller_host
        self._port = controller_port
        self._community = community
        self._timeout = timeout_seconds
        self._request_id = 0
        self._poll_interval = closed_loop_poll_interval_s
        # Closed-loop status read-back cache. Updated by background
        # poller thread; consumed by `get_actual_phase()`.
        self._status_lock = threading.Lock()
        self._last_actual_phase: dict | None = None
        self._poll_thread: threading.Thread | None = None
        self._stop = threading.Event()
        if closed_loop_poll_interval_s > 0:
            self._start_status_poller()
        log.info(
            "NTCIP bridge target: %s:%d (community=%s, closed-loop=%s)",
            controller_host,
            controller_port,
            community,
            "on" if closed_loop_poll_interval_s > 0 else "off",
        )

    def send_phase_request(self, output: ChamberOutput) -> None:
        direction = output.commanded_phase
        if direction.endswith("_green"):
            direction = direction[: -len("_green")]
        target_phase = DIRECTION_TO_PHASE.get(direction)
        if target_phase is None:
            log.warning(
                "no NEMA phase mapping for direction %s — skipping NTCIP send",
                direction,
            )
            return

        # NTCIP semantic: force-off TERMINATES a phase. To get our
        # target_phase green, we send force-off to every OTHER vehicle
        # phase. Once they terminate, the controller's coordinated cycle
        # advances to our target. This is the standard NEMA TS 4 phase-
        # request pattern (Western Reserve Engineering 2018 §7.3).
        other_phases = [p for p in DIRECTION_TO_PHASE.values() if p != target_phase]
        for phase_to_terminate in other_phases:
            oid = f"{NTCIP_PHASE_FORCE_OFF_BASE}.{phase_to_terminate}"
            try:
                packet = self._build_snmp_set_packet(oid, value=1)
                self._send_packet(packet)
                log.debug(
                    "NTCIP force-off phase %d (so phase %d / %s gets served)",
                    phase_to_terminate,
                    target_phase,
                    direction,
                )
            except OSError as e:
                log.warning("NTCIP send to %s:%d failed: %s", self._host, self._port, e)

    def _send_packet(self, packet: bytes) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(self._timeout)
            sock.sendto(packet, (self._host, self._port))
        finally:
            sock.close()

    def get_actual_phase(self) -> dict | None:
        """Return the most recent closed-loop status read from the
        controller. None if no successful read yet.
        """
        with self._status_lock:
            return dict(self._last_actual_phase) if self._last_actual_phase else None

    def _start_status_poller(self) -> None:
        """Start the background thread that polls controller phase
        status via NTCIP GET. Updates `_last_actual_phase` on each
        successful read.
        """
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        """Background loop: every `_poll_interval` seconds, send a GET
        for the phase status group and parse the response. Failure to
        get a response is logged (debug level) and the cache is left
        as-is so transient network glitches don't clear the chamber's
        view of controller state.
        """
        while not self._stop.is_set():
            try:
                actual = self._poll_once()
                if actual is not None:
                    with self._status_lock:
                        self._last_actual_phase = actual
            except Exception as e:
                log.debug("NTCIP status poll failed: %s", e)
            self._stop.wait(self._poll_interval)

    def _poll_once(self) -> dict | None:
        """Send a single GET-REQUEST for the phaseStatusGroupGreens OID
        and decode the response. Returns {"phase_greens": int, "ts": ...}
        on success.
        """
        # Use the green status group as the simplest single-OID poll.
        # Production deployments would batch with GET-BULK + read greens,
        # yellows, reds together.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(self._timeout)
            packet = self._build_snmp_get_packet(NTCIP_PHASE_STATUS_GREEN + ".0")
            sock.sendto(packet, (self._host, self._port))
            try:
                resp, _peer = sock.recvfrom(4096)
            except socket.timeout:
                return None
        finally:
            sock.close()

        # Parse the GET-RESPONSE for the integer value
        value = self._extract_response_integer(resp)
        if value is None:
            return None
        # NTCIP 1202 §4.5: phaseStatusGroupGreens is a bitmask of active
        # green phases. Bit 0 = phase 1, bit 1 = phase 2, etc.
        active_phases = [i + 1 for i in range(16) if value & (1 << i)]
        # Map to direction via the same DIRECTION_TO_PHASE table inverted
        phase_to_dir = {v: k for k, v in DIRECTION_TO_PHASE.items()}
        actual_directions = sorted({phase_to_dir.get(p) for p in active_phases if p in phase_to_dir})
        actual_directions = [d for d in actual_directions if d]
        return {
            "phase_greens_bitmask": value,
            "active_phases": active_phases,
            "active_directions": actual_directions,
            "read_at": datetime.now(timezone.utc).isoformat(),
        }

    def _build_snmp_get_packet(self, oid: str) -> bytes:
        """SNMPv1 GET-REQUEST PDU (type 0xA0). Same structure as SET but
        with NULL value placeholder (the agent fills it in the response).
        """
        self._request_id = (self._request_id + 1) & 0x7FFFFFFF
        oid_bytes = self._encode_oid(oid)
        # NULL value: tag 0x05, length 0
        value_bytes = bytes([0x05, 0x00])
        varbind = self._encode_sequence(oid_bytes + value_bytes)
        varbind_list = self._encode_sequence(varbind)
        pdu_body = (
            self._encode_integer(self._request_id)
            + self._encode_integer(0)
            + self._encode_integer(0)
            + varbind_list
        )
        pdu = bytes([0xA0]) + self._encode_length(len(pdu_body)) + pdu_body
        message = (
            self._encode_integer(0)
            + self._encode_octet_string(self._community.encode("ascii"))
            + pdu
        )
        return self._encode_sequence(message)

    def _extract_response_integer(self, resp: bytes) -> int | None:
        """Pull the integer value from an SNMPv1 GET-RESPONSE packet.
        Tolerates layout variations — looks for the first INTEGER after
        the VarBind sequence.
        """
        try:
            cursor = 0
            # Outer SEQUENCE
            cursor = self._expect_byte(resp, cursor, 0x30)
            _seq_len, cursor = self._read_length(resp, cursor)
            # version
            _v, cursor = self._read_int_at(resp, cursor)
            # community
            _c, cursor = self._read_octet_string_at(resp, cursor)
            # PDU type 0xA2 = GET-RESPONSE
            cursor = self._expect_byte(resp, cursor, 0xA2)
            _pdu_len, cursor = self._read_length(resp, cursor)
            # request-id, error-status, error-index
            _req_id, cursor = self._read_int_at(resp, cursor)
            err_status, cursor = self._read_int_at(resp, cursor)
            _err_idx, cursor = self._read_int_at(resp, cursor)
            if err_status != 0:
                log.debug("NTCIP error-status=%d in response", err_status)
                return None
            # VarBindList
            cursor = self._expect_byte(resp, cursor, 0x30)
            _vbl_len, cursor = self._read_length(resp, cursor)
            # VarBind
            cursor = self._expect_byte(resp, cursor, 0x30)
            _vb_len, cursor = self._read_length(resp, cursor)
            # OID
            cursor = self._expect_byte(resp, cursor, 0x06)
            oid_len, cursor = self._read_length(resp, cursor)
            cursor += oid_len
            # Value — should be INTEGER
            if resp[cursor] != 0x02:
                return None
            value, _ = self._read_int_at(resp, cursor)
            return value
        except (IndexError, ValueError):
            return None

    @staticmethod
    def _expect_byte(packet: bytes, cursor: int, expected: int) -> int:
        if packet[cursor] != expected:
            raise ValueError(f"expected 0x{expected:02x}")
        return cursor + 1

    @staticmethod
    def _read_length(packet: bytes, cursor: int) -> tuple[int, int]:
        first = packet[cursor]
        cursor += 1
        if first < 0x80:
            return first, cursor
        n = first & 0x7F
        length = 0
        for _ in range(n):
            length = (length << 8) | packet[cursor]
            cursor += 1
        return length, cursor

    @staticmethod
    def _read_int_at(packet: bytes, cursor: int) -> tuple[int, int]:
        if packet[cursor] != 0x02:
            raise ValueError("expected INTEGER tag")
        cursor += 1
        length, cursor = NtcipControllerBridge._read_length(packet, cursor)
        val = int.from_bytes(packet[cursor : cursor + length], "big", signed=False)
        return val, cursor + length

    @staticmethod
    def _read_octet_string_at(packet: bytes, cursor: int) -> tuple[bytes, int]:
        if packet[cursor] != 0x04:
            raise ValueError("expected OCTET STRING tag")
        cursor += 1
        length, cursor = NtcipControllerBridge._read_length(packet, cursor)
        return packet[cursor : cursor + length], cursor + length

    def close(self) -> None:
        self._stop.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)

    def _build_snmp_set_packet(self, oid: str, value: int) -> bytes:
        """Build an SNMPv1 SET-REQUEST packet by hand. We avoid the pysnmp
        async stack here because the chamber tick is synchronous and we
        want a tiny, dependency-light wire-format implementation.

        Packet structure (ASN.1 BER):
            SEQUENCE {
                INTEGER (version) 0 = SNMPv1
                OCTET STRING (community)
                Set-Request PDU {
                    INTEGER (request-id)
                    INTEGER (error-status) 0
                    INTEGER (error-index) 0
                    SEQUENCE OF VarBind {
                        SEQUENCE { OID, INTEGER value }
                    }
                }
            }
        """
        self._request_id = (self._request_id + 1) & 0x7FFFFFFF
        oid_bytes = self._encode_oid(oid)
        value_bytes = self._encode_integer(value)
        varbind = self._encode_sequence(oid_bytes + value_bytes)
        varbind_list = self._encode_sequence(varbind)
        pdu_body = (
            self._encode_integer(self._request_id)
            + self._encode_integer(0)  # error-status
            + self._encode_integer(0)  # error-index
            + varbind_list
        )
        # PDU type 0xA3 = Set-Request
        pdu = bytes([0xA3]) + self._encode_length(len(pdu_body)) + pdu_body
        message = (
            self._encode_integer(0)  # version SNMPv1
            + self._encode_octet_string(self._community.encode("ascii"))
            + pdu
        )
        return self._encode_sequence(message)

    @staticmethod
    def _encode_length(length: int) -> bytes:
        if length < 128:
            return bytes([length])
        lb = []
        while length > 0:
            lb.insert(0, length & 0xFF)
            length >>= 8
        return bytes([0x80 | len(lb)]) + bytes(lb)

    @staticmethod
    def _encode_sequence(body: bytes) -> bytes:
        return bytes([0x30]) + NtcipControllerBridge._encode_length(len(body)) + body

    @staticmethod
    def _encode_integer(value: int) -> bytes:
        # Minimum encoding per ASN.1 BER
        if value == 0:
            payload = b"\x00"
        else:
            n = value
            byte_count = (n.bit_length() + 8) // 8
            payload = n.to_bytes(byte_count, "big", signed=False)
            if payload[0] & 0x80:
                payload = b"\x00" + payload
        return bytes([0x02]) + NtcipControllerBridge._encode_length(len(payload)) + payload

    @staticmethod
    def _encode_octet_string(value: bytes) -> bytes:
        return bytes([0x04]) + NtcipControllerBridge._encode_length(len(value)) + value

    @staticmethod
    def _encode_oid(oid: str) -> bytes:
        parts = [int(p) for p in oid.split(".")]
        if len(parts) < 2:
            raise ValueError("OID needs at least two arcs")
        first_byte = parts[0] * 40 + parts[1]
        out = bytes([first_byte])
        for arc in parts[2:]:
            if arc < 0:
                raise ValueError("negative OID arc")
            chunks: list[int] = []
            chunks.append(arc & 0x7F)
            arc >>= 7
            while arc > 0:
                chunks.append((arc & 0x7F) | 0x80)
                arc >>= 7
            out += bytes(reversed(chunks))
        return bytes([0x06]) + NtcipControllerBridge._encode_length(len(out)) + out


__all__ = ["ControllerBridge", "StubControllerBridge", "NtcipControllerBridge"]


# Suppress unused-import warning for the encoder's struct dependency
_ = struct
