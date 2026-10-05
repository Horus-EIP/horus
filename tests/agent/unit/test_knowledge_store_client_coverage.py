"""Behavioral coverage tests for ``ai_agents.knowledge_store_client``.

All HTTP I/O is mocked at the ``httpx.AsyncClient`` boundary via a small fake
client, so no network, sleeps, or Prometheus side effects leak into the tests.
``asyncio.sleep`` is patched to a no-op so retry/backoff branches run instantly.
"""

import httpx
import pytest

import ai_agents.knowledge_store_client as ksc
from ai_agents.knowledge_store_client import (
    KnowledgeStoreClient,
    extract_probable_filename_from_query,
)

# ---------------------------------------------------------------------------
# Test doubles for httpx
# ---------------------------------------------------------------------------


class FakeResponse:
    """Stand-in for ``httpx.Response`` returned by the fake client."""

    def __init__(self, status_code=200, json_data=None, text="", raise_json=False):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://test/")
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=request, response=self
            )


class FakeAsyncClient:
    """Mimics ``httpx.AsyncClient`` used as an async context manager.

    ``handler`` is called with (method, url, kwargs) and returns a FakeResponse
    or raises. ``calls`` records every request for assertions.
    """

    def __init__(self, handler, calls, **client_kwargs):
        self._handler = handler
        self._calls = calls
        self.client_kwargs = client_kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        self._calls.append(("GET", url, {"params": params}))
        return self._produce("GET", url, {"params": params})

    async def post(self, url, json=None):
        self._calls.append(("POST", url, {"json": json}))
        return self._produce("POST", url, {"json": json})

    def _produce(self, method, url, kwargs):
        result = self._handler(method, url, kwargs)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            return result()
        return result


@pytest.fixture
def patched_httpx(monkeypatch):
    """Install a FakeAsyncClient factory; return a controller object.

    Usage::

        patched_httpx.handler = lambda method, url, kwargs: FakeResponse(...)
        ... call client method ...
        assert patched_httpx.calls == [...]

    ``handler`` may also return a list/iterator-backed callable for per-attempt
    behavior; see ``set_sequence``.
    """

    class Controller:
        def __init__(self):
            self.calls = []
            self.handler = lambda method, url, kwargs: FakeResponse()
            self.client_kwargs_seen = []

        def set_sequence(self, responses):
            """Make successive requests return/raise successive items."""
            seq = list(responses)
            idx = {"i": 0}

            def _h(method, url, kwargs):
                i = idx["i"]
                idx["i"] += 1
                item = seq[min(i, len(seq) - 1)]
                return item

            self.handler = _h

    controller = Controller()

    def factory(**client_kwargs):
        controller.client_kwargs_seen.append(client_kwargs)
        return FakeAsyncClient(controller.handler, controller.calls, **client_kwargs)

    monkeypatch.setattr(ksc.httpx, "AsyncClient", factory)
    return controller


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Make retry backoff instant."""

    async def _sleep(_delay):
        return None

    monkeypatch.setattr(ksc.asyncio, "sleep", _sleep)


@pytest.fixture(autouse=True)
def stub_metrics(monkeypatch):
    """Replace Prometheus metric objects with no-op fakes for isolation."""

    class _Metric:
        def observe(self, *a, **k):
            return None

        def labels(self, *a, **k):
            return self

        def inc(self, *a, **k):
            return None

    monkeypatch.setattr(ksc, "knowledge_store_request_duration", _Metric())
    monkeypatch.setattr(ksc, "knowledge_store_requests_total", _Metric())
    monkeypatch.setattr(ksc, "_METRICS_AVAILABLE", True)


def make_client(**overrides):
    """Client with small retry count and zero delay unless overridden."""
    params = {
        "base_url": "http://ks.test",
        "timeout": 1.0,
        "max_retries": 3,
        "retry_delay": 0.0,
        "api_prefix": "",
    }
    params.update(overrides)
    return KnowledgeStoreClient(**params)


# ===========================================================================
# extract_probable_filename_from_query
# ===========================================================================


class TestExtractProbableFilename:
    def test_empty_and_whitespace_return_none(self):
        assert extract_probable_filename_from_query("") is None
        assert extract_probable_filename_from_query("   ") is None
        assert extract_probable_filename_from_query(None) is None

    def test_quoted_filename(self):
        assert (
            extract_probable_filename_from_query('please open "report final.pdf" now')
            == "report final.pdf"
        )

    def test_single_quoted_filename(self):
        assert (
            extract_probable_filename_from_query("show me 'notes.md' contents")
            == "notes.md"
        )

    def test_file_keyword_pattern(self):
        assert (
            extract_probable_filename_from_query("look at file budget_2024.csv")
            == "budget_2024.csv"
        )

    def test_bare_filename_match(self):
        # No quotes / "file" keyword -> the bare-token regex (which allows
        # spaces in the char class) greedily spans up to the extension.
        result = extract_probable_filename_from_query("read alpha.txt please")
        assert result == "read alpha.txt"

    def test_bare_filename_returns_last_when_multiple_lines(self):
        # findall returns the *last* match; newlines break the greedy span.
        result = extract_probable_filename_from_query("alpha.txt\nbeta.docx")
        assert result == "beta.docx"

    def test_no_filename_present(self):
        assert extract_probable_filename_from_query("just a normal question") is None

    def test_unsupported_extension_ignored(self):
        assert extract_probable_filename_from_query("see image.png here") is None


# ===========================================================================
# __init__ / _api_root
# ===========================================================================


class TestInitAndApiRoot:
    def test_explicit_args_are_stored(self):
        client = KnowledgeStoreClient(
            base_url="http://example.com",
            timeout=5.5,
            max_retries=7,
            retry_delay=2.5,
            api_prefix="/api/ks",
        )
        assert client.base_url == "http://example.com"
        assert client.timeout == 5.5
        assert client.max_retries == 7
        assert client.retry_delay == 2.5
        assert client._api_prefix == "/api/ks"

    def test_defaults_pulled_from_settings(self):
        client = KnowledgeStoreClient()
        assert client.base_url == ksc.KNOWLEDGE_STORE_URL
        assert client.timeout == ksc.KNOWLEDGE_STORE_TIMEOUT
        assert client.max_retries == ksc.KNOWLEDGE_STORE_MAX_RETRIES
        assert client.retry_delay == ksc.KNOWLEDGE_STORE_RETRY_DELAY

    def test_trailing_slash_stripped(self):
        client = KnowledgeStoreClient(base_url="http://example.com/", api_prefix="")
        assert client.base_url == "http://example.com"

    def test_prefix_without_leading_slash_gets_one(self):
        client = KnowledgeStoreClient(
            base_url="http://example.com", api_prefix="api/knowledge-store"
        )
        assert client._api_prefix == "/api/knowledge-store"

    def test_prefix_trailing_slash_stripped(self):
        client = KnowledgeStoreClient(
            base_url="http://example.com", api_prefix="/api/ks/"
        )
        assert client._api_prefix == "/api/ks"

    def test_api_root_without_prefix(self):
        client = KnowledgeStoreClient(base_url="http://example.com", api_prefix="")
        assert client._api_root() == "http://example.com"

    def test_api_root_with_prefix(self):
        client = KnowledgeStoreClient(
            base_url="http://example.com", api_prefix="/api/ks"
        )
        assert client._api_root() == "http://example.com/api/ks"


# ===========================================================================
# query
# ===========================================================================


class TestQuery:
    async def test_success_with_documents(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"documents": [["alpha", "beta"]]}
        )

        result = await client.query("hello")

        assert result["query"] == "hello"
        assert result["data"] == "alpha\n\nbeta"
        assert [p["text"] for p in result["passages"]] == ["alpha", "beta"]
        # URL is api root + trailing slash; default n_results applied.
        method, url, kwargs = patched_httpx.calls[0]
        assert method == "GET"
        assert url == "http://ks.test/"
        assert kwargs["params"] == {
            "query": "hello",
            "n_results": ksc.KNOWLEDGE_STORE_N_RESULTS,
        }

    async def test_success_with_custom_n_results(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"documents": [["x"]]}
        )

        await client.query("hi", n_results=3)

        assert patched_httpx.calls[0][2]["params"]["n_results"] == 3

    async def test_success_no_documents_returns_empty(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(json_data={"documents": [[]]})

        result = await client.query("nothing")
        assert result == {"query": "nothing", "data": ""}

    async def test_missing_documents_key_returns_empty(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(json_data={})

        result = await client.query("nothing")
        assert result == {"query": "nothing", "data": ""}

    async def test_404_returns_empty_without_retry(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=404)

        result = await client.query("missing")

        assert result == {"query": "missing", "data": ""}
        # No retry on 404.
        assert len(patched_httpx.calls) == 1

    async def test_400_error_detail_from_json(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            status_code=400, json_data={"error": "bad query syntax"}
        )

        result = await client.query("oops")

        assert result == {
            "query": "oops",
            "data": "Error: Invalid request - bad query syntax",
            "error": "Invalid request - bad query syntax",
        }
        assert len(patched_httpx.calls) == 1

    async def test_400_error_detail_falls_back_to_text(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            status_code=400, text="plain failure", raise_json=True
        )

        result = await client.query("oops")
        assert result == {
            "query": "oops",
            "data": "Error: Invalid request - plain failure",
            "error": "Invalid request - plain failure",
        }

    async def test_500_retries_then_returns_error(self, patched_httpx):
        client = make_client(max_retries=3)
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=500)

        result = await client.query("boom")

        assert result["query"] == "boom"
        assert result["data"].startswith("Error: Failed to query knowledge store after 3 attempts")
        assert result["error"].startswith("Failed to query knowledge store after 3 attempts")
        assert len(patched_httpx.calls) == 3

    async def test_timeout_retries_then_returns_error(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: httpx.TimeoutException("slow")

        result = await client.query("slowq")

        assert result["data"].startswith(
            "Error: Failed to query knowledge store after 2 attempts"
        )
        assert "slow" in result["data"]
        assert len(patched_httpx.calls) == 2

    async def test_request_error_retries_then_error(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: httpx.ConnectError("refused")

        result = await client.query("q")
        assert result["data"].startswith("Error: Failed to query knowledge store")
        assert len(patched_httpx.calls) == 2

    async def test_unexpected_exception_retries_then_error(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: RuntimeError("weird")

        result = await client.query("q")
        assert result["data"].startswith("Error: Failed to query knowledge store")
        assert "weird" in result["data"]

    async def test_recovers_on_second_attempt(self, patched_httpx):
        client = make_client(max_retries=3)
        patched_httpx.set_sequence(
            [
                httpx.TimeoutException("first"),
                FakeResponse(json_data={"documents": [["recovered"]]}),
            ]
        )

        result = await client.query("retry-me")
        assert (result["query"], result["data"]) == ("retry-me", "recovered")
        assert len(patched_httpx.calls) == 2

    async def test_success_without_metrics(self, patched_httpx, monkeypatch):
        # When metrics are unavailable the success path skips metric emission.
        monkeypatch.setattr(ksc, "_METRICS_AVAILABLE", False)
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"documents": [["ok"]]}
        )

        result = await client.query("q")
        assert (result["query"], result["data"]) == ("q", "ok")

    async def test_failure_without_metrics(self, patched_httpx, monkeypatch):
        # Exhausted-retry path with metrics disabled (skips error metric branch).
        monkeypatch.setattr(ksc, "_METRICS_AVAILABLE", False)
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: httpx.TimeoutException("slow")

        result = await client.query("q")
        assert result["data"].startswith("Error: Failed to query knowledge store")


# ===========================================================================
# fetch_document_inventory
# ===========================================================================


class TestFetchDocumentInventory:
    async def test_success_builds_lines(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={
                "documents": [
                    {
                        "title": "Doc A",
                        "id": "1",
                        "date": "2024",
                        "category": "finance",
                        "summary": "a summary",
                    }
                ]
            }
        )

        result = await client.fetch_document_inventory()

        assert result["query"] == "__inventory__"
        assert "- Doc A (id=1, category=finance, date=2024)" in result["data"]
        assert "Summary: a summary" in result["data"]
        assert patched_httpx.calls[0][1] == "http://ks.test/file"

    async def test_fallback_fields_and_defaults(self, patched_httpx):
        client = make_client()
        # No title/category -> defaults; no summary/excerpt -> uses legacy content.
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"documents": [{"content": "legacy text"}]}
        )

        result = await client.fetch_document_inventory()
        assert "- Untitled (id=, category=general, date=)" in result["data"]
        assert "Summary: legacy text" in result["data"]

    async def test_excerpt_used_when_no_summary(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"documents": [{"title": "T", "excerpt": "the excerpt"}]}
        )

        result = await client.fetch_document_inventory()
        assert "Summary: the excerpt" in result["data"]

    async def test_snippet_truncation(self, patched_httpx):
        client = make_client()
        long_text = "x" * 500
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"documents": [{"title": "T", "summary": long_text}]}
        )

        result = await client.fetch_document_inventory(content_preview_chars=10)
        assert "xxxxxxxxxx..." in result["data"]

    async def test_empty_documents(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(json_data={"documents": []})

        result = await client.fetch_document_inventory()
        assert result == {"query": "__inventory__", "data": ""}

    async def test_http_error_exhausts_to_empty(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=500)

        result = await client.fetch_document_inventory()
        assert result == {"query": "__inventory__", "data": ""}
        assert len(patched_httpx.calls) == 2

    async def test_request_error_exhausts_to_empty(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: httpx.ConnectError("nope")

        result = await client.fetch_document_inventory()
        assert result == {"query": "__inventory__", "data": ""}

    async def test_recovers_after_error(self, patched_httpx):
        client = make_client(max_retries=3)
        patched_httpx.set_sequence(
            [
                httpx.ConnectError("first"),
                FakeResponse(json_data={"documents": [{"title": "OK"}]}),
            ]
        )

        result = await client.fetch_document_inventory()
        assert "- OK " in result["data"]
        assert len(patched_httpx.calls) == 2


# ===========================================================================
# resolve_by_filename
# ===========================================================================


class TestResolveByFilename:
    async def test_success_builds_header_and_text(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={
                "text": "file body",
                "matched_titles": ["Doc.txt"],
                "doc_ids": ["id1", "id2"],
            }
        )

        result = await client.resolve_by_filename("Doc.txt")

        assert result["query"] == "__file__:Doc.txt"
        assert result["data"].endswith("file body")
        assert "[Indexed file(s) matching 'Doc.txt': Doc.txt | ids: id1, id2]" in result["data"]
        method, url, kwargs = patched_httpx.calls[0]
        assert url == "http://ks.test/file/resolve"
        assert kwargs["params"] == {"name": "Doc.txt"}

    async def test_each_matched_document_becomes_a_citable_passage(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={
                "text": "first body\n\n---\n\nsecond body",
                "matched_titles": ["Doc.txt", "Doc.txt"],
                "doc_ids": ["id1", "id2"],
                "documents": [
                    {"doc_id": "id1", "title": "Doc.txt", "text": "first body"},
                    {"doc_id": "id2", "title": "Doc.txt", "text": "second body"},
                ],
            }
        )

        result = await client.resolve_by_filename("Doc.txt")

        assert [(p["doc_id"], p["title"], p["text"]) for p in result["passages"]] == [
            ("id1", "Doc.txt", "first body"),
            ("id2", "Doc.txt", "second body"),
        ]
        assert all(p["chunk_id"] is None and p["page"] is None for p in result["passages"])

    async def test_an_older_store_still_gives_its_single_match_as_a_passage(
        self, patched_httpx
    ):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"text": "only body", "matched_titles": ["One.md"], "doc_ids": ["id9"]}
        )

        result = await client.resolve_by_filename("One.md")

        assert result["passages"] == [
            {"chunk_id": None, "doc_id": "id9", "title": "One.md", "page": None, "text": "only body"}
        ]

    async def test_an_older_store_with_several_matches_gives_no_passages(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"text": "a\n\n---\n\nb", "matched_titles": ["A", "B"], "doc_ids": ["a", "b"]}
        )

        result = await client.resolve_by_filename("A")

        assert result["passages"] == []

    async def test_404_status_code_returns_empty(self, patched_httpx):
        client = make_client()
        # 404 detected via status_code before raise_for_status.
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=404)

        result = await client.resolve_by_filename("missing.pdf")
        assert result == {"query": "__file__:missing.pdf", "data": ""}
        assert len(patched_httpx.calls) == 1

    async def test_empty_text_returns_empty(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"text": "   ", "matched_titles": [], "doc_ids": []}
        )

        result = await client.resolve_by_filename("blank.txt")
        assert result == {"query": "__file__:blank.txt", "data": ""}

    async def test_non_404_http_error_exhausts(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=500)

        result = await client.resolve_by_filename("x.txt")
        assert result == {"query": "__file__:x.txt", "data": ""}
        assert len(patched_httpx.calls) == 2

    async def test_request_error_exhausts(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: httpx.ConnectError("nope")

        result = await client.resolve_by_filename("x.txt")
        assert result == {"query": "__file__:x.txt", "data": ""}

    async def test_404_surfaced_via_raise_for_status(self, patched_httpx):
        # Defensive branch: the pre-check sees a non-404 status, but
        # raise_for_status() still raises a 404 HTTPStatusError.
        client = make_client()

        def make_404_error():
            request = httpx.Request("GET", "http://ks.test/file/resolve")
            err_resp = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=err_resp)

        # status_code 200 passes the pre-check; raise_for_status raises 404.
        resp = FakeResponse(status_code=200)
        resp.raise_for_status = make_404_error
        patched_httpx.handler = lambda m, u, k: resp

        result = await client.resolve_by_filename("x.txt")
        assert result == {"query": "__file__:x.txt", "data": ""}
        # 404 short-circuits without retry.
        assert len(patched_httpx.calls) == 1


# ===========================================================================
# fetch_for_rag
# ===========================================================================


class TestFetchForRag:
    async def test_filename_resolves_short_circuits(self, patched_httpx):
        client = make_client()

        # The query names a file; resolve returns content -> used directly.
        def handler(method, url, kwargs):
            assert url == "http://ks.test/file/resolve"
            return FakeResponse(
                json_data={"text": "resolved body", "matched_titles": ["a.txt"]}
            )

        patched_httpx.handler = handler

        # Quoted name extracts to exactly "a.txt".
        result = await client.fetch_for_rag('please read "a.txt"')
        assert result["query"] == "__file__:a.txt"
        assert "resolved body" in result["data"]
        # Only the resolve call happened; no /query, no /file inventory.
        assert len(patched_httpx.calls) == 1

    async def test_filename_resolve_empty_falls_through_to_query(self, patched_httpx):
        client = make_client()

        def handler(method, url, kwargs):
            if url.endswith("/file/resolve"):
                return FakeResponse(status_code=404)  # resolve found nothing
            # semantic query succeeds
            return FakeResponse(json_data={"documents": [["semantic hit"]]})

        patched_httpx.handler = handler

        result = await client.fetch_for_rag("read a.txt please")
        assert (result["query"], result["data"]) == ("read a.txt please", "semantic hit")
        urls = [c[1] for c in patched_httpx.calls]
        assert urls == ["http://ks.test/file/resolve", "http://ks.test/"]

    async def test_no_filename_query_has_data(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"documents": [["direct answer"]]}
        )

        result = await client.fetch_for_rag("a generic question")
        assert (result["query"], result["data"]) == ("a generic question", "direct answer")
        # No filename -> single /query call only.
        assert len(patched_httpx.calls) == 1

    async def test_empty_query_appends_inventory(self, patched_httpx):
        client = make_client()

        def handler(method, url, kwargs):
            if url == "http://ks.test/":
                return FakeResponse(json_data={"documents": [[]]})  # no semantic hits
            # inventory
            return FakeResponse(json_data={"documents": [{"title": "Inv Doc"}]})

        patched_httpx.handler = handler

        result = await client.fetch_for_rag("a generic question")
        assert result["query"] == "a generic question"
        assert result["data"].startswith(
            "Semantic search did not return close excerpts"
        )
        assert "- Inv Doc " in result["data"]

    async def test_empty_query_and_empty_inventory(self, patched_httpx):
        client = make_client()

        def handler(method, url, kwargs):
            if url == "http://ks.test/":
                return FakeResponse(json_data={"documents": [[]]})
            return FakeResponse(json_data={"documents": []})

        patched_httpx.handler = handler

        result = await client.fetch_for_rag("a generic question")
        # data stays empty when inventory empty too.
        assert result == {"query": "a generic question", "data": ""}


# ===========================================================================
# __call__
# ===========================================================================


class TestCall:
    async def test_call_delegates_to_fetch_for_rag(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"documents": [["called"]]}
        )

        result = await client("just text")
        assert (result["query"], result["data"]) == ("just text", "called")


# ===========================================================================
# smart_search
# ===========================================================================


class TestSmartSearch:
    async def test_success_with_all_filters(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"results": {"documents": ["d1", "d2"]}, "total": 2}
        )

        result = await client.smart_search(
            "find",
            n_results=4,
            categories=["finance"],
            entities=["acme"],
            min_confidence=0.5,
            entity_type="org",
        )

        assert result == {"query": "find", "data": "d1\n\nd2", "total": 2}
        method, url, kwargs = patched_httpx.calls[0]
        assert method == "POST"
        assert url == "http://ks.test/smart-search"
        assert kwargs["json"] == {
            "query": "find",
            "n_results": 4,
            "categories": ["finance"],
            "entities": ["acme"],
            "min_confidence": 0.5,
            "entity_type": "org",
        }

    async def test_success_minimal_payload(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"results": {"documents": []}, "total": 0}
        )

        result = await client.smart_search("q")

        # Optional filters omitted from payload.
        assert patched_httpx.calls[0][2]["json"] == {"query": "q", "n_results": 5}
        assert result == {"query": "q", "data": "", "total": 0}

    async def test_min_confidence_zero_included(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"results": {"documents": []}, "total": 0}
        )

        await client.smart_search("q", min_confidence=0.0)
        # 0.0 is not None, so it must be included.
        assert patched_httpx.calls[0][2]["json"]["min_confidence"] == 0.0

    async def test_404_returns_empty(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=404)

        result = await client.smart_search("q")
        assert result == {"query": "q", "data": "", "total": 0}
        assert len(patched_httpx.calls) == 1

    async def test_500_retries_then_error(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=500)

        result = await client.smart_search("q")
        assert result == {
            "query": "q",
            "data": "Error: smart search failed after 2 attempts",
            "total": 0,
        }
        assert len(patched_httpx.calls) == 2

    async def test_exception_retries_then_error(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: httpx.TimeoutException("slow")

        result = await client.smart_search("q")
        assert result["data"] == "Error: smart search failed after 2 attempts"

    async def test_success_without_metrics(self, patched_httpx, monkeypatch):
        monkeypatch.setattr(ksc, "_METRICS_AVAILABLE", False)
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"results": {"documents": ["d1"]}, "total": 1}
        )

        result = await client.smart_search("q")
        assert result == {"query": "q", "data": "d1", "total": 1}


# ===========================================================================
# search_by_entity
# ===========================================================================


class TestSearchByEntity:
    async def test_success(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"results": {"documents": [["e1", "e2"]]}, "total": 9}
        )

        result = await client.search_by_entity("Acme", "ORG", n_results=7)

        assert result == {"entity": "Acme", "data": "e1\n\ne2", "total": 9}
        method, url, kwargs = patched_httpx.calls[0]
        assert url == "http://ks.test/search-by-entity"
        assert kwargs["params"] == {
            "entity": "Acme",
            "entity_type": "ORG",
            "n_results": 7,
        }

    async def test_no_documents(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"results": {"documents": [[]]}, "total": 0}
        )

        result = await client.search_by_entity("Acme", "ORG")
        assert result == {"entity": "Acme", "data": "", "total": 0}

    async def test_404_returns_empty(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=404)

        result = await client.search_by_entity("Acme", "ORG")
        assert result == {"entity": "Acme", "data": "", "total": 0}
        assert len(patched_httpx.calls) == 1

    async def test_400_returns_empty(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=400)

        result = await client.search_by_entity("Acme", "ORG")
        assert result == {"entity": "Acme", "data": "", "total": 0}

    async def test_500_retries_then_error(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=500)

        result = await client.search_by_entity("Acme", "ORG")
        assert result == {
            "entity": "Acme",
            "data": "Error: search by entity failed after 2 attempts",
            "total": 0,
        }
        assert len(patched_httpx.calls) == 2

    async def test_exception_retries_then_error(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: httpx.ConnectError("down")

        result = await client.search_by_entity("Acme", "ORG")
        assert result["data"] == "Error: search by entity failed after 2 attempts"


# ===========================================================================
# get_categories
# ===========================================================================


class TestGetCategories:
    async def test_success_returns_payload(self, patched_httpx):
        client = make_client()
        payload = {"total_documents": 3, "categories": [{"name": "finance", "count": 3}]}
        patched_httpx.handler = lambda m, u, k: FakeResponse(json_data=payload)

        result = await client.get_categories()

        assert result == payload
        assert patched_httpx.calls[0][1] == "http://ks.test/categories"

    async def test_http_error_exhausts_to_default(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=500)

        result = await client.get_categories()
        assert result == {"total_documents": 0, "categories": []}
        assert len(patched_httpx.calls) == 2

    async def test_request_error_exhausts_to_default(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: httpx.ConnectError("down")

        result = await client.get_categories()
        assert result == {"total_documents": 0, "categories": []}

    async def test_recovers_after_error(self, patched_httpx):
        client = make_client(max_retries=3)
        payload = {"total_documents": 1, "categories": ["x"]}
        patched_httpx.set_sequence(
            [httpx.ConnectError("first"), FakeResponse(json_data=payload)]
        )

        result = await client.get_categories()
        assert result == payload
        assert len(patched_httpx.calls) == 2


class TestQueryPassages:
    async def test_each_passage_keeps_its_chunk_id_document_and_metadata(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={
                "ids": [["doc-a:3", "doc-b:0"]],
                "documents": [["Hotel cap is $250.", "Laptops are leased."]],
                "metadatas": [[
                    {"doc_id": "doc-a", "title": "4_Expense_Policy.md", "chunk_index": 3},
                    {"doc_id": "doc-b", "title": "IT.pdf", "chunk_index": 0, "page": 2},
                ]],
                "distances": [[0.12, 0.4]],
            }
        )

        result = await client.query("hotel cap")

        first, second = result["passages"]
        assert (first["chunk_id"], first["doc_id"], first["title"]) == (
            "doc-a:3", "doc-a", "4_Expense_Policy.md"
        )
        assert first["chunk_index"] == 3
        assert first["distance"] == 0.12
        assert first["metadata"]["doc_id"] == "doc-a"
        assert (second["chunk_id"], second["page"]) == ("doc-b:0", 2)

    async def test_each_passage_is_shown_to_the_model_under_its_document_title(
        self, patched_httpx
    ):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={
                "ids": [["doc-a:3", "doc-b:0"]],
                "documents": [["Hotel cap is $250.", "Laptops are leased."]],
                "metadatas": [[
                    {"doc_id": "doc-a", "title": "4_Expense_Policy.md"},
                    {"doc_id": "doc-b", "title": "IT.pdf", "page": 2},
                ]],
            }
        )

        result = await client.query("hotel cap")

        assert result["data"] == (
            "[Source: 4_Expense_Policy.md]\nHotel cap is $250.\n\n"
            "[Source: IT.pdf, page 2]\nLaptops are leased."
        )


class TestResolveByDocId:
    async def test_success_returns_the_document_text_under_its_title(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(
            json_data={"doc_id": "abc", "title": "q4.md", "text": "Q4 revenue 4.2M", "chunk_count": 2}
        )

        result = await client.resolve_by_doc_id("abc")

        assert result["data"] == "[Indexed file: q4.md | id: abc]\n\nQ4 revenue 4.2M"
        assert (result["doc_id"], result["title"]) == ("abc", "q4.md")
        assert patched_httpx.calls[0][1] == "http://ks.test/file/abc/text"

    async def test_the_doc_id_is_escaped_in_the_path(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=404)

        await client.resolve_by_doc_id("a/b c")

        assert patched_httpx.calls[0][1] == "http://ks.test/file/a%2Fb%20c/text"

    async def test_an_unknown_doc_id_returns_empty_data_without_retrying(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=404)

        result = await client.resolve_by_doc_id("ghost")

        assert result == {"query": "__doc__:ghost", "data": ""}
        assert len(patched_httpx.calls) == 1

    async def test_blank_text_returns_empty_data(self, patched_httpx):
        client = make_client()
        patched_httpx.handler = lambda m, u, k: FakeResponse(json_data={"text": "  "})

        assert (await client.resolve_by_doc_id("abc"))["data"] == ""

    async def test_server_errors_are_retried_then_give_empty_data(self, patched_httpx):
        client = make_client(max_retries=2)
        patched_httpx.handler = lambda m, u, k: FakeResponse(status_code=500)

        result = await client.resolve_by_doc_id("abc")

        assert result == {"query": "__doc__:abc", "data": ""}
        assert len(patched_httpx.calls) == 2

    async def test_request_errors_are_retried(self, patched_httpx):
        client = make_client(max_retries=3)
        patched_httpx.set_sequence(
            [httpx.ConnectError("down"), FakeResponse(json_data={"title": "a", "text": "body"})]
        )

        result = await client.resolve_by_doc_id("abc")

        assert result["data"].endswith("body")
        assert len(patched_httpx.calls) == 2
