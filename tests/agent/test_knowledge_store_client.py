"""
Tests for KnowledgeStoreClient
Tests success paths, timeout handling, HTTP status branches, and error scenarios.
Supports async testing.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import httpx
from ai_agents.knowledge_store_client import (
    KnowledgeStoreClient,
    extract_probable_filename_from_query,
)


class TestExtractProbableFilename:
    """Filename hints in user queries (knowledge store resolve-by-name)."""

    def test_bare_filename_with_extension(self):
        assert (
            extract_probable_filename_from_query("summarize the file test_horus.txt")
            == "test_horus.txt"
        )

    def test_quoted_filename(self):
        assert extract_probable_filename_from_query('read "notes v2.pdf" please') == "notes v2.pdf"

    def test_file_keyword_prefix(self):
        assert extract_probable_filename_from_query("open file report.docx") == "report.docx"

    def test_no_filename_returns_none(self):
        assert extract_probable_filename_from_query("what is Project Horus?") is None


class TestKnowledgeStoreClientFetchForRagFileResolve:
    """fetch_for_rag prefers /file/resolve when the query names a file."""

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_resolve_short_circuits_semantic_search(self, mock_client_class):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "matched_titles": ["test_horus.txt"],
            "doc_ids": ["abc"],
            "text": "FULL TEXT CONTENT",
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        result = await client.fetch_for_rag("Summarize test_horus.txt")

        assert result["query"] == "__file__:test_horus.txt"
        assert "FULL TEXT CONTENT" in result["data"]
        assert "test_horus.txt" in result["data"]
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert call_args[0][0].endswith("/file/resolve")
        assert call_args[1]["params"]["name"] == "test_horus.txt"


class TestKnowledgeStoreClientSuccess:
    """Test successful query scenarios"""

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_successful_query_with_documents(self, mock_client_class):
        """Test successful query that returns documents"""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "documents": [["Document 1 text", "Document 2 text"]],
            "metadatas": [[{}, {}]],
            "distances": [[0.1, 0.2]]
        }
        mock_response.raise_for_status.return_value = None
        
        # Mock the AsyncClient instance that will be used in async with
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        # When AsyncClient() is instantiated, return our mock
        mock_client_class.return_value = mock_client
        
        # Execute
        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        result = await client.query("test query", n_results=2)
        
        # Assert
        assert result["query"] == "test query"
        assert result["data"] == "Document 1 text\n\nDocument 2 text"
        mock_client.get.assert_called_once()
        # Check that the call was made with correct params
        call_args = mock_client.get.call_args
        assert call_args[1]["params"]["query"] == "test query"
        assert call_args[1]["params"]["n_results"] == 2

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_successful_query_no_documents(self, mock_client_class):
        """Test successful query that returns no documents"""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]]
        }
        mock_response.raise_for_status.return_value = None
        
        # Mock the AsyncClient instance that will be used in async with
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        # When AsyncClient() is instantiated, return our mock
        mock_client_class.return_value = mock_client
        
        # Execute
        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        result = await client.query("test query")
        
        # Assert
        assert result["query"] == "test query"
        assert result["data"] == ""

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_successful_query_empty_documents_list(self, mock_client_class):
        """Test successful query with empty documents list"""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "documents": [],
            "metadatas": [],
            "distances": []
        }
        mock_response.raise_for_status.return_value = None
        
        # Mock the AsyncClient instance that will be used in async with
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        # When AsyncClient() is instantiated, return our mock
        mock_client_class.return_value = mock_client
        
        # Execute
        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        result = await client.query("test query")
        
        # Assert
        assert result["query"] == "test query"
        assert result["data"] == ""


class TestKnowledgeStoreClientHTTPErrors:
    """Test HTTP error handling"""

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_404_error_returns_empty_data(self, mock_client_class):
        """Test 404 error (no results) returns empty data without retry"""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "No results found"
        
        mock_http_error = httpx.HTTPStatusError(
            "Not Found",
            request=MagicMock(),
            response=mock_response
        )
        
        # Mock the AsyncClient instance that will be used in async with
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=mock_http_error)
        # When AsyncClient() is instantiated, return our mock
        mock_client_class.return_value = mock_client
        
        # Execute
        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=3)
        result = await client.query("test query")
        
        # Assert - should return empty data, no retries
        assert result["query"] == "test query"
        assert result["data"] == ""
        assert mock_client.get.call_count == 1  # No retries for 404

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_400_error_returns_error_message(self, mock_client_class):
        """Test 400 error (bad request) returns error message without retry"""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Invalid query"
        mock_response.json.return_value = {"error": "Invalid query parameter"}
        
        mock_http_error = httpx.HTTPStatusError(
            "Bad Request",
            request=MagicMock(),
            response=mock_response
        )
        
        # Mock the AsyncClient instance that will be used in async with
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=mock_http_error)
        # When AsyncClient() is instantiated, return our mock
        mock_client_class.return_value = mock_client
        
        # Execute
        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=3)
        result = await client.query("test query")
        
        # Assert - should return error message, no retries
        assert result["query"] == "test query"
        assert "Error: Invalid request" in result["data"]
        assert "Invalid query parameter" in result["data"]
        assert mock_client.get.call_count == 1  # No retries for 400

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    @patch("ai_agents.knowledge_store_client.asyncio.sleep")
    async def test_500_error_retries_then_fails(self, mock_sleep, mock_client_class):
        """Test 500 error retries then returns error message"""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        
        mock_http_error = httpx.HTTPStatusError(
            "Internal Server Error",
            request=MagicMock(),
            response=mock_response
        )
        
        # Mock the AsyncClient instance that will be used in async with
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=mock_http_error)
        # When AsyncClient() is instantiated, return our mock
        mock_client_class.return_value = mock_client
        
        # Execute
        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=3, retry_delay=0.01)
        result = await client.query("test query")
        
        # Assert - should retry 3 times then return error
        assert result["query"] == "test query"
        assert "Error: Failed to query knowledge store after 3 attempts" in result["data"]
        assert mock_client.get.call_count == 3  # Should retry 3 times
        assert mock_sleep.call_count == 2  # Should sleep between retries (2 sleeps for 3 attempts)


class TestKnowledgeStoreClientTimeout:
    """Test timeout handling"""

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    @patch("ai_agents.knowledge_store_client.asyncio.sleep")
    async def test_timeout_retries_then_fails(self, mock_sleep, mock_client_class):
        """Test timeout exception retries then returns error message"""
        # Setup mock to raise timeout
        # Mock the AsyncClient instance that will be used in async with
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))
        # When AsyncClient() is instantiated, return our mock
        mock_client_class.return_value = mock_client
        
        # Execute
        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=3, retry_delay=0.01)
        result = await client.query("test query")
        
        # Assert - should retry 3 times then return error
        assert result["query"] == "test query"
        assert "Error: Failed to query knowledge store after 3 attempts" in result["data"]
        assert mock_client.get.call_count == 3  # Should retry 3 times
        assert mock_sleep.call_count == 2  # Should sleep between retries

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    @patch("ai_agents.knowledge_store_client.asyncio.sleep")
    async def test_timeout_then_success(self, mock_sleep, mock_client_class):
        """Test timeout on first attempt, success on retry"""
        # Setup mock - first call times out, second succeeds
        mock_response_success = MagicMock()
        mock_response_success.json.return_value = {
            "documents": [["Success document"]],
            "metadatas": [[{}]],
            "distances": [[0.1]]
        }
        mock_response_success.raise_for_status.return_value = None
        
        # Mock the AsyncClient instance that will be used in async with
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=[
            httpx.TimeoutException("Request timed out"),
            mock_response_success
        ])
        # When AsyncClient() is instantiated, return our mock
        mock_client_class.return_value = mock_client
        
        # Execute
        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=3, retry_delay=0.01)
        result = await client.query("test query")
        
        # Assert - should succeed on retry
        assert result["query"] == "test query"
        assert result["data"] == "Success document"
        assert mock_client.get.call_count == 2  # One timeout, one success
        assert mock_sleep.call_count == 1  # Should sleep once before retry


class TestKnowledgeStoreClientConnectionErrors:
    """Test connection error handling"""

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    @patch("ai_agents.knowledge_store_client.asyncio.sleep")
    async def test_connection_error_retries_then_fails(self, mock_sleep, mock_client_class):
        """Test connection error retries then returns error message"""
        # Setup mock to raise connection error
        # Mock the AsyncClient instance that will be used in async with
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        # When AsyncClient() is instantiated, return our mock
        mock_client_class.return_value = mock_client
        
        # Execute
        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=3, retry_delay=0.01)
        result = await client.query("test query")
        
        # Assert - should retry 3 times then return error
        assert result["query"] == "test query"
        assert "Error: Failed to query knowledge store after 3 attempts" in result["data"]
        assert mock_client.get.call_count == 3  # Should retry 3 times
        assert mock_sleep.call_count == 2  # Should sleep between retries


class TestKnowledgeStoreClientConfiguration:
    """Test configuration and initialization"""

    def test_default_configuration_from_settings(self):
        """Test that client uses settings defaults when no parameters provided"""
        with patch("ai_agents.knowledge_store_client.KNOWLEDGE_STORE_URL", "http://default:8080"), \
             patch("ai_agents.knowledge_store_client.KNOWLEDGE_STORE_TIMEOUT", 15.0), \
             patch("ai_agents.knowledge_store_client.KNOWLEDGE_STORE_MAX_RETRIES", 5), \
             patch("ai_agents.knowledge_store_client.KNOWLEDGE_STORE_RETRY_DELAY", 2.0):
            
            client = KnowledgeStoreClient()
            
            assert client.base_url == "http://default:8080"
            assert client.timeout == 15.0
            assert client.max_retries == 5
            assert client.retry_delay == 2.0

    def test_custom_configuration_overrides_settings(self):
        """Test that custom parameters override settings"""
        with patch("ai_agents.knowledge_store_client.KNOWLEDGE_STORE_URL", "http://default:8080"), \
             patch("ai_agents.knowledge_store_client.KNOWLEDGE_STORE_TIMEOUT", 10.0), \
             patch("ai_agents.knowledge_store_client.KNOWLEDGE_STORE_MAX_RETRIES", 3), \
             patch("ai_agents.knowledge_store_client.KNOWLEDGE_STORE_RETRY_DELAY", 1.0):
            
            client = KnowledgeStoreClient(
                base_url="http://custom:8080",
                timeout=20.0,
                max_retries=7,
                retry_delay=3.0
            )
            
            assert client.base_url == "http://custom:8080"
            assert client.timeout == 20.0
            assert client.max_retries == 7
            assert client.retry_delay == 3.0

    def test_base_url_trailing_slash_removed(self):
        """Test that trailing slash is removed from base_url"""
        client = KnowledgeStoreClient(base_url="http://test:8080/")
        assert client.base_url == "http://test:8080"

    @pytest.mark.asyncio
    async def test_callable_interface(self):
        """Test that client is callable (__call__ method)"""
        with patch("ai_agents.knowledge_store_client.httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "documents": [["Test document"]],
                "metadatas": [[{}]],
                "distances": [[0.1]]
            }
            mock_response.raise_for_status.return_value = None
            
            # Mock the AsyncClient instance that will be used in async with
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            # When AsyncClient() is instantiated, return our mock
            mock_client_class.return_value = mock_client
            
            client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
            result = await client("test query")  # Call as function
            
            assert result["query"] == "test query"
            assert result["data"] == "Test document"


class TestKnowledgeStoreClientExponentialBackoff:
    """Test exponential backoff behavior"""

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    @patch("ai_agents.knowledge_store_client.asyncio.sleep")
    async def test_exponential_backoff_delay(self, mock_sleep, mock_client_class):
        """Test that retry delays increase exponentially"""
        # Setup mock to always timeout
        # Mock the AsyncClient instance that will be used in async with
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))
        # When AsyncClient() is instantiated, return our mock
        mock_client_class.return_value = mock_client
        
        # Execute
        client = KnowledgeStoreClient(
            base_url="http://test:8080",
            timeout=5.0,
            max_retries=4,
            retry_delay=1.0
        )
        await client.query("test query")
        
        # Assert - delays should be: 1.0, 2.0, 4.0 (exponential backoff)
        assert mock_sleep.call_count == 3
        # Check that delays increase (approximately, due to min() cap)
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert sleep_calls[0] == 1.0  # First delay
        assert sleep_calls[1] == 2.0  # Second delay (doubled)
        assert sleep_calls[2] == 4.0  # Third delay (doubled again)

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    @patch("ai_agents.knowledge_store_client.asyncio.sleep")
    async def test_backoff_delay_capped_at_10_seconds(self, mock_sleep, mock_client_class):
        """Test that backoff delay is capped at 10 seconds"""
        # Setup mock to always timeout
        # Mock the AsyncClient instance that will be used in async with
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))
        # When AsyncClient() is instantiated, return our mock
        mock_client_class.return_value = mock_client
        
        # Execute with large initial delay
        client = KnowledgeStoreClient(
            base_url="http://test:8080",
            timeout=5.0,
            max_retries=5,
            retry_delay=8.0  # Will become 16.0, but should be capped at 10.0
        )
        await client.query("test query")
        
        # Assert - delays should be capped at 10.0
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert all(delay <= 10.0 for delay in sleep_calls), "All delays should be <= 10.0"

class TestKnowledgeStoreClientSmartSearch:
    """Test smart search scenarios"""

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_smart_search_no_filters(self, mock_client_class):
        """Test smart search without filters"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "query": "docker ethereum",
            "filters": None,
            "total": 2,
            "results": {"documents": ["doc1", "doc2"]}
        }
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        result = await client.smart_search("docker ethereum")

        assert result["query"] == "docker ethereum"
        assert result["total"] == 2
        assert result["data"] == "doc1\n\ndoc2"
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["query"] == "docker ethereum"
        assert call_args[1]["json"]["n_results"] == 5

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_smart_search_with_filters(self, mock_client_class):
        """Test smart search with category and confidence filters"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "query": "contract",
            "filters": {"auto_category": {"$eq": "legal"}},
            "total": 1,
            "results": {"documents": ["legal doc"]}
        }
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        result = await client.smart_search(
            "contract",
            categories=["legal"],
            min_confidence=0.9
        )

        assert result["total"] == 1
        call_json = mock_client.post.call_args[1]["json"]
        assert call_json["categories"] == ["legal"]
        assert call_json["min_confidence"] == 0.9

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_smart_search_404_returns_empty(self, mock_client_class):
        """Test smart search 404 returns empty data"""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_http_error = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=mock_http_error)
        mock_client_class.return_value = mock_client

        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        result = await client.smart_search("xpto")

        assert result["data"] == ""
        assert result["total"] == 0

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    @patch("ai_agents.knowledge_store_client.asyncio.sleep")
    async def test_smart_search_500_retries(self, mock_sleep, mock_client_class):
        """Test smart search retries on 500 error"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_http_error = httpx.HTTPStatusError("Server Error", request=MagicMock(), response=mock_response)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=mock_http_error)
        mock_client_class.return_value = mock_client

        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=3, retry_delay=0.01)
        result = await client.smart_search("contract")

        assert "Error" in result["data"]
        assert mock_client.post.call_count == 3


class TestKnowledgeStoreClientSearchByEntity:
    """Test search by entity scenarios"""

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_search_by_entity_success(self, mock_client_class):
        """Test successful search by entity"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "entity": "Alice",
            "entity_type": "people",
            "total": 1,
            "results": {"documents": [["Contract between Alice and Bob"]]}
        }
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        result = await client.search_by_entity("Alice", "people")

        assert result["entity"] == "Alice"
        assert result["total"] == 1
        assert "Alice" in result["data"]
        call_params = mock_client.get.call_args[1]["params"]
        assert call_params["entity"] == "Alice"
        assert call_params["entity_type"] == "people"
        assert call_params["n_results"] == 5

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_search_by_entity_404_returns_empty(self, mock_client_class):
        """Test search by entity 404 returns empty"""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_http_error = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=mock_http_error)
        mock_client_class.return_value = mock_client

        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        result = await client.search_by_entity("Unknown", "people")

        assert result["data"] == ""
        assert result["total"] == 0

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_search_by_entity_400_returns_empty(self, mock_client_class):
        """Test search by entity 400 (invalid type) returns empty"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_http_error = httpx.HTTPStatusError("Bad Request", request=MagicMock(), response=mock_response)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=mock_http_error)
        mock_client_class.return_value = mock_client

        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        result = await client.search_by_entity("Alice", "invalid_type")

        assert result["data"] == ""
        assert result["total"] == 0

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_search_by_entity_custom_n_results(self, mock_client_class):
        """Test search by entity with custom n_results"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "entity": "Alice",
            "entity_type": "people",
            "total": 1,
            "results": {"documents": [["doc1"]]}
        }
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        await client.search_by_entity("Alice", "people", n_results=10)

        call_params = mock_client.get.call_args[1]["params"]
        assert call_params["n_results"] == 10


class TestKnowledgeStoreClientGetCategories:
    """Test get categories scenarios"""

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_get_categories_success(self, mock_client_class):
        """Test successful get categories"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "total_documents": 3,
            "categories": [
                {"category": "technical", "count": 2},
                {"category": "academic", "count": 1}
            ]
        }
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        result = await client.get_categories()

        assert result["total_documents"] == 3
        assert result["categories"][0] == {"category": "technical", "count": 2}
        assert result["categories"][1] == {"category": "academic", "count": 1}

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    async def test_get_categories_empty(self, mock_client_class):
        """Test get categories with empty store"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"total_documents": 0, "categories": []}
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=1)
        result = await client.get_categories()

        assert result["total_documents"] == 0
        assert result["categories"] == []

    @pytest.mark.asyncio
    @patch("ai_agents.knowledge_store_client.httpx.AsyncClient")
    @patch("ai_agents.knowledge_store_client.asyncio.sleep")
    async def test_get_categories_error_returns_empty(self, mock_sleep, mock_client_class):
        """Test get categories returns empty dict on failure"""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_class.return_value = mock_client

        client = KnowledgeStoreClient(base_url="http://test:8080", timeout=5.0, max_retries=3, retry_delay=0.01)
        result = await client.get_categories()

        assert result == {"total_documents": 0, "categories": []}
        assert mock_client.get.call_count == 3

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

