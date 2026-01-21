"""
knowledge_store_client.py
--------------------------
This module provides a client for interacting with the knowledge-store HTTP API.
It handles HTTP requests with timeout, retry logic, and graceful error handling.
Uses async/await for non-blocking I/O operations.
"""

from typing import Dict, Any, Optional
import httpx
import asyncio
import time
import logging

logger = logging.getLogger(__name__)

# Import metrics if available (avoid circular imports)
try:
    from core.metrics import (
        knowledge_store_requests_total,
        knowledge_store_request_duration,
    )
    _METRICS_AVAILABLE = True
except ImportError:
    _METRICS_AVAILABLE = False

from config.settings import (
    KNOWLEDGE_STORE_URL,
    KNOWLEDGE_STORE_TIMEOUT,
    KNOWLEDGE_STORE_MAX_RETRIES,
    KNOWLEDGE_STORE_RETRY_DELAY,
)


class KnowledgeStoreClient:
    """
    Client for querying the knowledge-store HTTP API.
    Provides timeout, retry logic, and error handling.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ):
        """
        Initialize the knowledge store client.

        Args:
            base_url: Base URL of the knowledge-store API. Defaults to KNOWLEDGE_STORE_URL from settings.
            timeout: Request timeout in seconds. Defaults to KNOWLEDGE_STORE_TIMEOUT from settings.
            max_retries: Maximum number of retry attempts. Defaults to KNOWLEDGE_STORE_MAX_RETRIES from settings.
            retry_delay: Initial delay between retries in seconds. Defaults to KNOWLEDGE_STORE_RETRY_DELAY from settings.
        """
        self.base_url = base_url or KNOWLEDGE_STORE_URL
        self.timeout = timeout if timeout is not None else KNOWLEDGE_STORE_TIMEOUT
        self.max_retries = max_retries if max_retries is not None else KNOWLEDGE_STORE_MAX_RETRIES
        self.retry_delay = retry_delay if retry_delay is not None else KNOWLEDGE_STORE_RETRY_DELAY
        # Remove trailing slash if present
        if self.base_url.endswith("/"):
            self.base_url = self.base_url.rstrip("/")
        
        logger.info(
            f"Initialized KnowledgeStoreClient: base_url={self.base_url}, "
            f"timeout={self.timeout}s, max_retries={self.max_retries}, retry_delay={self.retry_delay}s"
        )

    async def query(self, query: str, n_results: int = 1) -> Dict[str, Any]:
        """
        Query the knowledge store with a query string (async).

        Args:
            query: The search query string.
            n_results: The number of results to return. Defaults to 1.

        Returns:
            A dictionary with the query results. On error, returns a dict with
            'query' and 'data' fields, where 'data' contains an error message
            or empty string.
        """
        url = f"{self.base_url}/api/knowledge-store/"
        params = {"query": query, "n_results": n_results}

        logger.debug(f"Querying knowledge store: query='{query}', n_results={n_results}")

        start_time = time.time()
        last_exception = None
        delay = self.retry_delay

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    result = response.json()

                    # Extract documents from the response
                    # The API returns: {"documents": [[...]], ...}
                    documents = result.get("documents", [[]])
                    # Record successful request
                    duration = time.time() - start_time
                    if _METRICS_AVAILABLE:
                        knowledge_store_request_duration.observe(duration)
                        knowledge_store_requests_total.labels(status="success").inc()
                    
                    if documents and documents[0]:
                        # Combine all document texts
                        document_text = "\n\n".join(documents[0])
                        logger.debug(
                            f"Successfully retrieved {len(documents[0])} document(s) for query: {query} "
                            f"(duration: {duration:.3f}s)"
                        )
                        return {
                            "query": query,
                            "data": document_text,
                        }
                    else:
                        # No results found
                        logger.debug(f"No documents found for query: {query} (duration: {duration:.3f}s)")
                        return {
                            "query": query,
                            "data": "",
                        }

                except httpx.TimeoutException as e:
                    last_exception = e
                    logger.warning(
                        f"Timeout querying knowledge store (attempt {attempt + 1}/{self.max_retries}): {e}",
                        extra={"query": query, "attempt": attempt + 1, "max_retries": self.max_retries}
                    )
                except httpx.HTTPStatusError as e:
                    # For 404 (no results) or 400 (bad request), don't retry
                    if e.response.status_code in (400, 404):
                        if e.response.status_code == 404:
                            logger.debug(f"No results found for query: {query}")
                            return {"query": query, "data": ""}
                        else:
                            # Try to parse JSON error response
                            try:
                                error_detail = e.response.json().get("error", e.response.text)
                            except Exception:
                                error_detail = e.response.text
                            logger.error(
                                f"Bad request to knowledge store: {error_detail}",
                                extra={"query": query, "status_code": 400}
                            )
                            return {
                                "query": query,
                                "data": f"Error: Invalid request - {error_detail}",
                            }
                    last_exception = e
                    logger.warning(
                        f"HTTP error {e.response.status_code} querying knowledge store "
                        f"(attempt {attempt + 1}/{self.max_retries}): {e}",
                        extra={
                            "query": query,
                            "status_code": e.response.status_code,
                            "attempt": attempt + 1,
                            "max_retries": self.max_retries
                        }
                    )
                except httpx.RequestError as e:
                    last_exception = e
                    logger.warning(
                        f"Request error querying knowledge store (attempt {attempt + 1}/{self.max_retries}): {e}",
                        extra={"query": query, "attempt": attempt + 1, "max_retries": self.max_retries}
                    )
                except Exception as e:
                    last_exception = e
                    logger.error(
                        f"Unexpected error querying knowledge store (attempt {attempt + 1}/{self.max_retries}): {e}",
                        extra={"query": query, "attempt": attempt + 1, "max_retries": self.max_retries},
                        exc_info=True
                    )

                # Wait before retrying (exponential backoff)
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 10.0)  # Cap delay at 10 seconds

        # All retries failed - return error message
        error_msg = f"Failed to query knowledge store after {self.max_retries} attempts"
        if last_exception:
            error_msg += f": {str(last_exception)}"
        
        # Record failed request
        duration = time.time() - start_time
        if _METRICS_AVAILABLE:
            knowledge_store_request_duration.observe(duration)
            if isinstance(last_exception, httpx.TimeoutException):
                knowledge_store_requests_total.labels(status="timeout").inc()
            else:
                knowledge_store_requests_total.labels(status="error").inc()
        
        logger.error(
            f"{error_msg} (duration: {duration:.3f}s)",
            extra={"query": query, "max_retries": self.max_retries},
            exc_info=last_exception
        )

        return {
            "query": query,
            "data": f"Error: {error_msg}",
        }

    async def __call__(self, query: str) -> Dict[str, Any]:
        """
        Make the client callable for use as a store interface (async).

        Args:
            query: The search query string.

        Returns:
            A dictionary with the query results.
        """
        return await self.query(query)

