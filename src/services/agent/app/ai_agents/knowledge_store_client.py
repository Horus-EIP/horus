"""
knowledge_store_client.py
--------------------------
This module provides a client for interacting with the knowledge-store HTTP API.
It handles HTTP requests with timeout, retry logic, and graceful error handling.
Uses async/await for non-blocking I/O operations.
"""

from typing import Any, Dict, Optional
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
    KNOWLEDGE_STORE_API_PREFIX,
    KNOWLEDGE_STORE_TIMEOUT,
    KNOWLEDGE_STORE_MAX_RETRIES,
    KNOWLEDGE_STORE_RETRY_DELAY,
    KNOWLEDGE_STORE_N_RESULTS,
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
        api_prefix: Optional[str] = None,
    ):
        """
        Initialize the knowledge store client.

        Args:
            base_url: Base URL of the knowledge-store API. Defaults to KNOWLEDGE_STORE_URL from settings.
            timeout: Request timeout in seconds. Defaults to KNOWLEDGE_STORE_TIMEOUT from settings.
            max_retries: Maximum number of retry attempts. Defaults to KNOWLEDGE_STORE_MAX_RETRIES from settings.
            retry_delay: Initial delay between retries in seconds. Defaults to KNOWLEDGE_STORE_RETRY_DELAY from settings.
            api_prefix: Path prefix before store routes (e.g. /api/knowledge-store). Empty when calling the container directly on :8080.
        """
        self.base_url = base_url or KNOWLEDGE_STORE_URL
        self.timeout = timeout if timeout is not None else KNOWLEDGE_STORE_TIMEOUT
        self.max_retries = max_retries if max_retries is not None else KNOWLEDGE_STORE_MAX_RETRIES
        self.retry_delay = retry_delay if retry_delay is not None else KNOWLEDGE_STORE_RETRY_DELAY
        # Remove trailing slash if present
        if self.base_url.endswith("/"):
            self.base_url = self.base_url.rstrip("/")
        raw_prefix = (
            (api_prefix if api_prefix is not None else KNOWLEDGE_STORE_API_PREFIX)
            or ""
        ).strip().rstrip("/")
        if raw_prefix and not raw_prefix.startswith("/"):
            raw_prefix = f"/{raw_prefix}"
        self._api_prefix = raw_prefix

        logger.info(
            f"Initialized KnowledgeStoreClient: base_url={self.base_url}, api_prefix={self._api_prefix!r}, "
            f"timeout={self.timeout}s, max_retries={self.max_retries}, retry_delay={self.retry_delay}s"
        )

    def _api_root(self) -> str:
        """Base URL including optional gateway prefix (no trailing slash)."""
        if not self._api_prefix:
            return self.base_url
        return f"{self.base_url}{self._api_prefix}"

    async def query(self, query: str, n_results: Optional[int] = None) -> Dict[str, Any]:
        """
        Query the knowledge store with a query string (async).

        Args:
            query: The search query string.
            n_results: Max chunks to retrieve. Defaults to KNOWLEDGE_STORE_N_RESULTS (env, default 8).

        Returns:
            A dictionary with the query results. On error, returns a dict with
            'query' and 'data' fields, where 'data' contains an error message
            or empty string.
        """
        limit = (
            n_results if n_results is not None else KNOWLEDGE_STORE_N_RESULTS
        )
        url = f"{self._api_root()}/"
        params = {"query": query, "n_results": limit}

        logger.debug(
            f"Querying knowledge store: query='{query}', n_results={limit}"
        )

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

    async def fetch_document_inventory(
        self, content_preview_chars: int = 400
    ) -> Dict[str, Any]:
        """
        List documents via GET /file (titles and short text previews).

        Used when semantic search returns nothing or for broad \"what is stored\" questions.
        """
        url = f"{self._api_root()}/file"
        logger.debug("Fetching knowledge store document inventory from %s", url)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    payload = response.json()
                    docs = payload.get("documents") or []
                    if not docs:
                        return {"query": "__inventory__", "data": ""}

                    lines: list[str] = []
                    for d in docs:
                        title = d.get("title") or "Untitled"
                        doc_id = d.get("id", "")
                        date = d.get("date", "")
                        category = d.get("category") or "general"
                        summary = (d.get("summary") or "").strip()
                        excerpt = (d.get("excerpt") or "").strip()
                        legacy = (d.get("content") or "").strip()
                        snippet = summary or excerpt or legacy
                        if len(snippet) > content_preview_chars:
                            snippet = snippet[:content_preview_chars].rstrip() + "..."
                        lines.append(
                            f"- {title} (id={doc_id}, category={category}, date={date})\n"
                            f"  Summary: {snippet}"
                        )
                    return {
                        "query": "__inventory__",
                        "data": "\n".join(lines),
                    }
                except httpx.HTTPStatusError as e:
                    logger.warning(
                        "Inventory GET failed: %s %s (attempt %s/%s)",
                        e.response.status_code,
                        url,
                        attempt + 1,
                        self.max_retries,
                    )
                except (httpx.TimeoutException, httpx.RequestError, Exception) as e:
                    logger.warning(
                        "Inventory request error: %s (attempt %s/%s)",
                        e,
                        attempt + 1,
                        self.max_retries,
                    )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)

        return {"query": "__inventory__", "data": ""}

    async def fetch_for_rag(
        self, query: str, n_results: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Run semantic search; if no excerpts are returned, attach a document inventory.
        """
        result = await self.query(query, n_results=n_results)
        if (result.get("data") or "").strip():
            return result
        inv = await self.fetch_document_inventory()
        inv_text = (inv.get("data") or "").strip()
        if inv_text:
            result["data"] = (
                "Semantic search did not return close excerpts for this question. "
                "Documents currently in the knowledge store:\n\n"
                + inv_text
            )
        return result

    async def __call__(self, query: str) -> Dict[str, Any]:
        """
        Make the client callable for use as a store interface (async).

        Args:
            query: The search query string.

        Returns:
            A dictionary with the query results.
        """
        return await self.fetch_for_rag(query)

    async def smart_search(self, query: str, n_results: int = 5, categories: Optional[list] = None, entities: Optional[list] = None, min_confidence: Optional[float] = None, entity_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Perform a smart search on the knowledge store with optional filters.

        Args:
            query: The search query string.
            n_results: The number of results to return. Defaults to 5.
            categories: Optional list of categories to filter by.
            entities: Optional list of entities to filter by.
            min_confidence: Optional minimum confidence score to filter results.
            entity_type: Optional entity type to filter by.

        Returns:
            A dictionary with the search results. On error, returns a dict with
            'query' and 'data' fields, where 'data' contains an error message
            or empty string.
        """
        url = f"{self._api_root()}/smart-search"
        payload = {"query": query, "n_results": n_results}

        if categories:
            payload["categories"] = categories
        if entities:
            payload["entities"] = entities
        if min_confidence is not None:
            payload["min_confidence"] = min_confidence
        if entity_type:
            payload["entity_type"] = entity_type
        
        logger.debug(f"Smart search: query='{query}', filters={payload}")

        start_time = time.time()
        delay = self.retry_delay

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    result = response.json()

                    duration = time.time() - start_time
                    if _METRICS_AVAILABLE:
                        knowledge_store_request_duration.observe(duration)
                        knowledge_store_requests_total.labels(status="success").inc()
                    
                    documents = result.get("results", {}).get("documents", [[]])
                    document_text = "\n\n".join(documents) if documents and documents else ""

                    logger.debug(f"Smart search returned {result.get('total', 0)} results (duration: {duration:.3f}s)")
                    return {
                        "query": query,
                        "data": document_text,
                        "total": result.get("total", 0),
                    }

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        logger.debug(f"No results found for smart search query: {query}")
                        return {"query": query, "data": "", "total": 0}
                    
                    logger.warning(f"HTTP error {e.response.status_code} on smart search (attempt {attempt + 1}/{self.max_retries}): {e}")
                except (httpx.TimeoutException, httpx.RequestError, Exception) as e:
                    logger.warning(f"Error on smart search (attempt {attempt + 1}/{self.max_retries}): {e}", exc_info=True)

                if attempt < self.max_retries - 1:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 10.0)
        return {
            "query": query,
            "data": f"Error: smart search failed after {self.max_retries} attempts",
            "total": 0,
        }

    async def search_by_entity(self, entity: str, entity_type: str, n_results: int = 5) -> Dict[str, Any]:
        """
        Search for documents by entity.

        Args:
            entity: The entity to search for.
            entity_type: The type of the entity.
            n_results: The number of results to return. Defaults to 5.
        Returns:
            A dictionary with the search results. On error, returns a dict with
            'entity' and 'data' fields, where 'data' contains an error message
            or empty string.
        """
        url = f"{self._api_root()}/search-by-entity"
        params = {"entity": entity, "entity_type": entity_type, "n_results": n_results}

        logger.debug(f"Searching by entity: entity='{entity}', entity_type='{entity_type}', n_results={n_results}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    result = response.json()

                    documents = result.get("results", {}).get("documents", [[]])[0]
                    document_text = "\n\n".join(documents) if documents else ""

                    return {
                        "entity": entity,
                        "data": document_text,
                        "total": result.get("total", 0),
                    }

                except httpx.HTTPStatusError as e:
                    if e.response.status_code in (400, 404):
                        logger.debug(f"No results for entity: {entity} ({entity_type}) (status {e.response.status_code})")
                        return {"entity": entity, "data": "", "total": 0}
                    
                    logger.warning(f"HTTP error {e.response.status_code} on search by entity (attempt {attempt + 1}/{self.max_retries}): {e}")
                except (httpx.TimeoutException, httpx.RequestError, Exception) as e:
                    logger.warning(f"Error on search by entity (attempt {attempt + 1}/{self.max_retries}): {e}")

                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
        
        return {
            "entity": entity,
            "data": f"Error: search by entity failed after {self.max_retries} attempts",
            "total": 0,
        }
    
    async def get_categories(self) -> Dict[str, Any]:
        """
        Get the list of categories available in the knowledge store and their counts.

        Returns:
            A dictionary with the categories and their counts. On error, returns a dict with
            'total_documents' set to 0 and 'categories' as an empty list.
        """
        url = f"{self._api_root()}/categories"

        logger.debug("Getting categories from knowledge store")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as e:
                    logger.warning(f"HTTP error {e.response.status_code} on get categories: {e} (attempt {attempt + 1}/{self.max_retries})")
                except (httpx.TimeoutException, httpx.RequestError, Exception) as e:
                    logger.warning(f"Error on get categories: {e} (attempt {attempt + 1}/{self.max_retries})")
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)

        return {
            "total_documents": 0,
            "categories": [],
        }
