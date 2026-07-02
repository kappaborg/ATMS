#!/usr/bin/env python3
"""Minimal NTCIP-1202 controller emulator for dev testing.

Listens on UDP/161 (the standard SNMP port — bind on a high port for
non-root testing). Decodes SNMPv1 packets, validates the wire format,
logs received NTCIP-1202 phase requests + sends back a positive response.

Purpose:
- Verify the chamber's `NtcipControllerBridge` produces wire-compatible
  SNMP packets (real production controllers will accept the same bytes).
- Give the operator console / developer a live "this is what the chamber
  is sending to the field" view.
- Provide a deterministic test target so smoke tests don't need real hw.

Limitations (documented honestly):
- Implements only the SET request path. Real controllers also handle GET
  for status read-back (Phase 3 addition).
- No SNMPv3 auth (real production uses SNMPv3 with HMAC-SHA1).
- Single-threaded; not for load testing.

Run from repo root:
    python3 scripts/ntcip_emulator.py
    # Or on a different port:
    python3 scripts/ntcip_emulator.py --port 1611
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ntcip_emulator")

# NTCIP 1202 §4.6 phase control group base OIDs
NTCIP_BASE_OIDS = {
    "1.3.6.1.4.1.1206.4.2.1.1.4.1.1": "phaseControlGroupForceOff",
    "1.3.6.1.4.1.1206.4.2.1.1.4.1.2": "phaseControlGroupHold",
    "1.3.6.1.4.1.1206.4.2.1.1.4.1.3": "phaseControlGroupVehCall",
    "1.3.6.1.4.1.1206.4.2.1.1.4.1.4": "phaseControlGroupPedCall",
    "1.3.6.1.4.1.1206.4.2.1.1.4.1.5": "phaseControlGroupPedReleaseHold",
}

PHASE_TO_DIRECTION = {2: "north_south", 4: "east_west", 6: "north_south", 8: "east_west"}


def parse_snmp_packet(packet: bytes):
    """Pull PDU type, request_id, community, oid, value from an SNMPv1 packet.
    Handles both SET (0xA3) and GET (0xA0).

    Returns (pdu_type, request_id, community, oid, value_or_None, oid_name)
    or None if unparseable.
    """
    try:
        cursor = 0
        cursor = _expect_tag(packet, cursor, 0x30)
        _seq_len, cursor = _read_length(packet, cursor)
        _version, cursor = _read_integer(packet, cursor)
        community, cursor = _read_octet_string(packet, cursor)

        pdu_type = packet[cursor]
        if pdu_type not in (0xA0, 0xA3):
            return None
        cursor += 1
        _pdu_len, cursor = _read_length(packet, cursor)
        request_id, cursor = _read_integer(packet, cursor)
        _error_status, cursor = _read_integer(packet, cursor)
        _error_index, cursor = _read_integer(packet, cursor)

        cursor = _expect_tag(packet, cursor, 0x30)
        _vbl_len, cursor = _read_length(packet, cursor)
        cursor = _expect_tag(packet, cursor, 0x30)
        _vb_len, cursor = _read_length(packet, cursor)
        oid, cursor = _read_oid(packet, cursor)
        value = None
        if pdu_type == 0xA3:  # SET has a real value
            value, cursor = _read_integer(packet, cursor)

        oid_name = "unknown"
        for prefix, name in NTCIP_BASE_OIDS.items():
            if oid.startswith(prefix + ".") or oid == prefix:
                oid_name = name
                break

        return (
            pdu_type,
            request_id,
            community.decode("ascii", errors="replace"),
            oid,
            value,
            oid_name,
        )
    except (ValueError, IndexError) as e:
        log.warning("packet parse failed: %s (first 32 bytes: %s)", e, packet[:32].hex())
        return None


def build_get_response(request_id: int, community: str, oid: str, value: int) -> bytes:
    """Build an SNMPv1 GET-RESPONSE (PDU type 0xA2) with the given int value."""
    # Re-use the BER encoding helpers from the controller bridge module
    # via local minimal copies (to keep the script self-contained).
    def enc_len(n):
        if n < 128: return bytes([n])
        b = []
        while n > 0:
            b.insert(0, n & 0xFF); n >>= 8
        return bytes([0x80 | len(b)]) + bytes(b)
    def enc_int(v):
        if v == 0: pay = b"\x00"
        else:
            bl = (v.bit_length() + 8) // 8
            pay = v.to_bytes(bl, "big", signed=False)
            if pay[0] & 0x80: pay = b"\x00" + pay
        return bytes([0x02]) + enc_len(len(pay)) + pay
    def enc_seq(body): return bytes([0x30]) + enc_len(len(body)) + body
    def enc_str(s): return bytes([0x04]) + enc_len(len(s)) + s
    def enc_oid(o):
        parts = [int(p) for p in o.split(".")]
        first = parts[0] * 40 + parts[1]
        out = bytes([first])
        for arc in parts[2:]:
            chunks = [arc & 0x7F]; arc >>= 7
            while arc > 0:
                chunks.append((arc & 0x7F) | 0x80); arc >>= 7
            out += bytes(reversed(chunks))
        return bytes([0x06]) + enc_len(len(out)) + out

    varbind = enc_seq(enc_oid(oid) + enc_int(value))
    vbl = enc_seq(varbind)
    pdu_body = enc_int(request_id) + enc_int(0) + enc_int(0) + vbl
    pdu = bytes([0xA2]) + enc_len(len(pdu_body)) + pdu_body
    message = enc_int(0) + enc_str(community.encode("ascii")) + pdu
    return enc_seq(message)


# State tracked by the emulator — which phases are currently green.
# Updated when chamber sends a SET (force-off other phase), read when
# chamber sends a GET (closed-loop poll).
_current_green_phases: set[int] = {2}  # default NS


def _expect_tag(packet: bytes, cursor: int, expected: int) -> int:
    if packet[cursor] != expected:
        raise ValueError(f"expected tag 0x{expected:02x} got 0x{packet[cursor]:02x}")
    return cursor + 1


def _read_length(packet: bytes, cursor: int) -> tuple[int, int]:
    first = packet[cursor]
    cursor += 1
    if first < 0x80:
        return first, cursor
    n_octets = first & 0x7F
    length = 0
    for _ in range(n_octets):
        length = (length << 8) | packet[cursor]
        cursor += 1
    return length, cursor


def _read_integer(packet: bytes, cursor: int) -> tuple[int, int]:
    cursor = _expect_tag(packet, cursor, 0x02)
    length, cursor = _read_length(packet, cursor)
    val = int.from_bytes(packet[cursor : cursor + length], "big", signed=False)
    return val, cursor + length


def _read_octet_string(packet: bytes, cursor: int) -> tuple[bytes, int]:
    cursor = _expect_tag(packet, cursor, 0x04)
    length, cursor = _read_length(packet, cursor)
    return packet[cursor : cursor + length], cursor + length


def _read_oid(packet: bytes, cursor: int) -> tuple[str, int]:
    cursor = _expect_tag(packet, cursor, 0x06)
    length, cursor = _read_length(packet, cursor)
    end = cursor + length
    first_byte = packet[cursor]
    cursor += 1
    parts = [first_byte // 40, first_byte % 40]
    arc = 0
    while cursor < end:
        b = packet[cursor]
        cursor += 1
        arc = (arc << 7) | (b & 0x7F)
        if not (b & 0x80):
            parts.append(arc)
            arc = 0
    return ".".join(str(p) for p in parts), cursor


def main() -> int:
    parser = argparse.ArgumentParser(prog="ntcip_emulator.py")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1611, help="UDP port (1611 default; use 161 with sudo for real NTCIP)")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((args.host, args.port))
    except PermissionError:
        log.error(
            "port %d requires root. Use --port 1611 (or higher) for non-root testing.",
            args.port,
        )
        return 1
    except OSError as e:
        log.error("bind to %s:%d failed: %s", args.host, args.port, e)
        return 1

    log.info(
        "NTCIP-1202 emulator listening on UDP %s:%d (Ctrl+C to stop)",
        args.host,
        args.port,
    )
    n_received = 0
    try:
        while True:
            data, peer = sock.recvfrom(4096)
            n_received += 1
            parsed = parse_snmp_packet(data)
            if parsed is None:
                continue
            pdu_type, request_id, community, oid, value, oid_name = parsed

            try:
                phase = int(oid.rsplit(".", 1)[-1])
            except ValueError:
                phase = -1

            if pdu_type == 0xA3:  # SET
                # Chamber commanded a phase change. We model it by
                # interpreting force-off on phase X as "phase X is no
                # longer green; some other phase is".
                if "ForceOff" in oid_name and phase > 0:
                    other_phases = {p for p in (2, 4) if p != phase}
                    _current_green_phases.clear()
                    _current_green_phases.update(other_phases)
                direction = PHASE_TO_DIRECTION.get(phase, "?")
                log.info(
                    "[#%04d SET  from %s:%d] community=%s oid=%s (%s) value=%d phase=%d direction=%s green_now=%s",
                    n_received, peer[0], peer[1], community,
                    oid, oid_name, value, phase, direction,
                    sorted(_current_green_phases),
                )
            elif pdu_type == 0xA0:  # GET
                # Build a phase-status response (bitmask of greens).
                bitmask = 0
                for p in _current_green_phases:
                    if 1 <= p <= 16:
                        bitmask |= 1 << (p - 1)
                resp = build_get_response(request_id, community, oid, bitmask)
                sock.sendto(resp, peer)
                log.info(
                    "[#%04d GET  from %s:%d] community=%s oid=%s -> bitmask=0x%02x (phases %s)",
                    n_received, peer[0], peer[1], community,
                    oid, bitmask, sorted(_current_green_phases),
                )
    except KeyboardInterrupt:
        log.info("shutting down (%d packets received)", n_received)
        return 0
    finally:
        sock.close()


if __name__ == "__main__":
    sys.exit(main())
