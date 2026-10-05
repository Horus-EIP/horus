# Technology Watch

Active monitoring of technologies relevant to Horus AI: agent orchestration, RAG, LLM serving, message queues, vector stores, observability, security. This page is the **single source of truth** for the project's tech-watch deliverable (EIP Tech 4 — Objective 1).

It records what we've watched, where we got the signal, what we decided, and the evidence trail. For full architectural decision context, see the [ADRs](../adr/).

---

## How we watch

| Source type | Channels we follow | Cadence |
|-------------|--------------------|---------|
| Newsletters | TLDR AI · The Batch (DeepLearning.AI) · Pragmatic Engineer · Latent Space | Weekly |
| GitHub trending | `python`, `typescript`, topics `llm`, `rag`, `multi-agent`, `vector-database` | Weekly scan |
| Discord communities | LangChain · LlamaIndex · Ollama · Hugging Face · ChromaDB · FastAPI | Live channels muted, scanned weekly |
| Conferences / talks | PyCon FR · DotAI · AI Engineer Summit (YouTube) | Talk roundups after events |
| Scientific publications | arXiv `cs.AI`, `cs.CL`, `cs.IR` (ReAct, RAG-Fusion, agent benchmarks) | Monthly digest |
| Official docs RSS | FastAPI · LangChain · ChromaDB · OpenTelemetry · RabbitMQ blog | RSS aggregator |

> **Evidence to attach:** screenshots of the RSS reader / Discord channel list / GitHub stars history, plus a `docs/assets/tech-watch/` folder with PNGs. (Tracked separately as `[ TO ADD before jury ]`.)

---

## Watch log

Each row = one technology we evaluated. Status meanings:

- **Adopted** — in the codebase today, has an ADR.
- **Trialed** — built a POC / spike, evidence in `docs/assets/research/` or a dedicated branch.
- **Rejected** — considered with evidence, decided no, rationale recorded.
- **Watching** — on the radar, not actionable yet.

| Tech | Category | First spotted | Source | Status | Decision evidence |
|------|----------|---------------|--------|--------|--------------------|
| RabbitMQ | Message queue | 2025-08 | Pragmatic Engineer + official docs | Adopted | [ADR-001](../adr/ADR-001-rabbitmq.md) — chosen over Kafka/Redis Streams for ack semantics + per-queue policies |
| ChromaDB | Vector store | 2025-08 | LangChain Discord + GitHub trending | Adopted | [ADR-002](../adr/ADR-002-chromadb.md) — chosen over Pinecone/Weaviate for self-host + dev velocity |
| FastAPI | Web framework | 2025-05 | TLDR AI + GitHub trending | Adopted | [ADR-003](../adr/ADR-003-fastapi.md) — async-first, OpenAPI for free, ecosystem |
| OpenTelemetry → Tempo | Distributed tracing | 2025-08 | OpenTelemetry blog | Adopted | Compose stack — replaced Jaeger when Tempo's Grafana integration matured |
| Loki + Promtail | Log aggregation | 2026-04 | Grafana blog | Adopted | Compose stack — single Grafana UI for logs/metrics/traces (see commit `dbc8f5b`) |
| Qwen3-4B-Instruct (HF) | LLM | 2026-02 | Hugging Face trending | Adopted | Default decision model for the Agent service |
| BAAI/bge-base-en-v1.5 | Embedding model | 2025-08 | MTEB leaderboard | Adopted | Knowledge Store default — beat e5-base on internal corpus |
| ReAct agent pattern | Reasoning | 2026-02 | arXiv 2210.03629 + LangChain docs | Adopted | `src/services/agent/app/ai_agents/react_agent.py` |
| spaCy en_core_web_trf | NER | 2026-03 | spaCy 3.7 release notes | Adopted | Data extraction tool, trf when available, sm fallback |
| **LangGraph** | Agent orchestration | 2026-03 | LangChain Discord launch | Trialed → kept watching | Considered as ReAct replacement; revisit Q3 once stateful workflows are needed |
| **LlamaIndex** | RAG framework | 2025-09 | GitHub trending | Rejected | Too opinionated for our self-hosted-first model; we built thinner abstractions in `ai_agents/` |
| **Pinecone** | Vector store | 2025-08 | Official docs | Rejected | Hosted-only; conflicts with self-hosting requirement (see [ADR-002](../adr/ADR-002-chromadb.md)) |
| **Weaviate** | Vector store | 2025-08 | GitHub trending | Rejected | Heavier infra than ChromaDB for our scale (see [ADR-002](../adr/ADR-002-chromadb.md)) |
| **Kafka** | Message queue | 2025-08 | Pragmatic Engineer | Rejected | Overkill for our throughput, weaker per-message ack semantics for agent work (see [ADR-001](../adr/ADR-001-rabbitmq.md)) |
| **Datadog APM** | Observability SaaS | 2026-04 | DotAI talk | Rejected | Cost + data-sovereignty conflict with self-hosted promise |
| **vLLM** | LLM serving | 2026-04 | HF blog | Watching | Promising for throughput; would replace direct `transformers` calls in Agent. Revisit when GPU budget allows. |
| **Outlines / Instructor** | Structured LLM output | 2026-05 | Latent Space podcast | Watching | Would replace hand-rolled JSON-mode handling. Spike planned post-greenlight. |
| **DSPy** | LLM programming | 2026-05 | Stanford NLP Discord | Watching | Interesting paradigm but maturity vs. our timeline doesn't fit yet. |
| **llama.cpp Vulkan backend** (`server-vulkan` image) | LLM serving on integrated GPUs | 2026-10 | llama.cpp discussion #10879 + docs | Watching | [iGPU and NPU note](../tech-watch/IGPU_NPU_RESEARCH.md) (B-101): one measured spike on a Linux laptop before any profile; no container route on Windows |
| **llama.cpp OpenVINO backend** | LLM serving on Intel iGPUs and NPUs | 2026-10 | llama.cpp `docs/backend/OPENVINO.md` | Watching | [iGPU and NPU note](../tech-watch/IGPU_NPU_RESEARCH.md) (B-101): work in progress, Intel only, validated on Core Ultra Series 1 and 2 only; do not build yet |

---

## Research dossiers

Internal deep-dives produced by the team, beyond per-tool watch entries:

| Topic | File | Status |
|-------|------|--------|
| Agent management patterns | [assets/research/mas/Agent_Management.pdf](../assets/research/mas/Agent_Management.pdf) | ✅ |
| LLM infrastructure | [assets/research/mas/LLM_infrastructure.pdf](../assets/research/mas/LLM_infrastructure.pdf) | ✅ |
| Observability strategy | [assets/research/mas/Observability.pdf](../assets/research/mas/Observability.pdf) | ✅ |
| Orchestrator infrastructure | [assets/research/mas/Orchestrator_infrastructure.pdf](../assets/research/mas/Orchestrator_infrastructure.pdf) | ✅ |
| Security process | [assets/research/mas/Security_Process.pdf](../assets/research/mas/Security_Process.pdf) | ✅ |
| Integrated GPUs and NPUs for the CPU profiles (B-101) | [tech-watch/IGPU_NPU_RESEARCH.md](../tech-watch/IGPU_NPU_RESEARCH.md) | Note done; spike not run |
| Comparative tech brief (jury-facing) | [../greenlight/track-objectives-report/Comparative_Tech_Brief.docx](../../greenlight/track-objectives-report/Comparative_Tech_Brief.docx) | ✅ |

---

## Community engagement

We don't just consume — we engage. See [community-contributions.md](community-contributions.md) for the running log of issues opened, PRs sent, and discussion threads we participated in.

> ⚠️ Before jury: at least **one** contribution (issue, PR, or discussion reply) on an upstream project must be linked there. A 30-line bug report on FastAPI / ChromaDB / Tempo is sufficient — what matters is the proof of two-way engagement.

---

## Update protocol

This page is reviewed **monthly** during the sprint review. The latest review date and reviewer are recorded below.

- Last review: `[ TO FILL ]`
- Next review: `[ TO FILL ]`
- Reviewer: `[ TO FILL ]`
