# 🐳 Docker Infrastructure

This directory contains all Docker Compose configurations for the Traffic Management System.

## 📁 Structure

```
docker/
├── docker-compose.kafka.yml      # Kafka infrastructure (Zookeeper, Kafka, Kafka UI)
├── docker-compose.database.yml    # Database stack (PostgreSQL, Redis, PgAdmin)
└── monitoring/                    # Monitoring stack (Prometheus, Grafana)
    ├── docker-compose.yml
    ├── README.md
    ├── prometheus/
    └── grafana/
```

## 🚀 Quick Start

### Start All Infrastructure
```bash
# Kafka
docker-compose -f docker-compose.kafka.yml up -d

# Database
docker-compose -f docker-compose.database.yml up -d

# Monitoring
cd monitoring && docker-compose up -d
```

### Stop All Infrastructure
```bash
# Monitoring
cd monitoring && docker-compose down

# Database
docker-compose -f docker-compose.database.yml down

# Kafka
docker-compose -f docker-compose.kafka.yml down
```

## 📊 Service Groups

Services are automatically grouped in Docker Desktop:
- **"traffic"**: Kafka, Database services
- **"monitoring"**: Prometheus, Grafana

## 📝 Notes

- Each stack is independent and can be managed separately
- All stacks use the `atms-network` network for communication
- Ports are exposed to localhost for easy access
