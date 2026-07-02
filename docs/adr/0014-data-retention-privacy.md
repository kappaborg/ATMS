# ADR-0014: Data retention, anonymization, and DSAR handling

**Status:** Accepted
**Date:** 2026-05-30
**Closes:** PRODUCTION_GAPS.md gap #19 (Phase D4)

## Context

ATMS observes pedestrians and reads license plates from public-road cameras. That puts us under GDPR (ADR-0004 picked EU jurisdiction) and likely under equivalent national rules. The senior-engineer audit flagged three gaps:

1. **Default-on anonymization missing.** `services/ai-perception/src/license_plate_processor.py` has a `PlateAnonymizer` class but evidence of it being applied is absent — raw plate text leaks into downstream consumers.
2. **No DSAR endpoint.** "Data Subject Access Request" — under GDPR Art. 15/17 a subject has the right to access or erase records the operator holds about them. We have neither the API nor the storage model for it.
3. **Video retention policy missing.** `Processed_Videos/` has no TTL, no encryption-at-rest, no access audit.

C4 (TimescaleDB + Alembic) shipped per-table retention. D4 adds the privacy semantics on top.

## Decision

### 1. License-plate anonymization (default on)

Every plate read produces a **subject identifier hash** via HMAC-SHA256 with a per-deployment salt:

```
subject_id = HMAC-SHA256(salt, plate_text).hex
```

Properties:
- **Deterministic**: the same plate always yields the same `subject_id`. Enables longitudinal analytics ("count distinct vehicles at intersection X today") without storing plate text.
- **Irreversible** without the salt: a leak of the database without the salt does not leak plate text.
- **Salt rotation**: rotates per the secrets-rotation procedure (ADR-0002 §4.2). Old `subject_id`s become unmatchable across the rotation boundary — by design, the linkage drops out.

Storage rule:
- `traffic_detections.plate_text` does **not** exist as a column. Only `subject_id` (the hash) is stored.
- Raw plate text exists in memory only during the detection request, then is destroyed.
- For warranted access (law enforcement, audited investigation): a separate, gated path (§4 below).

Implementation: `shared/atms_common/privacy.py:PlateAnonymizer`. Every service consuming plate text MUST go through this module; direct string storage is prohibited.

### 2. DSAR (Data Subject Access Request)

A subject (or a regulator acting on their behalf) presents a license plate. The operator hashes it via the same `PlateAnonymizer` to derive the `subject_id`, then performs the requested action:

- **Access** (Art. 15): return every row where `subject_id` matches, across detections / mode_transitions / audit_log. Output is a signed JSON document with a request_id for the subject's records.
- **Erase** (Art. 17): nullify the `subject_id` column on every matching row. The remainder of the row (count, bbox, time) stays — that's anonymous traffic data not personal data. Hypertable retention also auto-removes the original rows on its own schedule.
- **Export** (Art. 20): same as access but with a structured-data format (CSV + JSON) sized for portability.

DSAR is operator-initiated via `POST /admin/dsar`. Endpoint is `engineer+` gated by JWT (A6) AND requires a "warranted access" claim — see §4. Every DSAR action lands in `dsar_requests` (new hypertable, migration 0006) with operator `principal_sub`, `principal_jti`, the action taken, completion time, and rows affected.

SLA: GDPR requires a response within one calendar month. Internal SLA: 5 business days.

### 3. Per-data-type retention (extends C4)

C4 set retention by env profile. D4 declares which data types are "personal data" and which are not, and assigns retention accordingly. The migration `0005_retention.py` already encodes these; this ADR documents the legal mapping.

| Data type | Storage | Retention (prod) | GDPR basis |
|-----------|---------|------------------|------------|
| `traffic_detections.subject_id` | `traffic_detections` hypertable | 90 days | Legitimate interest, anonymised |
| `traffic_detections.bbox`, `direction`, `class` | same | 90 days | Anonymous traffic data — not personal |
| `traffic_detections_1h` (aggregate) | continuous aggregate | 2 years | Aggregate; not personal |
| `decisions` | hypertable | 90 days | Operational audit |
| `audit_log` (operator + DSAR actions) | hypertable | 1 year (legal floor) | Required for compliance audits |
| Raw camera frames | object storage | **7 days max** | Only retained during active analysis |
| Anonymisation audit (`anonymization_audit`) | hypertable | 1 year | Required to prove anonymisation pipeline integrity |

### 4. Warranted access (break-glass for plate text)

For law-enforcement requests or formal investigations, an operator with the `admin` role plus a "warranted access" claim on their JWT may invoke a **separate** path that does not anonymize. Implementation rules:

- The warranted-access claim is short-lived (max 1 hour TTL).
- Every plate read in this mode emits an `anonymization_audit` row with `mode='warranted'`, the operator's `principal_sub`, and a free-text justification.
- The path is rate-limited to N reads per operator per hour (default 50; tunable per legal opinion).
- An automatic email goes to `@OWNER-legal` for every warranted-access session.

Default deployment: warranted-access is **disabled**. Operators must explicitly enable it per-deployment after legal sign-off — documented in the deployment runbook.

### 5. Encryption at rest

- Postgres data dir: encrypted via the storage class (LUKS or cloud-equivalent). Operator deploys with the appropriate StorageClass.
- Object storage for raw frames: server-side encryption with KMS-managed keys. Key rotation per the storage provider's standard.
- Secrets in transit: SOPS + age (A5) for git-tracked secrets; mTLS (B5) for in-cluster.
- Backups: encrypted at the storage layer; rotation key separate from the primary KMS key.

Each is independently auditable; the runbook lists how to verify each.

### 6. Logging hygiene

- The B3 JSON log schema NEVER includes plate text — only `subject_id` is permitted.
- `audit_log` includes the actor's `principal_sub` but the data subject's `subject_id` only when relevant. Never plate text.
- A CI rule (extends `.gitleaks.toml`) blocks PRs that introduce log statements containing `plate_text` or known plate-shaped patterns.

## Out of scope for D4

- **Face blurring** in raw frames. Documented as the pattern; concrete implementation lands when video storage becomes a deployment requirement.
- **Cross-jurisdiction consent UX.** EU-only for the pilot. Adding non-EU jurisdictions requires a follow-up ADR.
- **Right to portability beyond CSV/JSON.** GDPR Art. 20 is satisfied by structured-data export; specific schemas are jurisdiction-specific.

## Consequences

- `ai-perception`, `ntcip-interface`, and any future LPR consumer route plate text through `PlateAnonymizer` exactly once at ingestion. After that boundary, plate text does not exist anywhere reachable from the runtime.
- `services/api-gateway` gets a new `POST /admin/dsar` endpoint gated by `engineer+`. The dashboard service gets a corresponding UI panel (follow-up PR).
- New audit log signal: `anonymization_audit` — DSAR processors and warranted-access calls both write to it.
- The PR that turns on warranted-access in a deployment carries a Legal+Security review label (CODEOWNERS).
- `make secrets-check` (A5) and gitleaks (A4) gain a rule that blocks plate-text patterns in committed code or sample data.
