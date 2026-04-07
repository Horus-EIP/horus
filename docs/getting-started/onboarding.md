# Developer onboarding

This guide helps you set up a local environment for the Horus multi-agent system.

## Quick setup (under 30 minutes)

**Typical timing**

- Prerequisites: 2–5 minutes  
- Clone repository: 1–2 minutes  
- Environment file: 2–3 minutes  
- First Docker build: 10–15 minutes  
- Verification: 2–3 minutes  

---

## Prerequisites

### Required

- **Git** (2.30+)  
  [Download Git](https://git-scm.com/downloads)

- **Docker** with Compose v2 (`docker compose`)  
  [Docker Desktop](https://www.docker.com/products/docker-desktop)  
  Allocate at least 4 CPUs and 8 GB RAM in Docker settings.

### Optional (running services outside Docker)

- **Python 3.13+** for MAS and related services  
- **Node.js** compatible with Next.js 16 (see `src/services/web-client/package.json`) for frontend work  

### Optional prerequisite check

```bash
git --version
docker --version
docker compose version
python3 --version   # optional
node --version      # optional
```

---

## Project structure (high level)

```
├── src/
│   ├── infra/                 # Docker Compose, Grafana/Tempo/Prometheus config
│   │   ├── docker-compose.yml
│   │   ├── .env.example
│   │   └── grafana/
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

## Setup

### Step 1: Clone the repository

```bash
git clone <repository-url>
cd <repository-directory>
git checkout <your-working-branch>
```

### Step 2: Configure environment

```bash
cd src/infra
cp .env.example .env
```

Review values in `.env`. Defaults are suitable for many local setups. Important keys include `POSTGRES_*`, `REDIS_PASSWORD`, `RABBITMQ_*`, `JWT_SECRET_KEY`, and `SUPER_USER_*`. Never commit `.env`; only `.env.example` is tracked.

### Step 3: Start the stack

```bash
cd src/infra
docker compose up --build
```

First run builds images and can take several minutes. The stack includes PostgreSQL, Redis, RabbitMQ, MAS, Agent, Knowledge Store, Web Client, PgAdmin, RedisInsight, Prometheus (internal), Grafana, and Tempo. See **`src/infra/docker-compose.yml`** for the authoritative list.

### Step 4: Verify containers

In another terminal:

```bash
cd src/infra
docker compose ps
```

**PostgreSQL** (adjust user and database to match `.env`):

```bash
docker compose exec postgres psql -U postgres -d mas_db -c "SELECT version();"
```

**Redis** (password from `REDIS_PASSWORD` in `.env`):

```bash
docker compose exec redis redis-cli -a "$REDIS_PASSWORD" ping
```

---

## Web interfaces

| Service | URL | Notes |
|---------|-----|--------|
| RabbitMQ management | http://localhost:15672 | User/password from `RABBITMQ_USER` / `RABBITMQ_PASSWORD` |
| PgAdmin | http://localhost:5433 | `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` |
| Grafana | http://localhost:3301 | Default `admin` / `admin` in Compose; metrics and Tempo traces |
| RedisInsight | http://localhost:5540 | Configure connection to host `redis` from inside Docker |
| MAS API docs | http://localhost:8000/docs | When `mas` is running |
| Web client | http://localhost:3000 | When `web-client` is running |

**Prometheus** is not published on the host in the default Compose file. Use Grafana’s Prometheus datasource or see [Monitoring](../operations/monitoring.md).

There is **no** Metabase or PostgreSQL Exporter service in the default `docker-compose.yml`.

---

## Running tests

From the repository root:

```bash
./scripts/ci/run_all_python_tests.sh
```

MAS-focused tests:

```bash
bash scripts/python/mas/test_code.sh
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

## Running MAS on the host (optional)

Use when you want to debug Python without rebuilding the `mas` image. PostgreSQL, Redis, and RabbitMQ should still be reachable (often via Docker).

```bash
cd src/services/mas
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

From the repo root, with `DB_HOST`, `REDIS_HOST`, and `RABBITMQ_HOST` pointing at localhost (see CI workflow for patterns):

```bash
bash scripts/dev/mas/run_local.sh
```

Open http://localhost:8000/docs when the server is up.

---

## Troubleshooting

### Docker services fail to start

```bash
docker ps
docker system df
docker compose logs postgres
docker compose logs redis
```

Try a clean rebuild: `docker compose down -v` then `docker compose up --build` (destroys named volumes; use only if you accept data loss).

### Port already in use

Find the process using the port (example: 5432), stop it, or change the host mapping via `DB_PORT` in `.env` where applicable.

### Database connection errors from the host

Ensure Postgres is healthy: `docker compose ps postgres` and `docker compose logs postgres`.

### 401 from the API

Confirm `JWT_SECRET_KEY` is set. Super-user bootstrap runs at MAS startup via the container entrypoint.

### RabbitMQ errors

```bash
docker compose ps rabbitmq
docker compose exec rabbitmq rabbitmq-diagnostics -q ping
```

### `ModuleNotFoundError` (e.g. `core`)

Run from `src/services/mas` with `PYTHONPATH` including that directory, or use the provided scripts.

---

## Development workflow

1. Create a branch from your team’s integration branch.  
2. Make changes and run tests locally.  
3. Commit using [commit convention](../contributing/commit-convention.md).  
4. Open a pull request and request review.  

---

## Further reading

- [Architecture overview](../architecture/overview.md)  
- [Configuration](configuration.md)  
- [RBAC](../security/rbac.md)  
- [Secrets management](../operations/secrets-management.md)  
- [Workflow](../contributing/workflow.md)  
- [Testing policy](../contributing/testing-policy.md)  
- [Troubleshooting (extended)](troubleshooting.md)  

---

## Verification checklist

- [ ] Repository cloned  
- [ ] `src/infra/.env` created from `.env.example`  
- [ ] `docker compose ps` shows expected services  
- [ ] Postgres accepts connections  
- [ ] RabbitMQ UI reachable  
- [ ] Redis responds to `PING`  
- [ ] Tests pass (`pytest -c tests/mas/pytest.ini tests/mas` or project script)  

---

## Need help?

1. See [Troubleshooting](troubleshooting.md) and logs: `docker compose logs <service>`.  
2. Confirm `src/infra/.env` matches **`src/infra/.env.example`**.  
3. Open an issue or ask your team channel.  
