"""
Tests for shared/atms_common/{errors,config,logging,health,kafka}.py (Phase B1).

These tests exercise the new modules through the traffic-controller's test
harness so they share the existing CI lane and conftest path setup.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.atms_common.auth import AuthError
from shared.atms_common.config import AtmsBaseSettings
from shared.atms_common.errors import (
    AtmsError,
    ConfigError,
    KafkaError,
    SchemaError,
)
from shared.atms_common.health import CheckResult, HealthRouter
from shared.atms_common.logging import (
    bind_intersection,
    configure_logging,
    get_logger,
)


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    def test_all_inherit_from_atmserror(self):
        # AuthError predates AtmsError (A6) and lives in shared.atms_common.auth
        # — see the docstring of errors.py for the rationale. It's NOT in the
        # AtmsError hierarchy and is imported from its own module.
        for cls in (ConfigError, SchemaError, KafkaError):
            assert issubclass(cls, AtmsError)
        assert issubclass(AuthError, Exception)

    def test_atmserror_inherits_from_exception(self):
        assert issubclass(AtmsError, Exception)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


class TestAtmsBaseSettings:
    def test_defaults_load(self, monkeypatch):
        # Clear auth fields so the validator doesn't trip on short test value.
        monkeypatch.delenv("AUTH_HS256_SECRET", raising=False)
        s = AtmsBaseSettings()
        assert s.kafka_bootstrap_servers == "localhost:9092"
        assert s.intersection_id == 1
        assert s.log_level == "INFO"

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("ATMS_INTERSECTION_ID", "42")
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker:9092")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        # Provide a long-enough secret to satisfy the validator.
        monkeypatch.setenv("AUTH_HS256_SECRET", "x" * 32)
        s = AtmsBaseSettings()
        assert s.intersection_id == 42
        assert s.kafka_bootstrap_servers == "broker:9092"
        assert s.log_level == "DEBUG"
        assert s.auth_hs256_secret == "x" * 32

    def test_short_hs256_secret_rejected(self, monkeypatch):
        monkeypatch.setenv("AUTH_HS256_SECRET", "too-short")
        with pytest.raises(ConfigError):
            AtmsBaseSettings.load()

    def test_empty_hs256_secret_allowed(self, monkeypatch):
        monkeypatch.setenv("AUTH_HS256_SECRET", "")
        s = AtmsBaseSettings()
        assert s.auth_hs256_secret == ""

    def test_invalid_log_level_rejected(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "PARANOID")
        monkeypatch.delenv("AUTH_HS256_SECRET", raising=False)
        with pytest.raises(ConfigError):
            AtmsBaseSettings.load()

    def test_subclass_adds_field(self, monkeypatch):
        from pydantic import Field  # noqa: PLC0415

        class _MySettings(AtmsBaseSettings):
            my_widget: int = Field(default=7, validation_alias="MY_WIDGET")

        monkeypatch.delenv("AUTH_HS256_SECRET", raising=False)
        monkeypatch.setenv("MY_WIDGET", "99")
        s = _MySettings()
        assert s.my_widget == 99


# ---------------------------------------------------------------------------
# logging
# ---------------------------------------------------------------------------


class TestLogging:
    def test_configure_is_idempotent(self):
        configure_logging(service="svc-a", version="1.0.0")
        configure_logging(service="svc-a", version="1.0.0")
        log = get_logger()
        log.info("hello")

    def test_bind_intersection_updates_static_context(self):
        from shared.atms_common.logging import _CONTEXT  # noqa: PLC0415

        configure_logging(service="svc-a", version="1.0.0", intersection_id=1)
        assert _CONTEXT["intersection_id"] == "1"
        bind_intersection(99)
        assert _CONTEXT["intersection_id"] == "99"


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def _ok() -> CheckResult:
    return CheckResult(ok=True, detail="all good")


def _fail() -> CheckResult:
    return CheckResult(ok=False, detail="broker down")


async def _ok_async() -> CheckResult:
    return _ok()


async def _fail_async() -> CheckResult:
    return _fail()


class TestHealthRouter:
    def test_live_always_returns_200_pre_startup(self):
        app = FastAPI()
        HealthRouter(service_name="svc").attach(app)
        client = TestClient(app)
        assert client.get("/live").status_code == 200

    def test_startup_reports_starting_then_started(self):
        app = FastAPI()
        r = HealthRouter(service_name="svc")
        r.attach(app)
        client = TestClient(app)
        assert client.get("/startup").json()["status"] == "starting"
        r.mark_started()
        assert client.get("/startup").json()["status"] == "started"

    def test_ready_503_before_startup(self):
        app = FastAPI()
        HealthRouter(service_name="svc").attach(app)
        client = TestClient(app)
        assert client.get("/ready").status_code == 503

    def test_ready_503_when_a_check_fails(self):
        app = FastAPI()
        r = HealthRouter(service_name="svc")
        r.add_check("ok", _ok_async)
        r.add_check("broker", _fail_async)
        r.mark_started()
        r.attach(app)
        client = TestClient(app)
        body = client.get("/ready").json()
        assert body["detail"]["status"] == "not_ready"
        assert body["detail"]["checks"]["broker"]["ok"] is False

    def test_ready_200_when_all_checks_pass(self):
        app = FastAPI()
        r = HealthRouter(service_name="svc")
        r.add_check("ok", _ok_async)
        r.mark_started()
        r.attach(app)
        client = TestClient(app)
        body = client.get("/ready").json()
        assert body["status"] == "ready"
        assert body["checks"]["ok"]["ok"] is True


# ---------------------------------------------------------------------------
# kafka (importability + behaviour without a real broker)
# ---------------------------------------------------------------------------


class TestKafkaWrappers:
    def test_import_works(self):
        from shared.atms_common.kafka import (  # noqa: PLC0415
            AtmsKafkaConsumer,
            AtmsKafkaProducer,
        )

        assert AtmsKafkaProducer is not None
        assert AtmsKafkaConsumer is not None

    def test_send_without_start_raises_kafka_error(self):
        from shared.atms_common.kafka import AtmsKafkaProducer  # noqa: PLC0415

        p = AtmsKafkaProducer(bootstrap_servers="localhost:9092")
        with pytest.raises(KafkaError):
            asyncio.run(p.send("topic", value={"x": 1}))
