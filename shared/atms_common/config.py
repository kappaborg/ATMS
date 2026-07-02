"""
Pydantic-based settings — Phase B1.

Every service subclasses `AtmsBaseSettings` to add service-specific fields.
Reading from `os.getenv` directly is deprecated in favour of:

    class TrafficControllerSettings(AtmsBaseSettings):
        max_ai_staleness_ms: int = 2000

    settings = TrafficControllerSettings()  # raises ConfigError on bad input

Env var convention: shared fields use their natural names (`KAFKA_BOOTSTRAP_SERVERS`,
`AUTH_HS256_SECRET`, etc. — matching the SOPS-decrypted `.env`). Service-specific
fields use the `ATMS_` prefix (`ATMS_MAX_AI_STALENESS_MS`).

See ADR-0008.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.atms_common.errors import ConfigError


class AtmsBaseSettings(BaseSettings):
    """
    Base for every service's configuration.

    Service subclasses MUST NOT override `model_config`'s `env_file` /
    `env_file_encoding` / `extra` — those are project-wide defaults set here.
    """

    model_config = SettingsConfigDict(
        env_file=None,  # Production: from environment only (SOPS-decrypted at sync time).
        env_file_encoding="utf-8",
        extra="ignore",  # Tolerate unknown env vars — local .env may have many extras.
        case_sensitive=False,
    )

    # --- Service identity ---
    service_name: str = Field(default="atms-service")
    service_version: str = Field(default="0.0.0")

    # --- Logging ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )

    # --- Intersection identity (used by the safety pipeline) ---
    intersection_id: int = Field(default=1, validation_alias="ATMS_INTERSECTION_ID")

    # --- Kafka ---
    kafka_bootstrap_servers: str = Field(
        default="localhost:9092",
        validation_alias="KAFKA_BOOTSTRAP_SERVERS",
    )

    # --- Postgres ---
    postgres_host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field(default="atms", validation_alias="POSTGRES_DB")
    postgres_user: str = Field(default="atms", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(default="", validation_alias="POSTGRES_PASSWORD")

    # --- Redis ---
    redis_host: str = Field(default="localhost", validation_alias="REDIS_HOST")
    redis_port: int = Field(default=6379, validation_alias="REDIS_PORT")

    # --- Auth (ADR-0006). Service subclass sets a default audience. ---
    auth_algorithm: Literal["HS256", "RS256"] = Field(
        default="HS256", validation_alias="AUTH_ALGORITHM"
    )
    auth_issuer: str = Field(default="atms-dev", validation_alias="AUTH_ISSUER")
    auth_audience: str = Field(default="atms", validation_alias="AUTH_AUDIENCE")
    auth_hs256_secret: str | None = Field(default=None, validation_alias="AUTH_HS256_SECRET")
    auth_jwks_uri: str | None = Field(default=None, validation_alias="AUTH_JWKS_URI")
    auth_clock_skew_s: int = Field(default=30, validation_alias="AUTH_CLOCK_SKEW_S")

    # --- Run mode (atms_config.py legacy compatibility) ---
    run_mode: Literal["deployment", "experiment"] = Field(
        default="deployment", validation_alias="ATMS_RUN_MODE"
    )

    @field_validator("auth_hs256_secret")
    @classmethod
    def _hs256_min_length(cls, v: str | None) -> str | None:
        """Refuse to start with a too-short HS256 secret outside dev/test."""
        if v is None or v == "":
            return v
        if len(v) < 16:
            raise ValueError(
                "AUTH_HS256_SECRET must be at least 16 bytes (prefer 32+ per RFC 7518)"
            )
        return v

    @classmethod
    def load(cls) -> AtmsBaseSettings:
        """
        Load settings; translate Pydantic ValidationError → ConfigError so
        the top-level main.py can present a clean error message.
        """
        try:
            return cls()
        except ValidationError as e:
            raise ConfigError(f"invalid configuration:\n{e}") from e
