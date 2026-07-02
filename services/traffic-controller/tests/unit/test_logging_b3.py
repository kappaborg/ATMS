"""Tests for the Phase B3 logging context binders."""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from shared.atms_common.logging import (
    bind_decision_id,
    bind_log_context,
    configure_logging,
)


@pytest.fixture(autouse=True)
def _clean_handlers():
    yield
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)


class TestBindDecisionId:
    def test_inside_scope_decision_id_appears(self, capsys):
        configure_logging(service="svc", version="1.0")
        log = structlog.get_logger()
        with bind_decision_id(1234567890123):
            log.info("inside")
        captured = capsys.readouterr().out
        line = next(line for line in captured.splitlines() if '"event": "inside"' in line)
        record = json.loads(line)
        assert record["decision_id"] == "1234567890123"

    def test_outside_scope_decision_id_absent(self, capsys):
        configure_logging(service="svc", version="1.0")
        log = structlog.get_logger()
        with bind_decision_id(42):
            log.info("inside")
        log.info("outside")
        captured = capsys.readouterr().out
        outside_line = next(
            line for line in captured.splitlines() if '"event": "outside"' in line
        )
        record = json.loads(outside_line)
        # decision_id was unbound on context exit.
        assert "decision_id" not in record


class TestBindLogContext:
    def test_multiple_fields(self, capsys):
        configure_logging(service="svc", version="1.0")
        log = structlog.get_logger()
        with bind_log_context(principal_sub="alice", request_id="req-1"):
            log.info("scoped")
        captured = capsys.readouterr().out
        line = next(line for line in captured.splitlines() if '"event": "scoped"' in line)
        record = json.loads(line)
        assert record["principal_sub"] == "alice"
        assert record["request_id"] == "req-1"

    def test_unbinds_on_exit(self, capsys):
        configure_logging(service="svc", version="1.0")
        log = structlog.get_logger()
        with bind_log_context(foo="bar"):
            pass
        log.info("after")
        captured = capsys.readouterr().out
        line = next(line for line in captured.splitlines() if '"event": "after"' in line)
        record = json.loads(line)
        assert "foo" not in record
