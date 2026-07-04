# Data Protection Impact Assessment (DPIA) — ATMS Traffic Monitoring Pilot

**Status: DRAFT for completion by the deploying authority (the data
controller).** Fields marked `[CONTROLLER]` must be filled in before
processing begins. Drafted against GDPR concepts; Bosnia & Herzegovina's Law
on Personal Data Protection is GDPR-aligned — verify current local
requirements with the Personal Data Protection Agency (AZLP).

## 1. Processing description

| Item | Description |
|---|---|
| System | ATMS panel gateway: fixed traffic cameras → on-device AI detection (vehicles, pedestrians), signal-timing decision support, traffic-violation alerts with photographic evidence and license-plate capture |
| Controller | `[CONTROLLER: authority name + contact]` |
| DPO | `[CONTROLLER: data protection officer]` |
| Purpose | traffic-flow optimisation and road-safety monitoring; secondary: evidence records of traffic violations for `[CONTROLLER: define use — advisory analytics vs referral to enforcement]` |
| Lawful basis | `[CONTROLLER: e.g., public task / legal obligation for road safety; legitimate interest is unlikely to suffice for plate capture]` |

## 2. Data inventory

| Data | Personal? | Where | Retention |
|---|---|---|---|
| Live video frames | yes (transient) | processed in memory; not stored as video | not retained |
| Aggregate traffic metrics (counts, speeds, CO₂) | no (no identifiers) | history DB | indefinite (aggregates only) |
| Violation records: type, time, camera | limited | violations DB | `PANEL_VIOLATION_RETENTION_DAYS` (set to 30 in the provided deployment configs; 0/off must not be used for a pilot) — auto-purged |
| Violation snapshot (vehicle photo, may show plate/occupants) | **yes** | snapshot files | same auto-purge (row + file) |
| License-plate string (violators only) | **yes** | violations DB | same auto-purge |
| Operator accounts + audit log | yes (staff) | config + logs | `[CONTROLLER: log retention]` |

Key design fact: **plates are read only for vehicles already flagged for a
violation** — never for general traffic. The wider ATMS platform additionally
provides anonymisation and data-subject-request tooling
(`shared/atms_common/privacy.py`).

## 3. Necessity & proportionality

- Traffic optimisation uses **only aggregates**; no personal data is needed
  or kept for the signal-timing function.
- Violation evidence is minimised: single snapshot crop (not continuous
  video), plate only on violation, automatic retention purge, per-country
  format validation plus multi-frame consensus so an uncertain plate is
  recorded as *no plate* rather than a wrong one.
- `[CONTROLLER]` must justify: chosen retention period; which violation types
  are in scope; whether records are shared with police and under what
  agreement.

## 4. Risks and mitigations

| Risk | Mitigation (implemented) | Residual action `[CONTROLLER]` |
|---|---|---|
| Unauthorised access to evidence | RBAC (viewer/operator/admin), signed sessions, append-only audit log of logins/actions; bind to localhost or TLS reverse proxy | enforce TLS; account lifecycle policy |
| Excessive retention | automatic sweep deletes rows **and** snapshot files after the retention window | set/justify the window |
| Wrong-person identification | plate consensus + format validation (goal: zero wrong plates); ReID merges only on high-confidence; violation review procedure (see Validation Protocol §4) | human review before any enforcement referral |
| Function creep (tracking individuals) | no cross-camera person tracking; plates not read for non-violators; aggregates carry no IDs | policy prohibiting repurposing; access reviews |
| Data breach | data at rest on the deployment host/volume; no cloud dependency; PII never committed to source control (gitignored) | disk encryption; host hardening; breach procedure |
| Transparency | — | signage at monitored intersections; public privacy notice; AZLP consultation if required |

## 5. Data-subject rights

Access/erasure requests: violation records are queryable by time/camera/type/**plate** via the
violations API (`GET /violations?plate=…`), and a single record + its
snapshot can be erased (`DELETE /violations/{id}`, audited). `[CONTROLLER]` must
define the request channel and identity-verification procedure. Aggregate
metrics contain no identifiers and are out of DSAR scope.

## 6. Sign-off

```
DPO review: ____________  date ____
Controller approval: ____________  date ____
AZLP consultation required? yes/no — reference: ________
Review date (max 12 months): ________
```
