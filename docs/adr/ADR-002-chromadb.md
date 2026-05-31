# ADR-002: Selection of ChromaDB for Vector Search and RAG Pipeline

**Date:** 2026-04-14
**Status:** Accepted

## Context
Depending on the question asked to the agent, we needed a robust way to retrieve the most relevant contextual data from our documents (RAG). The challenge was finding the right balance between the integration complexity and the desired level of search efficiency. Furthermore, security and data privacy were critical requirements: we needed a 100% local solution that did not rely on external cloud providers, while remaining fully compatible with our AI models and Python backend (FastAPI/SentenceTransformers).

## Decision
We selected **ChromaDB** as our local vector database to power the Knowledge Store component.

## Consequences
**Pros:**
- **Low learning curve:** Extremely simple to understand and integrate for the team.
- **Great ecosystem fit:** Highly compatible with our Python stack and easy to combine with local Hugging Face models.
- **Privacy by design:** Fully open-source solution with zero reliance on cloud services.
- **Performance evidence:** The Comparative Tech Brief demonstrates local query latency of `<50ms` for 1M vectors. During testing (BTP F12), 92% of queries (23/25) successfully returned results in under 3 seconds.
- **Time saved:** Native LangChain integration saved approximately 3 weeks of development time compared to building a custom vector search.

**Cons / Accepted Risks:**
- **At-scale efficiency:** A potential degradation of performance and search latency could be observed over long periods in a large enterprise deployment.
- **Load limits:** Can struggle with stability under extremely heavy concurrent indexing or querying loads compared to distributed alternatives.

## Alternatives considered
- **Weaviate:** Rejected. While it offers powerful hybrid search capabilities, its schema management and architecture were overly complex for our immediate MVP needs.
- **Qdrant:** Rejected. A very fast vector database written in Rust, but it requires more configuration and operational overhead compared to the plug-and-play nature of Chroma.
- **pgvector:** Rejected. Although it unifies vector storage with our existing PostgreSQL database, it lacks the specialized, out-of-the-box RAG features and optimizations provided by a dedicated vector database like ChromaDB.
