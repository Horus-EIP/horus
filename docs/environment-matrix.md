# Configuration Matrix: Development, Staging, Production

This document outlines environment-specific configuration values for the three main deployment environments.

## Quick Reference Matrix

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

## Development Environment

### Purpose
Local development and rapid iteration. Permissive security, debugging enabled.

### Configuration Values

```env
# src/infra/.env (Development)
# ============================

# Server
DEBUG=true
LOG_LEVEL=DEBUG
NODE_ENV=development

# Database - Local container
POSTGRES_USER=admin
POSTGRES_PASSWORD=devpassword
POSTGRES_DB=horus_dev
DB_HOST=postgres
DB_PORT=5432

# Cache - Local container
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=devredis

# Message Queue - Local container
RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest

# Authentication
JWT_SECRET_KEY=dev-secret-key-change-in-production
JWT_ALGORITHM=HS256

# Initial Admin
SUPER_USER_USERNAME=admin
SUPER_USER_PASSWORD=admin

# Application
LLM_AUTOINIT=0
PgAdmin_PASSWORD=admin

# API Configuration
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_API_TIMEOUT=30000

# WebSocket
NEXT_PUBLIC_WEBSOCKET_URL=ws://localhost:8000/chat
NEXT_PUBLIC_WEBSOCKET_RECONNECT_INTERVAL=3000

# Features - All enabled
NEXT_PUBLIC_ENABLE_CHAT=true
NEXT_PUBLIC_ENABLE_AGENT_MANAGEMENT=true
NEXT_PUBLIC_ENABLE_TASK_MANAGEMENT=true
NEXT_PUBLIC_ENABLE_ANALYTICS=true
```

### Startup Commands

```bash
# Start all services with docker-compose
cd src/infra
docker-compose up --build

# Logs
docker-compose logs -f mas
docker-compose logs -f agent
docker-compose logs -f knowledge-store

# Stop all services
docker-compose down
```

### Database Initialization

```bash
# Create admin user
docker exec -it horus_mas_1 python -m pytest tests/ -k "test_init"

# Reset database
docker exec -it horus_postgres_1 psql -U admin -d horus_dev -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

### Debugging

```bash
# Access container shell
docker exec -it horus_mas_1 /bin/bash

# View logs with timestamps
docker-compose logs --timestamps mas

# Monitor in real-time
docker stats
```

## Staging Environment

### Purpose
Pre-production testing with realistic configuration, secret rotation enabled.

### Infrastructure

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

### Configuration Values

```env
# .env.staging (Not committed)
# =============================

# Server
DEBUG=false
LOG_LEVEL=INFO
NODE_ENV=production

# Database - AWS RDS
POSTGRES_USER=staging_admin
POSTGRES_PASSWORD=${STAGING_DB_PASSWORD}
POSTGRES_DB=horus_staging
DB_HOST=horus-staging-db.c9akciq32.us-east-1.rds.amazonaws.com
DB_PORT=5432

# Cache - AWS ElastiCache
REDIS_HOST=horus-staging-redis.xxxxxx.ng.0001.use1.cache.amazonaws.com
REDIS_PORT=6379
REDIS_PASSWORD=${STAGING_REDIS_PASSWORD}

# Message Queue - AWS MQ
RABBITMQ_HOST=horus-staging-mq.xxxxx.mq.us-east-1.amazonaws.com
RABBITMQ_PORT=5672
RABBITMQ_USER=staging_user
RABBITMQ_PASSWORD=${STAGING_RABBITMQ_PASSWORD}

# Authentication
JWT_SECRET_KEY=${STAGING_JWT_SECRET}
JWT_ALGORITHM=HS256

# Initial Admin
SUPER_USER_USERNAME=staging_admin
SUPER_USER_PASSWORD=${STAGING_ADMIN_PASSWORD}

# Application
LLM_AUTOINIT=1

# API Configuration
NEXT_PUBLIC_API_BASE_URL=https://staging-api.horus.example.com
NEXT_PUBLIC_API_TIMEOUT=30000
NEXT_PUBLIC_AUTH_ENABLED=true

# WebSocket
NEXT_PUBLIC_WEBSOCKET_URL=wss://staging-api.horus.example.com/chat
NEXT_PUBLIC_WEBSOCKET_RECONNECT_INTERVAL=5000

# Features
NEXT_PUBLIC_ENABLE_CHAT=true
NEXT_PUBLIC_ENABLE_AGENT_MANAGEMENT=true
NEXT_PUBLIC_ENABLE_TASK_MANAGEMENT=true
NEXT_PUBLIC_ENABLE_ANALYTICS=true

# TLS/Security
CORS_ORIGINS=https://staging.horus.example.com
TLS_ENABLED=true
TLS_CERT_PATH=/etc/ssl/staging-cert.pem
TLS_KEY_PATH=/etc/ssl/staging-key.pem
```

### Deployment Process

```bash
# GitHub Actions Workflow
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

### Database Migrations

```bash
# Run migrations on staging
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

## Production Environment

### Purpose
Live production system. Minimal logging, high availability, vault-managed secrets, strict security.

### Infrastructure (High Availability)

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

### Configuration Values

```env
# .env.production (Stored in AWS Secrets Manager)
# ================================================

# Server
DEBUG=false
LOG_LEVEL=WARN
NODE_ENV=production

# Database - AWS RDS Multi-AZ
POSTGRES_USER=prod_admin
POSTGRES_PASSWORD=${vault:horus/production/db_password}
POSTGRES_DB=horus_prod
DB_HOST=horus-prod-primary.xxxxxx.us-east-1.rds.amazonaws.com
DB_HOST_READ=horus-prod-read-replica.xxxxxx.us-east-1.rds.amazonaws.com
DB_PORT=5432
DB_SSL=require
DB_POOL_SIZE=30
DB_POOL_MIN=10

# Cache - AWS ElastiCache Cluster Mode
REDIS_HOST=horus-prod-redis.xxxxxx.cache.amazonaws.com
REDIS_PORT=6379
REDIS_PASSWORD=${vault:horus/production/redis_password}
REDIS_CLUSTER_MODE=true
REDIS_SSL=true

# Message Queue - AWS MQ Cluster
RABBITMQ_HOST=b-1-horus-prod-mq.xxxxx.mq.us-east-1.amazonaws.com
RABBITMQ_PORT=5671
RABBITMQ_USER=prod_user
RABBITMQ_PASSWORD=${vault:horus/production/rabbitmq_password}
RABBITMQ_SSL=true

# Authentication
JWT_SECRET_KEY=${vault:horus/production/jwt_secret}
JWT_ALGORITHM=HS256
JWT_EXPIRATION=1200

# Initial Admin (disabled in production)
SUPER_USER_USERNAME=
SUPER_USER_PASSWORD=

# Application
LLM_AUTOINIT=1
RATE_LIMIT=1000
RATE_LIMIT_WINDOW=3600

# API Configuration
NEXT_PUBLIC_API_BASE_URL=https://api.horus.example.com
NEXT_PUBLIC_API_TIMEOUT=60000
NEXT_PUBLIC_AUTH_ENABLED=true
NEXT_PUBLIC_TOKEN_STORAGE=localStorage

# WebSocket
NEXT_PUBLIC_WEBSOCKET_URL=wss://api.horus.example.com/chat
NEXT_PUBLIC_WEBSOCKET_RECONNECT_INTERVAL=10000

# Features - Production features only
NEXT_PUBLIC_ENABLE_CHAT=true
NEXT_PUBLIC_ENABLE_AGENT_MANAGEMENT=true
NEXT_PUBLIC_ENABLE_TASK_MANAGEMENT=true
NEXT_PUBLIC_ENABLE_ANALYTICS=false

# TLS/Security
CORS_ORIGINS=https://horus.example.com
TLS_ENABLED=true
TLS_CERT_PATH=/etc/ssl/prod-cert.pem
TLS_KEY_PATH=/etc/ssl/prod-key.pem

# Monitoring & Security
SENTRY_DSN=${vault:horus/production/sentry_dsn}
DATADOG_API_KEY=${vault:horus/production/datadog_key}
AUTH_AUDIT_LOG=true
COMPLIANCE_LOGGING=true
```

### Deployment & Rollout

```bash
# Blue-Green Deployment Strategy
# .github/workflows/deploy-production.yml

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

### Database Backup & Disaster Recovery

```bash
# Automated backups (AWS RDS handles this)
# Manual backup for critical operations
aws rds create-db-snapshot \
  --db-instance-identifier horus-prod-primary \
  --db-snapshot-identifier horus-prod-backup-$(date +%Y%m%d-%H%M%S)

# Verify backup
aws rds describe-db-snapshots \
  --snapshot-type manual \
  --query 'DBSnapshots[?DBInstanceIdentifier==`horus-prod-primary`]'
```

### Security Hardening

```bash
# Network Security Groups
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxx \
  --protocol tcp \
  --port 443 \
  --cidr 0.0.0.0/0

# Disable SSH
aws ec2 revoke-security-group-ingress \
  --group-id sg-xxxxxxxx \
  --protocol tcp \
  --port 22 \
  --cidr 0.0.0.0/0

# Enable WAF
aws wafv2 create-web-acl \
  --region us-east-1 \
  --name horus-prod-waf \
  --default-action Block={} \
  --rules file://waf-rules.json
```

## Environment-Specific Health Checks

### Development
- API responding on localhost:8000
- Services up (`docker ps`)

### Staging
- Database connectivity
- RabbitMQ queue connection
- Redis cache connectivity
- API health endpoint: `GET /health`
- WebSocket connectivity: `WS /chat`

### Production
- All of above, plus:
- Database replication lag < 100ms
- Error rate < 0.1%
- P99 latency < 500ms
- No secrets in logs
- Backup created in last 24h
- All services in at least 2 AZs

## Configuration Validation Checklist

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
