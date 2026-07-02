# Runbook: DSAR (Data Subject Access Request)

**Audience:** Operator on duty for compliance + on-call legal liaison.
**Design:** [ADR-0014](../adr/0014-data-retention-privacy.md).
**Owning modules:** [`shared/atms_common/dsar.py`](../../shared/atms_common/dsar.py), [`shared/atms_common/privacy.py`](../../shared/atms_common/privacy.py).
**SLA:** GDPR-mandated **one calendar month**. Internal target: **5 business days**.

---

## 1. Request intake

Subjects (or regulators acting on their behalf) submit a request via:

- **Email** to `dsar@<operator-domain>` (the dedicated mailbox; tickets auto-open in the operator's helpdesk).
- **Letter** sent to the postal address listed in the operator's GDPR privacy notice.
- **In-person** at the operator's data-protection office.

Required from the subject:

1. **Identity proof** — government ID, vehicle registration, or equivalent proof they are the data subject.
2. **The license plate** they're enquiring about, or a court-ordered subject identifier if law enforcement is acting on their behalf.
3. **The action requested** — access (Art. 15), erase (Art. 17), or export (Art. 20).

> **Important:** the plate text is processed once at the API call boundary (hashed to `subject_id`). It is never stored, logged, or sent anywhere. Operator handling: read the plate from the intake form, type it into the DSAR API, shred the intake form per retention policy.

## 2. Operator workflow

### 2.1 Prerequisites

- JWT (A6) with the `engineer` role.
- A clean, isolated terminal — never run DSAR commands from a shared session.
- The intake ticket open in your helpdesk system so you can paste the `request_id`.

### 2.2 Submit the request

The api-gateway exposes (or will expose; D4 follow-up wires the HTTP edge):

```bash
curl -X POST https://api.atms.internal/admin/dsar \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "plate_text": "AB-12-CD",
        "action": "access",
        "justification": "TICKET-1234 — data subject request received 2026-05-30"
      }'
```

Response:

```json
{
  "request_id": "5e1a...uuid",
  "status": "completed",
  "completed_at": "2026-05-30T14:22:00Z",
  "rows_affected": {"traffic_detections": 18},
  "payload": [ /* 18 rows of subject-linked data */ ]
}
```

For **access** / **export**: the `payload` is the data to deliver to the subject. The operator renders it as CSV/JSON, signs the envelope, and returns it via the same channel the subject used.

For **erase**: `rows_affected` is the count. Confirm the count to the subject in writing.

### 2.3 Verify completion

Every DSAR action writes a row to `dsar_requests` (D4 migration 0006). To confirm:

```sql
SELECT request_id, action, status, completed_at, rows_affected, operator_sub
FROM dsar_requests
WHERE request_id = '5e1a...uuid';
```

Both the request row and the corresponding `audit_log` entry should be present. If either is missing, escalate (§4).

## 3. SLA tracking

The helpdesk ticket carries the `request_id` and a deadline 30 days from receipt. The compliance ops dashboard (Grafana) tracks open DSAR requests + age:

```
LokiQL:  {service="api-gateway", event="dsar_request"} | json | status != "completed"
```

Alert: any open DSAR > 20 days → page compliance lead.

## 4. Escalation

| Situation | Escalate to |
|-----------|-------------|
| Request ambiguous or possibly fraudulent | Legal liaison; do not action |
| Subject also requests records the operator does NOT hold (camera images, audio) | Legal — respond with "we do not collect that" reply |
| Erase result is 0 rows | Verify with the subject they gave the right plate; if correct, return "no records held" |
| `audit_log` row missing for a completed DSAR | Security incident — open INC, do not delete or retry |
| Warranted-access mode requested (raw plate text recovery) | Manager + Legal; see §5 |

## 5. Warranted access (break-glass)

By default, the warranted-access path (which reverses anonymisation to recover plate text) is **disabled**. To enable for a specific investigation:

1. Receive court order or formal investigation authorisation.
2. Operator with `admin` role obtains a short-lived JWT carrying the `warranted_access` claim (max 1 hour TTL).
3. Issue the request. The system writes an `anonymization_audit` row with `mode='warranted'`, the operator's `principal_sub`, and the supplied justification.
4. Automatic notification to `@OWNER-legal`.
5. Rate-limited to 50 reads per operator per hour (default; tunable per legal opinion).

Warranted-access is implemented behind ADR-0014 §4. The HTTP wiring lands in a follow-up PR after operator-process sign-off.

## 6. After a request closes

- Tag the helpdesk ticket with the `request_id` for cross-reference.
- Move any intake documentation (forms, signed letters) to the operator's retained-records vault per the retention schedule in `docs/privacy.md`.
- If the request triggered an erase: confirm the next-day continuous-aggregate refresh has flushed any cached personal data downstream (it shouldn't — aggregates strip `subject_id` — but verify for the first 30 days of operation).

## 7. Statistics + reporting

Monthly report (auto-generated by the analytics service):

- Number of DSAR requests, by action.
- Median + P95 time to completion.
- Number of warranted-access sessions, by operator.
- Rows affected per erase.

The report goes to the operator's DPO (Data Protection Officer) and is filed alongside the GDPR Article 30 records-of-processing.
