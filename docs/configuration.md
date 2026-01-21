# 12-Factor Configuration Management

Horus uses a 12-factor app methodology for configuration management, with environment-specific settings managed through `.env` files and validated schemas.

## Overview

Configuration is managed through:

1. **Environment Variables**: Primary configuration source
2. **`.env` Files**: Local development defaults (never committed)
3. **`.env.example` Files**: Template for required variables (committed)
4. **Validation Schemas**: Runtime validation using Pydantic (Python) and Zod (TypeScript)
5. **Secrets Management**: Sensitive values via Docker Secrets or external vaults

## Services Configuration

### 1. MAS (Multi-Agent System)

**Location**: `src/services/mas/.env.example`

**Key Variables**:
- Database: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DB_PORT`
- Authentication: `JWT_SECRET_KEY`, `JWT_ALGORITHM`
- Message Queue: `RABBITMQ_HOST`, `RABBITMQ_PORT`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`
- Cache: `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
- Application: `LLM_AUTOINIT`, `SUPER_USER_USERNAME`, `SUPER_USER_PASSWORD`

**Validation**: Implemented in `src/services/mas/core/config.py` using **Pydantic BaseSettings**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    POSTGRES_USER: str  # Required
    POSTGRES_PASSWORD: str  # Required
    JWT_SECRET_KEY: str  # Required
    # ... other fields with defaults
```

### 2. Agent Service

**Location**: `src/services/agent/.env.example`

**Key Variables**:
- Server: `SERVER_HOST`, `SERVER_PORT`
- MAS Connection: `MAS_HOST`, `MAS_PORT`, `MAS_PROTOCOL`
- Authentication: `AGENT_ID`, `AGENT_API_KEY`
- Message Queue: `RABBITMQ_*`
- Performance: `HEARTBEAT_INTERVAL`, `TASK_TIMEOUT`, `MAX_CONCURRENT_TASKS`

**Validation**: Add Pydantic validation in `src/services/agent/app/config.py`

### 3. Knowledge Store Service

**Location**: `src/services/knowledge-store/.env.example`

**Key Variables**:
- Server: `SERVER_HOST`, `SERVER_PORT`
- Vector DB: `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_COLLECTION_NAME`
- Embedding Model: `EMBEDDING_MODEL`
- Database: `POSTGRES_*`
- Performance: `MAX_DOCUMENT_SIZE`, `MAX_SEARCH_RESULTS`, `SIMILARITY_THRESHOLD`

**Validation**: Add Pydantic validation in `src/services/knowledge-store/app/config.py`

### 4. Web Client

**Location**: `src/services/web-client/.env.example`

**Key Variables**:
- API: `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_API_TIMEOUT`
- Authentication: `NEXT_PUBLIC_AUTH_ENABLED`, `NEXT_PUBLIC_TOKEN_STORAGE`
- Features: `NEXT_PUBLIC_ENABLE_*` (feature flags)
- WebSocket: `NEXT_PUBLIC_WEBSOCKET_URL`, `NEXT_PUBLIC_WEBSOCKET_RECONNECT_INTERVAL`

**Validation**: Add Zod validation in `src/services/web-client/app/config.ts`

```typescript
import { z } from 'zod';

const envSchema = z.object({
  NEXT_PUBLIC_API_BASE_URL: z.string().url(),
  NEXT_PUBLIC_API_TIMEOUT: z.string().transform(Number),
  // ... other fields
});

export const config = envSchema.parse(process.env);
```

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
  command: [ "redis-server", ..., "--requirepass", "${REDIS_PASSWORD}" ]
```

### Quick Start with Docker Compose

```bash
# 1. Copy the environment template
cp src/infra/.env.example src/infra/.env

# 2. Update with your values (optional for development)
nano src/infra/.env

# 3. Start all services
cd src/infra
docker-compose up --build

# 4. Services are now available:
# - PostgreSQL: localhost:5432
# - Redis: localhost:6379
# - RabbitMQ: localhost:5672 (AMQP), localhost:15672 (Management UI)
# - PgAdmin: http://localhost:5433
# - Prometheus: http://localhost:9090
# - Grafana: http://localhost:3001
# - RedisInsight: http://localhost:5540
```

### Verify Configuration is Loaded

```bash
# Check that environment variables are properly set
docker-compose config | grep -A 20 "environment:"

# View actual values (be careful with secrets!)
docker-compose exec postgres env | grep POSTGRES

# Connect to PostgreSQL to verify
docker-compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "SELECT version();"
```

## Infrastructure Configuration

**Location**: `src/infra/.env.example`

Centralized configuration for all services used in Docker Compose:

- RabbitMQ
- PostgreSQL
- Redis
- PgAdmin
- All service-specific variables

## Configuration Matrix: Dev / Staging / Prod

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
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
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
NEXT_PUBLIC_API_BASE_URL=https://staging-api.horus.example.com
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
NEXT_PUBLIC_API_BASE_URL=https://api.horus.example.com
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
// src/services/web-client/app/config.ts
import { z } from 'zod';

const envSchema = z.object({
  NEXT_PUBLIC_API_BASE_URL: z.string().url(),
  NEXT_PUBLIC_API_TIMEOUT: z.string().transform(Number).positive(),
  NEXT_PUBLIC_AUTH_ENABLED: z.enum(['true', 'false']).transform(v => v === 'true'),
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
