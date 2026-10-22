"""
knowledge_retrieval_agent.py
----------------------------
This module defines the KnowledgeRetrievalAgent class, which retrieves data from a knowledge store (e.g., FAISS/ChromaDB).
It accepts a query and returns the corresponding data.
Supports async operations for non-blocking I/O.
"""

import inspect
import logging
from typing import Any

from ai_agents.step_emitter import emit_step

logger = logging.getLogger(__name__)


def _summarize_retrieved(data: Any) -> tuple[int, list[str], str]:
    """Best-effort summary of a knowledge-store response.

    Returns ``(chunk_count, doc_titles, preview)``. Knowledge-store responses
    are loose — handle the common ``{data: [...], sources: [...]}`` shape and
    fall back gracefully when chunks aren't structured.
    """
    chunk_count = 0
    doc_titles: list[str] = []
    preview = ""
    if not isinstance(data, dict):
        return chunk_count, doc_titles, preview

    chunks = data.get("data")
    passages = data.get("passages")
    if isinstance(passages, list) and passages:
        chunk_count = len(passages)
        for passage in passages:
            title = passage.get("title") if isinstance(passage, dict) else None
            if title and title not in doc_titles:
                doc_titles.append(str(title))
    elif isinstance(chunks, list):
        chunk_count = len(chunks)
        for c in chunks[:10]:
            if isinstance(c, dict):
                title = c.get("title") or c.get("filename") or c.get("source")
                if title and title not in doc_titles:
                    doc_titles.append(str(title))
    elif isinstance(chunks, str):
        chunk_count = 1 if chunks.strip() else 0
        preview = chunks[:240]

    sources = data.get("sources")
    if isinstance(sources, list):
        for s in sources:
            label = s.get("title") if isinstance(s, dict) else str(s)
            if label and label not in doc_titles:
                doc_titles.append(str(label))

    return chunk_count, doc_titles, preview


class KnowledgeRetrievalAgent:
    """
    Retrieves data from a knowledge store.
    Supports async operations.
    """

    def __init__(self, store_interface):
        """
        Args:
            store_interface: A callable (async or sync) that accepts a query (str) and returns data (dict).
        """
        self.store_interface = store_interface

    async def fetch(self, query: str) -> dict[str, Any]:
        """
        Retrieve data for a given query (async).

        Args:
            query: The search query string.

        Returns:
            A dictionary with the retrieved data.
        """
        logger.debug(f"KnowledgeRetrievalAgent: Fetching data for query='{query}'")
        query_preview = (query or "").strip()
        if len(query_preview) > 200:
            query_preview = query_preview[:200] + "…"
        emit_step(
            "retrieval.start",
            "Retrieving from knowledge store",
            f"Querying for: {query_preview}",
            query=query_preview,
        )
        try:
            # Check if store_interface is async (has __call__ that returns coroutine)
            result = self.store_interface(query)

            # If it's a coroutine, await it; otherwise return directly
            if inspect.isawaitable(result):
                data = await result
            else:
                data = result

            logger.info(
                f"KnowledgeRetrievalAgent result keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}"
            )

            chunk_count, doc_titles, preview = _summarize_retrieved(data)
            title_str = ", ".join(doc_titles[:3]) if doc_titles else "no source labels"
            if chunk_count:
                summary = f"{chunk_count} chunk(s) from {title_str}"
            elif preview:
                summary = f"Got context preview: {preview[:120]}"
            else:
                summary = "No matching content returned"
            emit_step(
                "retrieval.results",
                "Knowledge store responded",
                summary,
                chunk_count=chunk_count,
                chunks=doc_titles,
            )
            return data
        except Exception as e:
            logger.error(f"KnowledgeRetrievalAgent fetch failed: {e}", exc_info=True)
            emit_step(
                "error",
                "Knowledge store query failed",
                str(e),
                phase="retrieval",
            )
            raise e
