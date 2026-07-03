# Root-context multi-stage build.
# Build from the PROJECT ROOT so `shared/` is in the context:
#   docker build -f services/decision-engine/Dockerfile .
# (CI uses context: . — see .github/workflows/ci.yml)
FROM python:3.14-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# This service's Python requirements. `shared/` is NOT pip-installed
# (its setup.py references untracked subpackages); it is provided at
# runtime via `COPY shared /app/shared` + PYTHONPATH below.
COPY services/decision-engine/requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir --user -r /tmp/requirements.txt
# shared.atms_common runtime deps (declared in shared/setup.py) — install
# explicitly since shared itself is not pip-installed. --ignore-installed so
# `packaging` (satisfied globally by the pip upgrade) lands in --user site.
RUN pip install --no-cache-dir --user --ignore-installed \
    packaging structlog python-json-logger
# Force `packaging` into --user site (the global pip upgrade above
# satisfies it globally, so it would otherwise miss /root/.local).
RUN pip install --no-cache-dir --user --ignore-installed packaging

# Final stage
FROM python:3.14-slim

WORKDIR /app

COPY --from=builder /root/.local /root/.local

# Shared package + application code. config/ and models/ are not tracked
# in git (empty dirs), so they are NOT copied — mount them at deploy time
# if a service needs runtime config.
COPY shared /app/shared
COPY services/decision-engine/src/ ./src/
# Repo-root modules this service imports directly.
COPY ai_decision_system.py ./ai_decision_system.py

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app:/app/shared

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8007/health')" || exit 1

EXPOSE 8007

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8007"]
