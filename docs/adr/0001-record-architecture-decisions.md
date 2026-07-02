# ADR-0001: Record architecture decisions

**Status:** Accepted
**Date:** 2026-05-29

## Context

The ATMS codebase has grown from a coursework prototype into a real-life system targeted at safety-critical municipal deployment. Decisions taken from this point on must be discoverable and auditable months later — by a regulator, a safety reviewer, or a new engineer. Comments in code and PR descriptions are not enough; they decay and get lost.

## Decision

We will record every architecturally significant decision in an Architecture Decision Record (ADR) stored in `docs/adr/`, using the [Michael Nygard template](https://github.com/joelparkerhenderson/architecture-decision-record):

- `NNNN-kebab-case-title.md`, numbered monotonically.
- Sections: **Status**, **Date**, **Context**, **Decision**, **Consequences**.
- One decision per ADR. Supersession is explicit (`Status: Superseded by ADR-NNNN`).

"Architecturally significant" means any decision that:
- Constrains future implementation (technology choice, protocol, data model).
- Has a non-trivial reversal cost.
- Trades off safety, security, performance, or operability.

## Consequences

- Every PR introducing such a decision must include the ADR in the same PR.
- The ADR comes **before** the code: write the ADR, get review on the decision, then implement.
- ADRs are immutable once accepted. New circumstances => new ADR that supersedes.
- The senior engineer prompt and PRODUCTION_GAPS.md link to relevant ADRs as they accrete.
