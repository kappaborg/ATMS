"""
Pytest path setup for the traffic-controller service.

The service directory uses a hyphen (`traffic-controller`) which is not a
valid Python module name. We prepend the repo root and the service's `src/`
to sys.path so tests can do:

    from shared.atms_common.decision import DecisionMessage
    from failsafe import FailsafeController
"""
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
_SRC = _HERE / "src"

for p in (str(_REPO_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Auth env vars required by the JWTVerifier at import-time. These are
# test-only values; production secrets come from SOPS (ADR-0002).
os.environ.setdefault("AUTH_HS256_SECRET", "pytest-secret-do-not-use-in-prod")
os.environ.setdefault("AUTH_ISSUER", "atms-test")
os.environ.setdefault("AUTH_AUDIENCE", "atms-traffic-controller")
os.environ.setdefault("AUTH_CLOCK_SKEW_S", "5")
