# POC-002 - RabbitMQ vs Redis Streams

## What was tested

A throughput and latency comparison between RabbitMQ and Redis Streams.

| | RabbitMQ 3 | Redis Streams (Redis 7) |
|---|---|---|
| Protocol | AMQP 0-9-1 (via `pika`) | Redis protocol (via `redis-py`) |
| Message count | 1 000 | 1 000 |
| Payload size | 512 bytes | 512 bytes |
| Delivery model | Queue + ACK | Consumer group + ACK |
| Persistence | Non-durable (speed focus) | In-memory (speed focus) |

## How to run

```bash
# Start RabbitMQ and Redis (Docker required)
docker run -d --name rabbit -p 5672:5672 rabbitmq:3
docker run -d --name redis -p 6379:6379 redis:7

# Install Python dependencies
pip install pika redis

# Run the benchmark
python benchmark.py
```

## What was found

Observed results (1000 messages, 512 bytes payload, loopback):

| Metric | RabbitMQ | Redis Streams | Winner |
|---|---|---|---|
| Throughput | ~5 900 msg/s | ~38 700 msg/s | **Redis Streams** (~6.5×) |
| Avg latency | ~0.268 ms | ~0.034 ms | **Redis Streams** (~8×) |

Key observations:

- **Redis Streams is ~6.5x higher throughput**: driven by pipeline batching and the absence of AMQP framing overhead.
- **Latency difference is unambiguous**: 0.034ms vs 0.268ms, with Redis operating directly on an in-memory data structure, while RabbitMQ incurs AMQP framing + broker routing per message even on loopback. This is protocol cost, not network cost.
- **These results are consistent and reproducible**: unlike POC-001, this is not within noise margin. Redis Streams wins on raw throughput and latency in every run.
- **However, throughput was the wrong primary metric for this use case**: see conclusion below.

## What the benchmark does NOT measure

The benchmark measured raw publish/consume throughput with non-durable queues and no routing logic. The actual production use case ([ADR-001: RabbitMQ](architecture/ADR-001-rabbitmq.md)) has different requirements that this synthetic test does not capture:

- **Message durability across restarts**: RabbitMQ with durable queues persists messages to disk natively. Redis persistence (AOF/RDB) requires explicit configuration and is not enabled by default.
- **Semantic routing to specific agents**: RabbitMQ AMQP exchanges allow routing rules (direct, topic, fanout) with zero application code. Redis Streams is an append-only log, routing to different consumer groups requires more manual logic.
- **Dead-letter queues and automatic retry**: If an agent crashes mid.processing, RabbitMQ automatically requeues the message. With Redis Streams this must be implemented at the application layer via `XPENDING` + `XCLAIM`.
- **Real bottleneck is LLM inference, not the broker**: Agent tasks involve LLM requests that take seconds. At 5900msg/s, RabbitMQ is orders of magnitude faster than the actual workload demands.

## Conclusion

**Benchmark winner: Redis Streams** (throughput and latency).
**Correct choice for this project: RabbitMQ**, for reasons the benchmark did not test.

The team's decision to use RabbitMQ is well founded. For a task queue distributing work to autonomous LLM agents, the decisive criteria are durability, routing semantics and fault recovery, not raw throughput. RabbitMQ addresses all three natively, while Redis Streams would require significant application-level implementation to match them.

## Files

| File | Purpose |
|---|---|
| `benchmark.py` | Runnable benchmark script (~100 lines, graceful fallback) |
| `README.md` | This file |