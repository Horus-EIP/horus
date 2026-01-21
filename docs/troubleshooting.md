# Troubleshooting Guide

Common issues and their solutions for the Horus Multi-Agent System.

---

## Quick Diagnostics

### Check System Health

```bash
# All services status
docker ps

# MAS health
curl http://localhost:8000/rabbitmq/heartbeat

# Knowledge Store health
curl http://localhost:8080/health

# Agent status
curl http://localhost:8000/agents/ -H "Authorization: Bearer <token>"
```

### View Logs

```bash
# All service logs
cd src/infra && docker compose logs -f

# Specific service
docker logs mas --tail 100
docker logs agent --tail 100
docker logs knowledge_store --tail 100
docker logs postgres --tail 100
docker logs rabbitmq --tail 100
```

---

## Common Issues

### 1. Services Won't Start

**Symptoms:**
- `docker compose up` fails
- Services exit immediately

**Solutions:**

```bash
# Check port conflicts
lsof -i :8000
lsof -i :3000
lsof -i :8080

# Free up ports
kill -9 <PID>

# Rebuild containers
docker compose build --no-cache
docker compose up -d
```

**Check for Docker issues:**
```bash
# Restart Docker Desktop
# Or on Linux:
sudo systemctl restart docker
```

---

### 2. MAS Not Responding

**Symptoms:**
- http://localhost:8000/docs not loading
- Connection refused errors

**Solutions:**

```bash
# Check if MAS is running
docker ps | grep mas

# Check MAS logs for errors
docker logs mas --tail 100

# Restart MAS
docker restart mas

# If database connection issues:
docker restart postgres
sleep 10
docker restart mas
```

**Common causes:**
- PostgreSQL not ready
- RabbitMQ not ready
- Missing environment variables

---

### 3. Authentication Failures

**Symptoms:**
- 401 Unauthorized responses
- "Invalid credentials" errors

**Solutions:**

```bash
# Get a new token
curl -X POST http://localhost:8000/auth/token \
  -d "username=admin&password=admin"

# Check if user exists (in database)
docker exec -it postgres psql -U horus -d horus_db -c "SELECT * FROM users;"
```

**If admin user doesn't exist:**
```bash
# Restart MAS to trigger init_db
docker restart mas
```

---

### 4. No Agents Available

**Symptoms:**
- `GET /agents/` returns empty list
- Tasks fail with "No agent registered"

**Solutions:**

```bash
# Check agent logs
docker logs agent --tail 50

# Check if agent is running
docker ps | grep agent

# Restart agent
docker restart agent

# Wait for registration (30 seconds)
sleep 30

# Verify
curl http://localhost:8000/agents/ -H "Authorization: Bearer <token>"
```

**Common causes:**
- Agent can't reach MAS (network issue)
- MAS not ready when agent started
- Authentication failure during registration

---

### 5. Knowledge Store Queries Return Empty

**Symptoms:**
- Queries return no results
- RAG pipeline returns generic responses

**Solutions:**

```bash
# Check Knowledge Store health
curl http://localhost:8080/health

# Check if documents exist
curl -X POST http://localhost:8080/store/query \
  -H "Content-Type: application/json" \
  -d '{"query": "revenue", "k": 5}'

# Re-seed demo data
python scripts/demo/seed_demo_data.py

# Check Knowledge Store logs
docker logs knowledge_store --tail 50
```

---

### 6. Database Connection Issues

**Symptoms:**
- "Connection refused" to PostgreSQL
- Database errors in logs

**Solutions:**

```bash
# Check PostgreSQL status
docker ps | grep postgres
docker logs postgres --tail 50

# Test connection
docker exec -it postgres pg_isready -U horus

# Restart PostgreSQL
docker restart postgres
sleep 10
docker restart mas
```

**If database is corrupted:**
```bash
# WARNING: This deletes all data!
docker compose down -v
docker compose up -d
python scripts/demo/seed_demo_data.py
```

---

### 7. RabbitMQ Issues

**Symptoms:**
- Tasks not being processed
- "Connection refused" to RabbitMQ
- Queue errors in logs

**Solutions:**

```bash
# Check RabbitMQ status
docker ps | grep rabbitmq
docker logs rabbitmq --tail 50

# Access RabbitMQ management
# http://localhost:15672 (guest/guest)

# Restart RabbitMQ
docker restart rabbitmq
sleep 30
docker restart mas
docker restart agent
```

---

### 8. WebSocket Connection Issues

**Symptoms:**
- Chat messages not updating in real-time
- WebSocket connection errors in browser console

**Solutions:**

1. **Check browser console** for WebSocket errors
2. **Verify MAS is running** and accessible
3. **Check CORS configuration** in browser network tab
4. **Try a different browser** (WebSocket support varies)

```bash
# Test WebSocket endpoint
wscat -c ws://localhost:8000/chat/ws/{conversation_id}?token={jwt_token}
```

---

### 9. Slow Response Times

**Symptoms:**
- API calls taking > 5 seconds
- Timeouts

**Solutions:**

```bash
# Check resource usage
docker stats

# Check for slow queries in MAS logs
docker logs mas | grep "Slow Query"

# Increase container resources in docker-compose.yml
# deploy:
#   resources:
#     limits:
#       memory: 4G
```

**For GPU acceleration:**
```bash
# Check if GPU is being used
docker logs agent | grep "GPU\|CUDA\|device"

# Enable GPU in docker-compose.gpu.yml
docker compose -f docker-compose.gpu.yml up -d
```

---

### 10. Memory Issues

**Symptoms:**
- Containers being killed (OOM)
- System becoming unresponsive

**Solutions:**

```bash
# Check memory usage
docker stats

# Increase Docker memory limit
# Docker Desktop → Settings → Resources → Memory

# Reduce model size
# In agent settings, use smaller model (t5-small vs t5-base)
```

---

## Reset Procedures

### Soft Reset (Keep Data)

```bash
docker compose restart
```

### Hard Reset (Clear Data)

```bash
cd src/infra
docker compose down -v
docker compose up -d

# Re-seed
python scripts/demo/seed_demo_data.py
```

### Complete Reset (Rebuild)

```bash
cd src/infra
docker compose down -v --rmi all
docker compose build --no-cache
docker compose up -d
```

---

## Getting Help

### Collect Debug Information

```bash
# Create debug bundle
mkdir debug_bundle
docker ps > debug_bundle/services.txt
docker compose logs > debug_bundle/logs.txt
docker stats --no-stream > debug_bundle/stats.txt

# Check specific service
docker inspect mas > debug_bundle/mas_inspect.json
```

### Log Locations

| Service | Log Location |
|---------|--------------|
| MAS | `docker logs mas` or `/app/logs/` in container |
| Agent | `docker logs agent` |
| Knowledge Store | `docker logs knowledge_store` |
| PostgreSQL | `docker logs postgres` |
| RabbitMQ | `docker logs rabbitmq` |

### Environment Variables

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

## Performance Tuning

### Database

```sql
-- Check slow queries (if pg_stat_statements enabled)
SELECT query, mean_time, calls 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;
```

### Connection Pools

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

### Model Inference

For faster inference:
- Use GPU acceleration
- Use quantized models
- Adjust batch sizes
