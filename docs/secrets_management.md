# Secrets Management Guide

This guide provides best practices for managing sensitive credentials and secrets across the Horus multi-agent system in different environments.

## Overview

Secrets include:
- Database passwords
- API keys
- JWT secret keys
- Encryption keys
- External service credentials
- OAuth tokens

**Golden Rule**: Never commit secrets to version control. Use `.env.example` as a template only.

## Local Development Setup

### Step 1: Create Local `.env` Files

```bash
# Copy templates for each service
cp src/infra/.env.example src/infra/.env
cp src/services/mas/.env.example src/services/mas/.env
cp src/services/agent/.env.example src/services/agent/.env
cp src/services/knowledge-store/.env.example src/services/knowledge-store/.env
cp src/services/web-client/.env.example src/services/web-client/.env.local
```

### Step 2: Fill in Development Values

**`src/infra/.env`** (Infrastructure secrets):

```env
# Use weak passwords for local development
POSTGRES_PASSWORD=devpassword123
REDIS_PASSWORD=devpassword123
RABBITMQ_PASSWORD=devpassword123

# Use a simple JWT secret for local development
JWT_SECRET_KEY=dev-secret-key-change-in-production

# Admin credentials for testing
SUPER_USER_USERNAME=admin
SUPER_USER_PASSWORD=admin

PGADMIN_DEFAULT_PASSWORD=admin
```

### Step 3: Git Configuration

Ensure `.env` files are ignored:

```bash
# .gitignore
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
# Should NOT show .env files
```

## Staging Environment

### Using Environment Variables

For staging deployments, use environment-specific `.env` files:

**`.env.staging`** (Not committed):

```env
# Staging database - dedicated staging database
POSTGRES_USER=staging_user
POSTGRES_PASSWORD=${STAGING_DB_PASSWORD}  # From CI/CD secrets
POSTGRES_DB=horus_staging

# Staging Redis with password
REDIS_PASSWORD=${STAGING_REDIS_PASSWORD}  # From CI/CD secrets
REDIS_HOST=staging-redis.internal

# RabbitMQ staging instance
RABBITMQ_PASSWORD=${STAGING_RABBITMQ_PASSWORD}  # From CI/CD secrets
RABBITMQ_HOST=staging-rabbitmq.internal

# JWT secret for staging
JWT_SECRET_KEY=${STAGING_JWT_SECRET}  # From CI/CD secrets

# LLM enabled in staging
LLM_AUTOINIT=1
```

### CI/CD Integration (GitHub Actions)

Store secrets in GitHub repository settings and reference in workflows:

```yaml
# .github/workflows/deploy-staging.yml
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

## Production Environment

### Using Docker Secrets

For Docker Swarm deployments, use Docker Secrets:

```bash
# 1. Create secrets from files
docker secret create db_password <(echo "production_db_password_xyz")
docker secret create jwt_secret <(echo "production_jwt_secret_abc")
docker secret create redis_password <(echo "production_redis_password_def")
docker secret create rabbitmq_password <(echo "production_rabbitmq_password_ghi")

# 2. List created secrets
docker secret ls
```

Update `docker-compose.yml` for production:

```yaml
# src/infra/docker-compose.production.yml
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

### Using HashiCorp Vault

For Kubernetes or advanced scenarios, use Vault:

```bash
# 1. Authenticate to Vault
vault login -method=kubernetes role=horus-app

# 2. Store secrets
vault kv put secret/horus/production \
  POSTGRES_PASSWORD="$(openssl rand -base64 32)" \
  JWT_SECRET_KEY="$(openssl rand -base64 64)" \
  REDIS_PASSWORD="$(openssl rand -base64 32)" \
  RABBITMQ_PASSWORD="$(openssl rand -base64 32)"

# 3. Retrieve secrets
vault kv get secret/horus/production
```

**Kubernetes Integration**:

```yaml
# k8s-secret-sync.yml
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

## Secret Rotation

### Password Rotation Schedule

- **Development**: Not required
- **Staging**: Monthly
- **Production**: Every 90 days

### Automated Rotation Script

```bash
#!/bin/bash
# scripts/rotate-secrets.sh

set -e

ENVIRONMENT=$1  # staging or production
VAULT_ADDR=${VAULT_ADDR:-https://vault.internal}

if [ -z "$ENVIRONMENT" ]; then
  echo "Usage: ./rotate-secrets.sh [staging|production]"
  exit 1
fi

echo "🔄 Rotating secrets for $ENVIRONMENT..."

# Generate new secrets
NEW_DB_PASSWORD=$(openssl rand -base64 32)
NEW_JWT_SECRET=$(openssl rand -base64 64)
NEW_REDIS_PASSWORD=$(openssl rand -base64 32)
NEW_RABBITMQ_PASSWORD=$(openssl rand -base64 32)

# Store in Vault
vault kv put "${VAULT_ADDR}/secret/horus/${ENVIRONMENT}" \
  POSTGRES_PASSWORD="$NEW_DB_PASSWORD" \
  JWT_SECRET_KEY="$NEW_JWT_SECRET" \
  REDIS_PASSWORD="$NEW_REDIS_PASSWORD" \
  RABBITMQ_PASSWORD="$NEW_RABBITMQ_PASSWORD"

echo "✅ Secrets rotated successfully"
echo "📝 Update deployment configurations with new secrets"

# For Docker Swarm
docker secret rm db_password || true
docker secret rm jwt_secret || true
docker secret rm redis_password || true
docker secret rm rabbitmq_password || true

docker secret create db_password <(echo "$NEW_DB_PASSWORD")
docker secret create jwt_secret <(echo "$NEW_JWT_SECRET")
docker secret create redis_password <(echo "$NEW_REDIS_PASSWORD")
docker secret create rabbitmq_password <(echo "$NEW_RABBITMQ_PASSWORD")

# Restart services
docker service update --force horus_mas
docker service update --force horus_agent
docker service update --force horus_knowledge_store

echo "🚀 Services restarted with new secrets"
```

## Secret Backup & Recovery

### Backup Secrets

```bash
#!/bin/bash
# scripts/backup-secrets.sh

ENVIRONMENT=$1
BACKUP_DIR="./backups/secrets/$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"

# Backup from Vault
vault kv get -format=json "secret/horus/${ENVIRONMENT}" | \
  jq '.data.data' > "$BACKUP_DIR/${ENVIRONMENT}-secrets.json"

# Encrypt backup
openssl enc -aes-256-cbc -salt -in "$BACKUP_DIR/${ENVIRONMENT}-secrets.json" \
  -out "$BACKUP_DIR/${ENVIRONMENT}-secrets.json.enc" \
  -k "$(cat ~/.secret-backup-key)" && \
  rm "$BACKUP_DIR/${ENVIRONMENT}-secrets.json"

echo "✅ Secrets backed up to $BACKUP_DIR"
```

### Restore Secrets

```bash
#!/bin/bash
# scripts/restore-secrets.sh

ENVIRONMENT=$1
BACKUP_FILE=$2

if [ -z "$BACKUP_FILE" ]; then
  echo "Usage: ./restore-secrets.sh [staging|production] <backup-file>"
  exit 1
fi

# Decrypt backup
openssl enc -d -aes-256-cbc -in "$BACKUP_FILE" \
  -k "$(cat ~/.secret-backup-key)" | \
  vault kv put "secret/horus/${ENVIRONMENT}" @-

echo "✅ Secrets restored from $BACKUP_FILE"
```

## Security Audit Checklist

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

## References

- [OWASP: Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [12 Factor App: Config](https://12factor.net/config)
- [Docker Secrets](https://docs.docker.com/engine/swarm/secrets/)
- [HashiCorp Vault](https://www.vaultproject.io/)
- [GitHub: Secret Scanning](https://github.com/features/secret-scanning)
