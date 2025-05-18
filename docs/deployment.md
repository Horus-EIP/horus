# 🚀 Deployment Guide – Horus Project

## 📁 Repository Structure

This project follows a clean branching and contribution structure:

- **Main branch**: `main` – stable releases
- **Development branch**: `develop` – main integration branch
- **Feature branches**: `issue-<id>-<desc>` – per task or issue
- **No mirroring allowed** – This is the official GitHub repo

## 🔁 CI/CD Pipeline

A GitHub Actions pipeline will be used to automate:

- Linting with `flake8` / `eslint`
- Unit testing using `pytest` and test reports
- Docker image build (for agents and orchestrator)
- Optional deployment to a local or staging environment

### Example Workflow (`.github/workflows/ci.yml`)

```yaml
name: CI Pipeline

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: 3.11
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest --cov=.

  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build Docker
        run: docker build -t horus/agent .
```

## 🐳 Docker & Deployment

Each AI agent and the orchestrator run in Docker containers.

- To build the system:

```bash
docker-compose up --build
```

- To deploy in production:
  - Use Kubernetes or Docker Swarm
  - Attach PostgreSQL and VectorDB containers
  - Secure with reverse proxy (NGINX + SSL)
