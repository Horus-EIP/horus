# POC-001 - ChromaDB vs Qdrant

## What was tested

A head-to-head latency comparison of two vector stores:

| | ChromaDB | Qdrant |
|---|---|---|
| Mode used | In-memory (ephemeral client) | In-memory (`:memory:` mode) |
| Index size | 100 documents | 100 documents |
| Embedding model | `BAAI/bge-base-en-v1.5` (768-dim) | same |
| Queries run | 10 semantic queries | 10 semantic queries |
| Metric | cosine similarity | cosine similarity |

## How to run

```bash
# Install Python dependencies
pip install chromadb qdrant-client sentence-transformers

# Run the benchmark
python benchmark.py
```

## What was found

Observed across **4 full runs** (5 rounds each, 10 queries/round)

| Run | Chroma avg | Qdrant avg | Chroma p95 | Qdrant p95 | p95 winner |
|---|---|---|---|---|---|
| 1 | ~4.98 ms | ~6.15 ms | ~15.98 ms | ~8.87 ms | Qdrant |
| 2 | ~4.43 ms | ~4.90 ms | ~13.49 ms | ~5.80 ms | Qdrant |
| 3 | ~4.43 ms | ~11.64 ms | ~13.11 ms | ~17.85 ms | **ChromaDB** |
| 4 | ~4.21 ms | ~7.73 ms | ~12.57 ms | ~14.04 ms | **ChromaDB** |

| Metric | ChromaDB | Qdrant | Verdict |
|---|---|---|---|
| Index time | ~117–144 ms | ~77–84 ms | Qdrant consistently ~40% faster |
| Query avg | ~4.2–5.0 ms (stable) | ~4.9–11.6 ms (unstable) | **ChromaDB** wins every run |
| Query p95 | ~12–16 ms (stable) | ~5–18 ms (unstable) | Split: 2 runs each |

Key observations:

- **ChormaDB query avg is consistent across all 4 runs** (~4.2-5.0 ms). Qdrant oscillates between 4.9ms and 11.6ms with no clear pattern, more than 2x variance between runs.
- **Qdrant p95 is unpredictable**: wins by a large margin in runs 1-2, but loses in runs 3-4.
- **The only unambiguous winner** across all runs is Qdrant for indexing time (~40% faster), a less critical metric in a read-heavy RAG pipeline.
- At 100 documents, both stores are fast enough that the differences are largely within system noise. Neither result is a strong performance argument.

## Conclusion

**Benchmark result: inconclusive on latency. ChromaDB is the more consistent performer at this scale.**

The performance data does not justify choosing Qdrant over ChromaDB for this project. The team's decision ([ADR-002: ChromaDB](architecture/ADR-002-chromadb.md)) to adopt ChromaDB is supported by this POC for the following reasons:

1. **More predictable query latency**: ChromaDB's avg (4.2-5.0ms) and p95 (12-16ms) are stable across all runs. Qdrant's vary by 2-3x between runs at identical conditions, which is a reliability concern.
2. **Ecosystem fit**: Native LangChain integration, zero-config Python setup and direct compatibility with the existing FastAPI/SetenceTransformers stack.
3. **Development velocity**: The team estimated ~3 weeks saved compared to a custom implementation. Qdrant would not offer equivalent out-of-the-box integration.
4. **Qdrant's advantages don't apply here**: Faster indexing matters at high write volume, payload filtering matters at multi-tenant scale. Neither is a current requirement for the Horus.

## Files

| File | Purpose |
|---|---|
| `benchmark.py` | Runnable benchmark script |
| `README.md` | This file |
