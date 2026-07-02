#!/bin/bash
# Check Kafka Messages in detections topic

echo "🔍 Checking Kafka Detection Messages"
echo "===================================="
echo ""

# Check if Kafka container is running
if ! docker ps | grep -q atms-kafka; then
    echo "❌ Kafka container not running"
    exit 1
fi

echo "📊 Topic Statistics:"
docker exec atms-kafka kafka-run-class kafka.tools.GetOffsetShell \
  --broker-list localhost:9092 \
  --topic detections 2>/dev/null | head -5

echo ""
echo "📥 Latest Message from 'detections' topic:"
echo "-------------------------------------------"

# Get the latest message
docker exec atms-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic detections \
  --from-beginning \
  --max-messages 1 \
  --property print.key=true \
  --property print.value=true \
  2>/dev/null | head -100

echo ""
echo "===================================="
echo "✅ Check complete"

