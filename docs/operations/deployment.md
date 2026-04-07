# Deployment and CI

## Repository branches

Typical layout (confirm with your team):

- **`main`** — release-ready code  
- **`develop`** or similar — integration branch for features  
- **Feature branches** — often named `issue-<id>-<short-description>`  

This repository’s canonical remote is the project GitHub org; avoid unapproved mirrors.

---

## CI pipeline

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

---

## Local deployment with Docker

Build and run the full stack from the infra directory:

```bash
cd src/infra
cp .env.example .env   # once, then edit
docker compose up --build -d
```

Services are defined in **`src/infra/docker-compose.yml`**. See [Configuration](../getting-started/configuration.md) and [Monitoring](monitoring.md) for URLs and observability.

---

## Production considerations

For production, teams commonly:

- Run behind a reverse proxy (for example NGINX) with TLS  
- Use managed PostgreSQL, Redis, and RabbitMQ where appropriate  
- Store secrets in a vault or orchestrator secrets, not in committed `.env` files  
- Tune resource limits, health checks, and autoscaling per environment  

Kubernetes, Docker Swarm, or cloud-specific runtimes are outside this document; adapt the same images and environment variables your Compose file uses.
