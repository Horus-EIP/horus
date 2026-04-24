# Tech Watch - Community Contributions & Research Process

This file documents the team's engagement with technical communities and the research process conducted during Horus development. It covers both active contributions (questions asked, issues consulted) and passive research (documentation pages read, GitHub issues found helpful).

---

## 1. Community Research Conducted

The following entries document concrete research interactions that directly influenced architectural and implementation decisions in the project.

---

### Entry 1 - RabbitMQ vs WebSockets for Agent Communication

**Type:** Github Issue Research + Stack Overflow

**Context:** During Phase 2 (Agent Management), the team initially implemented WebSocket-based communication between agents. After testing, performance and security concerns led to a re-evaluation.

**Research conducted:**

- **GitHub Issue consulted:** `pika/pika` - Connection drops when handling tasks with a long duration  
  **URL:** https://github.com/pika/pika/issues/930

  *Helped understand how to handle RabbitMQ connection drops gracefully in Python consumers running inside Docker containers.*

- **Stack Overflow discussion:** Microservices Why Use RabbitMQ?  
  **URL:** https://stackoverflow.com/questions/45208766/microservices-why-use-rabbitmq

  *Confirmed that RabbitMQ is preferable for internal service-to-service communication due to built-in asynchronous processing, durability and decoupling, which transport protocols like WebSockets lack.*

**Decision influenced:** Adoption of RabbitMQ for agent task queueing, replacing the WebSocket prototype. Documented in `Agent_Management.pdf`.

---

### Entry 2 - JWT Stateless Authentication with FastAPI

**Type:** Stack Overflow + Official Documentation Reading

**Context:** During Phase 1 (Security), the team needed to implement JWT-based auth with role enforcement at the route level in FastAPI, without relying on external auth providers.

**Research conducted:**

- **Stack Overflow question consulted:** FastAPI decorators on endpoint  
  **URL:** https://stackoverflow.com/questions/74647143/fastapi-decorators-on-endpoint

  *Found a highly-voted answer explaining how to use FastAPI `Depends()` injection to validate JWT tokes and extract role claims per-route, directly adopted in the Horus security layer.*

- **FastAPI docs page read:** OAuth2 with Password (and hashing), Bearer with JWT tokens  
  **URL:** https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/

  *Even though the team chose not to use OAuth externally, this page clarified how to structure the token validation dependency correctly for stateless auth.*

**Decision influenced:** RBAC enforcement via FastAPI `Depends()` on protected routes. Redis used for logout-triggered session invalidation. Documented in `Security_Process.pdf`.

---

### Entry 3 - Redis TTL Strategy for Session Management

**Type:** Official Documentation + Community Blog

**Context:** The team evaluated whether to use cookies or Redis for session storage. This required understanding Redis TTL behavior and trade-offs for a containerized, on-premises deployment.

**Research conducted:**

- **Redis documentation page read:** EXPIRE command and key TTL management  
  **URL:** https://redis.io/commands/expire/

  *Confirmed that Redis natively supports key-level expiry with second-level precision, used to set a 1-hour session TTL and a 2-hour token database retention window.*

- **Community blog post consulted:** Remaining Stateless - JWT + Cookies in Node JS(REST)  
  **URL:** https://dev.to/mr_cea/remaining-stateless-jwt-cookies-in-node-js-3lle

  *Reinforced the decision to avoid traditional cookie-based sessions in favor of a stateless JWT approach. This is particularly relevant for our containerized microservices architecture, where maintaining state via cookies can be unreliable and complex to scale across multiple services and domains.*

**Decision influenced:** Redis selected for session caching with TTL-based invalidation. Explicitly compared against cookie-based auth and rejected for production use. Documented in `Security_Process.pdf` and `Orchestrator_infrastructure.pdf`.

---

### Entry 4 - PostgreSQL vs MongoDB for Audit Logging

**Type:** Official Documentation

**Context:** During the observability design phase, the team debated between PostgreSQL and MongoDB for storing structured logs and user data in the `CriticalLogs` table.

**Research conducted:**

- **PostgreSQL documentation page read:** Indexes and Query Planning for time-series log data

  **URL:** https://www.postgresql.org/docs/current/indexes.html

  *Confirmed that PostgreSQL's indexing capabilities make it suitable for querying structured log data by timestamp, category and component - a key requirement for the audit and compliance feature.*

**Decision influenced:** PostgreSQL chosen over MongoDB due to structured query requirements for log analysis and compliance reporting. Documented in `Observability.pdf` and `Orchestrator_infrastructure.pdf`.

---

### Entry 5 - Python vs C++ for LLM Runtime

**Type:** Technical Article + Official Documentation

**Context:** The team evaluated whether to implement the LLM inference layer in Python or C++ during the LLM infrastructure design phase.

**Research conducted:**

- **Technical article consulted:** "Python vs. C++ for Machine Learning"

  **URL:** https://www.netguru.com/blog/cpp-vs-python

  *Confirmed that for LLM applications, Python's role is primarily as an interface for high-performance C++ backends. The performance gap for model execution is effectively closed because the heavy computational lifting is offloaded to native libraries (CUDA/C++), making Python the optimal choice for production-level LLM orchestration.*

- **Cython documentation read:** Cython – C-Extensions for Python

  **URL:** https://cython.readthedocs.io/en/latest/

  *Evaluated as a fallback bridge between Python and C++ performance when needed. Identified as a viable option for future optimization of memory-intensive loops without abandoning the Python ecosystem.*

- **PyTorch documentation read:** GPU Acceleration with CUDA

  **URL:** https://pytorch.org/docs/stable/notes/cuda.html

  *Evaluated how PyTorch minimizes the performance gap with C++ by delegating heavy compute to CUDA kernels. Confirmed that for LLM workloads in the Horus context, the Python overhead is negligible compared to GPU execution time.*

**Decision influenced:** Python selected as the sole LLM runtime language. Cython noted as a future optimization path. Documented in `LLM_Infrastructure.pdf`.

---

## 2. Summary Table

| # | Type | Topic | Source | Decision Influenced |
|---|---|---|---|---|
| 1 | GitHub Issue + Stack Overflow | RabbitMQ vs WebSockets | pika/pika #930, SO microservices RabbitMQ | Agent communication architecture |
| 2 | Stack Overflow + Official Documentation | JWT + FastAPI RBAC | SO FastAPI decorators, FastAPI OAuth2-JWT docs | Security layer design |
| 3 | Official Documentation + Community Blog | Redis TTL sessions | Redis EXPIRE docs, Dev.to JWT+cookies article | Session management strategy |
| 4 | Official Documentation | PostgreSQL vs MongoDB | PostgreSQL indexes docs | Observability persistence layer |
| 5 | Technical Article + Official Documentation | Python vs C++ for LLM | Netguru article, Cython docs, PyTorch CUDA docs | LLM runtime language choice |
