#!/usr/bin/env bash
# scripts/download_test_video.sh
#
# Download a YouTube (or any yt-dlp-supported) video and optionally trim it
# to a short clip for ATMS perception testing. Output goes to videos/.
#
# Usage:
#   ./scripts/download_test_video.sh <URL>
#   ./scripts/download_test_video.sh <URL> 60        # trim to first 60s
#   ./scripts/download_test_video.sh <URL> 30 120    # trim 30s..120s (90s clip)
#
# Picks the best mp4 ≤1080p available (full 4K is overkill for YOLOv8n which
# downsamples to 640 internally anyway, and the smaller file iterates faster).
#
# Suggested search terms (paste any matching URL):
#   "4K traffic intersection real time"
#   "highway driving 4K daytime"
#   "city traffic 4K fixed camera"
#   "drone intersection 4K"
# Channels with reliably-good fixed-camera traffic footage:
#   - "Real Time Traffic Footage" (search YouTube)
#   - "BAR-RAYTHEON" (channel uploads long fixed-cam clips)
# For copyright-clean stock footage instead:
#   - https://www.pexels.com/search/videos/traffic/
#   - https://pixabay.com/videos/search/traffic/

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <URL> [start_sec_or_duration] [end_sec]"
    echo "Examples:"
    echo "  $0 'https://www.youtube.com/watch?v=...'              # full video"
    echo "  $0 'https://www.youtube.com/watch?v=...' 60           # first 60s"
    echo "  $0 'https://www.youtube.com/watch?v=...' 30 120       # 30s..120s"
    exit 2
fi

URL="$1"
ARG1="${2:-}"
ARG2="${3:-}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$REPO_ROOT/videos"
mkdir -p "$OUT_DIR"

# Get a friendly slug for the filename.
SLUG="$(python3 -m yt_dlp --get-id "$URL" 2>/dev/null || echo "$(date +%s)")"
FULL_PATH="$OUT_DIR/youtube_${SLUG}_full.mp4"

echo "─── Downloading (best mp4 ≤1080p) ───"
python3 -m yt_dlp \
    -f "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/best[height<=1080]" \
    --merge-output-format mp4 \
    -o "$FULL_PATH" \
    --no-playlist \
    "$URL"

if [[ ! -f "$FULL_PATH" ]]; then
    # yt-dlp sometimes adjusts the extension; find what it actually wrote.
    FULL_PATH="$(ls -t "$OUT_DIR"/youtube_${SLUG}_full.* 2>/dev/null | head -1)"
fi

if [[ -z "$ARG1" ]]; then
    echo
    echo "✓ saved: $FULL_PATH"
    echo "  run: python3 -m simulation.demo --video '$FULL_PATH' --brand-model clip"
    exit 0
fi

# Trim. If only one numeric arg, treat it as duration from start.
TRIMMED_PATH="$OUT_DIR/youtube_${SLUG}.mp4"
if [[ -z "$ARG2" ]]; then
    START=0
    DURATION="$ARG1"
else
    START="$ARG1"
    DURATION=$((ARG2 - ARG1))
fi

echo
echo "─── Trimming: start=${START}s duration=${DURATION}s ───"
ffmpeg -y -ss "$START" -i "$FULL_PATH" -t "$DURATION" \
    -c:v libx264 -preset fast -crf 23 -c:a aac \
    -movflags +faststart \
    "$TRIMMED_PATH" 2>&1 | tail -3

echo
echo "✓ saved: $TRIMMED_PATH"
echo "  full: $FULL_PATH ($(du -h "$FULL_PATH" | cut -f1))"
echo "  trim: $TRIMMED_PATH ($(du -h "$TRIMMED_PATH" | cut -f1))"
echo
echo "Run the demo:"
echo "  python3 -m simulation.demo --video '$TRIMMED_PATH' --brand-model clip"
echo "  python3 -m simulation.demo --video '$TRIMMED_PATH' --show     # OpenCV overlay"
