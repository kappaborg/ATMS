"""
Domain exception hierarchy — Phase B1.

See docs/adr/0008-shared-atms-common-library.md.

Rule (cross-cutting, from the senior engineer prompt): no bare
`except Exception:` outside top-level boundaries. Catch the specific
subclass, or let it propagate. The top-level boundaries that legitimately
catch `AtmsError` (or `Exception` of last resort) are:

- FastAPI exception handlers (translate to HTTP)
- Kafka consumer loops (per-message try/except wrapped around the user callback)
- The asyncio task supervisor in main.py (log + restart)

This module is the **base** of the shared library's exception graph and must
NOT import from auth / db / kafka / etc. — those modules depend on this one,
so the dependency cannot run in the other direction without creating a cycle
that forces every consumer of `errors` to also install the auth stack
(pyjwt, fastapi). `AuthError` lives in `shared.atms_common.auth`; import it
from there directly when you need it.
"""

from __future__ import annotations

__all__ = [
    "AtmsError",
    "ConfigError",
    "ControllerError",
    "KafkaError",
    "SafetyViolation",
    "SchemaError",
]


class AtmsError(Exception):
    """Base class for every domain exception raised by ATMS code."""


class ConfigError(AtmsError):
    """Raised at startup when required configuration is missing or invalid."""


class SchemaError(AtmsError):
    """Raised when an inbound message fails schema validation.

    The DecisionMessage / PreemptRequest / PedCallRequest validators use the
    enumerated `ValidationStatus` types instead of raising — but when a code
    path needs to fail-fast on a bad payload (rare), this is the type to use.
    """


class KafkaError(AtmsError):
    """Raised by AtmsKafkaProducer / AtmsKafkaConsumer on irrecoverable failure.

    Recoverable failures (transient broker outage, leader election) are
    handled internally by the producer/consumer with retry; only after the
    retry budget is exhausted does the failure surface as KafkaError.
    """


class ControllerError(AtmsError):
    """Raised by the failsafe controller for unexpected internal state."""


class SafetyViolation(ControllerError):
    """
    Raised when an attempted state transition would violate a hard safety
    invariant (e.g., two conflicting greens). The failsafe controller's
    safety filter normally PREVENTS such transitions; this exception type
    exists so that the rare "should never happen" path is loud rather than
    silent if it ever does.
    """
