"""Per-intersection deployment configuration.

A single YAML file per intersection contains everything that's site-
specific: camera calibration, crosswalk zones, NTCIP target IP, MQTT
broker, neighbour list for green-wave, transit route mapping. The
chamber loads it at startup and configures all components.

The schema is intentionally flat and human-editable — operators in
the field can update it without redeploying code.

Example (production):

```yaml
# intersection-005.yaml
intersection_id: alley-005
description: "5. Levent Buyukdere & Esentepe junction"

camera:
  pixels_per_meter: 32.5
  source: rtsp://10.4.5.6:554/stream1
  width: 1920
  height: 1080

crosswalk_zones:
  # x1, y1, x2, y2 in camera pixel coords
  north_south: [120, 820, 1800, 1050]
  east_west:   [60, 200, 380, 980]

ntcip:
  controller_host: 10.4.5.10
  controller_port: 161
  community: atms-public
  closed_loop_poll_seconds: 1.5

mqtt:
  broker_host: mosquitto.atms.city
  broker_port: 1883
  upstream_neighbors: [alley-004, alley-003]

green_wave:
  - intersection_id: alley-004
    offset_seconds: 18.0
    through_direction: north_south

transit_priority:
  feed_url: "https://api.ibb.gov.tr/iett/gtfs-rt/vehicles"
  delay_threshold_s: 60.0
  routes:
    metrobus-34: east_west
    metrobus-29: north_south

prometheus:
  listen_port: 9090

audit:
  db_path: /var/lib/atms/intersection-005-audit.db
  max_size_mb: 200
  retention_days: 90
```

Validation: missing required fields fail loudly at startup (chamber
refuses to run with incomplete config). Optional sections (transit,
green_wave) can be omitted — the chamber runs without them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("atms.chamber.site_config")


@dataclass(frozen=True)
class CameraConfig:
    pixels_per_meter: float
    source: str = ""  # RTSP URL or video file path
    width: int = 1920
    height: int = 1080
    # Per-camera homography JSON path (produced by site-survey tool).
    # When set, supersedes the single-ratio pixels_per_meter for speed
    # estimation. Empty = use single-ratio fallback.
    homography_path: str = ""


@dataclass(frozen=True)
class NtcipConfig:
    controller_host: str = "127.0.0.1"
    controller_port: int = 161
    community: str = "public"  # SNMPv1/v2c — dev / legacy controllers only
    closed_loop_poll_seconds: float = 2.0
    # SNMPv3 — production secure config. When `snmp_version: 3` is set
    # the chamber uses NtcipV3ControllerBridge; otherwise the SNMPv1
    # bridge. Production deployment defaults to v3 authPriv.
    snmp_version: int = 1  # 1 or 3
    v3_username: str = ""
    v3_auth_passphrase: str = ""
    v3_priv_passphrase: str = ""
    v3_security_level: str = "authPriv"  # noAuthNoPriv | authNoPriv | authPriv


@dataclass(frozen=True)
class MqttConfig:
    broker_host: str = ""
    broker_port: int = 1883
    username: str = ""
    password: str = ""
    upstream_neighbors: tuple[str, ...] = ()


@dataclass(frozen=True)
class GreenWaveNeighbor:
    intersection_id: str
    offset_seconds: float
    through_direction: str


@dataclass(frozen=True)
class TransitConfig:
    feed_url: str = ""
    delay_threshold_s: float = 60.0
    poll_interval_s: float = 10.0
    bonus_per_late_bus: float = 0.10
    routes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PrometheusConfig:
    listen_host: str = "0.0.0.0"
    listen_port: int = 9090


@dataclass(frozen=True)
class AuditConfig:
    db_path: str = ""  # if empty → in-memory JSONL fallback
    max_size_mb: float = 200.0
    retention_days: int = 90


@dataclass(frozen=True)
class RegionConfig:
    """Region-specific overlays for the emission table + operator locale.
    Loaded if `region.emission_overlay` is set; chamber uses these to
    adjust per-brand emission multipliers (older fleet, diesel share,
    regional brands) and operator-console language strings.
    """

    country_code: str = ""  # ISO-3166-1 alpha-2, e.g. "BA", "TR", "GB"
    pilot_city: str = ""
    emission_overlay: str = ""  # path to per-region multiplier YAML
    operator_locale: str = "en"  # "en", "bs", "tr"


@dataclass(frozen=True)
class SiteConfig:
    intersection_id: str
    description: str
    camera: CameraConfig
    crosswalk_zones: dict[str, tuple[int, int, int, int]]
    ntcip: NtcipConfig
    mqtt: MqttConfig
    green_wave: tuple[GreenWaveNeighbor, ...]
    transit: TransitConfig
    prometheus: PrometheusConfig
    audit: AuditConfig
    region: RegionConfig = RegionConfig()

    @classmethod
    def load(cls, path: Path | str) -> "SiteConfig":
        """Load + validate a site YAML config. Raises ValueError with a
        clear message if any required section is missing.

        Supports `${VAR}` env var expansion so secrets (SNMPv3
        passphrases, MQTT auth, GTFS feed tokens) can be injected from
        the deployment environment without checking them into config
        files. Operator pattern:

            v3_auth_passphrase: ${ATMS_NTCIP_AUTH_KEY}

        gets replaced with the value of `ATMS_NTCIP_AUTH_KEY` at load
        time. Missing env vars resolve to empty string (the validation
        layer fails loudly if a required field is empty).
        """
        import os  # noqa: PLC0415
        import re  # noqa: PLC0415

        import yaml  # noqa: PLC0415

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"site config not found: {path}")
        text = path.read_text()
        # Expand ${VAR} references. Quoted ${VAR} inside YAML strings
        # works because we substitute before parsing.
        text = re.sub(
            r"\$\{([A-Z_][A-Z0-9_]*)\}",
            lambda m: os.environ.get(m.group(1), ""),
            text,
        )
        raw = yaml.safe_load(text) or {}

        def _require(key: str) -> Any:
            if key not in raw:
                raise ValueError(f"site config {path}: missing required '{key}'")
            return raw[key]

        camera = _require("camera")
        if "pixels_per_meter" not in camera:
            raise ValueError(f"site config {path}: camera.pixels_per_meter is required")

        zones_raw = raw.get("crosswalk_zones", {})
        zones: dict[str, tuple[int, int, int, int]] = {}
        for direction, coords in zones_raw.items():
            if len(coords) != 4:
                raise ValueError(
                    f"site config {path}: crosswalk_zones.{direction} "
                    "must be [x1, y1, x2, y2]"
                )
            zones[direction] = (int(coords[0]), int(coords[1]),
                                int(coords[2]), int(coords[3]))

        # Green wave neighbours
        green_wave_raw = raw.get("green_wave", []) or []
        green_wave = tuple(
            GreenWaveNeighbor(
                intersection_id=item["intersection_id"],
                offset_seconds=float(item["offset_seconds"]),
                through_direction=item["through_direction"],
            )
            for item in green_wave_raw
        )

        return cls(
            intersection_id=_require("intersection_id"),
            description=raw.get("description", ""),
            camera=CameraConfig(
                pixels_per_meter=float(camera["pixels_per_meter"]),
                source=camera.get("source", ""),
                width=int(camera.get("width", 1920)),
                height=int(camera.get("height", 1080)),
                homography_path=camera.get("homography_path", ""),
            ),
            crosswalk_zones=zones,
            ntcip=NtcipConfig(
                controller_host=raw.get("ntcip", {}).get("controller_host", "127.0.0.1"),
                controller_port=int(raw.get("ntcip", {}).get("controller_port", 161)),
                community=raw.get("ntcip", {}).get("community", "public"),
                closed_loop_poll_seconds=float(
                    raw.get("ntcip", {}).get("closed_loop_poll_seconds", 2.0)
                ),
                snmp_version=int(raw.get("ntcip", {}).get("snmp_version", 1)),
                v3_username=raw.get("ntcip", {}).get("v3_username", ""),
                v3_auth_passphrase=raw.get("ntcip", {}).get("v3_auth_passphrase", ""),
                v3_priv_passphrase=raw.get("ntcip", {}).get("v3_priv_passphrase", ""),
                v3_security_level=raw.get("ntcip", {}).get("v3_security_level", "authPriv"),
            ),
            mqtt=MqttConfig(
                broker_host=raw.get("mqtt", {}).get("broker_host", ""),
                broker_port=int(raw.get("mqtt", {}).get("broker_port", 1883)),
                username=raw.get("mqtt", {}).get("username", ""),
                password=raw.get("mqtt", {}).get("password", ""),
                upstream_neighbors=tuple(
                    raw.get("mqtt", {}).get("upstream_neighbors", []) or []
                ),
            ),
            green_wave=green_wave,
            transit=TransitConfig(
                feed_url=raw.get("transit_priority", {}).get("feed_url", ""),
                delay_threshold_s=float(
                    raw.get("transit_priority", {}).get("delay_threshold_s", 60.0)
                ),
                poll_interval_s=float(
                    raw.get("transit_priority", {}).get("poll_interval_s", 10.0)
                ),
                bonus_per_late_bus=float(
                    raw.get("transit_priority", {}).get("bonus_per_late_bus", 0.10)
                ),
                routes=raw.get("transit_priority", {}).get("routes", {}) or {},
            ),
            prometheus=PrometheusConfig(
                listen_host=raw.get("prometheus", {}).get("listen_host", "0.0.0.0"),
                listen_port=int(raw.get("prometheus", {}).get("listen_port", 9090)),
            ),
            audit=AuditConfig(
                db_path=raw.get("audit", {}).get("db_path", ""),
                max_size_mb=float(raw.get("audit", {}).get("max_size_mb", 200.0)),
                retention_days=int(raw.get("audit", {}).get("retention_days", 90)),
            ),
            region=RegionConfig(
                country_code=raw.get("region", {}).get("country_code", ""),
                pilot_city=raw.get("region", {}).get("pilot_city", ""),
                emission_overlay=raw.get("region", {}).get("emission_overlay", ""),
                operator_locale=raw.get("region", {}).get("operator_locale", "en"),
            ),
        )
