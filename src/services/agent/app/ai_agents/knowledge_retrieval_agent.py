"""
knowledge_retrieval_agent.py
----------------------------
This module defines the KnowledgeRetrievalAgent class, which retrieves data from a knowledge store (e.g., FAISS/ChromaDB).
It accepts a query and returns the corresponding data.
"""

from typing import Dict, Any


class KnowledgeRetrievalAgent:
    """
    Retrieves data from a knowledge store.
    """

    def __init__(self, store_interface):
        """
        Args:
            store_interface: A callable that accepts a query (str) and returns data (dict).
        """
        self.store_interface = store_interface

    def fetch(self, query: str) -> Dict[str, Any]:
        """
        Retrieve data for a given query.

        Args:
            query: The search query string.

        Returns:
            A dictionary with the retrieved data.
        """
        print(f"[KnowledgeRetrievalAgent] Fetching data for query: '{query}'")
        return self.store_interface(query)
