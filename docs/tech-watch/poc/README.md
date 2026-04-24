# Tech Watch - Proof of Concept Evaluations

This folder contains runnable benchmarks that compare different technologies for the Horus project. Each POC follows the same structure:

```
POC-XXX-<technology-a>-vs-<technology-b>/
├── benchmark.py   ← runnable script
└── README.md      ← experiment description + conclusion
```

## POC Index

| ID | Topic | Benchmark winner | Project decision | Status |
|---|---|---|---|---|
| [POC-001](./POC-001-chromadb-vs-qdrant/) | Vector store: ChromaDB vs Qdrant | Inconclusive (ChromaDB more stable) | **ChromaDB** | ✅ Complete |
| [POC-002](./POC-002-rabbitmq-vs-redis-streams/) | Message broker: RabbitMQ vs Redis Streams | **Redis Streams** (~6.5× throughput) | **RabbitMQ** | ✅ Complete |

## Key findings summary

| Decision | Chosen | Benchmark said | Why benchmark wasn't the deciding factor |
|---|---|---|---|
| Vector store | **ChromaDB** | Inconclusive — no reliable p95 winner across 4 runs | ChromaDB had more consistent query avg; Qdrant advantages (payload filtering, scale) don't apply at MVP scope |
| Message broker | **RabbitMQ** | Redis Streams wins on throughput + latency | Real bottleneck is LLM inference (seconds), not broker (ms); RabbitMQ wins on durability, routing semantics, and dead-letter handling |

> Both decisions align with the team's ADRs ([ADR-001: RabbitMQ](architecture/ADR-001-rabbitmq.md), [ADR-002: ChromaDB](architecture/ADR-002-chromadb.md)). The POCs were used to validate the evaluation process, not to override architectural decisions made with broader project context.

## Running all POCs

```bash
# POC-001: ChromaDB vs Qdrant (no external services needed, both stores runs in-memory)
pip install chromadb qdrant-client sentence-transformers
python POC-001-chromadb-vs-qdrant/benchmark.py

# POC-002: RabbitMQ vs Redis Streams (requires Docker for RabbitMQ and Redis)
docker run -d --name rabbitmq -p 5672:5672 rabbitmq:3
docker run -d --name redis -p 6379:6379 redis:7
pip install pika redis
python POC-002-rabbitmq-vs-redis-streams/benchmark.py
```