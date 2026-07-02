#!/bin/bash
# Extract a test frame from video for testing

VIDEO_PATH="${1:-videos/LPDT.mp4}"
OUTPUT_PATH="${2:-test_frame.jpg}"
TIMESTAMP="${3:-00:00:05}"

if [ ! -f "$VIDEO_PATH" ]; then
    echo "❌ Video not found: $VIDEO_PATH"
    echo ""
    echo "Usage:"
    echo "  ./extract_test_frame.sh [video_path] [output_path] [timestamp]"
    echo ""
    echo "Examples:"
    echo "  ./extract_test_frame.sh videos/LPDT.mp4 test_frame.jpg 00:00:05"
    echo "  ./extract_test_frame.sh videos/T1.mp4 test_frame.jpg 00:00:02"
    exit 1
fi

echo "📹 Extracting frame from: $VIDEO_PATH"
echo "⏰ Timestamp: $TIMESTAMP"
echo "💾 Output: $OUTPUT_PATH"

ffmpeg -i "$VIDEO_PATH" -ss "$TIMESTAMP" -vframes 1 "$OUTPUT_PATH" -y 2>&1 | grep -E "(frame|Output|error)" || true

if [ -f "$OUTPUT_PATH" ]; then
    echo "✅ Frame extracted successfully: $OUTPUT_PATH"
    file "$OUTPUT_PATH"
else
    echo "❌ Failed to extract frame"
    exit 1
fi

