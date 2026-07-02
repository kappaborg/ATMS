"""
Anonymization + retention policy — Phase D4.

See docs/adr/0014-data-retention-privacy.md.

Default rule for the whole codebase: **plate text never reaches storage**.
Every license-plate value passes through `PlateAnonymizer.subject_id_for()`
once at ingestion. After that boundary, the canonical identifier is the
HMAC-SHA256 hash with the deployment salt — irreversible without it.

For warranted access (law enforcement / investigation): a separate, gated
path described in ADR-0014 §4. This module does not implement that path;
it lives in `services/api-gateway` behind explicit role + claim checks.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from shared.atms_common.errors import AtmsError


class PrivacyError(AtmsError):
    """Raised by privacy helpers when input is malformed or context is missing."""


# ---------------------------------------------------------------------------
# Plate anonymisation
# ---------------------------------------------------------------------------


def _normalise_plate(raw: str) -> str:
    """Strip whitespace, uppercase, drop common separators.

    The same physical plate observed by two cameras (or two times) must hash
    to the same subject_id, so we collapse trivial formatting differences.
    """
    if not raw:
        raise PrivacyError("plate text is empty")
    return "".join(c for c in raw.upper() if c.isalnum())


@dataclass(frozen=True)
class PlateAnonymizer:
    """
    Deterministic HMAC-SHA256 hasher.

    Construction requires a deployment-specific salt (loaded via SOPS, ADR-0002).
    The salt must be at least 32 bytes for cryptographic safety.
    """

    salt: bytes

    def __post_init__(self) -> None:
        if not self.salt:
            raise PrivacyError("PlateAnonymizer requires a non-empty salt")
        if len(self.salt) < 16:
            raise PrivacyError(
                f"PlateAnonymizer salt must be >= 16 bytes (>=32 recommended); got {len(self.salt)}"
            )

    def subject_id_for(self, plate_text: str) -> str:
        """Return the canonical 64-hex `subject_id` for a plate reading.

        Determinism: same plate (after normalisation) + same salt → same id.
        Irreversibility: brute-force of the full plate space is bounded by the
        salt entropy; without the salt, a leaked DB does not leak plate text.
        """
        normalised = _normalise_plate(plate_text).encode("utf-8")
        return hmac.new(self.salt, normalised, hashlib.sha256).hexdigest()

    def subject_ids_for(self, plates: Iterable[str]) -> list[str]:
        """Batch helper."""
        return [self.subject_id_for(p) for p in plates]


# ---------------------------------------------------------------------------
# Retention policy table (mirrors ADR-0014 §3 + C4 0005_retention.py)
# ---------------------------------------------------------------------------


class RetentionProfile(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


_RETENTION_HOURS: dict[str, dict[RetentionProfile, int]] = {
    # Raw detections — anonymised; retained for operational replay only.
    "traffic_detections": {
        RetentionProfile.DEV: 168,  # 7 d
        RetentionProfile.STAGING: 720,  # 30 d
        RetentionProfile.PROD: 2160,  # 90 d
    },
    # 1-min continuous aggregate.
    "traffic_detections_1min": {
        RetentionProfile.DEV: 720,
        RetentionProfile.STAGING: 2160,
        RetentionProfile.PROD: 4320,  # 180 d
    },
    # 1-hour continuous aggregate — aggregate, not personal.
    "traffic_detections_1h": {
        RetentionProfile.DEV: 2160,
        RetentionProfile.STAGING: 8760,
        RetentionProfile.PROD: 17520,  # 2 years
    },
    # Decisions — operational audit.
    "decisions": {
        RetentionProfile.DEV: 2160,
        RetentionProfile.STAGING: 4320,
        RetentionProfile.PROD: 2160,
    },
    # Mode transitions — incident review.
    "mode_transitions": {
        RetentionProfile.DEV: 2160,
        RetentionProfile.STAGING: 4320,
        RetentionProfile.PROD: 8760,  # 1 year
    },
    # Audit log — legal floor.
    "audit_log": {
        RetentionProfile.DEV: 8760,
        RetentionProfile.STAGING: 8760,
        RetentionProfile.PROD: 8760,  # 1 year minimum
    },
    # DSAR requests — kept for compliance audits.
    "dsar_requests": {
        RetentionProfile.DEV: 8760,
        RetentionProfile.STAGING: 8760,
        RetentionProfile.PROD: 8760,
    },
    # Anonymisation audit — proves the pipeline was applied.
    "anonymization_audit": {
        RetentionProfile.DEV: 8760,
        RetentionProfile.STAGING: 8760,
        RetentionProfile.PROD: 8760,
    },
    # Raw camera frames — VERY short; held only during active analysis.
    "raw_video_frames": {
        RetentionProfile.DEV: 24,  # 1 day
        RetentionProfile.STAGING: 72,  # 3 days
        RetentionProfile.PROD: 168,  # 7 days max
    },
}


def retention_horizon_for(
    data_type: str, profile: RetentionProfile | str = RetentionProfile.PROD
) -> int:
    """Return the retention horizon in hours for a data_type under a profile."""
    if isinstance(profile, str):
        try:
            profile = RetentionProfile(profile)
        except ValueError as e:
            raise PrivacyError(f"unknown retention profile: {profile}") from e
    if data_type not in _RETENTION_HOURS:
        raise PrivacyError(f"unknown data_type: {data_type}")
    return _RETENTION_HOURS[data_type][profile]


def all_data_types() -> tuple[str, ...]:
    """Used by tests to enforce that every type has a retention assigned."""
    return tuple(_RETENTION_HOURS.keys())


# ---------------------------------------------------------------------------
# Anonymisation audit event — emitted by every service that runs LPR
# ---------------------------------------------------------------------------


AnonymizationMode = Literal["anonymized", "warranted"]


@dataclass(frozen=True)
class AnonymizationEvent:
    """
    Audit-event payload emitted whenever plate text is observed.

    Written to the `anonymization_audit` hypertable (D4 migration 0006) and
    also surfaced on the structured-log stream so it's queryable in Loki.
    """

    subject_id_hash: str
    source_service: str
    mode: AnonymizationMode = "anonymized"
    # Warranted-access fields — empty for the default mode.
    operator_sub: str = ""
    operator_jti: str = ""
    justification: str = ""
    extras: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "subject_id_hash": self.subject_id_hash,
            "source_service": self.source_service,
            "mode": self.mode,
            "operator_sub": self.operator_sub,
            "operator_jti": self.operator_jti,
            "justification": self.justification,
        }
        if self.extras:
            out.update(self.extras)
        return out
