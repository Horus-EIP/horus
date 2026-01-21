#!/usr/bin/env python3
"""
MAS Performance Benchmark Suite

This script benchmarks key MAS operations:
- Agent registration and heartbeat
- Task creation and processing
- Conversation operations
- Database query performance

Usage:
    python benchmark_mas.py --url http://localhost:8000 --iterations 100

Requirements:
    pip install httpx asyncio statistics
"""

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass
from typing import List, Optional

import httpx


@dataclass
class BenchmarkResult:
    """Results from a benchmark run."""
    name: str
    iterations: int
    total_time: float
    mean_time: float
    median_time: float
    std_dev: float
    min_time: float
    max_time: float
    success_rate: float
    errors: List[str]


class MASBenchmark:
    """Benchmark suite for MAS API."""
    
    def __init__(self, base_url: str, token: str = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.results: List[BenchmarkResult] = []
    
    def _get_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
    
    async def authenticate(self, username: str, password: str) -> bool:
        """Authenticate and get token."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/auth/token",
                    data={"username": username, "password": password},
                    timeout=10.0
                )
                if response.status_code == 200:
                    self.token = response.json().get("access_token")
                    return True
            except Exception as e:
                print(f"Authentication failed: {e}")
        return False
    
    async def benchmark_health_check(self, iterations: int = 100) -> BenchmarkResult:
        """Benchmark health check endpoint (baseline latency)."""
        times = []
        errors = []
        successes = 0
        
        async with httpx.AsyncClient() as client:
            for _ in range(iterations):
                start = time.perf_counter()
                try:
                    response = await client.get(
                        f"{self.base_url}/rabbitmq/heartbeat",
                        headers=self._get_headers(),
                        timeout=5.0
                    )
                    if response.status_code == 200:
                        successes += 1
                except Exception as e:
                    errors.append(str(e))
                times.append(time.perf_counter() - start)
        
        return self._create_result("Health Check", iterations, times, successes, errors)
    
    async def benchmark_conversation_create(self, iterations: int = 50) -> BenchmarkResult:
        """Benchmark conversation creation."""
        times = []
        errors = []
        successes = 0
        
        async with httpx.AsyncClient() as client:
            for i in range(iterations):
                start = time.perf_counter()
                try:
                    response = await client.post(
                        f"{self.base_url}/conversations/create",
                        headers=self._get_headers(),
                        json={"name": f"Benchmark Conversation {i}"},
                        timeout=10.0
                    )
                    if response.status_code in [200, 201]:
                        successes += 1
                except Exception as e:
                    errors.append(str(e))
                times.append(time.perf_counter() - start)
        
        return self._create_result("Conversation Create", iterations, times, successes, errors)
    
    async def benchmark_conversation_list(self, iterations: int = 100) -> BenchmarkResult:
        """Benchmark conversation listing."""
        times = []
        errors = []
        successes = 0
        
        async with httpx.AsyncClient() as client:
            for _ in range(iterations):
                start = time.perf_counter()
                try:
                    response = await client.get(
                        f"{self.base_url}/conversations/all",
                        headers=self._get_headers(),
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        successes += 1
                except Exception as e:
                    errors.append(str(e))
                times.append(time.perf_counter() - start)
        
        return self._create_result("Conversation List", iterations, times, successes, errors)
    
    async def benchmark_agent_list(self, iterations: int = 100) -> BenchmarkResult:
        """Benchmark agent listing."""
        times = []
        errors = []
        successes = 0
        
        async with httpx.AsyncClient() as client:
            for _ in range(iterations):
                start = time.perf_counter()
                try:
                    response = await client.get(
                        f"{self.base_url}/agents/",
                        headers=self._get_headers(),
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        successes += 1
                except Exception as e:
                    errors.append(str(e))
                times.append(time.perf_counter() - start)
        
        return self._create_result("Agent List", iterations, times, successes, errors)
    
    async def benchmark_task_queue_stats(self, iterations: int = 100) -> BenchmarkResult:
        """Benchmark task queue statistics."""
        times = []
        errors = []
        successes = 0
        
        async with httpx.AsyncClient() as client:
            for _ in range(iterations):
                start = time.perf_counter()
                try:
                    response = await client.get(
                        f"{self.base_url}/tasks/stats/queue",
                        headers=self._get_headers(),
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        successes += 1
                except Exception as e:
                    errors.append(str(e))
                times.append(time.perf_counter() - start)
        
        return self._create_result("Task Queue Stats", iterations, times, successes, errors)
    
    def _create_result(
        self,
        name: str,
        iterations: int,
        times: List[float],
        successes: int,
        errors: List[str]
    ) -> BenchmarkResult:
        """Create a benchmark result from timing data."""
        if not times:
            times = [0.0]
        
        return BenchmarkResult(
            name=name,
            iterations=iterations,
            total_time=sum(times),
            mean_time=statistics.mean(times) * 1000,  # Convert to ms
            median_time=statistics.median(times) * 1000,
            std_dev=statistics.stdev(times) * 1000 if len(times) > 1 else 0,
            min_time=min(times) * 1000,
            max_time=max(times) * 1000,
            success_rate=(successes / iterations) * 100,
            errors=errors[:5]  # Keep only first 5 errors
        )
    
    async def run_all_benchmarks(self, iterations: int = 100) -> List[BenchmarkResult]:
        """Run all benchmarks."""
        print(f"\n{'='*60}")
        print("MAS Performance Benchmark Suite")
        print(f"{'='*60}")
        print(f"Base URL: {self.base_url}")
        print(f"Iterations: {iterations}")
        print(f"{'='*60}\n")
        
        benchmarks = [
            ("Health Check", self.benchmark_health_check),
            ("Conversation List", self.benchmark_conversation_list),
            ("Agent List", self.benchmark_agent_list),
            ("Task Queue Stats", self.benchmark_task_queue_stats),
            ("Conversation Create", self.benchmark_conversation_create),
        ]
        
        results = []
        for name, func in benchmarks:
            print(f"Running: {name}...", end=" ", flush=True)
            result = await func(iterations)
            results.append(result)
            print(f"Done ({result.mean_time:.2f}ms avg)")
        
        self.results = results
        return results
    
    def print_results(self):
        """Print benchmark results in a formatted table."""
        print(f"\n{'='*80}")
        print("BENCHMARK RESULTS")
        print(f"{'='*80}")
        print(f"{'Benchmark':<25} {'Mean (ms)':<12} {'Median':<12} {'Std Dev':<12} {'Success %':<10}")
        print(f"{'-'*80}")
        
        for result in self.results:
            print(
                f"{result.name:<25} "
                f"{result.mean_time:>10.2f} "
                f"{result.median_time:>10.2f} "
                f"{result.std_dev:>10.2f} "
                f"{result.success_rate:>8.1f}%"
            )
        
        print(f"{'-'*80}")
        print(f"\nMin/Max Latencies:")
        for result in self.results:
            print(f"  {result.name}: {result.min_time:.2f}ms - {result.max_time:.2f}ms")
        
        if any(r.errors for r in self.results):
            print(f"\nErrors encountered:")
            for result in self.results:
                if result.errors:
                    print(f"  {result.name}: {len(result.errors)} errors")
                    for error in result.errors[:3]:
                        print(f"    - {error[:80]}")
    
    def export_json(self, filename: str):
        """Export results to JSON file."""
        data = {
            "base_url": self.base_url,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "results": [
                {
                    "name": r.name,
                    "iterations": r.iterations,
                    "mean_ms": r.mean_time,
                    "median_ms": r.median_time,
                    "std_dev_ms": r.std_dev,
                    "min_ms": r.min_time,
                    "max_ms": r.max_time,
                    "success_rate": r.success_rate,
                }
                for r in self.results
            ]
        }
        
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nResults exported to: {filename}")


async def main():
    parser = argparse.ArgumentParser(description="MAS Performance Benchmark Suite")
    parser.add_argument("--url", default="http://localhost:8000", help="MAS API URL")
    parser.add_argument("--iterations", type=int, default=100, help="Number of iterations per benchmark")
    parser.add_argument("--username", default="admin", help="Username for authentication")
    parser.add_argument("--password", default="admin", help="Password for authentication")
    parser.add_argument("--output", default="benchmark_results.json", help="Output JSON file")
    
    args = parser.parse_args()
    
    benchmark = MASBenchmark(args.url)
    
    # Authenticate
    print(f"Authenticating as {args.username}...")
    if await benchmark.authenticate(args.username, args.password):
        print("Authentication successful")
    else:
        print("Warning: Authentication failed, some benchmarks may fail")
    
    # Run benchmarks
    await benchmark.run_all_benchmarks(args.iterations)
    
    # Print and export results
    benchmark.print_results()
    benchmark.export_json(args.output)


if __name__ == "__main__":
    asyncio.run(main())
