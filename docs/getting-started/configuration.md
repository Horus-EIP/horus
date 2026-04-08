# 12-Factor Configuration Management

Horus uses a 12-factor app methodology for configuration management, with environment-specific settings managed through `.env` files and validated schemas.

## Overview

Configuration is managed through:

1. **Environment Variables**: Primary configuration source
2. **`.env` Files**: Local development defaults (never committed)
3. **`.env.example` Files**: Template for required variables (committed)
4. **Validation Schemas**: Runtime validation using Pydantic (Python) and Zod (TypeScript)
5. **Secrets Management**: Sensitive values via Docker Secrets or external vaults

## Services configuration

The committed template for local and Compose deployments is **`src/infra/.env.example`** (repository root). Individual services under `src/services/` may read the same variables when run in Docker (see `src/infra/docker-compose.yml` `environment` blocks). There are no separate `src/services/*/.env.example` files in this repository.

### 1. MAS (Multi-Agent System)

**Variables** (see `src/infra/.env.example` and Compose):

- Database: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DB_PORT`, `DB_HOST`
- Authentication: `JWT_SECRET_KEY`, `JWT_ALGORITHM`
- Message queue: `RABBITMQ_HOST`, `RABBITMQ_PORT`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`
- Cache: `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
- Application: `LLM_AUTOINIT`, `LLM_BACKEND`, `SUPER_USER_USERNAME`, `SUPER_USER_PASSWORD`
- OpenTelemetry (Compose): `OTEL_ENABLED`, `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`

**Validation**: **`src/services/mas/core/config.py`** using Pydantic settings.

### 2. Agent service

**Variables** (see Compose `agent` service and **`src/services/agent/app/config/settings.py`**):

- MAS: `ORCHESTRATOR_URL` (e.g. `http://mas:8000` in Docker), optional `ORCHESTRATOR_TOKEN` or `ORCHESTRATOR_USERNAME` / `ORCHESTRATOR_PASSWORD` for token acquisition
- Knowledge Store: `KNOWLEDGE_STORE_URL`, `KNOWLEDGE_STORE_TIMEOUT`, `KNOWLEDGE_STORE_MAX_RETRIES`, `KNOWLEDGE_STORE_RETRY_DELAY`
- RabbitMQ: `RABBITMQ_HOST`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`
- Model: `MODEL_NAME`, `MODEL_DEVICE`, `AGENT_TYPE`
- Delegation: `DELEGATION_TIMEOUT`, `MAX_DELEGATION_DEPTH`

**Validation**: Environment is read in `settings.py` (no Pydantic `BaseSettings` class today).

### 3. Knowledge Store

Configured mainly via Compose and code defaults (Chroma persistence volumes, telemetry-disabled env vars). There is no separate `config.py` with Pydantic in this tree; see the service Dockerfile and `docker-compose.yml` for injected variables.

### 4. Web client

**Location**: **`src/services/web-client/utils/config.ts`** and **`src/services/web-client/.env.local.example`**.

**Variables** (all optional at build time; defaults are in `config.ts`):

- `NEXT_PUBLIC_API_URL` — MAS base URL (default `http://localhost:8000`)
- `NEXT_PUBLIC_KNOWLEDGE_STORE_URL` — Knowledge Store base URL (default `http://localhost:8080`)
- `NEXT_PUBLIC_WS_URL` — WebSocket origin for chat (default `ws://localhost:8000`; path is appended by the app)

Optional Zod (or similar) validation at startup is not implemented in the repo; you can add it if you want strict parsing of `process.env`.

## Infrastructure Configuration

**Location**: `src/infra/.env.example`

Centralized configuration for all services used in Docker Compose:

- RabbitMQ
- PostgreSQL
- Redis
- PgAdmin
- All service-specific variables

### Docker Compose Setup

All services are externalized using environment variables in `docker-compose.yml`:

```yaml
# Example from docker-compose.yml
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

### Quick Start with Docker Compose

```bash
# Option A — from the repository root: ensure src/infra/.env (if missing), build, start stack
chmod +x stack-up.sh && ./stack-up.sh -d
# Foreground logs instead: ./stack-up.sh

# Option B — manual steps (from src/infra)
cd src/infra
bash init-env.sh   # skips if .env already exists
# (Alternative: cp .env.example .env && set JWT_SECRET_KEY manually, e.g. openssl rand -hex 32)
nano .env          # optional: tune values for local/production
docker compose up --build -d

# Services are now available (host ports from docker-compose.yml):
# - PostgreSQL: localhost:${DB_PORT:-5432}
# - Redis: localhost:${REDIS_PORT:-6379}
# - RabbitMQ: AMQP localhost:${RABBITMQ_PORT:-5672}, UI http://localhost:15672
# - PgAdmin: http://localhost:5433
# - Grafana (metrics + traces UI): http://localhost:3301
# - RedisInsight: http://localhost:5540
# - Prometheus: no host port by default; use Grafana’s Prometheus datasource or add a port mapping (see docs/operations/monitoring.md)
```

### Verify configuration is loaded

```bash
cd src/infra
docker compose config | grep -A 20 "environment:"

docker compose exec postgres env | grep POSTGRES

docker compose exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT version();"
```

## Configuration matrix: dev / staging / prod

### Development Environment

```env
# .env.development
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

### Staging Environment

```env
# .env.staging
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

### Production Environment

```env
# .env.production (Never committed - use vault)
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

## Secrets Management

### Docker Secrets (Recommended for Docker Swarm)

```bash
# Create secrets
echo "postgres_password_123" | docker secret create db_password -
echo "jwt_secret_key_xyz" | docker secret create jwt_secret -

# Reference in docker-compose.yml
services:
  mas:
    secrets:
      - db_password
      - jwt_secret
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
      JWT_SECRET_KEY_FILE: /run/secrets/jwt_secret
```

### External Vault (Recommended for Kubernetes)

#### HashiCorp Vault

```bash
# Store secret
vault kv put secret/horus/prod \
  postgres_password="secure_password" \
  jwt_secret="secure_jwt_key" \
  rabbitmq_password="secure_rmq_pwd"

# Retrieve secrets in application startup
vault kv get -field=postgres_password secret/horus/prod
```

#### Environment Variables from CI/CD

```yaml
# GitHub Actions / GitLab CI
env:
  POSTGRES_PASSWORD: ${{ secrets.POSTGRES_PASSWORD }}
  JWT_SECRET_KEY: ${{ secrets.JWT_SECRET_KEY }}
  REDIS_PASSWORD: ${{ secrets.REDIS_PASSWORD }}
```

### Best Practices

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

## Configuration Validation

### Python Services (MAS, Agent, Knowledge Store)

**Startup Validation**:

```python
# src/services/mas/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    # ... other required fields
    
    class Config:
        env_file = ".env"

# This will raise ValidationError if required vars are missing
settings = Settings()
```

**Error Handling**:

```
Traceback:
  pydantic_core._pydantic_core.ValidationError: 1 validation error
  POSTGRES_PASSWORD
    Field required [type=missing, input_value={...}, input_type=dict]
```

### TypeScript/Next.js Web Client

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

## Deployment Checklist

- [ ] All required environment variables defined in `.env.example`
- [ ] Validation schemas created and tested
- [ ] Secrets stored in secure vault (not in `.env`)
- [ ] Configuration reviewed for environment (dev/staging/prod)
- [ ] Database migrations run with correct credentials
- [ ] Service health checks passing with current config
- [ ] Logs showing correct values (without secrets)
- [ ] Backup of encryption keys stored separately

## References

- [12 Factor App - Config](https://12factor.net/config)
- [Pydantic Settings Documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [Docker Secrets](https://docs.docker.com/engine/swarm/secrets/)
- [HashiCorp Vault](https://www.vaultproject.io/)
