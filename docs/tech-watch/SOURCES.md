# Tech Watch - Sources

This file documents all technical sources consulted during the research and development of the Horus project. It covers the five main implementation domains: Orchestrator Architecture, LLM Infrastructure, Agent Management, Security and Observability.

---

## 1. Official Documentation

### 1.1 FastAPI
**URL:** https://fastapi.tiangolo.com/
**Relevance:** Core gramework used to build the orchestrator's REST and WebSocket backend. Used extensively to implement asynchronous routes, dependency injection for RBAC enforcement and automatic OpenAPI documentation generation.

### 1.2 RabbitMQ
**URL:** https://www.rabbitmq.com/documentation.html
**Relevance:** Primary source for understanding message broker concepts, queue durability, consumer acknowledgement and retry mechanisms. Guided the decision to adopt RabbitMQ over WebSockets for inter-agent communication.

### 1.3 Redis
**URL:** https://redis.io/docs/
**Relevance:** Used to design the session management layer. Specifically, the TTL (time-to-live) feature informed the one-hour token expiry strategy for invalidating sessions on logout.

### 1.4 PostgreSQL
**URL:** https://www.postgresql.org/docs/
**Relevance:** Reference for structuring the persistent data layer, including the `CriticalLogs` audit table and user/agent registry schemas. Informed the choice of PostgreSQL over MongoDB for structured queryable data.

### 1.5 Docker
**URL:** https://docs.docker.com/
**Relevance:** Used to design the containerized microservices architecture. Guided network isolation strategies, port exposure policies and inter-container communication patterns for agents and the orchestrator.

---

## 2. Security References

### 2.1 JWT.io - JSON Web Tokens Introduction
**URL:** https://jwt.io/introduction/
**Relevance:** Primary reference for understanding stateless authentication with signed tokens. Informed the decision to embed user ID and role claims directly in the JWT payload, enabling per-request authorization checks.

### 2.2 OWASP - Authnetication Cheat Sheet
**URL:** https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
**Relevance:** Consulted to validate security design choices, particularly around session invalidation, token expiry and the risks of cookie-based authentication in distributed systems.

### 2.3 RFC 7519 - JSON Web Token (JWT) Standard
**URL:** https://datatracker.ietf.org/doc/html/rfc7519
**Relevance:** Formal specification used to ensure correct JWT structure and claim naming conventions in the Horus authentication implementation.

---

## 3. AI & LLM Infrastructure

### 3.1 Python Packaging Index (PyPI) - AI/ML Libraries
**URL:** https://pypi.org/
**Relevance:** Used to evaluate and compare Python AI libraries (TensorFlow, PyTorch, scikit-learn, Cython) when making the language choice between Python and C++ for the LLM runtime component.

### 3.2 Hugging Face - Model Hub & Documentation
**URL:** https://huggingface.co/docs
**Relevance:** Reference for deploying and integrating open-source language models, embedding models and understanding model hosting practices relevant to the Horus AI stack (including the RAG knowledge store).

### 3.3 LangChain - Offical Blog and Documentation
**URL:** https://blog.langchain.dev/ / https://docs.langchain.com/
**Relevance:** Consulted when evaluating orchestration frameworks and agent architectures.

---

## 4. Observability & Testing

### 4.1 pytest - Official Documentation
**URL:** https://docs.pytest.org/
**Relevance:** Core testing framework adopted for the project's unit, integration and functional test suites. The documentation guided test organization, fixture design and coverage reporting via `coverage.py`.

### 4.2 Python `logging` - Standard Library Documentation
**URL:** https://docs.python.org/3/library/logging.html
**Relevance:** Foundation for the hybrid logging system. Used to implement categorized, timestamped log output (SYSTEM, AGENT, SECURITY, USER) that feeds both the console and the PostgreSQL `CriticalLogs` table.

---

## 5. Internal Research Documents (Horus Project - `/docs/Research_paper/mas/`)

These five documents were produced internally by the team and serve as the primary research justification artifacts for each architectural decision made in the project.

| File | Topic | Key Decision Documented |
|---|---|---|
| `Security_Process.pdf` | Security Architecture | JWT + RBAC + Redis session management over cookie-based auth |
| `Agent_Management.pdf` | Agent Parallelization | RabbitMQ message queuing over WebSockets for inter-agent communication |
| `LLM_infrastructure.pdf` | Language Selection | Python over C++ for LLM runtime; use of GPU-compatible libraries |
| `Observability.pdf` | Monitoring & Testing | Hybrid logging (console + PostgreSQL) + pytest coverage strategy |
| `Orchestrator_infrastructure.pdf` | System Architecture | Microservices + message-driven architecture over monolithic design |

---

## Summary

| Category | Sources Count |
|---|---|
| Official documentation | 5 |
| Security references | 3 |
| AI & LLM infrastructure | 3 |
| Observability & testing | 2 |
| Internal research papers | 5 |
| **Total** | **18** |