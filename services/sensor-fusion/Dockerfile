# Multi-stage build for optimization
# NOTE: Build from project root: docker build -f services/sensor-fusion/Dockerfile .
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies (including pkg-config for PyAV)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    pkg-config \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy shared package (when building from project root)
COPY shared /tmp/shared

# Copy requirements and install dependencies
COPY services/sensor-fusion/requirements.txt /tmp/requirements.txt
# Create a temporary requirements file without the shared package line
RUN grep -v "^-e \.\.\/\.\.\/shared" /tmp/requirements.txt > /tmp/requirements_clean.txt || \
    sed '/^-e \.\.\/\.\.\/shared/d' /tmp/requirements.txt > /tmp/requirements_clean.txt || \
    cat /tmp/requirements.txt > /tmp/requirements_clean.txt
# Upgrade pip and install setuptools first
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
# Install shared package from local copy
RUN if [ -f /tmp/shared/setup.py ]; then pip install --no-cache-dir --user /tmp/shared; fi
# Install other requirements
RUN pip install --no-cache-dir --user -r /tmp/requirements_clean.txt

# Final stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies for video processing
# Note: libgl1-mesa-glx is replaced by libgl1 in newer Debian versions
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY services/sensor-fusion/src/ ./src/
COPY services/sensor-fusion/config/ ./config/

# Set environment variables
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8008/health')" || exit 1

# Expose port
EXPOSE 8008

# Run application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8008"]
