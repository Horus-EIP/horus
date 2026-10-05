# Operations

Running Horus in dev/staging/prod: deployment, monitoring, secrets, and the per-environment configuration matrix.

---

## Deployment and CI

### Repository branches

Typical layout (confirm with your team):

- **`main`** — release-ready code  
- **`develop`** or similar — integration branch for features  
- **Feature branches** — often named `issue-<id>-<short-description>`  

This repository’s canonical remote is the project GitHub org; avoid unapproved mirrors.

---

### CI pipeline

Continuous integration is defined in **`.github/workflows/ci.yml`** at the repository root. It runs on every push and pull request.

**Summary**

1. **`test-unit`**  
   - Python **3.13**  
   - Starts infrastructure with `docker compose` from `src/infra`: `postgres`, `redis`, `rabbitmq`  
   - Installs MAS dependencies from `src/services/mas/requirements-cpu.txt`  
   - Runs Alembic migrations and `init_db` for MAS, starts Uvicorn on port 8000  
   - Runs `pytest -c tests/mas/pytest.ini tests/mas` with `tests/mas/test_integration.py` ignored  

2. **`test-integration`**  
   - Depends on `test-unit`  
   - Similar infrastructure and MAS startup  
   - Runs `pytest -c tests/mas/pytest.ini tests/mas/test_integration.py` with `TEST_BASE_URL` and `TEST_WS_BASE_URL` pointing at the local MAS instance  

For exact steps and env overrides (e.g. `DB_HOST=localhost`), read the workflow file. Frontend and other services may add jobs later; the workflow file remains the source of truth.

The **`cpu-images`** job builds the mas, agent and knowledge-store images through the CPU overlay (one runner per image). It fails if `pip list` in an image shows any `nvidia-*`, `cuda-*` or `triton` package, or a torch other than the pinned `+cpu` build (`scripts/ci/check-cpu-image.py`). It writes each image's size and build time to the job summary. The **`cpu-build-wiring`** job runs first: `tests/ci/test_cpu_torch_build.py` checks the torch pin, the Dockerfiles, the overlay and the `cpu-images` job without building anything.

---

### Local deployment with Docker

Build and run the full stack from the infra directory:

```bash
cd src/infra
cp .env.example .env   # once, then edit
docker compose up --build -d
```

Services are defined in **`src/infra/docker-compose.yml`**. See [Configuration](../getting-started/configuration.md) and [Monitoring](monitoring.md) for URLs and observability.

On a machine without an NVIDIA GPU, add the CPU overlay. The installer does this for the `cpu-*` profiles by writing `COMPOSE_FILE` to `.env`:

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up --build -d
```

The overlay sets the build argument `TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu` for mas, agent and knowledge_store. Each of these Dockerfiles installs the `torch==X` line of its `requirements.txt` from that index first, then the rest of the requirements, which keep the torch already installed. Without the overlay, the argument defaults to `https://pypi.org/simple`, which is the CUDA build the GPU profiles use. All requirement files pin the same torch version; change them together.

---

### Production considerations

For production, teams commonly:

- Run behind a reverse proxy (for example NGINX) with TLS  
- Use managed PostgreSQL, Redis, and RabbitMQ where appropriate  
- Store secrets in a vault or orchestrator secrets, not in committed `.env` files  
- Tune resource limits, health checks, and autoscaling per environment  

Kubernetes, Docker Swarm, or cloud-specific runtimes are outside this document; adapt the same images and environment variables your Compose file uses.

---

## Monitoring and observability

This document describes the monitoring stack shipped with **`src/infra/docker-compose.yml`** (repository root): metrics (Prometheus), traces (Tempo, OTLP), and logs (Loki), all viewed in the web client's admin pages (`/admin/logs`, `/admin/metrics`, `/admin/traces`), plus admin UIs for data stores.

---

### Stack overview

| Layer | Components |
|-------|------------|
| Data stores | PostgreSQL, Redis, RabbitMQ, ChromaDB (Knowledge Store volume) |
| Metrics | Prometheus scrapes MAS, Agent, and Knowledge Store `/metrics` endpoints; viewed at **`/admin/metrics`** in the web client |
| Traces | Grafana Tempo receives OTLP from application containers; viewed at **`/admin/traces`** in the web client (trace search + span waterfall) |
| Logs | Grafana Loki ingests stdout/stderr from **all Docker Compose services** via Promtail (Docker service discovery); viewed at **`/admin/logs`** in the web client |
| Visualization | Web client admin pages (`/admin/logs`, `/admin/metrics`, `/admin/traces`), backed by Loki, Prometheus, and Tempo; require the `admin` role |
| Admin UIs | PgAdmin, RedisInsight, RabbitMQ management plugin |

The default Compose file does **not** include SigNoz, a standalone OpenTelemetry Collector service, PostgreSQL Exporter, or Metabase. If you add those services, extend this document accordingly.

#### Quick start

```bash
cd src/infra
docker compose up -d
```

PostgreSQL is started with `pg_stat_statements` preloading (see the `postgres` service `command` in Compose). If you change extension-related settings, restart the stack: `docker compose down && docker compose up -d`.

---

### Admin observability pages (web client)

Logs, metrics, and traces are viewed in the Next.js web client's admin pages. These require the `admin` role.

| Page | URL | Backend |
|------|-----|---------|
| Logs | http://localhost:3000/admin/logs | Loki |
| Metrics | http://localhost:3000/admin/metrics | Prometheus |
| Traces | http://localhost:3000/admin/traces | Tempo |

The **Metrics** page replicates the former "MAS Overview" dashboard: Task Queue Depth, Task Errors Rate, and Active Agents. The **Traces** page offers trace search and a span waterfall.

#### Backend datasources

The backends run **inside** the Docker network and are **not** published to the host by default:

- **Prometheus** at `http://prometheus:9090` (internal-only).
- **Tempo** at `http://tempo:3200` for trace queries (internal-only); only the Tempo OTLP ports `4317` / `4318` are published.
- **Loki** at `http://loki:3100` for log queries (internal-only; labels include `compose_service`, `compose_project`, `container`).

#### Log retention and integrity (Loki)

In **`src/infra/observability/loki.yaml`**, the compactor has **`retention_enabled: false`** (no automatic expiry of old logs) and **`limits_config.allow_deletes: false`** (the log-deletion API is off). Loki’s ingest path is append-only: existing lines are not updated in place through the query API.

That is **not** cryptographic immutability: anyone who can remove the Docker volume or files on disk can still destroy data. For strict write-once retention (for example compliance), use object storage with **Object Lock** (or an enterprise log archive) and restrict who can change buckets or Compose volumes.

---

### Prometheus

| Item | Value |
|------|--------|
| Scrape config (mounted in Compose) | **`src/infra/observability/prometheus.yaml`** |
| Jobs | `prometheus` (self), `mas-api`, `agent-api`, `knowledge-store` |

**Host access:** The `prometheus` service has **no** `ports:` mapping in the default Compose file. You cannot open `http://localhost:9090` on the host unless you add a port mapping. Use either:

- The web client **`/admin/metrics`** page, which reads from the Prometheus backend, or  
- **Docker**: `docker exec -it prometheus wget -qO- http://localhost:9090/api/v1/targets` (or add `9090:9090` under `prometheus` for local debugging only).

#### Verification

Inside the Docker network, targets should include `mas:8000`, `agent:8001`, and `knowledge_store:8080` when those services are up. There is no `postgres` scrape job in the default config.

---

### Tempo (distributed tracing)

| Item | Value |
|------|--------|
| OTLP gRPC (from apps) | `tempo:4317` inside the network; host ports `4317` / `4318` are published for optional external collectors |
| App env | `OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317` (set per service in Compose) |

View traces in the web client **`/admin/traces`** page (trace search + span waterfall), backed by Tempo.

---

### Application metrics endpoints

When services run on the host (not only in Docker), raw Prometheus text format is available at:

| Service | URL (default local) |
|---------|---------------------|
| MAS | http://localhost:8000/metrics/ |
| Agent | http://localhost:8001/metrics/ |
| Knowledge Store | http://localhost:8080/metrics/ |

---

### PgAdmin 4

- **URL:** http://localhost:5433  
- **Credentials:** `PGADMIN_DEFAULT_EMAIL` and `PGADMIN_DEFAULT_PASSWORD` in `src/infra/.env`.

Register a server with host `postgres`, port `5432`, database `postgres` (or your `POSTGRES_DB`), using `POSTGRES_USER` / `POSTGRES_PASSWORD` from `.env`.

---

### RedisInsight

- **URL:** http://localhost:5540  
- Add database: host `redis`, port `6379`, password from `REDIS_PASSWORD` in `.env`.

---

### RabbitMQ management

- **URL:** http://localhost:15672  
- **Credentials:** `RABBITMQ_USER` / `RABBITMQ_PASSWORD` in `.env`.

Monitor queues and connections for `mas` and `agent` consumers.

---

### Structured logging

#### Log format

Services can emit structured JSON logs (example shape):

```json
{
  "timestamp": "2026-01-12T10:30:00.000Z",
  "level": "INFO",
  "logger": "task",
  "message": "Task created: task-123",
  "module": "routes",
  "function": "create_new_task",
  "line": 260,
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "extra": {
    "task_id": "task-123",
    "agent_id": "agent-456",
    "conversation_id": 1
  }
}
```

#### Correlation IDs

1. Incoming requests: `X-Request-ID` or `X-Correlation-ID` when present  
2. Otherwise: generated UUID  
3. Propagated downstream via headers  
4. Returned on responses where middleware supports it  

#### Log levels

| Level | Use |
|-------|-----|
| DEBUG | Verbose diagnostics |
| INFO | Normal operation |
| WARNING | Recoverable anomalies |
| ERROR | Failures requiring attention |
| CRITICAL | Severe failures |

#### Typical environment variables

```bash
LOG_LEVEL=INFO
JSON_LOGGING=true
```

---

### Metrics reference (MAS examples)

PromQL examples assume metric names exported by the MAS service; verify with `/metrics` if names differ.

```promql
rate(mas_http_requests_total[5m])
histogram_quantile(0.95, rate(mas_http_request_duration_seconds_bucket[5m]))
```

---

### Distributed tracing (application code)

Trace context is propagated via standard headers (for example W3C `traceparent` and correlation IDs) where instrumentation is enabled.

Example pattern (adjust imports to your service’s tracing module):

```python
from core.tracing import create_span, add_span_attributes

with create_span("my_operation", {"key": "value"}) as span:
    span.set_attribute("result", "success")
```

---

### Alerting

Alerting on Prometheus metrics is not configured in the minimal Compose defaults; wire your own rules into the Prometheus backend (for example via Alertmanager) if you need them. Suggested thresholds for your own rules:

| Signal | Warning | Critical |
|--------|---------|----------|
| Error rate | greater than 1% | greater than 5% |
| p95 latency | greater than 500 ms | greater than 2 s |
| Active agents | fewer than 2 | zero |
| Task queue depth | greater than 100 | greater than 500 |

---

### Environment variables reference

#### MAS (excerpt)

```bash
LOG_LEVEL=INFO
JSON_LOGGING=true
OTEL_ENABLED=true
OTEL_SERVICE_NAME=mas
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
OTEL_PYTHON_EXCLUDED_URLS=/health,/metrics,/rabbitmq/heartbeat,/agents/heartbeat/
TASK_TIMEOUT_SECONDS=300
```

In Docker Compose, `OTEL_EXPORTER_OTLP_ENDPOINT` points at the `tempo` service, not a separate OpenTelemetry Collector container.

#### Agent and Knowledge Store

Follow the same `OTEL_*` pattern as in Compose for each service; see service-specific env blocks in `docker-compose.yml`.

---

### Performance impact

Observability adds small per-request overhead (logging, metrics, tracing). To reduce load in production: raise `LOG_LEVEL`, use trace sampling if configured in instrumentation, and reserve sufficient resources for Tempo and Prometheus volumes.

---

### Troubleshooting

#### `/admin/metrics` shows no Prometheus data

- Confirm `prometheus`, `mas`, `agent`, and `knowledge_store` containers are running.  
- Check the Prometheus targets directly: `docker exec -it prometheus wget -qO- http://localhost:9090/api/v1/targets`.  
- If Prometheus is unreachable from the web client, check the Docker network and **`src/infra/observability/prometheus.yaml`**.

#### Cannot open Prometheus on the host

- Expected with the default Compose file: add a host port for `prometheus` or use the `/admin/metrics` page / `docker exec` as described above.

#### No traces at `/admin/traces`

- Ensure `OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317` for the service.  
- Check `docker logs tempo` and that the app container can resolve `tempo`.  
- A chat message shows up under the `mas` service as `POST /tasks/new_task/`, with `route_task`, `publish horus.work.<type>`, the agent's `knowledge_store_fetch_for_rag` and the result post as child spans. Healthcheck probes, Prometheus scrapes and agent heartbeats are left out on purpose (`OTEL_PYTHON_EXCLUDED_URLS` in `docker-compose.yml`), and so are database or HTTP calls that MAS makes outside a request.

#### Connection refused from PgAdmin to the database

- From PgAdmin running in Docker, use host `postgres`, not `localhost`.

#### Slow query panels empty

- Confirm `pg_stat_statements` is loaded (`postgres` service command in Compose).  
- Test in SQL: `SELECT * FROM pg_stat_statements LIMIT 5;`

#### Logs not JSON

- Set `JSON_LOGGING=true` and restart the service.

---

### References

- [Prometheus documentation](https://prometheus.io/docs/)  
- [Grafana Tempo documentation](https://grafana.com/docs/tempo/latest/)  
- [Grafana Loki documentation](https://grafana.com/docs/loki/latest/)  
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)

---

## Secrets Management Guide

This guide provides best practices for managing sensitive credentials and secrets across the Horus multi-agent system in different environments.

### Overview

Secrets include:
- Database passwords
- API keys
- JWT secret keys
- Encryption keys
- External service credentials
- OAuth tokens

**Golden Rule**: Never commit secrets to version control. Use `.env.example` as a template only.

### Local Development Setup

#### Step 1: Create Local `.env` Files

```bash
## Copy templates for each service
cp src/infra/.env.example src/infra/.env
cp src/services/mas/.env.example src/services/mas/.env
cp src/services/agent/.env.example src/services/agent/.env
cp src/services/knowledge-store/.env.example src/services/knowledge-store/.env
cp src/services/web-client/.env.example src/services/web-client/.env.local
```

#### Step 2: Fill in Development Values

**`src/infra/.env`** (Infrastructure secrets):

```env
## Use weak passwords for local development
POSTGRES_PASSWORD=devpassword123
REDIS_PASSWORD=devpassword123
RABBITMQ_PASSWORD=devpassword123

## Use a simple JWT secret for local development
JWT_SECRET_KEY=dev-secret-key-change-in-production

## Admin credentials for testing
SUPER_USER_USERNAME=admin
SUPER_USER_PASSWORD=admin

PGADMIN_DEFAULT_PASSWORD=admin
```

#### Step 3: Git Configuration

Ensure `.env` files are ignored:

```bash
## .gitignore
.env
.env.local
.env.*.local
!.env.example
!.env.staging.example
!.env.production.example
```

Verify configuration:

```bash
git status
## Should NOT show .env files
```

### Staging Environment

#### Using Environment Variables

For staging deployments, use environment-specific `.env` files:

**`.env.staging`** (Not committed):

```env
## Staging database - dedicated staging database
POSTGRES_USER=staging_user
POSTGRES_PASSWORD=${STAGING_DB_PASSWORD}  # From CI/CD secrets
POSTGRES_DB=horus_staging

## Staging Redis with password
REDIS_PASSWORD=${STAGING_REDIS_PASSWORD}  # From CI/CD secrets
REDIS_HOST=staging-redis.internal

## RabbitMQ staging instance
RABBITMQ_PASSWORD=${STAGING_RABBITMQ_PASSWORD}  # From CI/CD secrets
RABBITMQ_HOST=staging-rabbitmq.internal

## JWT secret for staging
JWT_SECRET_KEY=${STAGING_JWT_SECRET}  # From CI/CD secrets

## LLM enabled in staging
LLM_AUTOINIT=1
```

#### CI/CD Integration (GitHub Actions)

Store secrets in GitHub repository settings and reference in workflows:

```yaml
## .github/workflows/deploy-staging.yml
name: Deploy to Staging

on:
  push:
    branches: [develop]

jobs:
  deploy:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Deploy to staging
        env:
          STAGING_DB_PASSWORD: ${{ secrets.STAGING_DB_PASSWORD }}
          STAGING_REDIS_PASSWORD: ${{ secrets.STAGING_REDIS_PASSWORD }}
          STAGING_JWT_SECRET: ${{ secrets.STAGING_JWT_SECRET }}
        run: |
          # Create .env from template and secrets
          cp src/infra/.env.example src/infra/.env
          
          # Inject secrets
          echo "POSTGRES_PASSWORD=${STAGING_DB_PASSWORD}" >> src/infra/.env
          echo "REDIS_PASSWORD=${STAGING_REDIS_PASSWORD}" >> src/infra/.env
          echo "JWT_SECRET_KEY=${STAGING_JWT_SECRET}" >> src/infra/.env
          
          # Deploy
          docker-compose -f src/infra/docker-compose.yml up -d
```

### Production Environment

#### Using Docker Secrets

For Docker Swarm deployments, use Docker Secrets:

```bash
## 1. Create secrets from files
docker secret create db_password <(echo "production_db_password_xyz")
docker secret create jwt_secret <(echo "production_jwt_secret_abc")
docker secret create redis_password <(echo "production_redis_password_def")
docker secret create rabbitmq_password <(echo "production_rabbitmq_password_ghi")

## 2. List created secrets
docker secret ls
```

Update `docker-compose.yml` for production:

```yaml
## src/infra/docker-compose.production.yml
version: '3.8'

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    command: redis-server --requirepass $(cat /run/secrets/redis_password)
    secrets:
      - redis_password

  mas:
    image: horus-mas:latest
    environment:
      JWT_SECRET_KEY_FILE: /run/secrets/jwt_secret
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
      REDIS_PASSWORD_FILE: /run/secrets/redis_password
    secrets:
      - db_password
      - jwt_secret
      - redis_password

secrets:
  db_password:
    external: true
  jwt_secret:
    external: true
  redis_password:
    external: true
  rabbitmq_password:
    external: true
```

#### Using HashiCorp Vault

For Kubernetes or advanced scenarios, use Vault:

```bash
## 1. Authenticate to Vault
vault login -method=kubernetes role=horus-app

## 2. Store secrets
vault kv put secret/horus/production \
  POSTGRES_PASSWORD="$(openssl rand -base64 32)" \
  JWT_SECRET_KEY="$(openssl rand -base64 64)" \
  REDIS_PASSWORD="$(openssl rand -base64 32)" \
  RABBITMQ_PASSWORD="$(openssl rand -base64 32)"

## 3. Retrieve secrets
vault kv get secret/horus/production
```

**Kubernetes Integration**:

```yaml
## k8s-secret-sync.yml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: vault-secret-sync
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: vault-auth
          containers:
          - name: vault-sync
            image: vault:latest
            env:
            - name: VAULT_ADDR
              value: "https://vault.internal"
            - name: VAULT_ROLE
              value: "horus-app"
            volumeMounts:
            - name: vault-token
              mountPath: /var/run/secrets/kubernetes.io/serviceaccount
            command:
            - /bin/sh
            - -c
            - |
              TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
              vault write -tls-skip-verify auth/kubernetes/login role=horus-app jwt=$TOKEN
              vault kv get -tls-skip-verify secret/horus/production > /etc/secrets/.env
              kubectl patch secret horus-secrets --from-file=/etc/secrets/.env
          volumes:
          - name: vault-token
            projected:
              sources:
              - serviceAccountToken:
                  path: token
          restartPolicy: OnFailure
```

### Secret Rotation

#### Password Rotation Schedule

- **Development**: Not required
- **Staging**: Monthly
- **Production**: Every 90 days

#### Automated Rotation Script

```bash
#!/bin/bash
## scripts/rotate-secrets.sh

set -e

ENVIRONMENT=$1  # staging or production
VAULT_ADDR=${VAULT_ADDR:-https://vault.internal}

if [ -z "$ENVIRONMENT" ]; then
  echo "Usage: ./rotate-secrets.sh [staging|production]"
  exit 1
fi

echo "Rotating secrets for $ENVIRONMENT..."

## Generate new secrets
NEW_DB_PASSWORD=$(openssl rand -base64 32)
NEW_JWT_SECRET=$(openssl rand -base64 64)
NEW_REDIS_PASSWORD=$(openssl rand -base64 32)
NEW_RABBITMQ_PASSWORD=$(openssl rand -base64 32)

## Store in Vault
vault kv put "${VAULT_ADDR}/secret/horus/${ENVIRONMENT}" \
  POSTGRES_PASSWORD="$NEW_DB_PASSWORD" \
  JWT_SECRET_KEY="$NEW_JWT_SECRET" \
  REDIS_PASSWORD="$NEW_REDIS_PASSWORD" \
  RABBITMQ_PASSWORD="$NEW_RABBITMQ_PASSWORD"

echo "Secrets rotated successfully"
echo "Update deployment configurations with new secrets"

## For Docker Swarm
docker secret rm db_password || true
docker secret rm jwt_secret || true
docker secret rm redis_password || true
docker secret rm rabbitmq_password || true

docker secret create db_password <(echo "$NEW_DB_PASSWORD")
docker secret create jwt_secret <(echo "$NEW_JWT_SECRET")
docker secret create redis_password <(echo "$NEW_REDIS_PASSWORD")
docker secret create rabbitmq_password <(echo "$NEW_RABBITMQ_PASSWORD")

## Restart services
docker service update --force horus_mas
docker service update --force horus_agent
docker service update --force horus_knowledge_store

echo "Services restarted with new secrets"
```

### Secret Backup & Recovery

#### Backup Secrets

```bash
#!/bin/bash
## scripts/backup-secrets.sh

ENVIRONMENT=$1
BACKUP_DIR="./backups/secrets/$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"

## Backup from Vault
vault kv get -format=json "secret/horus/${ENVIRONMENT}" | \
  jq '.data.data' > "$BACKUP_DIR/${ENVIRONMENT}-secrets.json"

## Encrypt backup
openssl enc -aes-256-cbc -salt -in "$BACKUP_DIR/${ENVIRONMENT}-secrets.json" \
  -out "$BACKUP_DIR/${ENVIRONMENT}-secrets.json.enc" \
  -k "$(cat ~/.secret-backup-key)" && \
  rm "$BACKUP_DIR/${ENVIRONMENT}-secrets.json"

echo "Secrets backed up to $BACKUP_DIR"
```

#### Restore Secrets

```bash
#!/bin/bash
## scripts/restore-secrets.sh

ENVIRONMENT=$1
BACKUP_FILE=$2

if [ -z "$BACKUP_FILE" ]; then
  echo "Usage: ./restore-secrets.sh [staging|production] <backup-file>"
  exit 1
fi

## Decrypt backup
openssl enc -d -aes-256-cbc -in "$BACKUP_FILE" \
  -k "$(cat ~/.secret-backup-key)" | \
  vault kv put "secret/horus/${ENVIRONMENT}" @-

echo "Secrets restored from $BACKUP_FILE"
```

### Security Audit Checklist

- [ ] All `.env` files are in `.gitignore`
- [ ] No secrets committed in git history (`git log -p | grep -i password`)
- [ ] All services validate required secrets at startup
- [ ] Secrets are rotated on schedule
- [ ] Database audit logs track all connections
- [ ] API keys have expiration dates
- [ ] Backup of secrets stored separately
- [ ] Team members have access to secrets management system
- [ ] Secrets marked with environment (dev/staging/prod)
- [ ] Unused secrets removed regularly

### References

- [OWASP: Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [12 Factor App: Config](https://12factor.net/config)
- [Docker Secrets](https://docs.docker.com/engine/swarm/secrets/)
- [HashiCorp Vault](https://www.vaultproject.io/)
- [GitHub: Secret Scanning](https://github.com/features/secret-scanning)

---

## Configuration Matrix: Development, Staging, Production

This document outlines environment-specific configuration values for the three main deployment environments.

### Quick Reference Matrix

| Variable | Development | Staging | Production |
|----------|-------------|---------|-----------|
| **DEBUG** | `true` | `false` | `false` |
| **LOG_LEVEL** | `DEBUG` | `INFO` | `WARN` |
| **NODE_ENV** | `development` | `production` | `production` |
| **Database** | Local container | RDS instance | RDS cluster (HA) |
| **Redis** | Local container | ElastiCache | ElastiCache (cluster) |
| **RabbitMQ** | Local container | Managed service | Managed service (cluster) |
| **CORS** | `["*"]` | `["https://staging.example.com"]` | `["https://app.example.com"]` |
| **TLS/HTTPS** | No | Yes | Yes (enforced) |
| **Secret Rotation** | Manual | Monthly | 90 days |

### Development Environment

#### Purpose
Local development and rapid iteration. Permissive security, debugging enabled.

#### Configuration Values

```env
## src/infra/.env (Development)
## ============================

## Server
DEBUG=true
LOG_LEVEL=DEBUG
NODE_ENV=development

## Database - Local container
POSTGRES_USER=admin
POSTGRES_PASSWORD=devpassword
POSTGRES_DB=horus_dev
DB_HOST=postgres
DB_PORT=5432

## Cache - Local container
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=devredis

## Message Queue - Local container
RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest

## Authentication
JWT_SECRET_KEY=dev-secret-key-change-in-production
JWT_ALGORITHM=HS256

## Initial Admin
SUPER_USER_USERNAME=admin
SUPER_USER_PASSWORD=admin

## Application
LLM_AUTOINIT=0

## PgAdmin (see src/infra/.env.example)
PGADMIN_DEFAULT_EMAIL=admin@admin.com
PGADMIN_DEFAULT_PASSWORD=admin

## Web client (implemented in src/services/web-client/utils/config.ts)
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_KNOWLEDGE_STORE_URL=http://localhost:8080
NEXT_PUBLIC_WS_URL=ws://localhost:8000

## Not used by the current web client config module (examples only if you extend the app):
## NEXT_PUBLIC_API_TIMEOUT, NEXT_PUBLIC_AUTH_ENABLED, NEXT_PUBLIC_ENABLE_* feature flags
```

#### Startup Commands

```bash
## Start all services
cd src/infra
docker compose up --build

## Logs
docker compose logs -f mas
docker compose logs -f agent
docker compose logs -f knowledge_store

## Stop all services
docker compose down
```

#### Database Initialization

```bash
## Admin user is created by MAS startup (entrypoint runs init_db). To re-run inside the mas container:
docker exec -it mas python -c "from db.init_setup import init_db; init_db()"

## Reset database (adjust user/database to match src/infra/.env)
docker exec -it postgres psql -U postgres -d mas_db -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

#### Debugging

```bash
## Access container shell
docker exec -it mas /bin/bash

## View logs with timestamps
docker compose logs --timestamps mas

## Monitor in real-time
docker stats
```

### Staging Environment

#### Purpose
Pre-production testing with realistic configuration, secret rotation enabled.

#### Infrastructure

```
┌─────────────────────────────────────────┐
│   AWS / Cloud Provider                  │
├─────────────────────────────────────────┤
│ ECS Cluster / Kubernetes                │
│  - MAS Service (2 instances)            │
│  - Agent Service (1 instance)           │
│  - Knowledge Store (1 instance)         │
│  - Web Client (CloudFront / CDN)        │
├─────────────────────────────────────────┤
│ RDS PostgreSQL (db.t3.small)            │
│ ElastiCache Redis (cache.t3.micro)      │
│ RabbitMQ Managed Instance               │
│ Secrets Manager (AWS)                   │
└─────────────────────────────────────────┘
```

#### Configuration Values

```env
## .env.staging (Not committed)
## =============================

## Server
DEBUG=false
LOG_LEVEL=INFO
NODE_ENV=production

## Database - AWS RDS
POSTGRES_USER=staging_admin
POSTGRES_PASSWORD=${STAGING_DB_PASSWORD}
POSTGRES_DB=horus_staging
DB_HOST=horus-staging-db.c9akciq32.us-east-1.rds.amazonaws.com
DB_PORT=5432

## Cache - AWS ElastiCache
REDIS_HOST=horus-staging-redis.xxxxxx.ng.0001.use1.cache.amazonaws.com
REDIS_PORT=6379
REDIS_PASSWORD=${STAGING_REDIS_PASSWORD}

## Message Queue - AWS MQ
RABBITMQ_HOST=horus-staging-mq.xxxxx.mq.us-east-1.amazonaws.com
RABBITMQ_PORT=5672
RABBITMQ_USER=staging_user
RABBITMQ_PASSWORD=${STAGING_RABBITMQ_PASSWORD}

## Authentication
JWT_SECRET_KEY=${STAGING_JWT_SECRET}
JWT_ALGORITHM=HS256

## Initial Admin
SUPER_USER_USERNAME=staging_admin
SUPER_USER_PASSWORD=${STAGING_ADMIN_PASSWORD}

## Application
LLM_AUTOINIT=1

## Web client
NEXT_PUBLIC_API_URL=https://staging-api.horus.example.com
NEXT_PUBLIC_KNOWLEDGE_STORE_URL=https://staging-knowledge.horus.example.com
NEXT_PUBLIC_WS_URL=wss://staging-api.horus.example.com

## TLS/Security
CORS_ORIGINS=https://staging.horus.example.com
TLS_ENABLED=true
TLS_CERT_PATH=/etc/ssl/staging-cert.pem
TLS_KEY_PATH=/etc/ssl/staging-key.pem
```

#### Deployment Process

```bash
## GitHub Actions Workflow
## .github/workflows/deploy-staging.yml

name: Deploy to Staging
on:
  push:
    branches: [develop]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Build Docker images
        run: |
          docker build -t horus-mas:staging src/services/mas/
          docker build -t horus-agent:staging src/services/agent/
          docker build -t horus-knowledge-store:staging src/services/knowledge-store/
          docker build -t horus-web-client:staging src/services/web-client/
      
      - name: Push to ECR
        run: |
          aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $ECR_REGISTRY
          docker tag horus-mas:staging $ECR_REGISTRY/horus-mas:staging
          docker push $ECR_REGISTRY/horus-mas:staging
      
      - name: Update ECS services
        run: |
          aws ecs update-service --cluster horus-staging --service mas --force-new-deployment
```

#### Database Migrations

```bash
## Run migrations on staging
aws ecs run-task \
  --cluster horus-staging \
  --task-definition horus-migration:1 \
  --count 1 \
  --launch-type FARGATE \
  --overrides '{
    "containerOverrides": [{
      "name": "migration",
      "environment": [
        {"name": "DATABASE_URL", "value": "postgresql://..."}
      ]
    }]
  }'
```

### Production Environment

#### Purpose
Live production system. Minimal logging, high availability, vault-managed secrets, strict security.

#### Infrastructure (High Availability)

```
┌────────────────────────────────────────────────────────────────┐
│   AWS / Cloud Provider (Multi-AZ)                              │
├────────────────────────────────────────────────────────────────┤
│ ECS Cluster / Kubernetes (3+ AZ)                               │
│  - MAS Service (6+ instances, auto-scaling)                    │
│  - Agent Service (4+ instances, auto-scaling)                  │
│  - Knowledge Store (3+ instances)                              │
│  - Web Client (CloudFront CDN, edge locations)                 │
├────────────────────────────────────────────────────────────────┤
│ RDS PostgreSQL (db.r5.xlarge, Multi-AZ, read replicas)         │
│ ElastiCache Redis (cache.r5.large, cluster mode)               │
│ RabbitMQ Managed Cluster (3 nodes)                             │
│ AWS Secrets Manager (automatic rotation)                       │
│ AWS Certificate Manager (TLS)                                  │
│ CloudFront (CDN)                                               │
│ WAF (Web Application Firewall)                                 │
│ Application Load Balancer (multi-AZ)                           │
└────────────────────────────────────────────────────────────────┘
```

#### Configuration Values

```env
## .env.production (Stored in AWS Secrets Manager)
## ================================================

## Server
DEBUG=false
LOG_LEVEL=WARN
NODE_ENV=production

## Database - AWS RDS Multi-AZ
POSTGRES_USER=prod_admin
POSTGRES_PASSWORD=${vault:horus/production/db_password}
POSTGRES_DB=horus_prod
DB_HOST=horus-prod-primary.xxxxxx.us-east-1.rds.amazonaws.com
DB_HOST_READ=horus-prod-read-replica.xxxxxx.us-east-1.rds.amazonaws.com
DB_PORT=5432
DB_SSL=require
DB_POOL_SIZE=30
DB_POOL_MIN=10

## Cache - AWS ElastiCache Cluster Mode
REDIS_HOST=horus-prod-redis.xxxxxx.cache.amazonaws.com
REDIS_PORT=6379
REDIS_PASSWORD=${vault:horus/production/redis_password}
REDIS_CLUSTER_MODE=true
REDIS_SSL=true

## Message Queue - AWS MQ Cluster
RABBITMQ_HOST=b-1-horus-prod-mq.xxxxx.mq.us-east-1.amazonaws.com
RABBITMQ_PORT=5671
RABBITMQ_USER=prod_user
RABBITMQ_PASSWORD=${vault:horus/production/rabbitmq_password}
RABBITMQ_SSL=true

## Authentication
JWT_SECRET_KEY=${vault:horus/production/jwt_secret}
JWT_ALGORITHM=HS256
JWT_EXPIRATION=1200

## Initial Admin (disabled in production)
SUPER_USER_USERNAME=
SUPER_USER_PASSWORD=

## Application
LLM_AUTOINIT=1
RATE_LIMIT=1000
RATE_LIMIT_WINDOW=3600

## Web client
NEXT_PUBLIC_API_URL=https://api.horus.example.com
NEXT_PUBLIC_KNOWLEDGE_STORE_URL=https://knowledge.horus.example.com
NEXT_PUBLIC_WS_URL=wss://api.horus.example.com

## TLS/Security
CORS_ORIGINS=https://horus.example.com
TLS_ENABLED=true
TLS_CERT_PATH=/etc/ssl/prod-cert.pem
TLS_KEY_PATH=/etc/ssl/prod-key.pem

## Monitoring & Security
SENTRY_DSN=${vault:horus/production/sentry_dsn}
DATADOG_API_KEY=${vault:horus/production/datadog_key}
AUTH_AUDIT_LOG=true
COMPLIANCE_LOGGING=true
```

#### Deployment & Rollout

```bash
## Blue-Green Deployment Strategy
## .github/workflows/deploy-production.yml

name: Deploy to Production (Blue-Green)
on:
  release:
    types: [published]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Deploy to green environment
        run: |
          # Deploy to ECS "green" task definition
          aws ecs update-service \
            --cluster horus-prod-green \
            --service mas \
            --task-definition horus-mas:${{ github.run_id }} \
            --desired-count 6
      
      - name: Health checks (2 hours)
        run: |
          # Wait for green environment to stabilize
          # Run integration tests
          # Monitor error rates
          timeout 7200 bash -c 'until health-check-passes; do sleep 30; done'
      
      - name: Switch traffic (Blue to Green)
        run: |
          aws elbv2 modify-target-group \
            --target-group-arn $GREEN_TG_ARN \
            --matcher HttpCode=200-299
          
          # Update ALB to point to green
          aws elbv2 modify-listener \
            --listener-arn $LISTENER_ARN \
            --default-actions Type=forward,TargetGroupArn=$GREEN_TG_ARN
      
      - name: Monitor (30 minutes)
        run: |
          # Monitor error rates, latency, etc.
          # If issues detected, automatic rollback
          timeout 1800 bash -c 'monitor-metrics && rollback-if-needed'
```

#### Database Backup & Disaster Recovery

```bash
## Automated backups (AWS RDS handles this)
## Manual backup for critical operations
aws rds create-db-snapshot \
  --db-instance-identifier horus-prod-primary \
  --db-snapshot-identifier horus-prod-backup-$(date +%Y%m%d-%H%M%S)

## Verify backup
aws rds describe-db-snapshots \
  --snapshot-type manual \
  --query 'DBSnapshots[?DBInstanceIdentifier==`horus-prod-primary`]'
```

#### Security Hardening

```bash
## Network Security Groups
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxx \
  --protocol tcp \
  --port 443 \
  --cidr 0.0.0.0/0

## Disable SSH
aws ec2 revoke-security-group-ingress \
  --group-id sg-xxxxxxxx \
  --protocol tcp \
  --port 22 \
  --cidr 0.0.0.0/0

## Enable WAF
aws wafv2 create-web-acl \
  --region us-east-1 \
  --name horus-prod-waf \
  --default-action Block={} \
  --rules file://waf-rules.json
```

### Environment-Specific Health Checks

#### Development
- API responding on localhost:8000
- Services up (`docker ps`)

#### Staging
- Database connectivity
- RabbitMQ queue connection
- Redis cache connectivity
- API health endpoint: `GET /health`
- WebSocket connectivity: `WS /chat`

#### Production
- All of above, plus:
- Database replication lag < 100ms
- Error rate < 0.1%
- P99 latency < 500ms
- No secrets in logs
- Backup created in last 24h
- All services in at least 2 AZs

### Configuration Validation Checklist

- [ ] All `.env.example` files up-to-date
- [ ] Environment variables documented
- [ ] Secrets stored in vault/manager (not in `.env`)
- [ ] TLS/HTTPS enforced in staging/prod
- [ ] Database backup strategy tested
- [ ] Monitoring and alerting configured
- [ ] Logging doesn't contain secrets
- [ ] Rate limiting configured
- [ ] CORS restricted appropriately
- [ ] Load balancing configured
