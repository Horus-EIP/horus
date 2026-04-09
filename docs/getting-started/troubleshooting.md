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

### Chat or `/tasks/new_task` is very slow (browser “pending”)

**Expected with embedded images:** `docker compose build` should download **Qwen3 4B** into the **mas** and **agent** images (`DOWNLOAD_LLM=1` in `.env`). At runtime, Compose sets **`HF_HUB_OFFLINE=1`** so the stack does not call Hugging Face again. The first chat may still wait while **RAM load** and **CPU/GPU inference** run (much shorter than a full network download). Use `docker compose logs -f mas` to see preload / `ask_llm`.

**If you still see Hugging Face URLs in logs at runtime:** Rebuild with a network: `docker compose build --no-cache mas agent`, and ensure `.env` has not set `HF_HUB_OFFLINE=0` unless you intend to allow Hub access.

**Agent dev bind-mount:** Compose mounts `../services/agent/app` over `/app`. The image stores weights under `/opt/llm-bundle`; **`entrypoint.sh` copies them into `app/models/Qwen3_instruct_4B` once** if that folder is missing (so baked weights survive the mount).

**What we changed:** With `LLM_AUTOINIT=1`, MAS starts a **background preload** after RabbitMQ connects so the HTTP server stays responsive. The `mas` healthcheck allows a longer timeout during heavy load.

**Optional:** Add `HF_TOKEN` at **build** time for higher rate limits when downloading during `docker compose build`. Default Compose assigns GPUs to `mas`, `agent`, and `knowledge_store` when the NVIDIA toolkit is present; keep `LLM_FORCE_CPU=0` for orchestrator CUDA.

### Chat spinner never stops (task cancelled in MAS logs)

**Cause:** Background **TASK_TIMEOUT** cancels RUNNING tasks after a wall-clock limit. Values like **`TASK_TIMEOUT=120`** (2 minutes) are often too short for Qwen/agent work, so MAS interrupts the task. The UI only clears the spinner when it receives a WebSocket assistant message; timeout did not send one before.

**Fix:** Set **`TASK_TIMEOUT=1800`** (30 minutes) or higher in `src/infra/.env` (Compose passes it into `mas`). Ensure you are not using a stale `TASK_TIMEOUT_SECONDS` without `TASK_TIMEOUT` unless your MAS build reads both (current code accepts `TASK_TIMEOUT` and `TASK_TIMEOUT_SECONDS`). After a timeout, MAS should push an explanatory line over the chat WebSocket.

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
docker logs mas | grep "GPU\|CUDA\|device"

# Default compose already sets gpus: all for mas, agent, and knowledge_store.
# Install the NVIDIA Container Toolkit; if you have no GPU, comment out those gpus: lines in docker-compose.yml.
cd src/infra && docker compose up -d
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

# Reduce model size / VRAM
# Lower AGENT_MAX_NEW_TOKENS, set MODEL_DEVICE=cpu or AGENT_FORCE_CPU=1, or use a smaller hub model via MODEL_NAME.
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
