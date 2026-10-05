# Getting Started

This chapter covers everything you need to go from a fresh clone to a running stack: prerequisites and onboarding, configuration via environment variables, and troubleshooting when things go wrong.

---

## Developer onboarding

This guide helps you set up a local environment for the Horus multi-agent system.

### Quick setup (under 30 minutes)

**Typical timing**

- Prerequisites: 2–5 minutes  
- Clone repository: 1–2 minutes  
- Environment file: 2–3 minutes  
- First Docker build: 10–15 minutes  
- Verification: 2–3 minutes  

---

### Prerequisites

#### Required

- **Git** (2.30+)  
  [Download Git](https://git-scm.com/downloads)

- **Docker** with Compose v2 (`docker compose`)  
  [Docker Desktop](https://www.docker.com/products/docker-desktop)  
  Allocate at least 4 CPUs and 8 GB RAM in Docker settings.

#### Optional (running services outside Docker)

- **Python 3.13+** for MAS and related services  
- **Node.js** compatible with Next.js 16 (see `src/services/web-client/package.json`) for frontend work  

#### Optional prerequisite check

```bash
git --version
docker --version
docker compose version
python3 --version   # optional
node --version      # optional
```

---

### Project structure (high level)

```
├── src/
│   ├── infra/                 # Docker Compose, Loki/Tempo/Prometheus config
│   │   ├── docker-compose.yml
│   │   ├── .env.example
│   │   └── observability/
│   └── services/
│       ├── mas/               # Orchestrator (FastAPI)
│       ├── agent/             # Agent worker (FastAPI)
│       ├── knowledge-store/   # Vector store API (FastAPI)
│       └── web-client/        # Next.js UI
├── docs/                      # Project documentation
├── tests/                     # Centralized tests (e.g. tests/mas)
└── scripts/                   # CI and dev helpers
```

---

### Setup

#### Step 1: Clone the repository

```bash
git clone <repository-url>
cd <repository-directory>
git checkout <your-working-branch>
```

#### Step 2: Configure environment

```bash
cd src/infra
cp .env.example .env
```

Review values in `.env`. Defaults are suitable for many local setups. Important keys include `POSTGRES_*`, `REDIS_PASSWORD`, `RABBITMQ_*`, `JWT_SECRET_KEY`, and `SUPER_USER_*`. Never commit `.env`; only `.env.example` is tracked.

#### Step 3: Start the stack

```bash
cd src/infra
docker compose up --build
```

First run builds images and can take several minutes. The stack includes PostgreSQL, Redis, RabbitMQ, MAS, Agent, Knowledge Store, Web Client, PgAdmin, RedisInsight, and the observability backends Prometheus, Loki, and Tempo (all internal). Logs, metrics, and traces are viewed from the admin-only observability pages in the web client (`/admin/logs`, `/admin/metrics`, `/admin/traces`). See **`src/infra/docker-compose.yml`** for the authoritative list.

#### Step 4: Verify containers

In another terminal:

```bash
cd src/infra
docker compose ps
```

Every application service declares a healthcheck, so wait until `mas`, `agent`, `knowledge_store` and `web-client` (and `vllm` on a GPU machine) show `(healthy)`, not just `Up`. Each one probes an unauthenticated endpoint inside its own container:

| Service | Probe | Allowed first start |
|---------|-------|---------------------|
| `mas` | `POST /rabbitmq/heartbeat` (curl) | 15 min (router model download) |
| `agent` | `GET /health` on :8001 (python) | 30 min (decision model download and load) |
| `knowledge_store` | `GET /health` on :8080 (python) | 10 min |
| `web-client` | `GET /api/health` on :3000 (wget) | 2 min |

A service is only marked `unhealthy` after that start window, so `(health: starting)` during a first install is normal. The agent starts only once `mas` and `knowledge_store` are healthy, and `mas` only once `postgres`, `redis` and `rabbitmq` are.

**PostgreSQL** (adjust user and database to match `.env`):

```bash
docker compose exec postgres psql -U postgres -d mas_db -c "SELECT version();"
```

**Redis** (password from `REDIS_PASSWORD` in `.env`):

```bash
docker compose exec redis redis-cli -a "$REDIS_PASSWORD" ping
```

---

### Web interfaces

| Service | URL | Notes |
|---------|-----|--------|
| RabbitMQ management | http://localhost:15672 | User/password from `RABBITMQ_USER` / `RABBITMQ_PASSWORD` |
| PgAdmin | http://localhost:5433 | `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` |
| RedisInsight | http://localhost:5540 | Configure connection to host `redis` from inside Docker |
| MAS API docs | http://localhost:8000/docs | When `mas` is running |
| Web client | http://localhost:3000 | When `web-client` is running |
| Logs | http://localhost:3000/admin/logs | Admin-only (requires `admin` role); backed by Loki |
| Metrics | http://localhost:3000/admin/metrics | Admin-only; backed by Prometheus (Task Queue Depth, Task Errors Rate, Active Agents) |
| Traces | http://localhost:3000/admin/traces | Admin-only; backed by Tempo (trace search + span waterfall) |

**Prometheus** is not published on the host in the default Compose file. View metrics from the admin **Metrics** page (http://localhost:3000/admin/metrics) or see [Monitoring](../operations/monitoring.md).

There is **no** Metabase or PostgreSQL Exporter service in the default `docker-compose.yml`.

---

### Running tests

From the repository root:

```bash
./scripts/test/run-all.sh
```

MAS-focused tests:

```bash
bash scripts/test/run-mas.sh
```

Or directly:

```bash
pytest -c tests/mas/pytest.ini tests/mas -v
```

Client-style scripts (if present):

```bash
cd tests/mas/client_tests
python client_multiple_agents.py
```

---

### Running MAS on the host (optional)

Use when you want to debug Python without rebuilding the `mas` image. PostgreSQL, Redis, and RabbitMQ should still be reachable (often via Docker).

```bash
cd src/services/mas
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

From the repo root, with `DB_HOST`, `REDIS_HOST`, and `RABBITMQ_HOST` pointing at localhost (see CI workflow for patterns):

```bash
bash scripts/dev/run-mas.sh
```

Open http://localhost:8000/docs when the server is up.

---

### Troubleshooting

#### Docker services fail to start

```bash
docker ps
docker system df
docker compose logs postgres
docker compose logs redis
```

Try a clean rebuild: `docker compose down -v` then `docker compose up --build` (destroys named volumes; use only if you accept data loss).

#### Port already in use

Find the process using the port (example: 5432), stop it, or change the host mapping via `DB_PORT` in `.env` where applicable.

#### Database connection errors from the host

Ensure Postgres is healthy: `docker compose ps postgres` and `docker compose logs postgres`.

#### 401 from the API

Confirm `JWT_SECRET_KEY` is set. Super-user bootstrap runs at MAS startup via the container entrypoint.

#### RabbitMQ errors

```bash
docker compose ps rabbitmq
docker compose exec rabbitmq rabbitmq-diagnostics -q ping
```

#### `ModuleNotFoundError` (e.g. `core`)

Run from `src/services/mas` with `PYTHONPATH` including that directory, or use the provided scripts.

---

### Development workflow

1. Create a branch from your team’s integration branch.  
2. Make changes and run tests locally.  
3. Commit using [commit convention](../contributing/commit-convention.md).  
4. Open a pull request and request review.  

---

### Further reading

- [Architecture overview](../architecture/overview.md)  
- [Configuration](configuration.md)  
- [RBAC](../security/rbac.md)  
- [Secrets management](../operations/secrets-management.md)  
- [Workflow](../contributing/workflow.md)  
- [Testing policy](../contributing/testing-policy.md)  
- [Troubleshooting (extended)](troubleshooting.md)  

---

### Verification checklist

- [ ] Repository cloned  
- [ ] `src/infra/.env` created from `.env.example`  
- [ ] `docker compose ps` shows expected services  
- [ ] Postgres accepts connections  
- [ ] RabbitMQ UI reachable  
- [ ] Redis responds to `PING`  
- [ ] Tests pass (`pytest -c tests/mas/pytest.ini tests/mas` or project script)  

---

### Need help?

1. See [Troubleshooting](troubleshooting.md) and logs: `docker compose logs <service>`.  
2. Confirm `src/infra/.env` matches **`src/infra/.env.example`**.  
3. Open an issue or ask your team channel.  

---

## 12-Factor Configuration Management

Horus uses a 12-factor app methodology for configuration management, with environment-specific settings managed through `.env` files and validated schemas.

### Overview

Configuration is managed through:

1. **Environment Variables**: Primary configuration source
2. **`.env` Files**: Local development defaults (never committed)
3. **`.env.example` Files**: Template for required variables (committed)
4. **Validation Schemas**: Runtime validation using Pydantic (Python) and Zod (TypeScript)
5. **Secrets Management**: Sensitive values via Docker Secrets or external vaults

### Services configuration

The committed template for local and Compose deployments is **`src/infra/.env.example`** (repository root). Individual services under `src/services/` may read the same variables when run in Docker (see `src/infra/docker-compose.yml` `environment` blocks). There are no separate `src/services/*/.env.example` files in this repository.

#### 1. MAS (Multi-Agent System)

**Variables** (see `src/infra/.env.example` and Compose):

- Database: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DB_PORT`, `DB_HOST`
- Authentication: `JWT_SECRET_KEY`, `JWT_ALGORITHM`
- Message queue: `RABBITMQ_HOST`, `RABBITMQ_PORT`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`
- Cache: `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
- Application: `TASK_TIMEOUT` (or `TASK_TIMEOUT_SECONDS`, seconds; default 1800 for long LLM runs), `LLM_AUTOINIT`, `LLM_FORCE_CPU` (default in Compose is GPU when available), optional `LLM_GPU_MEMORY_CAP` / `LLM_CPU_OFFLOAD_CAP`, `LLM_TORCH_INTRAOP_THREADS`, `SUPER_USER_USERNAME`, `SUPER_USER_PASSWORD`
- **GPU+CPU hybrid (Transformers / Accelerate):** Setting `LLM_GPU_MEMORY_CAP` (and optionally `LLM_CPU_OFFLOAD_CAP`) makes the orchestrator put **some layers on GPU and the rest in CPU RAM** — useful when VRAM is smaller than the model, but **usually slower** than keeping the whole 4-bit model on GPU (CPU layers dominate latency). Same idea for the agent with `AGENT_GPU_MEMORY_CAP` / `AGENT_CPU_OFFLOAD_CAP`. This differs from **llama.cpp + GGUF** (`n_gpu_layers`), which is a separate inference stack (see project notes such as `share_cpu_gpu.md`).
- OpenTelemetry (Compose): `OTEL_ENABLED`, `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT` (this repo targets **Tempo** at `http://tempo:4317`, not Jaeger)

**Validation**: **`src/services/mas/core/config.py`** using Pydantic settings.

#### 2. Agent service

**Variables** (see Compose `agent` service and **`src/services/agent/app/config/settings.py`**):

- MAS: `ORCHESTRATOR_URL` (e.g. `http://mas:8000` in Docker), optional `ORCHESTRATOR_TOKEN` or `ORCHESTRATOR_USERNAME` / `ORCHESTRATOR_PASSWORD` for token acquisition
- Knowledge Store: `KNOWLEDGE_STORE_URL`, `KNOWLEDGE_STORE_TIMEOUT`, `KNOWLEDGE_STORE_MAX_RETRIES`, `KNOWLEDGE_STORE_RETRY_DELAY`
- RabbitMQ: `RABBITMQ_HOST`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`
- Model: `MODEL_NAME` (default Qwen3 4B instruct), `MODEL_DEVICE`, optional `AGENT_GPU_MEMORY_CAP`, `AGENT_CPU_OFFLOAD_CAP`, `AGENT_TORCH_INTRAOP_THREADS`, `AGENT_FORCE_CPU`, `AGENT_MAX_NEW_TOKENS`, `AGENT_LAZY_DECISION_MODEL` (default `0` in Compose: load at startup), `AGENT_TYPE`
- Delegation: `DELEGATION_TIMEOUT`, `MAX_DELEGATION_DEPTH`

**Validation**: Environment is read in `settings.py` (no Pydantic `BaseSettings` class today).

#### 3. Knowledge Store

Configured mainly via Compose and code defaults (Chroma persistence volumes, telemetry-disabled env vars). There is no separate `config.py` with Pydantic in this tree; see the service Dockerfile and `docker-compose.yml` for injected variables.

#### 4. Web client

**Location**: **`src/services/web-client/utils/config.ts`** and **`src/services/web-client/.env.local.example`**.

**Variables** (all optional at build time; defaults are in `config.ts`):

- `NEXT_PUBLIC_API_URL` — MAS base URL (default `http://localhost:8000`)
- `NEXT_PUBLIC_KNOWLEDGE_STORE_URL` — Knowledge Store base URL (default `http://localhost:8080`)
- `NEXT_PUBLIC_WS_URL` — WebSocket origin for chat (default `ws://localhost:8000`; path is appended by the app)

Optional Zod (or similar) validation at startup is not implemented in the repo; you can add it if you want strict parsing of `process.env`.

### Infrastructure Configuration

**Location**: `src/infra/.env.example`

Centralized configuration for all services used in Docker Compose:

- RabbitMQ
- PostgreSQL
- Redis
- PgAdmin
- All service-specific variables

#### Docker Compose Setup

All services are externalized using environment variables in `docker-compose.yml`:

```yaml
## Example from docker-compose.yml
rabbitmq:
  environment:
    - RABBITMQ_DEFAULT_USER=${RABBITMQ_USER}
    - RABBITMQ_DEFAULT_PASS=${RABBITMQ_PASSWORD}

postgres:
  environment:
    POSTGRES_DB: ${POSTGRES_DB}
    POSTGRES_USER: ${POSTGRES_USER}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}

redis:
  command: ["redis-server", "/usr/local/etc/redis/redis.conf", "--requirepass", "${REDIS_PASSWORD}"]
```

#### Quick Start with Docker Compose

```bash
## Option A — from the repository root: ensure src/infra/.env (if missing), build, start stack
chmod +x stack-up.sh && ./stack-up.sh -d
## Foreground logs instead: ./stack-up.sh

## Option B — manual steps (from src/infra)
cd src/infra
bash init-env.sh   # skips if .env already exists
## (Alternative: cp .env.example .env && set JWT_SECRET_KEY manually, e.g. openssl rand -hex 32)
nano .env          # optional: tune values for local/production
docker compose up --build -d

## Services are now available (host ports from docker-compose.yml):
## - PostgreSQL: localhost:${DB_PORT:-5432}
## - Redis: localhost:${REDIS_PORT:-6379}
## - RabbitMQ: AMQP localhost:${RABBITMQ_PORT:-5672}, UI http://localhost:15672
## - PgAdmin: http://localhost:5433
## - RedisInsight: http://localhost:5540
## - Web client: http://localhost:3000 (observability lives here: /admin/logs, /admin/metrics, /admin/traces — admin role required)
## - Prometheus, Loki, Tempo: no host ports by default (internal-only backends); view logs/metrics/traces from the admin pages above or add a port mapping (see docs/operations.md)
```

#### Verify configuration is loaded

```bash
cd src/infra
docker compose config | grep -A 20 "environment:"

docker compose exec postgres env | grep POSTGRES

docker compose exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT version();"
```

### Configuration matrix: dev / staging / prod

#### Development Environment

```env
## .env.development
DEBUG=true
LOG_LEVEL=DEBUG
JWT_ALGORITHM=HS256
POSTGRES_PASSWORD=dev_password
REDIS_PASSWORD=dev_password
RABBITMQ_PASSWORD=guest
LLM_AUTOINIT=0
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_KNOWLEDGE_STORE_URL=http://localhost:8080
NEXT_PUBLIC_WS_URL=ws://localhost:8000
NODE_ENV=development
```

**Use Case**: Local development, debugging enabled, permissive CORS, test databases

#### Staging Environment

```env
## .env.staging
DEBUG=false
LOG_LEVEL=INFO
JWT_ALGORITHM=HS256
POSTGRES_PASSWORD=${STAGING_DB_PASSWORD}  # From vault
REDIS_PASSWORD=${STAGING_REDIS_PASSWORD}  # From vault
RABBITMQ_PASSWORD=${STAGING_RABBITMQ_PASSWORD}  # From vault
LLM_AUTOINIT=1
NEXT_PUBLIC_API_URL=https://staging-api.horus.example.com
NEXT_PUBLIC_KNOWLEDGE_STORE_URL=https://staging-knowledge.horus.example.com
NEXT_PUBLIC_WS_URL=wss://staging-api.horus.example.com
NODE_ENV=production
```

**Use Case**: Pre-production testing, realistic configuration, secret rotation enabled

#### Production Environment

```env
## .env.production (Never committed - use vault)
DEBUG=false
LOG_LEVEL=WARN
JWT_ALGORITHM=HS256
POSTGRES_PASSWORD=${PROD_DB_PASSWORD}  # From vault
REDIS_PASSWORD=${PROD_REDIS_PASSWORD}  # From vault
RABBITMQ_PASSWORD=${PROD_RABBITMQ_PASSWORD}  # From vault
LLM_AUTOINIT=1
NEXT_PUBLIC_API_URL=https://api.horus.example.com
NEXT_PUBLIC_KNOWLEDGE_STORE_URL=https://knowledge.horus.example.com
NEXT_PUBLIC_WS_URL=wss://api.horus.example.com
NODE_ENV=production
TLS_ENABLED=true
```

**Use Case**: Production deployment, minimal logging, all secrets from vault

### Secrets Management

#### Docker Secrets (Recommended for Docker Swarm)

```bash
## Create secrets
echo "postgres_password_123" | docker secret create db_password -
echo "jwt_secret_key_xyz" | docker secret create jwt_secret -

## Reference in docker-compose.yml
services:
  mas:
    secrets:
      - db_password
      - jwt_secret
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
      JWT_SECRET_KEY_FILE: /run/secrets/jwt_secret
```

#### External Vault (Recommended for Kubernetes)

##### HashiCorp Vault

```bash
## Store secret
vault kv put secret/horus/prod \
  postgres_password="secure_password" \
  jwt_secret="secure_jwt_key" \
  rabbitmq_password="secure_rmq_pwd"

## Retrieve secrets in application startup
vault kv get -field=postgres_password secret/horus/prod
```

##### Environment Variables from CI/CD

```yaml
## GitHub Actions / GitLab CI
env:
  POSTGRES_PASSWORD: ${{ secrets.POSTGRES_PASSWORD }}
  JWT_SECRET_KEY: ${{ secrets.JWT_SECRET_KEY }}
  REDIS_PASSWORD: ${{ secrets.REDIS_PASSWORD }}
```

#### Best Practices

1. **Never commit `.env` or production secrets to version control**
   ```bash
   # .gitignore
   .env
   .env.local
   .env.production
   !.env.example
   ```

2. **Use `.env.example` as a template**
   ```bash
   cp .env.example .env
   # Then fill in your local values
   ```

3. **Rotate secrets regularly**
   - Database passwords every 90 days
   - JWT keys when compromised
   - API keys at least annually

4. **Separate secrets by environment**
   - Development: Less restrictive, can be simple
   - Staging: Match production closely
   - Production: Highly restricted, vault-managed

5. **Log sensitive data carefully**
   ```python
   # Bad
   logger.info(f"Connecting to {password}@{host}")
   
   # Good
   logger.info(f"Connecting to {host} as {username}")
   ```

### Configuration Validation

#### Python Services (MAS, Agent, Knowledge Store)

**Startup Validation**:

```python
## src/services/mas/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    # ... other required fields
    
    class Config:
        env_file = ".env"

## This will raise ValidationError if required vars are missing
settings = Settings()
```

**Error Handling**:

```
Traceback:
  pydantic_core._pydantic_core.ValidationError: 1 validation error
  POSTGRES_PASSWORD
    Field required [type=missing, input_value={...}, input_type=dict]
```

#### TypeScript/Next.js Web Client

**Startup Validation**:

```typescript
// Example only — not present in repo. Real defaults: src/services/web-client/utils/config.ts
import { z } from 'zod';

const envSchema = z.object({
  NEXT_PUBLIC_API_URL: z.string().url(),
  NEXT_PUBLIC_KNOWLEDGE_STORE_URL: z.string().url(),
  NEXT_PUBLIC_WS_URL: z.string().url(),
});

export const config = envSchema.parse(process.env);
```

### Deployment Checklist

- [ ] All required environment variables defined in `.env.example`
- [ ] Validation schemas created and tested
- [ ] Secrets stored in secure vault (not in `.env`)
- [ ] Configuration reviewed for environment (dev/staging/prod)
- [ ] Database migrations run with correct credentials
- [ ] Service health checks passing with current config
- [ ] Logs showing correct values (without secrets)
- [ ] Backup of encryption keys stored separately

### References

- [12 Factor App - Config](https://12factor.net/config)
- [Pydantic Settings Documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [Docker Secrets](https://docs.docker.com/engine/swarm/secrets/)
- [HashiCorp Vault](https://www.vaultproject.io/)

---

## Troubleshooting Guide

Common issues and their solutions for the Horus Multi-Agent System.

---

### Quick Diagnostics

#### Check System Health

```bash
## All services status
docker ps

## MAS health
curl http://localhost:8000/rabbitmq/heartbeat

## Knowledge Store health
curl http://localhost:8080/health

## Agent status
curl http://localhost:8000/agents/ -H "Authorization: Bearer <token>"
```

#### View Logs

```bash
## All service logs
cd src/infra && docker compose logs -f

## Specific service
docker logs mas --tail 100
docker logs agent --tail 100
docker logs knowledge_store --tail 100
docker logs postgres --tail 100
docker logs rabbitmq --tail 100
```

---

### Common Issues

#### 1. Services Won't Start

**Symptoms:**
- `docker compose up` fails
- Services exit immediately

**Solutions:**

```bash
## Check port conflicts
lsof -i :8000
lsof -i :3000
lsof -i :8080

## Free up ports
kill -9 <PID>

## Rebuild containers
docker compose build --no-cache
docker compose up -d
```

**Check for Docker issues:**
```bash
## Restart Docker Desktop
## Or on Linux:
sudo systemctl restart docker
```

---

#### 2. MAS Not Responding

**Symptoms:**
- http://localhost:8000/docs not loading
- Connection refused errors

**Solutions:**

```bash
## Check if MAS is running
docker ps | grep mas

## Check MAS logs for errors
docker logs mas --tail 100

## Restart MAS
docker restart mas

## If database connection issues:
docker restart postgres
sleep 10
docker restart mas
```

**Common causes:**
- PostgreSQL not ready
- RabbitMQ not ready
- Missing environment variables

---

#### Chat or `/tasks/new_task` is very slow (browser “pending”)

**Expected with embedded images:** `docker compose build` should download **Qwen3 4B** into the **mas** and **agent** images (`DOWNLOAD_LLM=1` in `.env`). At runtime, Compose sets **`HF_HUB_OFFLINE=1`** so the stack does not call Hugging Face again. The first chat may still wait while **RAM load** and **CPU/GPU inference** run (much shorter than a full network download). Use `docker compose logs -f mas` to see preload / `ask_llm`.

**If you still see Hugging Face URLs in logs at runtime:** Rebuild with a network: `docker compose build --no-cache mas agent`, and ensure `.env` has not set `HF_HUB_OFFLINE=0` unless you intend to allow Hub access.

**Agent dev bind-mount:** Compose mounts `../services/agent/app` over `/app`. The image stores weights under `/opt/llm-bundle`; **`entrypoint.sh` copies them into `app/models/Qwen3_instruct_4B` once** if that folder is missing (so baked weights survive the mount).

**What we changed:** With `LLM_AUTOINIT=1`, MAS starts a **background preload** after RabbitMQ connects so the HTTP server stays responsive. The `mas` healthcheck allows a longer timeout during heavy load.

**Optional:** Add `HF_TOKEN` at **build** time for higher rate limits when downloading during `docker compose build`. Default Compose assigns GPUs to `mas`, `agent`, and `knowledge_store` when the NVIDIA toolkit is present; keep `LLM_FORCE_CPU=0` for orchestrator CUDA.

#### Chat spinner never stops (task cancelled in MAS logs)

**Cause:** Background **TASK_TIMEOUT** cancels RUNNING tasks after a wall-clock limit. Values like **`TASK_TIMEOUT=120`** (2 minutes) are often too short for Qwen/agent work, so MAS interrupts the task. The UI only clears the spinner when it receives a WebSocket assistant message; timeout did not send one before.

**Fix:** Set **`TASK_TIMEOUT=1800`** (30 minutes) or higher in `src/infra/.env` (Compose passes it into `mas`). Ensure you are not using a stale `TASK_TIMEOUT_SECONDS` without `TASK_TIMEOUT` unless your MAS build reads both (current code accepts `TASK_TIMEOUT` and `TASK_TIMEOUT_SECONDS`). After a timeout, MAS should push an explanatory line over the chat WebSocket.

---

#### 3. Authentication Failures

**Symptoms:**
- 401 Unauthorized responses
- "Invalid credentials" errors

**Solutions:**

```bash
## Get a new token
curl -X POST http://localhost:8000/auth/token \
  -d "username=admin&password=admin"

## Check if user exists (in database)
docker exec -it postgres psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-mas_db}" -c "SELECT * FROM users;"
```

**If admin user doesn't exist:**
```bash
## Restart MAS to trigger init_db
docker restart mas
```

---

#### 4. No Agents Available

**Symptoms:**
- `GET /agents/` returns empty list
- Tasks fail with "No agent registered"

**Solutions:**

```bash
## Check agent logs
docker logs agent --tail 50

## Check if agent is running
docker ps | grep agent

## Restart agent
docker restart agent

## Wait for registration (30 seconds)
sleep 30

## Verify
curl http://localhost:8000/agents/ -H "Authorization: Bearer <token>"
```

**Common causes:**
- Agent can't reach MAS (network issue)
- MAS not ready when agent started
- Authentication failure during registration

---

#### 5. Knowledge Store Queries Return Empty

**Symptoms:**
- Queries return no results
- RAG pipeline returns generic responses

**Solutions:**

```bash
## Check Knowledge Store health
curl http://localhost:8080/health

## Check if documents exist
curl -X POST http://localhost:8080/store/query \
  -H "Content-Type: application/json" \
  -d '{"query": "revenue", "k": 5}'

## Re-seed demo data
python scripts/demo/seed-data.py

## Check Knowledge Store logs
docker logs knowledge_store --tail 50
```

---

#### 6. Database Connection Issues

**Symptoms:**
- "Connection refused" to PostgreSQL
- Database errors in logs

**Solutions:**

```bash
## Check PostgreSQL status
docker ps | grep postgres
docker logs postgres --tail 50

## Test connection
docker exec -it postgres pg_isready -U "${POSTGRES_USER:-postgres}"

## Restart PostgreSQL
docker restart postgres
sleep 10
docker restart mas
```

**If database is corrupted:**
```bash
## WARNING: This deletes all data!
docker compose down -v
docker compose up -d
python scripts/demo/seed-data.py
```

---

#### 7. RabbitMQ Issues

**Symptoms:**
- Tasks not being processed
- "Connection refused" to RabbitMQ
- Queue errors in logs

**Solutions:**

```bash
## Check RabbitMQ status
docker ps | grep rabbitmq
docker logs rabbitmq --tail 50

## Access RabbitMQ management
## http://localhost:15672 (guest/guest)

## Restart RabbitMQ
docker restart rabbitmq
sleep 30
docker restart mas
docker restart agent
```

---

#### 8. WebSocket Connection Issues

**Symptoms:**
- Chat messages not updating in real-time
- WebSocket connection errors in browser console

**Solutions:**

1. **Check browser console** for WebSocket errors
2. **Verify MAS is running** and accessible
3. **Check CORS configuration** in browser network tab
4. **Try a different browser** (WebSocket support varies)

```bash
## Test WebSocket endpoint
wscat -c ws://localhost:8000/chat/ws/{conversation_id}?token={jwt_token}
```

---

#### 9. Slow Response Times

**Symptoms:**
- API calls taking > 5 seconds
- Timeouts

**Solutions:**

```bash
## Check resource usage
docker stats

## Check for slow queries in MAS logs
docker logs mas | grep "Slow Query"

## Increase container resources in docker-compose.yml
## deploy:
##   resources:
##     limits:
##       memory: 4G
```

**For GPU acceleration:**
```bash
## Check if GPU is being used
docker logs agent | grep "GPU\|CUDA\|device"
docker logs mas | grep "GPU\|CUDA\|device"

## Default compose already sets gpus: all for four services: mas, agent, vllm, and knowledge_store.
## Install the NVIDIA Container Toolkit; if you have no GPU, comment out those gpus: lines in docker-compose.yml.
cd src/infra && docker compose up -d
```

---

#### 10. Memory Issues

**Symptoms:**
- Containers being killed (OOM)
- System becoming unresponsive

**Solutions:**

```bash
## Check memory usage
docker stats

## Increase Docker memory limit
## Docker Desktop → Settings → Resources → Memory

## Reduce model size / VRAM
## Lower AGENT_MAX_NEW_TOKENS, set MODEL_DEVICE=cpu or AGENT_FORCE_CPU=1, or use a smaller hub model via MODEL_NAME.
```

---

### Reset Procedures

#### Soft Reset (Keep Data)

```bash
docker compose restart
```

#### Hard Reset (Clear Data)

```bash
cd src/infra
docker compose down -v
docker compose up -d

## Re-seed
python scripts/demo/seed-data.py
```

#### Complete Reset (Rebuild)

```bash
cd src/infra
docker compose down -v --rmi all
docker compose build --no-cache
docker compose up -d
```

---

### Getting Help

#### Collect Debug Information

```bash
## Create debug bundle
mkdir debug_bundle
docker ps > debug_bundle/services.txt
docker compose logs > debug_bundle/logs.txt
docker stats --no-stream > debug_bundle/stats.txt

## Check specific service
docker inspect mas > debug_bundle/mas_inspect.json
```

#### Log Locations

| Service | Log Location |
|---------|--------------|
| MAS | `docker logs mas` or `/app/logs/` in container |
| Agent | `docker logs agent` |
| Knowledge Store | `docker logs knowledge_store` |
| PostgreSQL | `docker logs postgres` |
| RabbitMQ | `docker logs rabbitmq` |

#### Environment Variables

Verify `.env` file in `src/infra/`:
```bash
cat src/infra/.env
```

Required variables:
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `RABBITMQ_USER`, `RABBITMQ_PASSWORD`
- `JWT_SECRET_KEY`
- `SUPER_USER_USERNAME`, `SUPER_USER_PASSWORD`

---

### Performance Tuning

#### Database

```sql
-- Check slow queries (if pg_stat_statements enabled)
SELECT query, mean_time, calls 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;
```

#### Connection Pools

In MAS `database.py`:
```python
engine = create_engine(
    URL_DATABASE,
    pool_size=20,      # Increase for higher load
    max_overflow=30,
    pool_timeout=30,
    pool_recycle=1800,
)
```

#### Model Inference

For faster inference:
- Use GPU acceleration
- Use quantized models
- Adjust batch sizes
