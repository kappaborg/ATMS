"""
Legacy `security/` package.

The deprecated A6 modules `jwt_handler.py` and `middleware.py` have been
removed (per ADR-0006 follow-up). Authn/RBAC lives in
`shared/atms_common/auth.py`.

This package now hosts only the legacy helpers awaiting migration:

- rate_limiter — still imported by `services/api-gateway/src/main.py`;
  will fold into `shared/atms_common/` (rate-limit follow-up of Phase B4).
- secrets_manager — superseded by SOPS + age (Phase A5); kept as a
  reference for the operator on-prem secret-rotation flow.
- tls_config — superseded by Linkerd-managed mTLS (Phase B5); kept as a
  reference for the pre-mesh transport-security parameters.

Do not import from this package in new code — use the shared library.
"""
