# Community Contributions

Running log of two-way engagement with upstream projects and developer communities. Required by EIP Tech 4 Objective 1 (Tech Watch — *Sharing & openness*). Tracked here so anyone can verify a real contribution exists and link to it.

---

## Log

| Date | Project | Type | Description | Link | Outcome |
|------|---------|------|-------------|------|---------|
| `[ TO ADD ]` | `[ e.g. fastapi ]` | issue / PR / discussion | `[ what you wrote ]` | `[ url ]` | `[ open / merged / closed-helpful / closed-wontfix ]` |

> **Before jury:** at least one row must be filled with a real link. The "Drafts" section below gives you ready-to-post starting points if you haven't engaged yet.

---

## Drafts you can post in 15 minutes

These are pre-written contributions targeting projects we actually use. Pick one, customise the version numbers / repro steps, and post.

---

### Draft 1 — ChromaDB: document a `n_results` upper-bound gotcha

**Project:** [chroma-core/chroma](https://github.com/chroma-core/chroma)
**Type:** documentation issue or small docs PR
**Channel:** GitHub Issues → "Documentation" label

**Title:** `Docs: clarify behaviour when n_results > collection size`

**Body:**

> Hi team — we're using ChromaDB 0.4.x as the vector store in a multi-agent RAG pipeline. We hit a small surprise that I think is worth a one-line doc note.
>
> When calling `collection.query(query_texts=[...], n_results=N)` with `N > len(collection)`, ChromaDB silently returns only the available results without raising or warning. This is the correct behaviour, but it's not explicitly documented in [the Query docs](https://docs.trychroma.com/usage-guide#querying-a-collection). For RAG pipelines that compute a precision@k metric, the silent shrinking can skew the denominator.
>
> Would a short note like *"If `n_results` exceeds the number of items in the collection, all items are returned without error."* be welcome? Happy to send a PR.

---

### Draft 2 — FastAPI: clarify WebSocket auth dependency behaviour

**Project:** [fastapi/fastapi](https://github.com/fastapi/fastapi)
**Type:** Discussion or docs issue
**Channel:** GitHub Discussions → "Questions" category

**Title:** `WebSocket auth via Depends — should HTTPException close the connection?`

**Body:**

> We're using FastAPI for a WebSocket chat endpoint. Our auth dependency raises `HTTPException(401)` when the JWT is invalid. Empirically, this works (the connection is closed), but it took some digging to learn the recommended pattern.
>
> Could the [WebSocket section](https://fastapi.tiangolo.com/advanced/websockets/) include a short example showing the canonical pattern for WS auth via `Depends`? Specifically the difference between:
>
> - raising `HTTPException` from a `Depends`, vs.
> - calling `await websocket.close(code=1008)` explicitly inside the dependency.
>
> Happy to draft a small docs PR if there's a preferred pattern.

---

### Draft 3 — Tempo: report a small dashboard provisioning quirk

**Project:** [grafana/tempo](https://github.com/grafana/tempo)
**Type:** issue with reproducible example
**Channel:** GitHub Issues → "type/bug" or "type/docs"

**Title:** `Provisioned datasource: jsonData.serviceMap requires lokiSearch when Loki not in stack`

**Body:**

> Running Tempo 2.6.0 with the Grafana datasource provisioned via `datasources.yaml`. When Loki isn't in the same stack, enabling `serviceMap: true` produces noisy log lines (`failed to query LokiSearch`). Workaround: explicitly set `lokiSearch: { datasourceUid: '' }`.
>
> Filing in case others trip on the same thing — happy to send a small PR to call it out in the provisioning docs.

---

## Why a single 30-line bug report is enough

The EIP guide's bar for *Sharing & openness* is **active participation**, not a major upstream commit. A single well-written issue that demonstrates:

- you read the existing docs first,
- you can reproduce a problem in a minimal way,
- you offer to do the work,

…clears the bar. Anything more is a bonus.

---

## How to make the contribution count for the jury

1. Pick one draft above, customise it, post it.
2. Copy the URL into the Log table at the top of this file.
3. Take a screenshot of the issue / PR page (so the jury doesn't need to follow a live link) → save under `docs/assets/community/`.
4. If you get a maintainer reply or a merge, update the **Outcome** column.

---

## Related

- [tech-watch.md](tech-watch.md) — sources we follow.
- [diffusion-strategy.md](diffusion-strategy.md) — what we publish vs. keep closed.
