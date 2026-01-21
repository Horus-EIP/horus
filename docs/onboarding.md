# Developer Onboarding Guide

Welcome to the Horus Multi-Agent System! This guide will help you set up your development environment and get started in less than 30 minutes.

## ⏱️ Quick Setup (< 30 minutes)

**Estimated time breakdown:**
- Prerequisites check: 2-5 min
- Repository clone: 1-2 min
- Environment setup: 3-5 min
- Docker services startup: 10-15 min
- Verification: 2-3 min

---

## 📋 Prerequisites

Before you begin, ensure you have the following installed on your system:

### Required
- **Git** (v2.30+)
  ```bash
  git --version
  ```
  [Download Git](https://git-scm.com/downloads)

- **Docker** (v20.10+) and **Docker Compose** (v1.29+)
  ```bash
  docker --version
  docker-compose --version
  ```
  [Download Docker Desktop](https://www.docker.com/products/docker-desktop)
  - Includes both Docker and Docker Compose
  - Allocate at least 4 CPU cores and 8GB RAM in Docker Desktop settings

### Optional (for local Python development)
- **Python 3.10+** (only if running services outside Docker)
  ```bash
  python --version
  ```
  [Download Python](https://www.python.org/downloads/)

- **Node.js 18+** (only for web client development)
  ```bash
  node --version
  npm --version
  ```
  [Download Node.js](https://nodejs.org/)

### Verification Script
```bash
#!/bin/bash
echo "✓ Checking prerequisites..."
git --version > /dev/null && echo "✅ Git" || echo "❌ Git"
docker --version > /dev/null && echo "✅ Docker" || echo "❌ Docker"
docker-compose --version > /dev/null && echo "✅ Docker Compose" || echo "❌ Docker Compose"
python --version > /dev/null 2>&1 && echo "✅ Python" || echo "⚠️  Python (optional)"
node --version > /dev/null 2>&1 && echo "✅ Node.js" || echo "⚠️  Node.js (optional)"
```

---

## 📁 Project Structure

```
Horus/
├── src/
│   ├── infra/                    # Infrastructure & Docker Compose
│   │   ├── docker-compose.yml   # Service orchestration
│   │   ├── .env.example         # Configuration template
│   │   ├── prometheus.yml       # Monitoring config
│   │   └── rabbitmq.conf        # Message queue config
│   │
│   └── services/
│       ├── mas/                 # Multi-Agent System (Python/FastAPI)
│       │   ├── core/            # Core modules (config, logger)
│       │   ├── auth/            # Authentication & RBAC
│       │   ├── agents/          # Agent registry & management
│       │   ├── tasks/           # Task orchestration
│       │   ├── db/              # Database models & migrations
│       │   └── tests/           # Unit tests
│       │
│       ├── agent/               # AI Agent Service (Python)
│       ├── knowledge-store/     # Knowledge Base (Python)
│       └── web-client/          # Frontend (Next.js)
│
├── docs/                        # Documentation
│   ├── architecture.md
│   ├── configuration.md
│   ├── rbac.md
│   ├── secrets-management.md
│   └── ...
│
└── README.md
```

---

## 🚀 Setup Instructions

### Step 1: Clone the Repository

```bash
# Clone the repository
git clone https://github.com/EpitechPromo2027/G-EIP-600-BAR-6-1-eip-loup.marquez.git
cd G-EIP-600-BAR-6-1-eip-loup.marquez

# Verify you're on the correct branch
git branch
# Output should show: * 96-25-agent-authentication
```

**Estimated time: 1-2 minutes**

---

### Step 2: Configure Environment Variables

The project uses centralized environment configuration. You'll create a `.env` file from the template.

#### 2a. Copy the Environment Template

```bash
cd src/infra
cp .env.example .env
```

#### 2b. Review Default Values

```bash
cat .env
```

**Default values for local development:**
- `POSTGRES_PASSWORD=postgres`
- `REDIS_PASSWORD=redis_password`
- `RABBITMQ_PASSWORD=guest`
- `JWT_SECRET_KEY=dev-secret-key-change-in-production`
- `SUPER_USER_USERNAME=admin`
- `SUPER_USER_PASSWORD=admin`

#### 2c. (Optional) Customize Values

For local development, defaults are fine. For production or team setup:

```bash
# Edit the .env file
nano .env

# Make secure passwords (production only):
# POSTGRES_PASSWORD=<strong-password-32-chars>
# REDIS_PASSWORD=<strong-password-32-chars>
# JWT_SECRET_KEY=<random-secret-64-chars>
```

**⚠️ Security Note**: Never commit `.env` to git (it's in `.gitignore`). Only `.env.example` is tracked.

**Estimated time: 2-3 minutes**

---

### Step 3: Start All Services with Docker Compose

```bash
# Make sure you're in the infra directory
cd src/infra

# Start all services (builds images on first run)
docker-compose up --build

# This will start:
# ✓ PostgreSQL (database)
# ✓ Redis (cache)
# ✓ RabbitMQ (message queue)
# ✓ Prometheus (metrics)
# ✓ Grafana (dashboards)
# ✓ PgAdmin (database UI)
# ✓ PostgreSQL Exporter (monitoring)
```

**Estimated time: 10-15 minutes**

The first build takes longer as Docker pulls and builds images. Subsequent runs are much faster.

**✅ Success indicators:**
```
postgres_1 | database system is ready to accept connections
rabbitmq_1 | Server startup complete
redis_1 | Ready to accept connections
prometheus_1 | Ready to accept connections
pgadmin_1 | tailing /var/log/pgadmin4/pgadmin4.log, exit page with CTRL-C
```

---

### Step 4: Verify Services are Running

In a **new terminal** (keep docker-compose running):

```bash
# Check all services are healthy
docker-compose ps

# Expected output:
# NAME                    STATUS
# postgres                healthy
# redis                   healthy
# rabbitmq                healthy
# prometheus              Up
# grafana                 Up
# pgadmin                 Up
```

**Test database connectivity:**

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U postgres -d mas_db -c "SELECT version();"

# Should return PostgreSQL version
```

**Test Redis connectivity:**

```bash
# Check Redis
docker-compose exec redis redis-cli -a redis_password ping

# Should return: PONG
```

**Estimated time: 2-3 minutes**

---

### Step 5: Access Web Interfaces

Once all services are running, you can access:

| Service | URL | Credentials |
|---------|-----|-------------|
| **RabbitMQ** | http://localhost:15672 | guest / guest |
| **PgAdmin** | http://localhost:5433 | admin@admin.com / admin |
| **Prometheus** | http://localhost:9090 | - |
| **Grafana** | http://localhost:3001 | admin / admin |
| **RedisInsight** | http://localhost:5540 | - |
| **Metabase** | http://localhost:5434 | - |

**Default Credentials** (change in production):
- Admin Username: `admin`
- Admin Password: `admin`
- PostgreSQL User: `postgres`
- PostgreSQL Password: `postgres`

---

## 🧪 Running Tests

### Option A: Run All Tests (with coverage)

```bash
cd src/services/mas
./test_code.sh

# This runs:
# - Unit tests for all modules
# - Coverage report (HTML at htmlcov/index.html)
# - Takes 2-5 minutes
```

### Option B: Run Specific Tests

```bash
cd src/services/mas

# Run tests for a specific module
pytest tests/test_auth.py -v

# Run a specific test function
pytest tests/test_auth.py::test_login -v

# Run with coverage
pytest --cov=. --cov-report=html

# View coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### Option C: Integration Tests (requires running services)

```bash
cd src/services/mas/client_tests

# Run comprehensive integration test
python client_multiple_agents.py

# Expected output:
# ✅ ALL TESTS COMPLETED SUCCESSFULLY!
```

---

## 🐍 Running MAS Locally (Optional)

For faster development iteration without Docker, run MAS locally:

```bash
cd src/services/mas

# Create virtual environment
python -m venv venv

# Activate virtual environment
source venv/bin/activate  # macOS/Linux
# OR
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Ensure PostgreSQL, Redis, RabbitMQ are running (via Docker)
# Then start MAS
./run_local.sh

# Server starts on http://localhost:8000
# Swagger docs: http://localhost:8000/docs
```

---

## 🔧 Troubleshooting

### Common Issues & Solutions

#### 1. Docker Services Won't Start

**Problem**: `docker-compose up` fails with connection errors

**Solutions**:
```bash
# Check Docker daemon is running
docker ps

# Check available disk space
docker system df

# Clean up unused Docker resources
docker system prune

# Rebuild from scratch
docker-compose down -v
docker-compose up --build

# Check Docker logs
docker-compose logs postgres
docker-compose logs redis
```

**For Windows/Mac**: Ensure Docker Desktop is running and has sufficient resources:
- Settings → Resources → CPU: at least 4 cores
- Settings → Resources → Memory: at least 8GB

---

#### 2. Port Already in Use

**Problem**: `Port 5432 is already in use`

**Solutions**:
```bash
# Find what's using the port (Linux/Mac)
lsof -i :5432
# or
netstat -tulpn | grep 5432

# Kill the process
kill -9 <PID>

# Change port in .env (if needed)
echo "DB_PORT=5433" >> .env
```

---

#### 3. Database Connection Errors

**Problem**: `psycopg2.OperationalError: connection refused`

**Solutions**:
```bash
# Verify PostgreSQL is running
docker-compose ps postgres

# Check PostgreSQL logs
docker-compose logs postgres

# Verify environment variables
docker-compose exec postgres env | grep POSTGRES

# Manually test connection
docker-compose exec postgres psql -U postgres -c "SELECT 1"
```

---

#### 4. Authentication Issues

**Problem**: `401 Unauthorized` errors

**Solutions**:
```bash
# Verify JWT_SECRET_KEY is set
grep JWT_SECRET_KEY .env

# Check if admin user was created
docker-compose exec postgres psql -U postgres -d mas_db -c "SELECT * FROM users LIMIT 1"

# Reset admin user
docker-compose exec mas python -c "from db.init_setup import init_db; init_db()"
```

---

#### 5. RabbitMQ Connection Issues

**Problem**: `pika.exceptions.AMQPConnectionError`

**Solutions**:
```bash
# Check RabbitMQ is healthy
docker-compose ps rabbitmq

# Test RabbitMQ connectivity
docker-compose exec rabbitmq rabbitmq-diagnostics -q ping

# Check RabbitMQ logs
docker-compose logs rabbitmq

# Verify credentials
docker-compose exec rabbitmq rabbitmqctl list_users
```

---

#### 6. "Module not found" Errors

**Problem**: `ModuleNotFoundError: No module named 'core'`

**Solutions**:
```bash
# Verify you're in the correct directory
pwd
# Should be: .../src/services/mas

# Add to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Or run with explicit path
python -m pytest tests/
```

---

## 📚 Development Workflow

### 1. **Create a Feature Branch**

```bash
git checkout -b feature/my-feature
# or
git checkout -b fix/bug-description
```

### 2. **Make Changes**

Edit files in your preferred editor/IDE:
```bash
# Recommended: VS Code with Python extension
code .
```

### 3. **Run Tests Locally**

```bash
cd src/services/mas
pytest tests/ -v

# Or with coverage
./test_code.sh
```

### 4. **Commit with Conventional Messages**

```bash
git add .
git commit -m "feat(agents): add agent heartbeat monitoring"
# Follow commit convention: docs/commit_convention.md
```

### 5. **Push and Create Pull Request**

```bash
git push origin feature/my-feature
```

Then create a Pull Request on GitHub.

---

## 📖 Additional Resources

- **[Architecture](architecture.md)**: System design and components
- **[Configuration Guide](configuration.md)**: Detailed environment variables
- **[RBAC Documentation](rbac.md)**: User roles and permissions
- **[Secrets Management](secrets-management.md)**: Secure credential handling
- **[Commit Convention](commit_convention.md)**: Git commit standards
- **[Testing Policy](testing_policy.md)**: Test guidelines
- **[Workflow Guide](workflow.md)**: Development process

---

## ✅ Verification Checklist

Before starting development, verify:

- [ ] Git repository cloned
- [ ] `.env` file created in `src/infra/`
- [ ] Docker services running (`docker-compose ps`)
- [ ] PostgreSQL accessible (`docker-compose exec postgres psql -U postgres -c "SELECT 1"`)
- [ ] RabbitMQ running (`curl -i http://localhost:15672`)
- [ ] Redis running (`docker-compose exec redis redis-cli ping`)
- [ ] Tests pass (`cd src/services/mas && ./test_code.sh`)
- [ ] Can access http://localhost:15672 (RabbitMQ UI)

If all checks pass, you're ready to start developing! 🎉

---

## ❓ Need Help?

1. **Check the troubleshooting section above** for your specific issue
2. **Review logs**: `docker-compose logs <service-name>`
3. **Check configuration**: Verify `.env` file has correct values
4. **Ask the team**: Slack or open an issue on GitHub
5. **Documentation**: See `/docs` folder for detailed guides
