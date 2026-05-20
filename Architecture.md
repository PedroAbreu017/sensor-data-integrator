# Sensor Platform — Complete Architecture

## Overview

A production-grade, cloud-ready microservices platform for industrial sensor data ingestion, validation, storage, quality analysis, and alerting.

---

## Repositories

| Repository | Language | Status | Description |
|------------|----------|--------|-------------|
| `sensor-data-integrator` | Python/FastAPI | ✅ Done | Multi-tenant ingestion and validation |
| `sensor-warehouse-api` | Java/Spring Boot | 🔄 In Progress | Sensor readings storage and query |
| `sensor-quality-service` | Python/FastAPI | 📋 Planned | Data quality reports and analysis |
| `sensor-notification-service` | Python/FastAPI | 📋 Planned | Email and alert notifications |
| `sensor-api-gateway` | Java/Spring Boot | 📋 Planned | Single entry point, auth, routing |

---

## Architecture Diagram

```
                        ┌─────────────────────────────┐
                        │       React Frontend          │
                        │      (localhost:5173)         │
                        └──────────────┬──────────────┘
                                       │ HTTP
                        ┌──────────────▼──────────────┐
                        │       API Gateway             │
                        │   Java/Spring Boot :8080      │  ← Planned
                        │  Auth, Rate Limit, Routing    │
                        └──────┬───────────┬───────────┘
                               │           │
               ┌───────────────▼──┐   ┌────▼──────────────────┐
               │ Integrator API    │   │   Warehouse API         │
               │ Python/FastAPI    │   │   Java/Spring Boot      │
               │ :8000             │──▶│   :8096                 │
               │                   │   │                         │
               │ - Multi-tenant    │   │ - REST endpoints        │
               │ - File parsing    │   │ - TimescaleDB queries   │
               │ - Validation      │   │ - Pagination            │
               │ - MAD spike       │   │ - Filtering by tenant   │
               │ - Frozen sensor   │   └──────────┬─────────────┘
               └────────┬──────────┘              │
                        │                          │
                        │ Publish                  │ Read/Write
                        ▼                          ▼
               ┌─────────────────┐    ┌────────────────────────┐
               │    RabbitMQ      │    │  PostgreSQL/TimescaleDB │
               │  :5672 / :15672  │    │  :5432                  │
               │                  │    │                          │
               │ Queues:          │    │ Tables:                  │
               │ - upload.orion   │    │ - industry               │
               │ - upload.nexus   │    │ - asset                  │
               │ - upload.atlas   │    │ - equipment              │
               │ - quality.events │    │ - tag                    │
               │ - notifications  │    │ - sensor_readings        │
               └────┬─────────────┘    └──────────────────────────┘
                    │
         ┌──────────┴──────────┐
         │                     │
┌────────▼──────────┐ ┌────────▼──────────┐
│  Quality Service   │ │ Notification Svc   │
│  Python/FastAPI    │ │ Python/FastAPI     │
│  :8097             │ │ :8098              │  ← Planned
│                    │ │                    │
│ - Quality reports  │ │ - Email alerts     │
│ - Spike summary    │ │ - Spike detected   │
│ - Frozen summary   │ │ - Frozen sensor    │
│ - Tenant dashboard │ │ - SMTP/SendGrid    │
└────────────────────┘ └────────────────────┘
```

---

## Services Detail

### 1. Sensor Data Integrator ✅
**Repo:** `sensor-data-integrator`
**Stack:** Python 3.12, FastAPI, Pandas, aio-pika

Responsibilities:
- Receive CSV, TXT, XLSX files via REST upload
- Parse and normalize data per tenant (ORION, NEXUS, ATLAS)
- Validate data statistically (MAD, frozen sensor, duplicates)
- Publish jobs to RabbitMQ queues
- Workers consume queues and forward to Warehouse API

Key endpoints:
```
POST /upload          — upload sensor file
GET  /jobs/{job_id}   — get job status
GET  /jobs            — list all jobs
GET  /health          — health check
```

---

### 2. Sensor Warehouse API 🔄
**Repo:** `sensor-warehouse-api`
**Stack:** Java 21, Spring Boot 3, Spring Data JPA, TimescaleDB

Responsibilities:
- Receive processed CSV from Integrator
- Insert sensor readings into TimescaleDB hypertable
- Expose query endpoints for dashboards
- Multi-tenant routing via `X-Tenant` header

Key endpoints:
```
POST /v1/warehouse/integrator/ingest   — ingest CSV data
GET  /v1/warehouse/readings            — query readings
GET  /v1/warehouse/readings/{tag_id}   — readings by tag
GET  /v1/warehouse/assets              — list assets
GET  /health                           — health check
```

---

### 3. Data Quality Service 📋
**Repo:** `sensor-quality-service`
**Stack:** Python 3.12, FastAPI, Pandas, aio-pika

Responsibilities:
- Consume `quality.events` queue from RabbitMQ
- Generate quality reports per tenant and equipment
- Track spike and frozen sensor occurrences over time
- Expose REST endpoints for quality dashboards

Key endpoints:
```
GET  /quality/report/{tenant}          — quality report by tenant
GET  /quality/summary                  — global summary
GET  /quality/equipment/{equipment_id} — quality by equipment
GET  /health                           — health check
```

---

### 4. Notification Service 📋
**Repo:** `sensor-notification-service`
**Stack:** Python 3.12, FastAPI, aio-pika, SMTP/SendGrid

Responsibilities:
- Consume `notifications` queue from RabbitMQ
- Send email alerts when spike or frozen sensor detected
- Configurable thresholds per tenant
- Alert history and acknowledgment

Key endpoints:
```
POST /notifications/config             — configure alert rules
GET  /notifications/history            — alert history
GET  /health                           — health check
```

---

### 5. API Gateway 📋
**Repo:** `sensor-api-gateway`
**Stack:** Java 21, Spring Boot 3, Spring Cloud Gateway

Responsibilities:
- Single entry point for all services
- JWT authentication and authorization
- Rate limiting per tenant
- Route requests to correct microservice
- Request/response logging

Routes:
```
/api/integrator/**  → sensor-data-integrator:8000
/api/warehouse/**   → sensor-warehouse-api:8096
/api/quality/**     → sensor-quality-service:8097
/api/notify/**      → sensor-notification-service:8098
```

---

## Data Flow

### Upload Flow
```
1. User uploads file via Frontend
2. Integrator API validates file format and size
3. Integrator publishes job to RabbitMQ (upload.{tenant})
4. Worker consumes queue
5. Worker parses and validates data (MAD, frozen, duplicates)
6. Worker publishes quality event to RabbitMQ (quality.events)
7. Worker forwards clean data to Warehouse API
8. Warehouse API inserts into TimescaleDB
9. Quality Service consumes quality event and updates report
10. If anomaly detected → publishes to notifications queue
11. Notification Service sends email alert
```

### Query Flow
```
1. Frontend requests data via API Gateway
2. Gateway authenticates JWT token
3. Gateway routes to Warehouse API
4. Warehouse API queries TimescaleDB
5. Returns paginated sensor readings
```

---

## Infrastructure

### Docker Compose Services
| Service | Image | Port |
|---------|-------|------|
| db | timescale/timescaledb:latest-pg15 | 5432 |
| rabbitmq | rabbitmq:3.13-management | 5672, 15672 |
| api | sensor-data-integrator | 8000 |
| warehouse | sensor-warehouse-api | 8096 |
| quality | sensor-quality-service | 8097 |
| notification | sensor-notification-service | 8098 |

### RabbitMQ Queues
| Queue | Producer | Consumer |
|-------|----------|----------|
| sensor.upload.orion | Integrator API | Worker |
| sensor.upload.nexus | Integrator API | Worker |
| sensor.upload.atlas | Integrator API | Worker |
| sensor.quality.events | Worker | Quality Service |
| sensor.notifications | Quality Service | Notification Service |

---

## Technology Summary

| Technology | Usage |
|------------|-------|
| Python 3.12 | Integrator, Quality, Notification services |
| Java 21 | Warehouse API, API Gateway |
| FastAPI | REST APIs (Python) |
| Spring Boot 3 | REST APIs (Java) |
| PostgreSQL 15 + TimescaleDB | Time-series sensor data |
| RabbitMQ 3.13 | Async message broker |
| React + Vite | Frontend dashboard |
| Docker + Docker Compose | Containerization |
| Pytest | Unit and integration tests |
| JUnit 5 | Java tests |

---

## Build Order

1. ✅ `sensor-data-integrator` — Python ingestion pipeline
2. 🔄 `sensor-warehouse-api` — Java storage layer
3. 📋 `sensor-quality-service` — Python quality analysis
4. 📋 `sensor-notification-service` — Python alerting
5. 📋 `sensor-api-gateway` — Java gateway

---

## Getting Started (Full Platform)

```bash
# 1. Start infrastructure
docker-compose up db rabbitmq -d

# 2. Start Warehouse API (Java)
cd sensor-warehouse-api
./mvnw spring-boot:run

# 3. Start Integrator API (Python)
cd sensor-data-integrator
make api

# 4. Start Quality Service (Python)
cd sensor-quality-service
make api

# 5. Start Frontend
cd sensor-data-integrator
make frontend
```

---

## Technical Debt & Improvements

### sensor-data-integrator
- [ ] Expand unit tests — edge cases for validator (empty tags, mixed quality)
- [ ] Integration tests — full upload flow with mock Warehouse API (httpx)
- [ ] Load tests — multiple concurrent uploads
- [ ] Mock RabbitMQ in tests — avoid needing broker running
- [ ] Test coverage report — pytest-cov

### sensor-warehouse-api
- [ ] JUnit 5 unit tests
- [ ] Integration tests with TestContainers

### General
- [ ] CI/CD pipeline — GitHub Actions
- [ ] Docker Compose production profile
- [ ] Environment-based configuration per service