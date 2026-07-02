# Multi-stage build for optimization
# NOTE: Build from project root: docker build -f services/ai-perception/Dockerfile .
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Copy shared package (when building from project root)
COPY shared /tmp/shared

# Copy requirements and install dependencies
COPY services/ai-perception/requirements.txt /tmp/requirements.txt
# Install setuptools first (required for some packages)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
# Install shared package from local copy
RUN if [ -f /tmp/shared/setup.py ]; then pip install --no-cache-dir --user /tmp/shared; fi
# Install other requirements
RUN pip install --no-cache-dir --user -r /tmp/requirements.txt

# Final stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies
# Note: libgl1 is replaced by libgl1 in newer Debian versions
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgthread-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local

# Copy shared package (needed at runtime)
COPY shared /app/shared

# Copy application code
COPY services/ai-perception/src/ ./src/
COPY services/ai-perception/models/ ./models/
COPY services/ai-perception/config/ ./config/

# Make sure scripts are executable
RUN chmod +x src/main.py

# Set environment variables
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Add shared to Python path (use default if PYTHONPATH not set)
ENV PYTHONPATH=/app:/app/shared

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8004/health')" || exit 1

# Expose port
EXPOSE 8004

# Run application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8004"]

