import time
import statistics
import threading

try:
    import pika
except ImportError:
    raise SystemExit("Missing: pip install pika")

try:
    import redis
except ImportError:
    raise SystemExit("Missing: pip install redis")

# Configuration
N_MESSAGES = 1000
PAYLOAD = b"x" * 512
RMQ_QUEUE = "poc_queue"
REDIS_STREAM = "poc:stream"
REDIS_GROUP = "poc_group"
REDIS_CONSUMER = "worker-1"

# RabbitMQ
def bench_rabbitmq():
    print("\n--- RabbitMQ ---")

    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
    except Exception as e:
        print(f"  Could not connect: {e}")
        print("  Start RabbitMQ: docker run -d --name rabbit -p 5672:5672 rabbitmq:3")
        return None, None
    
    channel = connection.channel()
    channel.queue_declare(queue=RMQ_QUEUE, durable=False, arguments={"x-expires": 60000})

    # Publish
    start = time.perf_counter()
    for _ in range(N_MESSAGES):
        channel.basic_publish(exchange="", routing_key=RMQ_QUEUE, body=PAYLOAD)
    
    publish_time = time.perf_counter() - start
    throughput = N_MESSAGES / publish_time

    # Consume
    latencies = []
    received = [0]

    def on_message(ch, method, properties, body):
        latencies.append((time.perf_counter() - start) * 1000 / N_MESSAGES)
        received[0] += 1
        ch.basic_ack(method.delivery_tag)
        if received[0] >= N_MESSAGES:
            ch.stop_consuming()
    
    channel.basic_qos(prefetch_count=100)
    channel.basic_consume(queue=RMQ_QUEUE, on_message_callback=on_message)
    channel.start_consuming()
    connection.close()

    avg_latency = statistics.mean(latencies) if latencies else 0
    print(f"  Throughput: {throughput:>8.0f} msg/s")
    print(f"  Avg latency: {avg_latency:>8.3f} ms")
    return throughput, avg_latency

# Redis Streams
def bench_redis_streams():
    print("\n--- Redis Streams ---")

    try:
        r = redis.Redis(host="localhost", port=6379, decode_responses=False)
        r.ping()
    except Exception as e:
        print(f"  Could not connect: {e}")
        print("  Start Redis: docker run -d --name redis -p 6379:6379 redis:7")
        return None, None
    
    # Clean up previous run
    r.delete(REDIS_STREAM)

    try:
        r.xgroup_create(REDIS_STREAM, REDIS_GROUP, id="0", mkstream=True)
    except redis.exceptions.ResponseError:
        pass
    
    # Publish
    start = time.perf_counter()
    pipe = r.pipeline(transaction=False)
    for i in range(N_MESSAGES):
        pipe.xadd(REDIS_STREAM, {"data": PAYLOAD, "seq": i})
        if i % 200 == 0:
            pipe.execute()
    
    pipe.execute()
    publish_time = time.perf_counter() - start
    throughput = N_MESSAGES / publish_time

    # Consume
    latencies = []
    received = 0
    t_start = time.perf_counter()
    while received < N_MESSAGES:
        entries = r.xreadgroup(REDIS_GROUP, REDIS_CONSUMER, {REDIS_STREAM: ">"}, count=100, block=500)
        if not entries:
            break
        for _stream, msgs in entries:
            ids = [msg_id for msg_id, _ in msgs]
            r.xack(REDIS_STREAM, REDIS_GROUP, *ids)
            received += len(msgs)
            latencies.append((time.perf_counter() - t_start) * 1000 / max(received, 1))
    
    avg_latency = statistics.mean(latencies) if latencies else 0
    print(f"  Throughput: {throughput:>8.0f} msg/s")
    print(f"  Avg latency: {avg_latency:>8.3f} ms")
    r.delete(REDIS_STREAM)
    return throughput, avg_latency

# Run & Summary

rmq_tp, rmq_lat = bench_rabbitmq()
redis_tp, redis_lat = bench_redis_streams()

print("\n--- Summary ---")
print(f"  {'Metric':<28} {'RabbitMQ':>14} {'Redis Streams':>14}")
print(f"  {'-'*56}")

def fmt_tp(v):
    return f"{v:>14.0f}" if v else "N/A"

def fmt_lat(v):
    return f"{v:>14.3f}" if v else "N/A"

print(f"  {'Throughput (msg/s)':<28} {fmt_tp(rmq_tp)} {fmt_tp(redis_tp)}")
print(f"  {'Avg Latency (ms)':<28} {fmt_lat(rmq_lat)} {fmt_lat(redis_lat)}")

if redis_tp and rmq_tp:
    winner = "Redis Streams" if redis_tp > rmq_tp else "RabbitMQ"
    print(f"\n  Higher throughput: {winner}")