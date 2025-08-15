### 📦 Horus MVP – Complete System Overview

Horus is a multi-service system composed of:
- 🧠 AI Agents that retrieve knowledge and make decisions
- 🔁 An Orchestrator API (MAS) coordinating tasks and messaging
- 📚 A Knowledge Store API to upload/query documents
- 🖥️ A Web Dashboard (Next.js) to operate the system

All services are containerized and orchestrated with Docker Compose.

---

### 🗂 Repository Layout

```
MVP-Complete/
  infra/                      # Orchestration & infra
    docker-compose.yml        # Single compose to run all services

  services/
    mas/                      # Orchestrator API (FastAPI)
      agents/                 # Agent registry, routes and utilities
      chat/                   # Chat routes and tools
      conversations/          # Conversation routes and tools
      core/                   # App factory, CORS, rabbitmq tool
      schemas/                # Pydantic models
      tasks/                  # Task routes and tools
      tests/                  # Pytest suite for MAS
      main.py                 # FastAPI entrypoint (app = create_app_environment())
      requirements.txt
      Dockerfile

    agent/                    # Agent service (FastAPI)
      app/
        agent_server/         # FastAPI server, queues consumption, heartbeat
        ai_agents/            # Retrieval agent, decision agent, RAG pipeline
        config/               # Service config (e.g., ORCHESTRATOR_URL)
        main.py               # Local entry to run the agent server
      Dockerfile

    knowledge-store/          # Knowledge Store API (FastAPI + Chroma)
      app/
        api/routes/           # REST endpoints (file mgmt, store queries)
        chroma_db/            # Chroma data model & services
        main.py               # FastAPI application with root_path/docs
      documents/              # Uploaded documents (mounted volume in compose)
      chroma_data/            # Vector DB data (mounted volume in compose)
      requirements.txt
      Dockerfile

    web-client/               # Next.js dashboard (dev server)
      app/
        pages/                # Pages: dashboard, chat, knowledge-store
        ui/                   # Reusable UI components
        public/               # Static assets
        package.json          # NPM dependencies
        tsconfig.json         # TS config
        next.config.ts        # Next.js config
        ...
      Dockerfile

  docs/                       # High-level docs (add architecture, flows, etc.)
  README.md                   # You are here
```

---

### 🔧 Prerequisites
- Docker & Docker Compose
- Optional: Python 3.10+ (to run MAS tests locally without Docker)

---

### 🚀 Run Everything (Recommended)
From `infra/`:
```bash
cd infra
docker compose up --build
```
Services and ports:
- RabbitMQ: 5672, 15672
- MAS (FastAPI): 8000
- Agent: 8001
- Knowledge Store (FastAPI): 8080
- Web (Next.js): 3000

API docs:
- MAS: http://localhost:8000/docs
- Knowledge Store: http://localhost:8080/api/knowledge-store/docs

---

### 🧭 What Each Service Does
- services/mas (Orchestrator)
  - Manages agent registry, conversations, chat actions, and task lifecycle
  - Exposes REST APIs for clients and the agent
  - Publishes tasks to RabbitMQ queues
  - Key files: `core/app.py`, `agents/routes.py`, `tasks/routes.py`, `schemas/schemas.py`

- services/agent (Agent)
  - Registers with MAS, sends heartbeats, consumes tasks from RabbitMQ
  - Runs a RAG pipeline: `KnowledgeRetrievalAgent` + `DecisionMakingAgent`
  - Sends results back to MAS
  - Key files: `agent_server/server.py`, `ai_agents/*`, `app/main.py`

- services/knowledge-store (Knowledge Store)
  - Uploads, lists, deletes documents; supports retrieval query endpoints
  - Persists data in mounted volumes: `documents/`, `chroma_data/`
  - Key files: `app/main.py`, `app/api/routes/{file.py,store.py}`, `app/chroma_db/*`

- services/web-client (Dashboard)
  - Next.js app for UI: upload docs, chat, view dashboard
  - Code lives under `services/web-client/app/`

---

### 🧪 Testing (MAS)
From `services/mas/`:
```bash
pytest -vv
```

---

### ⚙️ Configuration & Environment
- Common (Compose):
  - `RABBITMQ_HOST`: set to `rabbitmq` inside Docker network
  - `ORCHESTRATOR_URL`: agent uses `http://mas:8000` inside Docker network
- Knowledge Store persistence:
  - Volumes mounted for `documents/` and `chroma_data/` in `infra/docker-compose.yml`

---

### 🧑‍💻 Local Development Tips
- Hot reload in containers is enabled by bind mounts for the agent and web-client in compose.
- To run a service outside Docker, use its entry point:
  - MAS: `uvicorn main:app --reload --port 8000` (from `services/mas`)
  - Agent: `python app/main.py` (from `services/agent`)
  - Knowledge Store: `uvicorn app.main:app --reload --port 8080` (from `services/knowledge-store`)
  - Web Client: `cd services/web-client/app && npm run dev`

---

### 🧰 Troubleshooting
- Ports already in use: stop existing processes or change published ports in `infra/docker-compose.yml`.
- MAS not seeing the agent: ensure RabbitMQ is healthy and the agent container can reach `http://mas:8000`.
- Knowledge store not listing documents: confirm volumes are mounted and API reachable on 8080.

---

### 📑 Notes
- Single Docker Compose file: `infra/docker-compose.yml`.
- Legacy local scripts and duplicate Compose/Dockerfiles were removed.
