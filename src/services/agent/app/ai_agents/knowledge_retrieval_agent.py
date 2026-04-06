"""
knowledge_retrieval_agent.py
----------------------------
This module defines the KnowledgeRetrievalAgent class, which retrieves data from a knowledge store (e.g., FAISS/ChromaDB).
It accepts a query and returns the corresponding data.
Supports async operations for non-blocking I/O.
"""

from typing import Dict, Any
import logging
import inspect

logger = logging.getLogger(__name__)


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

    async def fetch(self, query: str) -> Dict[str, Any]:
        """
        Retrieve data for a given query (async).

        Args:
            query: The search query string.

        Returns:
            A dictionary with the retrieved data.
        """
        logger.debug(f"KnowledgeRetrievalAgent: Fetching data for query='{query}'")
        try:
            # Check if store_interface is async (has __call__ that returns coroutine)
            result = self.store_interface(query)

            # If it's a coroutine, await it; otherwise return directly
            if inspect.isawaitable(result):
                data = await result
            else:
                data = result
            
            logger.info(f"KnowledgeRetrievalAgent result keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
            return data
        except Exception as e:
            logger.error(f"KnowledgeRetrievalAgent fetch failed: {e}", exc_info=True)
            raise e
