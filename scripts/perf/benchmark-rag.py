#!/usr/bin/env python3
"""
RAG Pipeline Performance Benchmark

Benchmarks the Knowledge Store HTTP API (RAG backing service):
- GET /health
- POST / — add text document (id, title, content, size)
- GET /?query=&n_results= — vector query

Usage:
    python benchmark_rag.py --url http://localhost:8080 --iterations 50

Requirements:
    pip install httpx asyncio statistics
"""

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass

import httpx


@dataclass
class RAGBenchmarkResult:
    """Results from a RAG benchmark run."""
    name: str
    iterations: int
    mean_time_ms: float
    median_time_ms: float
    p95_time_ms: float
    p99_time_ms: float
    min_time_ms: float
    max_time_ms: float
    success_rate: float
    avg_results_count: float


class RAGBenchmark:
    """Benchmark suite for RAG pipeline."""

    def __init__(self, knowledge_store_url: str):
        self.ks_url = knowledge_store_url.rstrip("/")
        self.results: list[RAGBenchmarkResult] = []

    async def benchmark_query(
        self,
        iterations: int = 50,
        queries: list[str] = None
    ) -> RAGBenchmarkResult:
        """Benchmark knowledge store queries."""
        if queries is None:
            queries = [
                "What is the quarterly revenue?",
                "Tell me about sales performance",
                "What are the key metrics?",
                "Summarize the financial report",
                "What is the growth rate?",
            ]

        times = []
        results_counts = []
        successes = 0

        async with httpx.AsyncClient() as client:
            for i in range(iterations):
                query = queries[i % len(queries)]
                start = time.perf_counter()
                try:
                    # Knowledge store: GET /?query=&n_results= (see knowledge-store app/api/routes/store.py)
                    response = await client.get(
                        f"{self.ks_url}/",
                        params={"query": query, "n_results": 5},
                        timeout=30.0,
                    )
                    elapsed = time.perf_counter() - start
                    times.append(elapsed)

                    if response.status_code == 200:
                        successes += 1
                        data = response.json()
                        docs = data.get("documents") or [[]]
                        results_counts.append(len(docs[0]) if docs and docs[0] else 0)
                    elif response.status_code == 404:
                        # Valid response when the store has no matches
                        successes += 1
                        results_counts.append(0)
                    else:
                        results_counts.append(0)
                except Exception as e:
                    times.append(time.perf_counter() - start)
                    results_counts.append(0)
                    print(f"  Query error: {e}")

        return self._create_result(
            "Knowledge Store Query",
            iterations,
            times,
            successes,
            results_counts
        )

    async def benchmark_document_add(
        self,
        iterations: int = 20
    ) -> RAGBenchmarkResult:
        """Benchmark document addition."""
        times = []
        successes = 0

        async with httpx.AsyncClient() as client:
            for i in range(iterations):
                content = (
                    f"This is benchmark document {i} with some sample content for testing purposes. " * 10
                )
                doc = {
                    "id": f"benchmark_doc_{i}_{time.time()}",
                    "title": f"Benchmark Document {i}",
                    "content": content,
                    "size": len(content),
                }

                start = time.perf_counter()
                try:
                    response = await client.post(
                        f"{self.ks_url}/",
                        json=doc,
                        timeout=30.0,
                    )
                    if response.status_code in [200, 201]:
                        successes += 1
                except Exception as e:
                    print(f"  Add error: {e}")
                times.append(time.perf_counter() - start)

        return self._create_result(
            "Document Add",
            iterations,
            times,
            successes,
            [1] * iterations
        )

    async def benchmark_health_check(self, iterations: int = 100) -> RAGBenchmarkResult:
        """Benchmark health check (baseline latency)."""
        times = []
        successes = 0

        async with httpx.AsyncClient() as client:
            for _ in range(iterations):
                start = time.perf_counter()
                try:
                    response = await client.get(
                        f"{self.ks_url}/health",
                        timeout=5.0
                    )
                    if response.status_code == 200:
                        successes += 1
                except Exception:
                    pass
                times.append(time.perf_counter() - start)

        return self._create_result(
            "Health Check",
            iterations,
            times,
            successes,
            [0] * iterations
        )

    def _create_result(
        self,
        name: str,
        iterations: int,
        times: list[float],
        successes: int,
        results_counts: list[int]
    ) -> RAGBenchmarkResult:
        """Create a benchmark result."""
        if not times:
            times = [0.0]

        times_ms = [t * 1000 for t in times]
        sorted_times = sorted(times_ms)

        p95_idx = int(len(sorted_times) * 0.95)
        p99_idx = int(len(sorted_times) * 0.99)

        return RAGBenchmarkResult(
            name=name,
            iterations=iterations,
            mean_time_ms=statistics.mean(times_ms),
            median_time_ms=statistics.median(times_ms),
            p95_time_ms=sorted_times[min(p95_idx, len(sorted_times) - 1)],
            p99_time_ms=sorted_times[min(p99_idx, len(sorted_times) - 1)],
            min_time_ms=min(times_ms),
            max_time_ms=max(times_ms),
            success_rate=(successes / iterations) * 100,
            avg_results_count=statistics.mean(results_counts) if results_counts else 0
        )

    async def run_all_benchmarks(self, iterations: int = 50) -> list[RAGBenchmarkResult]:
        """Run all RAG benchmarks."""
        print(f"\n{'='*60}")
        print("RAG Pipeline Performance Benchmark")
        print(f"{'='*60}")
        print(f"Knowledge Store URL: {self.ks_url}")
        print(f"Iterations: {iterations}")
        print(f"{'='*60}\n")

        results = []

        print("Running: Health Check...", end=" ", flush=True)
        result = await self.benchmark_health_check(iterations)
        results.append(result)
        print(f"Done ({result.mean_time_ms:.2f}ms avg)")

        print("Running: Document Add...", end=" ", flush=True)
        result = await self.benchmark_document_add(min(iterations, 20))
        results.append(result)
        print(f"Done ({result.mean_time_ms:.2f}ms avg)")

        print("Running: Knowledge Store Query...", end=" ", flush=True)
        result = await self.benchmark_query(iterations)
        results.append(result)
        print(f"Done ({result.mean_time_ms:.2f}ms avg)")

        self.results = results
        return results

    def print_results(self):
        """Print benchmark results."""
        print(f"\n{'='*90}")
        print("RAG BENCHMARK RESULTS")
        print(f"{'='*90}")
        print(f"{'Benchmark':<25} {'Mean':<10} {'Median':<10} {'P95':<10} {'P99':<10} {'Success':<10}")
        print(f"{'-'*90}")

        for r in self.results:
            print(
                f"{r.name:<25} "
                f"{r.mean_time_ms:>8.2f}ms "
                f"{r.median_time_ms:>8.2f}ms "
                f"{r.p95_time_ms:>8.2f}ms "
                f"{r.p99_time_ms:>8.2f}ms "
                f"{r.success_rate:>7.1f}%"
            )

        print(f"{'-'*90}")

        # Query-specific stats
        for r in self.results:
            if "Query" in r.name and r.avg_results_count > 0:
                print(f"\n{r.name} - Avg results per query: {r.avg_results_count:.1f}")

    def export_json(self, filename: str):
        """Export results to JSON."""
        data = {
            "knowledge_store_url": self.ks_url,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "results": [
                {
                    "name": r.name,
                    "iterations": r.iterations,
                    "mean_ms": r.mean_time_ms,
                    "median_ms": r.median_time_ms,
                    "p95_ms": r.p95_time_ms,
                    "p99_ms": r.p99_time_ms,
                    "min_ms": r.min_time_ms,
                    "max_ms": r.max_time_ms,
                    "success_rate": r.success_rate,
                    "avg_results": r.avg_results_count,
                }
                for r in self.results
            ]
        }

        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nResults exported to: {filename}")


async def main():
    parser = argparse.ArgumentParser(description="RAG Pipeline Benchmark")
    parser.add_argument("--url", default="http://localhost:8080", help="Knowledge Store URL")
    parser.add_argument("--iterations", type=int, default=50, help="Iterations per benchmark")
    parser.add_argument("--output", default="rag_benchmark_results.json", help="Output JSON file")

    args = parser.parse_args()

    benchmark = RAGBenchmark(args.url)
    await benchmark.run_all_benchmarks(args.iterations)
    benchmark.print_results()
    benchmark.export_json(args.output)


if __name__ == "__main__":
    asyncio.run(main())
