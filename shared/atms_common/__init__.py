"""
ATMS shared library (atms_common).

Created in Phase A for the failsafe controller (gap #1); will be expanded in
Phase B (B1) to host the full set of cross-service utilities: Config, Logger,
Tracing, KafkaProducer/Consumer, HealthEndpoints, HttpClient, Errors, Metrics.

Scope today:
- decision: DecisionMessage schema + validation result.
- clock: Clock protocol + production + fake implementations.
- metrics: MetricsRecorder protocol + production + in-memory implementations.
- safety: hard safety invariants + FixedTimePlan.
- auth: JWT verifier, role hierarchy, FastAPI dependency factory (Phase A6).

See docs/adr/0005-failsafe-controller-state-machine.md and
    docs/adr/0006-rbac-jwt-roles.md.
"""

__version__ = "0.2.0"
