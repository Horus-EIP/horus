# Knowledge Store Client

`KnowledgeStoreClient` (in
`src/services/agent/app/ai_agents/knowledge_store_client.py`) is the
async HTTP client the Agent service uses to talk to the Knowledge Store
service. It powers the `search_knowledge` tool, the ingestion endpoints,
and the inventory listing used when a semantic search returns nothing
useful.

The module uses `httpx.AsyncClient` so the client composes with the
FastAPI event loop. Every request is wrapped in timeouts, bounded
retries with exponential backoff, and optional Prometheus metrics.

---

## 1. Endpoint coverage

| Client method | HTTP | Knowledge Store route | Purpose |
|---------------|------|------------------------|---------|
| `fetch_for_rag(query)` | `POST` | `/search` | Semantic RAG retrieval |
| `smart_search(query, ...)` | `POST` | `/smart-search` | RAG with category / entity / confidence filters |
| `list_inventory()` | `GET` | `/files` | All documents currently in the store |
| `__call__(query)` | `POST` | `/search` | Alias to `fetch_for_rag` for callable interfaces |

## 2. Retry and timeout behavior

The client is configured with:

- `timeout` — per-request `httpx.Timeout` (default 30 s total).
- `max_retries` — how many attempts per call (default 3).
- `retry_delay` — initial wait between attempts (default 0.5 s).

On retriable errors (5xx, connection errors, read timeouts), the client
waits `retry_delay`, doubles it, and retries until `max_retries` is
reached. On the final failure, it logs the error and returns a result
dict with `"data": ""` so the ReAct loop can continue without the
retrieved context. Non-retriable errors (4xx client errors) are raised
immediately.

## 3. Graceful-empty-result handling

When semantic search returns zero matches or only low-confidence hits,
`fetch_for_rag` calls `list_inventory()` and returns the list of
document titles/IDs in the store. The ReAct loop can then either:

- give the user a "no direct match found, here is what is available"
  answer, or
- make a follow-up `search_knowledge` call with refined terms.

This avoids the failure mode where the agent silently produces an
answer without any retrieved context.

## 4. Prometheus metrics

When `core.metrics` is importable, every call records:

- `knowledge_store_requests_total{method, route, status}` — counter
- `knowledge_store_request_duration{method, route}` — histogram

The import is wrapped in `try/except ImportError` so the client stays
usable in lightweight test contexts where the metrics module is not
wired up.

## 5. Correlation IDs

The Agent service propagates its current correlation ID
(`X-Request-ID`) into every Knowledge Store call. The Knowledge Store
logs the ID on its side, which lets Grafana + Tempo stitch the whole
span chain end-to-end:

```
user → MAS → Agent → Knowledge Store
             └── same X-Request-ID ──┘
```

See `src/services/agent/app/agent_server/middleware.py` for how the
correlation ID is bound to the contextvar used by the logger.

## 6. Connection pooling

A single `httpx.AsyncClient` is reused per `KnowledgeStoreClient`
instance. The instance is long-lived (created at agent startup) so
connection pooling works. Do not create a new client per request — it
defeats the purpose of `AsyncClient` and doubles latency under load.

## 7. Why this design

- **Async** — the Agent's ReAct loop is already async. A sync client
  would block the event loop during retrieval and kill throughput.
- **Bounded retries** — the Knowledge Store is a hard dependency; we
  would rather the agent time out cleanly than hang the user request.
- **Metrics optional** — keeps the module importable in unit-test
  contexts that do not need full observability wiring.
- **Inventory fallback** — retrieval failure is more common than
  people expect; always having *something* to say is better than a
  blank answer.

## 8. Related code

- `src/services/agent/app/ai_agents/knowledge_store_client.py` — this module
- `src/services/agent/app/ai_agents/knowledge_retrieval_agent.py` — wraps the client with ranking
- `src/services/knowledge-store/app/api/routes/store.py` — server-side counterpart
- `src/services/agent/app/agent_server/middleware.py` — correlation ID propagation
