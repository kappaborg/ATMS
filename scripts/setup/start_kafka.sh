#!/bin/bash

cat << 'EOF'

╔══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║     🚀 STARTING KAFKA INFRASTRUCTURE                                 ║
║                                                                       ║
╚══════════════════════════════════════════════════════════════════════╝

📦 Starting Services:
  • Zookeeper (coordination service)
  • Apache Kafka (message queue)
  • Kafka UI (web interface on port 8080)

⏱️  This may take 30-60 seconds for first-time setup...

EOF

cd "$(dirname "$0")"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running!"
    echo ""
    echo "Please start Docker Desktop and try again."
    echo ""
    exit 1
fi

# Stop any existing containers
echo "🧹 Cleaning up old containers..."
docker-compose -f docker-compose.kafka.yml down 2>/dev/null

# Start Kafka infrastructure
echo ""
echo "🚀 Starting Kafka infrastructure..."
echo ""

docker-compose -f docker-compose.kafka.yml up -d

echo ""
echo "⏳ Waiting for services to be ready..."
echo ""

# Wait for Kafka to be healthy
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if docker exec atms-kafka kafka-broker-api-versions --bootstrap-server localhost:9092 > /dev/null 2>&1; then
        echo "✅ Kafka is ready!"
        break
    fi
    
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "   Waiting for Kafka... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "❌ Kafka failed to start in time"
    echo ""
    echo "Check logs with: docker-compose -f docker-compose.kafka.yml logs"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ KAFKA INFRASTRUCTURE READY!"
echo ""
echo "📊 Services Running:"
echo "   • Zookeeper:  localhost:2181"
echo "   • Kafka:      localhost:9092"
echo "   • Kafka UI:   http://localhost:8080"
echo ""
echo "🎯 Topics (auto-created on first use):"
echo "   • camera-frames    (Sensor Fusion → AI Perception)"
echo "   • detections       (AI Perception → Analytics)"
echo "   • traffic-metrics  (System metrics)"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🌐 Kafka UI: http://localhost:8080"
echo "   View messages, topics, and consumers in real-time!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 NEXT STEPS:"
echo ""
echo "1. Restart Sensor Fusion service"
echo "2. Restart AI Perception service"
echo "3. Watch live object detection from iPhone camera!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "💡 To stop Kafka:"
echo "   docker-compose -f docker-compose.kafka.yml down"
echo ""
echo "💡 To view Kafka logs:"
echo "   docker-compose -f docker-compose.kafka.yml logs -f kafka"
echo ""


