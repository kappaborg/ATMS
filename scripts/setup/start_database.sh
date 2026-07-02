#!/bin/bash

# Start Database Infrastructure
# =============================
# Starts PostgreSQL and Redis using Docker

echo "🗄️  Starting Database Infrastructure..."
echo "=" * 60

# Check if Docker is running
if ! docker ps > /dev/null 2>&1; then
    echo "❌ Docker is not running. Starting Docker..."
    open -a Docker
    echo "⏳ Waiting for Docker to start..."
    sleep 15
fi

# Create network if it doesn't exist
if ! docker network ls | grep -q atms-network; then
    echo "📡 Creating atms-network..."
    docker network create atms-network
else
    echo "✅ atms-network already exists"
fi

# Start database services
echo ""
echo "🚀 Starting PostgreSQL and Redis..."
echo "----------------------------------------"
docker-compose -f docker-compose.database.yml up -d

# Wait for services to be healthy
echo ""
echo "⏳ Waiting for services to be ready..."
sleep 5

# Check PostgreSQL
echo ""
echo "🔍 Checking PostgreSQL..."
docker exec atms-postgres pg_isready -U atms_user -d atms
if [ $? -eq 0 ]; then
    echo "✅ PostgreSQL is ready"
else
    echo "❌ PostgreSQL is not ready yet, waiting longer..."
    sleep 10
    docker exec atms-postgres pg_isready -U atms_user -d atms
fi

# Check Redis
echo ""
echo "🔍 Checking Redis..."
docker exec atms-redis redis-cli -a atms_redis_password ping
if [ $? -eq 0 ]; then
    echo "✅ Redis is ready"
else
    echo "❌ Redis is not ready"
fi

echo ""
echo "=" * 60
echo "✅ Database infrastructure started!"
echo "=" * 60
echo ""
echo "📊 Service URLs:"
echo "  - PostgreSQL:  localhost:5432"
echo "  - Redis:       localhost:6379"
echo "  - pgAdmin:     http://localhost:5050"
echo ""
echo "📋 Connection Details:"
echo "  PostgreSQL:"
echo "    Database: atms"
echo "    User:     atms_user"
echo "    Password: atms_password"
echo ""
echo "  Redis:"
echo "    Password: atms_redis_password"
echo ""
echo "  pgAdmin:"
echo "    Email:    admin@atms.local"
echo "    Password: admin"
echo ""
echo "💡 To stop database services:"
echo "   docker-compose -f docker-compose.database.yml down"
echo ""
echo "🧪 To test database connection:"
echo "   python database/database.py"
echo "   python database/redis_cache.py"
echo ""
