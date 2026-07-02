#!/usr/bin/env python3
"""Send a real ASN.1 UPER-encoded SRM packet to the chamber's V2X detector.

Same wire format an RSU would produce — used for dev testing and
demonstration. The detector cannot tell this apart from a real RSU
forward.

Usage:
    # Send one preempt SRM for east_west (NEMA phase 4)
    python3 scripts/v2x_srm_sender.py --phase 4 --type preempt

    # Send a priority request (will NOT trigger preemption — see V2XSrmDetector
    # for the type discrimination)
    python3 scripts/v2x_srm_sender.py --phase 2 --type priority

    # Send to a different target (e.g., remote chamber instance)
    python3 scripts/v2x_srm_sender.py --target 192.168.1.10 --port 4444
"""

from __future__ import annotations

import argparse
import socket
import sys

from simulation.decision_chamber.v2x import encode_srm


def main() -> int:
    p = argparse.ArgumentParser(prog="v2x_srm_sender.py")
    p.add_argument("--target", default="127.0.0.1")
    p.add_argument("--port", type=int, default=4444)
    p.add_argument("--phase", type=int, required=True, help="NEMA phase 1-8")
    p.add_argument(
        "--type",
        choices=("preempt", "priority", "transit"),
        default="preempt",
    )
    p.add_argument("--vehicle-id", type=int, default=12345)
    p.add_argument("--msg-id", type=int, default=0x29, help="J2735 msgID (0x29 = SRM)")
    args = p.parse_args()

    if not 1 <= args.phase <= 8:
        print(f"phase must be 1-8 (got {args.phase})", file=sys.stderr)
        return 2

    packet = encode_srm(
        msg_id=args.msg_id,
        vehicle_id=args.vehicle_id,
        requested_phase=args.phase,
        request_type=args.type,
    )
    print(f"encoded SRM: {len(packet)} bytes  hex={packet.hex()}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, (args.target, args.port))
        print(
            f"sent to {args.target}:{args.port}  "
            f"phase={args.phase} type={args.type} vehicle_id={args.vehicle_id}"
        )
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
