"""
This script tests the retrieval quality of the knowledge store by running a set of queries and printing the retrieved documents along with their similarity scores.

Usage:
    python scripts/perf/retrieval-quality.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src/services/knowledge-store"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src/services/knowledge-store/app"))

from chroma_db.setup import BGE_QUERY_PREFIX, knowledge_collection, model

TEST_QUERIES = [
    "how to setup docker for ethereum?",
    "live block explorer ethereum network transactions",
    "What is the MGMT 451 course about?",
]

print(f"Model: {model._modules}\n")

for query in TEST_QUERIES:
    prefixed = BGE_QUERY_PREFIX + query
    embedding = model.encode(prefixed, normalize_embeddings=True).tolist()

    results = knowledge_collection.query(
        query_embeddings=[embedding],
        n_results=5,
        include=["documents", "distances"]
    )

    print(f"Query: {query}")

    for doc, dist in zip(results["documents"][0], results["distances"][0], strict=False):
        score = 1 - dist
        print(f"\t(Score: {score:.4f}) {doc[:100]}...")

    print()
