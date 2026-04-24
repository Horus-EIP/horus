# Technology Changelog - Horus

This changelog documents technology decisions made during Horus development from August 2025 to April 2026. Each entry records a concrete adoption, upgrade, rejection or configuration change made to the project's technology stack, along with the rationale behind it. Entries are listed in chronological order.

---

## Format

```
DATE | ACTION | TECHNOLOGY | VERSION | REASON
```

**Actions:**
- `ADOPT`: Technology selected and integrated into the stack
- `REJECT`: Technology evaluated but not chosen
- `UPGRADE`: Existing dependency updated to a newer version
- `CONFIG`: Significant configuration change to an existing technology
- `DEPRECATE`: Technology phased out and replaced

---

## Entries

---

### 2025-09 | ADOPT | Python | 3.13 | Selected as the primary backend language for all AI/ML components (MAS Orchestrator, Agent Service, Knowledge Store). Chosen over C++ due to its dominant ecosystem for LLM inference (PyTorch, Transformers, SentenceTransformers) and zero friction with Hugging Face model hosting. The PyPI ecosystem was explicitly evaluated for GPU-compatible AI libraries before committing Python over compiled alternatives.

---

### 2025-09 | ADOPT | FastAPI | 0.115.11 | Selected as the HTTP and WebSocket framework for the MAS Orchestrator, agent and knowledge store services. Chosen for native async support, built-in Pydantic validation and automatic OpenAPI documentation generation. Estimated 4 weeks of development time saved compared to Flask with manual validation.

---

### 2025-09 | REJECT | Django | - | Evaluated as an alternative backend framework. Rejected due to its monolithic "batteries-included" architecture being too rigid for a microservices-first design and its poor native WebSocket support for real-time agent communication.

---

### 2025-09 | REJECT | Flask | - | Evaluated alongside FastAPI. Rejected for lacking native async support (critical for concurrent LLM calls and WebSockets) and requiring excessive third-party plugins to replicate FastAPI's built-in features like validation and documentation.

---

### 2025-09 | ADOPT | ChromaDB | 1.5.2 | Selected as the vector database for the Knowledge Store. Chosen over FAISS, Qdrant and Weaviate for its persistent storage support, native Python client and LangChain integration. Estimated 3 weeks of development time saved due to ChromaDB's out-of-the-box features compared to the custom infrastructure required for FAISS and the additional complexity of Qdrant and Weaviate.

---

### 2025-09 | REJECT | Qdrant | - | Evaluated against ChromaDB. Qdrant showed ~40% faster indexing, but query latency was unstable (2-3x variance between identical runs versus ChromaDB's stable 4.2-5.0 ms). ChromaDB's consistent performance and better ecosystem fit were decisive. Qdrant's operational overhead was also higher for a read-heavy pipeline with no high write-volume requirement.

---

### 2025-09 | REJECT | Weaviate | - | Evaluated alongside ChromaDB and Qdrant. Rejected because its schema management and hybrid-search architecture introduced unnecessary complexity for the project's requirements. ChromaDB offered equivalent features with a much lower learning curve.

---

### 2025-09 |REJECT | pgvector | - | Evaluated as a vector search option co-located with PostgreSQL. Rejected for lacking specialized out-of-the-box RAG features and performance optimizations found in a dedicated vector database like ChromaDB.

---

### 2025-09 | REJECT | FAISS | - | Evaluated alongside ChromaDB. Rejected because FAISS operates as an in-memory index library without a built-in server or persistence layer, requiring significantly more custom infrastructure to match ChromaDB's out-of-the-box capabilities for a RAG pipeline.

---

### 2025-09 | ADOPT | RabbitMQ | 3.13 | Selected as the message broker for async task distribution between the MAS Orchestrator and agents. Chosen for native AMQP routing semantics, durable queues, dead-letter queue support and built-in fault recovery.

---

### 2025-09 | REJECT | ZeroMQ | - | Evaluated as a message transport option during. Rejected in favour of RabbitMQ because ZeroMQ is a low-level socket library requiring manual implementation of durability, routing and retry semantics, all provided natively by RabbitMQ's AMQP protocol.

---

### 2025-09 | REJECT | Kafka | - | Evaluated as a message streaming alternative. Rejected as unnecessarily complex for the project's use case of a simple, reliable task queue. Kafka's strengths do not apply to dispatching LLM inference jobs between a small number of agents.

---

### 2025-09 | ADOPT | Next.js + React | Next.js 16 / React 19 | Frontend stack adopted for the web client dashboard. Next.js 16 (App Router) provides server-side rendering and API routes. React 19 powers the component-based UI.

---

### 2025-09 | ADOPT | SentenceTransformers + `all-MiniLM-L6-v2` | - | Initial embedding model adopted for the RAG pipeline. The `all-MiniLM-L6-v2` model was selected for its small footprint and fast CPU inference.

---

### 2025-09 | ADOPT | Docker | 27.5.1 | Adopted as the containerization and local orchestration strategy across all services. Enabled reproducible development environments, network isolation and inter-container communication between MAS, Agent, Knowledge Store, Web Client and RabbitMQ.

---

### 2025-09 | ADOPT | LangChain | 0.3.27 | Adopted as the primary framework for building the RAG pipeline and agent reasoning logic. LangChain's modular abstractions for LLMs, vector stores and prompt management saved an estimated 3 weeks of development time compared to building custom integrations.

---

### 2025-11 | ADOPT | PostgreSQL | 17 | Formalized as the primary relational database. Replaced the in-memory `agent_registry: dict` and in-memory conversation stores. Chosen over MongoDB for the relational structure of the data model (users, conversations, tasks, agents).

---

### 2025-11 | REJECT | MongoDB | - | Evaluated as a NoSQL alternative to PostgreSQL. Rejected due to the structured relational nature of the data model and the team's familiarity with SQL databases.

### 2025-11 | ADOPT | SQLAlchemy + Alembic | 2.0 / 1.12 | Adopted as the ORM and schema migration tool for PostgreSQL. SQLAlchemy's async engine was required for compatibility with FastAPI's async request handling. Alembic manages incremental schema migrations.

---

### 2025-11 | ADOPT | Redis | 7 | Adopted for WebSocket session metadata and JWT token invalidation on logout via TTL-based expiry (one-hour window)

---

### 2025-11 | REJECT | Redis Streams | - | Evaluated against RabbitMQ. Redis Streams requires manual application-layer implementation of durability, dead-letter queues and semantic routing, all provided natively by RabbitMQ.

---

### 2025-11 | REJECT | Celery | - | Evaluated as a worker framework. Rejected because it adds an abstraction layer over the broker that conflicts with the architecture's goal of autonomous, directky-controlled agents.

---

### 2025-12 | ADOPT | Prometheus + Grafana + OpenTelemetry + Tempo | - | Adopted full observability stack. Prometheus collects metrics from all services. Grafana provides dashboards. OpenTelemetry with OTLP export enables distributed tracing, with Tempo as the trace backend. Structured JSON logging with correlation IDs provides request-scoped log context across services.

---

### 2026-02 | CONFIG | ChromaDB | 1.5.2 | Dimesion mismatch issue resolved ahead of the embedding model upgrade. ChromaDB collection rebuilt to align vector dimensions with the planned replacement model (`BAAI/bge-base-en-v1.5`, 768 dimensions), requiring a full re-embedding migration of all stored documents.

---

### 2026-02 | UPGRADE | Embedding Model | `all-MiniLM-L6-v2` → `BAAI/bge-base-en-v1.5` | The BGE basemodel was selected after evaluation on the Hugging Face MTEB leaderboard. The larger embedding space improves semantic similarity across longer interprise documents. A migration script was created to re-embed all existing documents.

