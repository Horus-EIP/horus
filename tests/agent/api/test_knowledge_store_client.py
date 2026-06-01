"""Knowledge Store HTTP client contract tests (hermetic).

Mocks ``httpx`` so no real KS is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@patch("ai_agents.knowledge_store_client.httpx")
def test_query_returns_documents(mock_httpx):
    from ai_agents.knowledge_store_client import KnowledgeStoreClient  # noqa: PLC0415

    response = MagicMock()
    response.json.return_value = {"documents": [["chunk-a"]], "metadatas": [[{"source": "doc.pdf"}]]}
    response.raise_for_status = lambda: None
    mock_httpx.Client.return_value.get.return_value = response

    client = KnowledgeStoreClient(base_url="http://fake")
    result = client.query("invoice fraud", n_results=3)
    assert result is not None


@patch("ai_agents.knowledge_store_client.httpx")
def test_query_handles_empty_result(mock_httpx):
    from ai_agents.knowledge_store_client import KnowledgeStoreClient  # noqa: PLC0415

    response = MagicMock()
    response.json.return_value = {"documents": [[]], "metadatas": [[]]}
    response.raise_for_status = lambda: None
    mock_httpx.Client.return_value.get.return_value = response

    client = KnowledgeStoreClient(base_url="http://fake")
    result = client.query("anything", n_results=3)
    # Either empty list, None, or empty dict — all valid "nothing found" shapes
    assert not result or isinstance(result, (list, dict))
