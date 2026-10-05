import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

KNOWLEDGE_STORE_ROOT = Path(__file__).resolve().parents[2] / "src" / "services" / "knowledge-store"
DEFAULT_QUERIES = (
    "how to setup docker for ethereum?",
    "live block explorer ethereum network transactions",
    "What is the MGMT 451 course about?",
)
DEFAULT_TOP = 5
PREVIEW_CHARS = 100


def knowledge_store_setup():
    if str(KNOWLEDGE_STORE_ROOT) not in sys.path:
        sys.path.insert(0, str(KNOWLEDGE_STORE_ROOT))
    from app.chroma_db import setup

    return setup


def ranked_passages(
    query: str, collection, embed: Callable[..., list[float]], top: int
) -> list[tuple[float, str, str]]:
    results = collection.query(
        query_embeddings=[embed(query, is_query=True)],
        n_results=top,
        include=["documents", "distances"],
    )
    return [
        (1 - distance, passage_id, document)
        for passage_id, document, distance in zip(
            results["ids"][0], results["documents"][0], results["distances"][0], strict=True
        )
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/perf/retrieval-quality.py",
        description=(
            "Embed each query with the knowledge store's own embedder (FastEmbed BGE, "
            "query prefix included) and print the closest passages with their scores."
        ),
    )
    parser.add_argument("queries", nargs="*", help="Queries to run (default: a fixed set).")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="Passages per query.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    setup = knowledge_store_setup()
    print(f"Model: {setup.EMBED_MODEL}\n")
    for query in args.queries or DEFAULT_QUERIES:
        print(f"Query: {query}")
        for score, passage_id, document in ranked_passages(
            query, setup.knowledge_collection, setup.get_embedding, args.top
        ):
            print(f"\t(Score: {score:.4f}) {passage_id} {document[:PREVIEW_CHARS]}...")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
