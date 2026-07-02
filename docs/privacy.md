# Privacy & data-protection compliance

A map of ATMS controls to GDPR + CCPA obligations. Specific deployments may have additional national requirements; consult the operator's DPO.

Master ADR: [`docs/adr/0014-data-retention-privacy.md`](adr/0014-data-retention-privacy.md).
Operational runbook: [`docs/runbooks/dsar.md`](runbooks/dsar.md).

## Control map

### Personal data classification

| Data | Personal data? | Why |
|------|----------------|-----|
| License plate text | YES | Direct identifier |
| `subject_id` (HMAC-SHA256 of plate + salt) | "pseudonymised" per GDPR Art. 4(5) | Reversible only with the salt — kept offline / SOPS-encrypted |
| Detection bbox, object class, speed | NO (aggregate / anonymous) | No link to an individual |
| Continuous aggregates (`*_1min`, `*_1h`) | NO | Aggregation removes the linkage |
| Operator JWT `sub` | YES (the operator's identity) | Stored in `audit_log` — retained per legal floor |

### GDPR articles

| Article | What it requires | How ATMS satisfies it | Ref |
|---------|------------------|-----------------------|-----|
| **Art. 5(1)(b)** — Purpose limitation | Data only for stated purpose | Traffic flow analytics + signal control; no marketing, no behavioural profiling | ADR-0014 §1, ADR-0004 |
| **Art. 5(1)(c)** — Data minimisation | Collect only what's needed | Plate text destroyed after hashing; only `subject_id` + bbox stored | ADR-0014 §1, `shared/atms_common/privacy.py` |
| **Art. 5(1)(e)** — Storage limitation | Retain only as long as needed | Per-table retention via C4 (`add_retention_policy`); enforced automatically | ADR-0013, ADR-0014 §3 |
| **Art. 5(1)(f)** — Integrity & confidentiality | Encrypt + secure | Encryption at rest (Postgres + object store), mTLS in transit (B5), SOPS-encrypted secrets (A5) | ADR-0014 §5, ADR-0012, ADR-0002 |
| **Art. 6** — Lawful basis | Has a legal basis | Public-interest traffic management + operator legitimate interest (documented per deployment) | Per-pilot legal opinion |
| **Art. 15** — Right of access | Provide a copy on request | `POST /admin/dsar` with `action=access` | ADR-0014 §2, `shared/atms_common/dsar.py` |
| **Art. 17** — Right to erasure | Erase on request | `POST /admin/dsar` with `action=erase` | ADR-0014 §2, `shared/atms_common/dsar.py` |
| **Art. 20** — Data portability | Provide structured-data export | `POST /admin/dsar` with `action=export` (CSV/JSON) | ADR-0014 §2 |
| **Art. 25** — Data protection by design | Build privacy in, not on top | Anonymisation is the default code path; opt-out requires explicit ADR + Legal sign-off | ADR-0014 §1 §4 |
| **Art. 30** — Records of processing | Maintain a register | Monthly DSAR statistics + system-architecture docs filed | DSAR runbook §7 |
| **Art. 32** — Security of processing | Appropriate technical measures | Resilience (B4), mTLS (B5), JWT+RBAC (A6), audit log (A1+A6) | ADR-0009, ADR-0012, ADR-0006 |
| **Art. 33** — Breach notification | Notify within 72h | Loki alert `AuthDenialSpike` + SOPS-leak gates kick off the IR runbook | `docs/runbooks/secrets.md` §7 |
| **Art. 35** — DPIA when high risk | Conduct a data protection impact assessment | Required per deployment; out of scope here |

### CCPA (California, if applicable)

| Right | How ATMS supports it |
|-------|---------------------|
| Right to know what data is collected | Privacy notice + DSAR access request |
| Right to delete | DSAR erase action |
| Right to opt-out of sale | Not applicable — ATMS does not sell data |
| Right to non-discrimination | Not applicable — no consumer interaction |

## Operator responsibilities (NOT enforced by the code)

The code provides the controls; the operator must run them. Specifically:

- Publish a public privacy notice naming the data controller, purposes, retention, and DSAR contact.
- Sign a Data Processing Agreement (DPA) with the operator's hosting provider.
- Conduct a DPIA before pilot launch in any new jurisdiction.
- Train operators on the DSAR runbook before granting them the `engineer` role.
- Maintain a register of warranted-access sessions per ADR-0014 §4.
- Notify supervisory authorities within 72h of any breach involving personal data.

## What this codebase does NOT cover

- Privacy-notice content (legal text per jurisdiction).
- DPIA templates.
- Cross-border data transfer mechanisms (SCCs etc.).
- Sub-processor management.
- Consent capture (ATMS doesn't capture consent — lawful basis is public-interest / legitimate interest).

These are operator-side artefacts; track them in the operator's compliance management system.
