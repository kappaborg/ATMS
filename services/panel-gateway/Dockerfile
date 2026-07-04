# ATMS Panel Gateway — headless deployment image.
# Build from the REPO ROOT (the gateway reuses the tracker, decision engine
# and models that live outside its own directory):
#
#   docker build -f services/panel-gateway/Dockerfile -t atms-panel-gateway .
#   docker run -p 8090:8090 -v atms-data:/data atms-panel-gateway
#
# The container binds 0.0.0.0 — SET PANEL_USERS (RBAC) or PANEL_API_TOKEN in
# any deployment that is reachable from the network.

FROM python:3.12-slim

# ffmpeg: robust HLS/RTSP demuxing for live streams (OpenCV's bundled build
# covers most cases; the system one is the fallback yt-dlp can also use).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency layer (cached until requirements.txt changes).
COPY services/panel-gateway/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# The gateway plus exactly the shared pieces it imports.
COPY services/panel-gateway/src/ services/panel-gateway/src/
COPY services/ai-perception/src/tracking/ services/ai-perception/src/tracking/
COPY ai_decision_system.py ai_decision_system.py
COPY ai/ ai/
# Detection weights: baked in so the container works offline.
COPY yolov8n.pt yolov8n.pt
# Plate-detector weights (only used when PANEL_READ_PLATES=1).
COPY models/license_plate_training/outputs/license_plate_model/weights/best.pt \
     models/license_plate_training/outputs/license_plate_model/weights/best.pt

# Durable state lives in /data (mount a volume).
ENV PANEL_HOST=0.0.0.0 \
    PANEL_PORT=8090 \
    PANEL_STATE_FILE=/data/panel_state.json \
    PANEL_HISTORY_DB=/data/panel_history.db \
    PANEL_VIOLATIONS_DB=/data/panel_violations.db \
    PANEL_VIOLATIONS_DIR=/data/violation_snaps \
    PANEL_VIOLATION_RETENTION_DAYS=30 \
    ATMS_ALLOWED_VIDEO_DIRS=/videos
RUN useradd -m atms && mkdir -p /data /videos && chown -R atms /data /videos /app
USER atms
VOLUME ["/data"]
EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8090/health',timeout=4)"

CMD ["python", "-m", "uvicorn", "main:app", \
     "--host", "0.0.0.0", "--port", "8090", \
     "--app-dir", "services/panel-gateway/src"]
