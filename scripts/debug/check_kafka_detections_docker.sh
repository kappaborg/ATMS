#!/bin/bash
# Check Kafka Detection Messages using Docker

echo "🔍 Checking Kafka Detection Messages"
echo "===================================="
echo ""

# Get the latest message from detections topic
echo "📥 Fetching latest message from 'detections' topic..."
echo ""

docker exec -it atms-kafka-1 kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic detections \
  --from-beginning \
  --max-messages 1 \
  --property print.key=true \
  --property print.value=true \
  2>/dev/null | head -200

echo ""
echo "===================================="
echo "✅ Check complete"
echo ""
echo "If you see JSON output above, messages are in Kafka."
echo "If empty, AI Perception may not be sending detections."

