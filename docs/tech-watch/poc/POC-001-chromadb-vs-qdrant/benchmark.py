import time
import uuid
import statistics

# Dependency check
try:
    import chromadb
except ImportError:
    raise SystemExit("Missing: pip install chromadb")

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct
except ImportError:
    raise SystemExit("Missing: pip install qdrant-client")

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    raise SystemExit("Missing: pip install sentence-transformers")

# Configuration
N_DOCS = 100
N_QUERIES = 10
N_ROUNDS = 5
MODEL = "BAAI/bge-base-en-v1.5"
DIM = 768
COLLECTION = "poc_bench"

# Sample data
DOCS = [
    f"Document {i}: This is a sample text about topic {i % 10} with additional context for embedding evaluation."
    for i in range(N_DOCS)
]

QUERIES = [
    f"Find information about topic {i}"
    for i in range(N_QUERIES)
]

print("Loading embedding model...")
model = SentenceTransformer(MODEL)

print("Encoding documents...")
doc_embeddings = model.encode(DOCS, show_progress_bar=False).tolist()
print("Encoding queries...")
query_embeddings = model.encode(QUERIES, show_progress_bar=False).tolist()

# ChromaDB
# print("\n--- ChromaDB ---")

def run_chroma_round():
    chroma_client = chromadb.Client()

    try:
        chroma_client.delete_collection(COLLECTION)
    except Exception:
        pass

    chroma_collection = chroma_client.create_collection(name=COLLECTION)

    start = time.perf_counter()

    chroma_collection.add(
        ids=[str(i) for i in range(N_DOCS)],
        embeddings=doc_embeddings,
        documents=DOCS
    )
    chroma_index_ms = (time.perf_counter() - start) * 1000
    # print(f" Indexing {N_DOCS} documents: {chroma_index_ms:.1f} ms")

    chroma_latencies = []
    for query in query_embeddings:
        start = time.perf_counter()
        chroma_collection.query(
            query_embeddings=[query],
            n_results=5
        )
        chroma_latencies.append((time.perf_counter() - start) * 1000)
    
    return chroma_index_ms, chroma_latencies

# print(f" Query avg: {statistics.mean(chroma_latencies):.2f} ms")
# print(f" Query p95: {sorted(chroma_latencies)[int(0.95*N_QUERIES)]:.2f} ms")

# Qdrant
# print("\n--- Qdrant ---")

def run_qdrant_round():
    qdrant_client = QdrantClient(":memory:")
    qdrant_client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=DIM, distance=Distance.COSINE)
    )

    start = time.perf_counter()
    qdrant_client.upsert(
        collection_name=COLLECTION,
        points=[
            PointStruct(id=i, vector=doc_embeddings[i], payload={"text": DOCS[i]})
            for i in range(N_DOCS)
        ]
    )
    qdrant_index_ms = (time.perf_counter() - start) * 1000
    # print(f" Indexing {N_DOCS} documents: {qdrant_index_ms:.1f} ms")

    qdrant_latencies = []
    for query in query_embeddings:
        start = time.perf_counter()
        qdrant_client.query_points(
            collection_name=COLLECTION,
            query=query,
            limit=5
        )
        qdrant_latencies.append((time.perf_counter() - start) * 1000)
    
    return qdrant_index_ms, qdrant_latencies

# print(f" Query avg: {statistics.mean(qdrant_latencies):.2f} ms")
# print(f" Query p95: {sorted(qdrant_latencies)[int(0.95*N_QUERIES)]:.2f} ms")

# Summary
# print("\n--- Summary ---")

# print(f"{'Metric':<25} {'ChromaDB':>12} {'Qdrant':>12}")
# print(f"{'-'*50}")
# print(f"{'Index time (ms)':<25} {chroma_index_ms:>11.1f} {qdrant_index_ms:>11.1f}")
# print(f"{'Query avg (ms)':<25} {statistics.mean(chroma_latencies):>11.2f} {statistics.mean(qdrant_latencies):>11.2f}")
# print(f"{'Query p95 (ms)':<25} {sorted(chroma_latencies)[int(0.95*N_QUERIES)]:>11.2f} {sorted(qdrant_latencies)[int(0.95*N_QUERIES)]:>11.2f}")

# winner = "Qdrant" if statistics.mean(qdrant_latencies) < statistics.mean(chroma_latencies) else "ChromaDB"

# print(f"\n Faster query engine: \033[92m{winner}\033[0m")

# Run rounds
print(f"\nRunning {N_ROUNDS} rounds to reduce noise...")

chroma_index_times, chroma_query_latencies, chroma_p95s = [], [], []
qdrant_index_times, qdrant_query_latencies, qdrant_p95s = [], [], []

for i in range(N_ROUNDS):
    chroma_index_ms, chroma_latencies = run_chroma_round()
    qdrant_index_ms, qdrant_latencies = run_qdrant_round()

    chroma_index_times.append(chroma_index_ms)
    chroma_query_latencies.append(statistics.mean(chroma_latencies))
    chroma_p95s.append(sorted(chroma_latencies)[int(0.95*N_QUERIES)])

    qdrant_index_times.append(qdrant_index_ms)
    qdrant_query_latencies.append(statistics.mean(qdrant_latencies))
    qdrant_p95s.append(sorted(qdrant_latencies)[int(0.95*N_QUERIES)])

    print(f"  Round {i+1}/{N_ROUNDS} - Chroma query avg: {statistics.mean(chroma_latencies):.2f} ms | Qdrant query avg: {statistics.mean(qdrant_latencies):.2f} ms")

# Summary
print("\n--- Summary ---")
print(f"{'Metric':<30} {'ChromaDB':>12} {'Qdrant':>12}")
print(f"{'-'*55}")

chroma_avg = statistics.mean(chroma_query_latencies)
qdrant_avg = statistics.mean(qdrant_query_latencies)
chroma_p95_avg = statistics.mean(chroma_p95s)
qdrant_p95_avg = statistics.mean(qdrant_p95s)

print(f"{'Index time (ms)':<30} {statistics.mean(chroma_index_times):>11.1f} {statistics.mean(qdrant_index_times):>11.1f}")
print(f"{'Query avg (ms)':<30} {chroma_avg:>11.2f} {qdrant_avg:>11.2f}")
print(f"{'Query p95 (ms)':<30} {chroma_p95_avg:>11.2f} {qdrant_p95_avg:>11.2f}")

avg_winner = "Qdrant" if qdrant_avg < chroma_avg else "ChromaDB"
diff_percent = abs(qdrant_avg - chroma_avg) / max(chroma_avg, qdrant_avg) * 100
noise_note = " (within noise at 100 docs)" if diff_percent < 10 else ""
print(f"  Query average winner: \033[92m{avg_winner}\033[0m{noise_note}")

p95_winner = "Qdrant" if qdrant_p95_avg < chroma_p95_avg else "ChromaDB"
p95_diff_percent = abs(qdrant_p95_avg - chroma_p95_avg) / max(chroma_p95_avg, qdrant_p95_avg) * 100
print(f"  p95 winner: \033[92m{p95_winner}\033[0m ({p95_diff_percent:.1f}% margin - more reliable signal)")