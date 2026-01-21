# Performance Benchmark Suite

This directory contains performance benchmark scripts for the Horus system.

## Benchmarks

### MAS API Benchmark (`benchmark_mas.py`)

Benchmarks the Multi-Agent System API:
- Health check latency (baseline)
- Conversation creation and listing
- Agent listing
- Task queue statistics

```bash
# Install dependencies
pip install httpx

# Run benchmarks
python benchmark_mas.py --url http://localhost:8000 --iterations 100

# With authentication
python benchmark_mas.py --url http://localhost:8000 --username admin --password admin

# Export results
python benchmark_mas.py --output my_results.json
```

### RAG Pipeline Benchmark (`benchmark_rag.py`)

Benchmarks the RAG (Retrieval-Augmented Generation) pipeline:
- Knowledge Store health check
- Document addition
- Query performance

```bash
python benchmark_rag.py --url http://localhost:8080 --iterations 50
```

## Baseline Metrics

Expected baseline performance targets:

| Metric | Target | Notes |
|--------|--------|-------|
| Health Check | < 10ms | Baseline network latency |
| Conversation List | < 50ms | Database query |
| Agent List | < 50ms | Database query |
| Task Queue Stats | < 100ms | Aggregation query |
| Knowledge Store Query | < 500ms | Vector search + embedding |
| Document Add | < 1000ms | Embedding generation |

## Output Format

Results are exported as JSON:

```json
{
  "base_url": "http://localhost:8000",
  "timestamp": "2026-01-12T10:00:00Z",
  "results": [
    {
      "name": "Health Check",
      "iterations": 100,
      "mean_ms": 5.23,
      "median_ms": 4.87,
      "p95_ms": 8.12,
      "p99_ms": 12.45,
      "success_rate": 100.0
    }
  ]
}
```

## Running in CI

For CI/CD pipelines:

```bash
# Run all benchmarks with default settings
python benchmark_mas.py && python benchmark_rag.py

# Check for performance regressions
# Compare against baseline in benchmark_baseline.json
```
