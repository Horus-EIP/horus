# Architecture Fiche - Horus Multi-Agent System

**Document Type:** Technical Architecture Overview  
**Version:** 1.0  
**Last Updated:** January 2026  
**Classification:** Internal

---

## 1. System Overview

### 1.1 Purpose

Horus is an AI-powered Multi-Agent System (MAS) designed to orchestrate intelligent agents for enterprise task automation. The system provides:

- **Intelligent Task Routing:** LLM-based agent selection and task distribution
- **RAG-Powered Responses:** Context-aware answers using document retrieval
- **Real-Time Communication:** WebSocket-based chat interface
- **Enterprise Security:** RBAC, JWT authentication, audit logging

### 1.2 Architecture Style

- **Microservices Architecture:** Loosely coupled services with well-defined APIs
- **Event-Driven:** RabbitMQ message broker for async task processing
- **Containerized:** Docker-based deployment with orchestration support

---

## 2. System Components

### 2.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           EXTERNAL LAYER                                 │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │  Web Client  │    │  API Client  │    │ Admin Tools  │              │
│  │  (Next.js)   │    │   (REST)     │    │              │              │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘              │
│         │                   │                   │                       │
│         └───────────────────┼───────────────────┘                       │
│                             │ HTTPS/WSS                                 │
└─────────────────────────────┼───────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         APPLICATION LAYER                                │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    MAS (Multi-Agent System)                        │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐  │  │
│  │  │    Auth     │ │   Agents    │ │    Tasks    │ │    Chat     │  │  │
│  │  │   Module    │ │   Module    │ │   Module    │ │   Module    │  │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘  │  │
│  │  ┌─────────────────────────────────────────────────────────────┐  │  │
│  │  │              Core Services                                   │  │  │
│  │  │  Logging | Metrics | Tracing | RBAC | RabbitMQ Manager      │  │  │
│  │  └─────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                           │
│         ┌────────────────────┼────────────────────┐                     │
│         ▼                    ▼                    ▼                     │
│  ┌─────────────┐     ┌─────────────┐      ┌─────────────┐              │
│  │   Agent     │     │  Knowledge  │      │  RabbitMQ   │              │
│  │  Service    │     │   Store     │      │  (Broker)   │              │
│  │             │     │             │      │             │              │
│  │ ┌─────────┐ │     │ ┌─────────┐ │      │             │              │
│  │ │RAG Pipe │ │     │ │ChromaDB │ │      │             │              │
│  │ │ line    │ │     │ │(Vector) │ │      │             │              │
│  │ └─────────┘ │     │ └─────────┘ │      │             │              │
│  └─────────────┘     └─────────────┘      └─────────────┘              │
└─────────────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────┼───────────────────────────────────────────┐
│                         DATA LAYER                                       │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐     ┌─────────────┐      ┌─────────────┐              │
│  │ PostgreSQL  │     │   Redis     │      │ File Store  │              │
│  │  (Primary   │     │  (Cache/    │      │ (Documents) │              │
│  │  Database)  │     │  Sessions)  │      │             │              │
│  └─────────────┘     └─────────────┘      └─────────────┘              │
└─────────────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────┼───────────────────────────────────────────┐
│                     OBSERVABILITY LAYER                                  │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐     ┌─────────────┐      ┌─────────────┐              │
│  │ Prometheus  │     │   Grafana   │      │   Jaeger    │              │
│  │  (Metrics)  │     │ (Dashboards)│      │  (Tracing)  │              │
│  └─────────────┘     └─────────────┘      └─────────────┘              │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Component Descriptions

| Component | Purpose | Technology |
|-----------|---------|------------|
| **MAS** | API Gateway, Orchestration, RBAC | FastAPI, Python 3.11 |
| **Agent** | AI Processing, RAG Pipeline | FastAPI, Transformers |
| **Knowledge Store** | Document Storage, Vector Search | FastAPI, ChromaDB |
| **Web Client** | User Interface | Next.js, React 18 |
| **PostgreSQL** | Relational Data | PostgreSQL 15+ |
| **Redis** | Caching, Sessions | Redis 7+ |
| **RabbitMQ** | Message Broker | RabbitMQ 3.12+ |
| **Prometheus** | Metrics Collection | Prometheus 2.x |
| **Grafana** | Dashboards | Grafana 10.x |
| **Jaeger** | Distributed Tracing | Jaeger 1.x |

---

## 3. Data Flows

### 3.1 User Query Flow

```
1. User → Web Client: Submit query
2. Web Client → MAS: POST /tasks/new_task/ (REST)
3. MAS → RabbitMQ: Publish task message
4. Agent ← RabbitMQ: Consume task
5. Agent → Knowledge Store: Query documents (REST)
6. Knowledge Store → Agent: Return relevant docs
7. Agent: Process with LLM (RAG)
8. Agent → RabbitMQ: Publish result
9. MAS ← RabbitMQ: Consume result
10. MAS → WebSocket: Push to client
11. Web Client ← WebSocket: Receive response
```

### 3.2 Agent Registration Flow

```
1. Agent → MAS: POST /agents/register (REST)
2. MAS: Validate credentials, create record
3. MAS → Agent: Registration confirmation
4. Agent → MAS: POST /agents/heartbeat (every 30s)
5. MAS: Update last_heartbeat timestamp
```

### 3.3 Authentication Flow

```
1. Client → MAS: POST /auth/token (username, password)
2. MAS: Validate credentials
3. MAS → Client: JWT token
4. Client → MAS: Subsequent requests with Authorization header
5. MAS: Validate JWT, check permissions
```

---

## 4. Technology Stack

### 4.1 Backend Services

| Service | Language | Framework | Key Libraries |
|---------|----------|-----------|---------------|
| MAS | Python 3.11 | FastAPI | SQLAlchemy, Pydantic, Pika |
| Agent | Python 3.11 | FastAPI | Transformers, Torch, HTTPX |
| Knowledge Store | Python 3.11 | FastAPI | ChromaDB, Sentence-Transformers |

### 4.2 Frontend

| Component | Framework | Key Libraries |
|-----------|-----------|---------------|
| Web Client | Next.js 14 | React 18, TailwindCSS, TypeScript |

### 4.3 Infrastructure

| Component | Technology | Version |
|-----------|------------|---------|
| Container Runtime | Docker | 24.x |
| Orchestration | Docker Compose | 2.x |
| Database | PostgreSQL | 15+ |
| Cache | Redis | 7+ |
| Message Broker | RabbitMQ | 3.12+ |
| Vector Database | ChromaDB | 0.4+ |

### 4.4 Observability

| Component | Technology | Purpose |
|-----------|------------|---------|
| Metrics | Prometheus | Collect and store metrics |
| Dashboards | Grafana | Visualize metrics |
| Tracing | Jaeger | Distributed tracing |
| Logging | Structured JSON | Application logs |

---

## 5. Security Architecture

### 5.1 Authentication

- **Method:** JWT (JSON Web Tokens)
- **Token Lifetime:** Configurable (default 30 minutes)
- **Password Storage:** bcrypt with cost factor 12

### 5.2 Authorization

- **Model:** Role-Based Access Control (RBAC)
- **Roles:** admin, manager, user, system
- **Enforcement:** FastAPI dependencies on each route

### 5.3 Network Security

- **External:** HTTPS/TLS (production)
- **Internal:** Docker bridge network
- **Agent Auth:** API key + JWT

### 5.4 Data Protection

- **At Rest:** PostgreSQL (encryption available)
- **In Transit:** TLS 1.3 (production)
- **Secrets:** Environment variables / Docker secrets

---

## 6. Deployment Architecture

### 6.1 Development

```yaml
# Single host deployment via Docker Compose
docker compose up -d
```

All services run on a single host with exposed ports for development.

### 6.2 Production (Recommended)

```
┌─────────────────────────────────────────────────────┐
│                 Load Balancer (nginx)               │
│                 (TLS Termination)                   │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────┐
│                 Kubernetes Cluster                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ MAS Pod  │  │MAS Pod   │  │MAS Pod   │ (3+)     │
│  └──────────┘  └──────────┘  └──────────┘          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │Agent Pod │  │Agent Pod │  │Agent Pod │ (Scale)  │
│  └──────────┘  └──────────┘  └──────────┘          │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────┐
│              Managed Services                        │
│  PostgreSQL (RDS) | Redis (ElastiCache) | RabbitMQ  │
└─────────────────────────────────────────────────────┘
```

---

## 7. Scalability

### 7.1 Horizontal Scaling

| Component | Scaling Strategy |
|-----------|------------------|
| MAS | Stateless, multiple replicas behind LB |
| Agent | Stateless, scale based on queue depth |
| Knowledge Store | Single instance (can shard by collection) |
| PostgreSQL | Read replicas, connection pooling |
| RabbitMQ | Cluster mode |

### 7.2 Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| API Latency (p95) | < 200ms | Excluding LLM inference |
| LLM Response Time | < 5s | Depends on model size |
| Concurrent Users | 100+ | Per MAS instance |
| Task Throughput | 1000/min | With 3 agents |

---

## 8. High Availability

### 8.1 Component Redundancy

| Component | HA Strategy |
|-----------|-------------|
| MAS | 3+ replicas, stateless |
| Agent | 2+ replicas per skill type |
| PostgreSQL | Primary + standby |
| RabbitMQ | Cluster with quorum queues |
| Redis | Sentinel or cluster mode |

### 8.2 Failure Recovery

| Failure | Recovery |
|---------|----------|
| MAS restart | Agents re-register, conversations persist |
| Agent failure | Tasks reassigned via RabbitMQ |
| Database restart | Connection pool reconnects |
| RabbitMQ restart | Durable queues, messages preserved |

---

## 9. Integration Points

### 9.1 APIs

| API | Protocol | Authentication |
|-----|----------|----------------|
| MAS REST API | HTTPS | JWT Bearer token |
| MAS WebSocket | WSS | JWT in query param |
| Knowledge Store | HTTP | None (internal) |
| Agent Registration | HTTPS | API Key + JWT |

### 9.2 External Integrations

| Integration | Purpose | Protocol |
|-------------|---------|----------|
| LLM Provider | Model inference (future) | HTTPS |
| SSO Provider | Enterprise auth (future) | OIDC/SAML |
| Monitoring | Alerting (future) | Webhook |

---

## 10. Operational Procedures

### 10.1 Deployment

```bash
# Build and deploy
docker compose build
docker compose up -d

# Run migrations
docker exec mas alembic upgrade head
```

### 10.2 Backup

```bash
# Database backup
docker exec postgres pg_dump -U horus horus_db > backup.sql

# ChromaDB backup
docker cp knowledge_store:/app/chroma_data ./chroma_backup
```

### 10.3 Monitoring

- **Metrics:** http://localhost:9090 (Prometheus)
- **Dashboards:** http://localhost:3001 (Grafana)
- **Traces:** http://localhost:16686 (Jaeger)

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | Jan 2026 | Development Team | Initial version |
