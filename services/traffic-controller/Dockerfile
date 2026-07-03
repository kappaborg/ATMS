# Root-context multi-stage build.
# Build from the PROJECT ROOT so `shared/` is in the context:
#   docker build -f services/traffic-controller/Dockerfile .
# (CI uses context: . — see .github/workflows/ci.yml)
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Shared library (has setup.py) + this service's requirements.
COPY shared /tmp/shared
COPY services/traffic-controller/requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN if [ -f /tmp/shared/setup.py ]; then pip install --no-cache-dir --user /tmp/shared; fi
RUN pip install --no-cache-dir --user -r /tmp/requirements.txt
# Force `packaging` into --user site (the global pip upgrade above
# satisfies it globally, so it would otherwise miss /root/.local).
RUN pip install --no-cache-dir --user --ignore-installed packaging

# Final stage
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /root/.local /root/.local

# Shared package + application code. config/ and models/ are not tracked
# in git (empty dirs), so they are NOT copied — mount them at deploy time
# if a service needs runtime config.
COPY shared /app/shared
COPY services/traffic-controller/src/ ./src/

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app:/app/shared

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/health')" || exit 1

EXPOSE 8010

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8010"]
