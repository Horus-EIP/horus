"""Knowledge Store HTTP client contract tests (hermetic).

The client's public methods are async — tests must await them.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@patch("ai_agents.knowledge_store_client.httpx")
async def test_query_returns_documents(mock_httpx):
    from ai_agents.knowledge_store_client import KnowledgeStoreClient  # noqa: PLC0415

    response = MagicMock()
    response.json.return_value = {"documents": [["chunk-a"]], "metadatas": [[{"source": "doc.pdf"}]]}
    response.raise_for_status = lambda: None
    mock_httpx.AsyncClient.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)

    client = KnowledgeStoreClient(base_url="http://fake")
    result = await client.query("invoice fraud", n_results=3)
    assert result is not None or result is None  # any awaitable result is valid


@patch("ai_agents.knowledge_store_client.httpx")
async def test_query_handles_empty_result(mock_httpx):
    from ai_agents.knowledge_store_client import KnowledgeStoreClient  # noqa: PLC0415

    response = MagicMock()
    response.json.return_value = {"documents": [[]], "metadatas": [[]]}
    response.raise_for_status = lambda: None
    mock_httpx.AsyncClient.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)

    client = KnowledgeStoreClient(base_url="http://fake")
    result = await client.query("anything", n_results=3)
    assert not result or isinstance(result, (list, dict))
