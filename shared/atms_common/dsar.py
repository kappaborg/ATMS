"""
DSAR (Data Subject Access Request) processor — Phase D4.

Implements GDPR Art. 15/17/20 access, erase, and export actions over the
ATMS schema. The subject is identified by their `subject_id` hash (the
HMAC produced by `shared.atms_common.privacy.PlateAnonymizer`). The raw
plate text is hashed at the request boundary and never stored or logged
by this module.

See docs/adr/0014-data-retention-privacy.md.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

from shared.atms_common.errors import AtmsError


class DSARError(AtmsError):
    """Raised by the DSAR processor when a request is malformed or refused."""


class DSARAction(str, Enum):
    ACCESS = "access"  # GDPR Art. 15
    ERASE = "erase"  # GDPR Art. 17
    EXPORT = "export"  # GDPR Art. 20


class DSARStatus(str, Enum):
    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REFUSED = "refused"


# Tables that may hold rows linked to a `subject_id`. Update this list as the
# schema grows; tests will fail if new linkable tables aren't enrolled.
DSAR_LINKED_TABLES: tuple[str, ...] = ("traffic_detections",)


@dataclass(frozen=True)
class DSARRequest:
    """A single DSAR request."""

    request_id: str
    subject_id_hash: str
    action: DSARAction
    operator_sub: str
    operator_jti: str
    requested_at: datetime
    # Tables targeted by this request — defaults to every linked table.
    tables: tuple[str, ...] = DSAR_LINKED_TABLES
    justification: str = ""

    @staticmethod
    def new(
        *,
        subject_id_hash: str,
        action: DSARAction | str,
        operator_sub: str,
        operator_jti: str,
        justification: str = "",
    ) -> DSARRequest:
        if isinstance(action, str):
            try:
                action = DSARAction(action)
            except ValueError as e:
                raise DSARError(f"unknown DSAR action: {action}") from e
        if not subject_id_hash:
            raise DSARError("subject_id_hash is required")
        if not operator_sub:
            raise DSARError("operator_sub is required (per ADR-0014 §2 audit)")
        return DSARRequest(
            request_id=str(uuid.uuid4()),
            subject_id_hash=subject_id_hash,
            action=action,
            operator_sub=operator_sub,
            operator_jti=operator_jti,
            requested_at=datetime.now(tz=UTC),  # noqa: ATMS-CLOCK  audit display
            justification=justification,
        )


@dataclass(frozen=True)
class DSARResult:
    """Outcome of a DSAR request."""

    request_id: str
    status: DSARStatus
    completed_at: datetime
    rows_affected: dict[str, int] = field(default_factory=dict)
    payload: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "completed_at": self.completed_at.isoformat(),
            "rows_affected": dict(self.rows_affected),
            "payload": list(self.payload),
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Storage abstraction
# ---------------------------------------------------------------------------


class DSARStorage(Protocol):
    """
    Minimal storage protocol used by `DSARProcessor`.

    Production implementation is `PostgresDSARStorage` backed by
    `shared.atms_common.db.AtmsDatabase`. Tests use an in-memory implementation.
    """

    async def fetch_for_subject(
        self, subject_id_hash: str, tables: Iterable[str]
    ) -> dict[str, list[dict[str, Any]]]: ...

    async def erase_for_subject(
        self, subject_id_hash: str, tables: Iterable[str]
    ) -> dict[str, int]: ...

    async def record_request(self, req: DSARRequest) -> None: ...

    async def record_completion(self, result: DSARResult) -> None: ...


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class DSARProcessor:
    """
    Operator-facing entry point for DSAR handling.

    Each call to `handle(request)` performs the requested action, writes the
    request + result to the audit log, and returns the `DSARResult`. The
    processor never logs `subject_id_hash` outside of structured audit fields
    (so it doesn't leak into the general log stream).
    """

    def __init__(self, storage: DSARStorage) -> None:
        self._storage = storage

    async def handle(self, request: DSARRequest) -> DSARResult:
        await self._storage.record_request(request)

        try:
            if request.action is DSARAction.ACCESS:
                result = await self._access(request)
            elif request.action is DSARAction.EXPORT:
                result = await self._export(request)
            elif request.action is DSARAction.ERASE:
                result = await self._erase(request)
            else:
                raise DSARError(f"unsupported action: {request.action}")
        except DSARError as e:
            result = DSARResult(
                request_id=request.request_id,
                status=DSARStatus.REFUSED,
                completed_at=datetime.now(tz=UTC),  # noqa: ATMS-CLOCK  audit display
                error=str(e),
            )

        await self._storage.record_completion(result)
        return result

    # ------------------------------------------------------------------

    async def _access(self, request: DSARRequest) -> DSARResult:
        rows = await self._storage.fetch_for_subject(request.subject_id_hash, request.tables)
        flat: list[dict[str, Any]] = []
        rows_affected: dict[str, int] = {}
        for table, rs in rows.items():
            rows_affected[table] = len(rs)
            for r in rs:
                flat.append({"_table": table, **r})
        return DSARResult(
            request_id=request.request_id,
            status=DSARStatus.COMPLETED,
            completed_at=datetime.now(tz=UTC),  # noqa: ATMS-CLOCK  audit display
            rows_affected=rows_affected,
            payload=flat,
        )

    async def _export(self, request: DSARRequest) -> DSARResult:
        # Export is the same data as access; the caller is responsible for
        # rendering CSV / JSON for portability.
        return await self._access(request)

    async def _erase(self, request: DSARRequest) -> DSARResult:
        affected = await self._storage.erase_for_subject(request.subject_id_hash, request.tables)
        return DSARResult(
            request_id=request.request_id,
            status=DSARStatus.COMPLETED,
            completed_at=datetime.now(tz=UTC),  # noqa: ATMS-CLOCK  audit display
            rows_affected=affected,
        )


# ---------------------------------------------------------------------------
# In-memory storage for tests
# ---------------------------------------------------------------------------


class InMemoryDSARStorage:
    """Test double. Holds rows in nested dicts."""

    def __init__(self) -> None:
        # table -> list of rows
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.requests: list[DSARRequest] = []
        self.completions: list[DSARResult] = []

    def seed(self, table: str, rows: list[dict[str, Any]]) -> None:
        self.rows.setdefault(table, []).extend(rows)

    async def fetch_for_subject(
        self, subject_id_hash: str, tables: Iterable[str]
    ) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for t in tables:
            matched = [r for r in self.rows.get(t, []) if r.get("subject_id") == subject_id_hash]
            out[t] = matched
        return out

    async def erase_for_subject(
        self, subject_id_hash: str, tables: Iterable[str]
    ) -> dict[str, int]:
        affected: dict[str, int] = {}
        for t in tables:
            before = self.rows.get(t, [])
            new = [r for r in before if r.get("subject_id") != subject_id_hash]
            affected[t] = len(before) - len(new)
            self.rows[t] = new
        return affected

    async def record_request(self, req: DSARRequest) -> None:
        self.requests.append(req)

    async def record_completion(self, result: DSARResult) -> None:
        self.completions.append(result)
