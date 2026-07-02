"""Emergency vehicle preemption — Layer 1 of the Decision Chamber.

Multi-source by design. Each source implements `EmergencyDetector` and
contributes a list of `EmergencySignal` per tick. The chamber treats
sources as a logical OR — any one positive triggers preemption — but
the audit log records which source(s) fired so reliability can be
analysed offline.

Sources implemented in Phase 1:
- OperatorOverrideDetector  — file-based signal from the operator console
- VisualLightbarDetector    — colour heuristic on vehicle crops

Stubs for Phase 2 (kept as Protocol implementations returning empty
lists, so the integration interface doesn't change later):
- AudioSirenDetector        — short-time FFT + classifier (mic input)
- V2XSrmDetector            — SAE J2735 Signal Request Message handler
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from simulation.decision_chamber.state import EmergencySignal, EmergencySource

log = logging.getLogger("atms.chamber.preemption")


class EmergencyDetector(Protocol):
    """Production interface for any emergency-vehicle detector. Real
    implementations talk to real protocols (V2X, NTCIP, RTSP, audio).
    Dev implementations talk to synthetic sources but produce the same
    `EmergencySignal` output shape, so the chamber doesn't know or care
    where the signal came from.
    """

    name: str

    def poll(self, tick_time: datetime, context: dict[str, Any]) -> list[EmergencySignal]:
        """Return any emergency signals current as of `tick_time`. May
        return an empty list. `context` carries per-tick data the
        detector might need (e.g., vehicle crops for the visual
        detector). Must NOT raise — detector errors should surface as
        empty result + a log warning.
        """
        ...


class OperatorOverrideDetector:
    """File-based operator override. The operator console writes a small
    JSON file when the operator presses "Force Emergency Preempt"; this
    detector polls that file. JSON shape:

        {
            "direction": "north_south",
            "expires_at": "2026-06-13T20:35:00Z",
            "notes": "ambulance reported by call centre"
        }

    Production swap: replace this with a real REST endpoint subscriber
    fed by the operator console. The signal shape stays identical.
    """

    name = "operator_override"

    def __init__(self, override_path: Path):
        self._path = override_path

    def poll(self, tick_time: datetime, context: dict[str, Any]) -> list[EmergencySignal]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning("operator override file unreadable: %s", e)
            return []
        try:
            expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError) as e:
            log.warning("operator override missing/bad expires_at: %s", e)
            return []
        if tick_time.astimezone() > expires_at.astimezone():
            return []  # expired — ignore stale overrides
        return [
            EmergencySignal(
                source=EmergencySource.OPERATOR_OVERRIDE,
                direction=data.get("direction", "unknown"),
                confidence=1.0,  # operator override is authoritative
                detected_at=tick_time,
                notes=data.get("notes", ""),
            )
        ]


class VisualLightbarDetector:
    """Detects emergency-vehicle lightbars in vehicle crops. Heuristic:
    in the top 25% of a bbox, count pixels in the strong-red and
    strong-blue hue bands; if both colours are present above a threshold,
    that's a lightbar signature.

    Limitations (documented honestly):
    - No temporal pulsing detection in Phase 1 — false-positive risk on
      red/blue body paint. Phase 2 adds frame-to-frame saturation pulse
      detection to discriminate paint from flashing lights.
    - Min bbox size 80×80 px — smaller vehicles can't reliably show a
      lightbar signature in our resolution.

    Production data: this consumes the SAME vehicle crops the brand
    classifier sees — no extra sensor, no mock.
    """

    name = "visual_lightbar"

    def __init__(
        self,
        min_bbox_px: int = 80,
        min_red_fraction: float = 0.02,
        min_blue_fraction: float = 0.02,
        confidence_floor: float = 0.30,
    ):
        self._min_bbox_px = min_bbox_px
        self._min_red_fraction = min_red_fraction
        self._min_blue_fraction = min_blue_fraction
        self._confidence_floor = confidence_floor

    def poll(self, tick_time: datetime, context: dict[str, Any]) -> list[EmergencySignal]:
        """`context` must include `vehicle_crops`: list of
        `(direction, crop_bgr_ndarray)` tuples for vehicles currently
        tracked. Returns one signal per detection above the confidence
        floor.
        """
        crops = context.get("vehicle_crops") or []
        if not crops:
            return []

        try:
            import cv2  # noqa: PLC0415
            import numpy as np  # noqa: PLC0415
        except ImportError:
            log.warning("visual lightbar detector needs opencv-python + numpy")
            return []

        out: list[EmergencySignal] = []
        for direction, crop in crops:
            if crop is None or crop.size == 0:
                continue
            h, w = crop.shape[:2]
            if h < self._min_bbox_px or w < self._min_bbox_px:
                continue
            top = crop[: max(1, int(h * 0.25)), :]
            hsv = cv2.cvtColor(top, cv2.COLOR_BGR2HSV)
            hue = hsv[:, :, 0]
            sat = hsv[:, :, 1]
            val = hsv[:, :, 2]
            # Red: OpenCV hue wraps; covers 0-10 and 170-180.
            red_mask = ((hue <= 10) | (hue >= 170)) & (sat > 100) & (val > 100)
            # Blue: 100-130 hue range.
            blue_mask = (hue >= 100) & (hue <= 130) & (sat > 100) & (val > 100)
            n_pixels = top.shape[0] * top.shape[1]
            red_frac = float(red_mask.sum() / n_pixels)
            blue_frac = float(blue_mask.sum() / n_pixels)
            if red_frac < self._min_red_fraction or blue_frac < self._min_blue_fraction:
                continue
            # Combined confidence — saturated by 10× to land in [0,1] range
            confidence = float(min(1.0, (red_frac + blue_frac) * 10))
            if confidence < self._confidence_floor:
                continue
            out.append(
                EmergencySignal(
                    source=EmergencySource.VISUAL_LIGHTBAR,
                    direction=direction,
                    confidence=confidence,
                    detected_at=tick_time,
                    notes=f"red={red_frac:.3f} blue={blue_frac:.3f}",
                )
            )
        return out


class AudioSirenDetector:
    """Phase 2 — short-time FFT + classifier on microphone input.

    Phase 1 stub: returns empty. Kept as a real Protocol implementation
    so that integration is a drop-in once the model is trained and the
    audio pipeline is wired.
    """

    name = "audio_siren"

    def poll(self, tick_time: datetime, context: dict[str, Any]) -> list[EmergencySignal]:
        return []


class V2XSrmDetector:
    """Phase 2 — SAE J2735 Signal Request Message subscriber.

    Real implementation will:
    1. Subscribe to V2X RSU on UDP port 2099 (or local mesh)
    2. Decode J2735 SRM messages (PSID 0x82, ITS spec)
    3. Extract requesting vehicle ID, requested phase, priority level
    4. Translate to our direction names via static lane-to-direction
       lookup loaded from per-intersection config

    Phase 1 stub: returns empty. Real protocol parser ready in
    `simulation/decision_chamber/v2x.py` (Phase 2).
    """

    name = "v2x_srm"

    def poll(self, tick_time: datetime, context: dict[str, Any]) -> list[EmergencySignal]:
        return []


def aggregate_signals(detectors: list[EmergencyDetector], tick_time: datetime,
                      context: dict[str, Any]) -> list[EmergencySignal]:
    """Run all detectors in parallel (well, sequentially in Phase 1) and
    concatenate their signals. Exceptions in one detector don't kill the
    chain — we log and continue.
    """
    out: list[EmergencySignal] = []
    for det in detectors:
        try:
            out.extend(det.poll(tick_time, context))
        except Exception as e:
            log.warning("detector %s raised: %s — skipping", det.name, e)
    return out


def stale_signal_filter(
    signals: list[EmergencySignal], tick_time: datetime, max_age_seconds: float = 5.0
) -> list[EmergencySignal]:
    """Drop signals older than `max_age_seconds`. A stale operator
    override or visual blip shouldn't keep preempting after the actual
    vehicle has passed.
    """
    cutoff = tick_time - timedelta(seconds=max_age_seconds)
    return [s for s in signals if s.detected_at >= cutoff]
