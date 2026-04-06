# Horus AI — Project Overview

---

## The Problem

Most companies that want to use AI today depend on third-party cloud services like OpenAI or Google Cloud. This creates concerns around **data privacy**, **cost**, and **vendor lock-in** — the company's sensitive data leaves their walls, and they have no control over it.

## The Solution

**Horus AI** is a platform I built that lets a company **run its own AI system entirely in-house**. No data ever leaves the company's servers. It's not just one AI — it's a system where **multiple AI agents work together**, each specialized in a different task, coordinated by a central brain called the orchestrator.

Think of it like a smart office: a user asks a question through a chat interface, the orchestrator figures out which agent is best suited to answer, that agent searches through the company's own documents to find relevant information, and then delivers an accurate, grounded answer — all in real time.

---

## How It Works (In Plain Terms)

```
   User chats via Web App
          │
          ▼
   Orchestrator receives the message
   and decides which AI agent should handle it
          │
          ▼
   The right AI Agent picks up the task,
   searches through company documents,
   and generates an answer
          │
          ▼
   Answer is sent back to the user in real time
```

The system is made up of four main pieces:

| Component              | What It Does                                                                                 |
|------------------------|----------------------------------------------------------------------------------------------|
| **Web App**            | The interface users interact with — chat, document uploads, admin dashboard                   |
| **Orchestrator**       | The central brain — receives requests, authenticates users, and routes tasks to the right agent |
| **AI Agents**          | Specialized workers — they read company documents, reason over them, and produce answers       |
| **Knowledge Store**    | The company's private memory — stores and searches documents (PDFs, Word files, text, images)  |

---

## What Makes This Project Interesting

- **Private AI** — Everything runs on the company's own servers. No data is sent to external services. Full control over privacy and compliance.
- **Multiple AI Agents** — Instead of one general-purpose AI, the system uses specialized agents that can be added, removed, or updated independently.
- **Smart Document Search** — When an agent answers a question, it first searches through real company documents to ground its response in facts (a technique called Retrieval-Augmented Generation, or RAG).
- **Real-Time Chat** — Users get instant responses through a live chat interface, similar to ChatGPT but connected to the company's own data.
- **Security & Access Control** — Different users have different permissions (Admin, Manager, User). Every action is logged for audit purposes.
- **Self-Healing & Monitoring** — The system tracks its own health, detects when something goes wrong, and provides dashboards to monitor performance.

---

## Technical Depth

**Backend:** Python 3.13, FastAPI, SQLAlchemy, Alembic migrations, async throughout.

**Frontend:** TypeScript, Next.js 16, React 19, Tailwind CSS, Radix UI, TanStack Query.

**AI / ML:** LLM orchestration with swappable model support (model selection driven by ongoing performance research). RAG pipeline using ChromaDB as vector store with SentenceTransformers embeddings. Agent decision model via Hugging Face Transformers. 4-bit quantization with bitsandbytes for efficient GPU inference.

**Infrastructure:** Microservices orchestrated via Docker Compose (with GPU override). RabbitMQ for async task dispatch between orchestrator and agents. PostgreSQL for persistence, Redis for caching and session management. WebSocket-based real-time chat with JWT authentication.

**Observability:** Prometheus metrics on every service, Grafana dashboards, distributed tracing via OpenTelemetry and Tempo, structured JSON logging with correlation IDs.

**Security:** JWT + bcrypt authentication, OAuth2 password flow, four-tier RBAC (Admin/Manager/User/System), granular permissions, API key auth for agent-to-orchestrator communication, audit logging.

**Testing & CI/CD:** pytest with async support, Vitest and Playwright for frontend, Locust for load testing, custom resilience test suite. GitHub Actions CI with real service containers (PostgreSQL, Redis, RabbitMQ).

---

## Skills Demonstrated

| Area                     | Skills                                                                 |
|--------------------------|------------------------------------------------------------------------|
| **AI & Machine Learning**| LLM integration, RAG pipelines, vector search, embeddings, model quantization, prompt engineering |
| **Backend Development**  | Python, FastAPI, REST APIs, WebSockets, async programming, database design |
| **Frontend Development** | TypeScript, React, Next.js, responsive UI, real-time interfaces        |
| **Infrastructure**       | Docker, microservices, message queues (RabbitMQ), caching (Redis)      |
| **Security**             | Authentication, authorization, RBAC, audit logging, secrets management |
| **DevOps & Quality**     | CI/CD, automated testing, load testing, resilience testing, monitoring |
| **System Design**        | Distributed systems, event-driven architecture, scalable design        |

---

*Built by Loup Marquez — loup.m.marquez@gmail.com
*With the help of Matheus Lopez — matheus.lopez@epitech.eu and Noah Gibelli — noah.gibelli@epitech.eu*

