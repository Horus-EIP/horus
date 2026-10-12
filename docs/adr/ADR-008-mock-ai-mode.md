# ADR-008: Mock AI mode is a mock model server

**Date:** 2026-10-09
**Status:** Accepted (09/10/2026)
**Deciders:** Loup Marquez-Luttringer, Noah Gibelli, Matheus Lopez
**Backlog:** B-69
**Related:**

- [ADR-004](ADR-004-closed-source-licence.md) (Horus runs offline and keeps documents private)
- [ADR-005](ADR-005-accepted-quality-debt.md), item B1 (no end-to-end test in CI)
- [ADR-006](ADR-006-low-ram-machines.md) (what the CPU profiles need)
- The design this ADR records: *Horus Mock AI mode, v2: a mock model server* (09/10/2026), which supersedes v1 of 25/09/2026

---

## Context

The first acceptance test (ATP, 18/09/2026) showed that the core of Horus was barely testable on ordinary machines:

- 4 of the 6 testers had no usable GPU, so the answer scenarios F18–F20 were run by 2 testers only;
- one tester's 16 GB machine froze, and 11 scenarios could not be run at all;
- the install was heavy: 1.5 to 2 hours on a first run, about 150 GB of disk at its peak.

Most of what testers and CI check has nothing to do with the language model: sign-in, permissions, upload, search, routing, tasks, the WebSocket, the admin pages. CI has no end-to-end test because a runner cannot run the model (ADR-005, B1).

v1 of the design (25/09/2026) answered with a provider layer inside each service. Since then the ground has moved:

- every install talks to its model over HTTP: llama.cpp (`llm`) on CPU, vLLM on GPU, both behind the same OpenAI-style API and the services' one client (`LLM_BACKEND=vllm`, `LLM_VLLM_URL`);
- the CPU images already leave out torch and transformers (B-87, B-96).

## Decision

Mock AI mode is a small server, `llm-mock`, that speaks the same OpenAI-style API as our model servers. With `HORUS_AI_MODE=mock` it replaces them: llama.cpp on CPU installs, vLLM on GPU installs.

- **Only the language model is mocked.** The embeddings (FastEmbed) and spaCy's small English model stay real, so search is real and switching modes needs no re-indexing.
- **The services get no mock code.** MAS, the agent and the knowledge store keep their one HTTP client. Two changes only:
  - each model request names its purpose in an `X-Horus-Purpose` header, which real servers ignore;
  - MAS reports the mode it finds on the model server (`GET /v1/models`, `owned_by: "horus-mock"`).
- **The mock knows what to answer** from the request itself:
  - a structured call carries `response_format.json_schema`: its `name` says which call it is, and the mock returns JSON valid against the schema that came with it;
  - a text call carries `X-Horus-Purpose`;
  - anything else gets a short neutral text and a WARNING log line, so a new or renamed call shows up instead of silently getting nonsense.
- **Every response is deterministic,** and answers are assembled from the retrieved documents with their sources, never invented. A factual question is never answered without them (regression F20, "the capital of Peru"), and a question the documents do not cover gets the agent's own refusal, "I don't have that information yet.".
- **Latency and failures can be injected** (`HORUS_MOCK_LATENCY_MS`, `HORUS_MOCK_SCENARIO`: normal, slow, invalid_json, refuse, error).
- It runs on the CPU (lite) images: no GPU and no model download. A Compose overlay, `docker-compose.mock.yml`, adds `llm-mock` and removes `llm`, `llm-model` and `vllm`. The installer offers a `mock` profile and switches with `--ai mock | local | status`.

**Why:** since every install already reaches its model over HTTP, a mock server covers every call with no change to the services' code paths. The work drops from 12–13 days for v1 to about 6.

## What it is for, and what it is not

- **First, the end-to-end test in CI** (B-77): Tek5 Objective 2.5, due at the end of October. It repays ADR-005 B1.
- **Then** testers whose machine cannot run the model, and demos without hardware (ATP v8).
- **Not** a product mode for customers.
- **Never** a cloud AI as a fallback: that would break the offline and privacy promise of ADR-004.
- **Answer quality** is judged only on real models, and so is performance.

## Options we did not take

### v1's in-process provider package

v1 put a provider layer (`get_llm()`, `get_embedder()`, `get_ner()`, `get_analyzer()`) inside every service, with a local, a vLLM and a mock implementation of each, and purpose tags on every call. B-69 asked where that package would live:

- **one shared package**, `src/packages/horus_ai/`, which moves every Compose build context from `../services/<svc>` to `..` so each image can install it;
- **or a copy per service** under `core/ai/`, kept identical by a CI hash check: no build change, but the same code three times.

Both need every call site moved behind the interfaces, lazy imports so that a mock process never loads the heavy libraries, and mock code shipped in every production image. With a mock server none of that is needed, and B-69's question disappears: there is no package to place.

### Mocking the embeddings

v1 also replaced the embedders with a hash embedder, with collections named per embedder and a re-index job on every switch (B-73), and moved the knowledge store onto providers (B-74). We keep the real embeddings instead:

- FastEmbed already runs on the CPU in every image, so mocking it saves little;
- a mock embedder would make every switch a re-index, and a first start of 0.2.0 a Chroma migration;
- real embeddings keep search real, which is most of what a tester checks.

## Consequences

- A new service, `src/services/llm-mock/`, its image, and the overlay. B-70 (the provider package), B-73 (mock embeddings) and B-74 (the knowledge store on providers) are dropped.
- The mock can drift when a prompt or a schema changes. Contract tests run the same assertions against the mock in CI and against a real model by hand, and an unknown purpose is logged at WARNING.
- Testers could take mock answers for the AI's. Mock mode is always visible: `GET /system/ai`, a banner on every page, a "Simulated" badge on each mock answer, "AI: Mock" in the desktop app, and one WARNING line per service at start.
- The answer cache must never serve a mock answer in local mode or the reverse: its key must include the model.
- Whether a commercial licence key may be used in mock mode is left to the licence-key work (ADR-004).

---

## Update 09/10/2026: no model at all

**Backlog:** B-73 and B-74, reopened with a smaller scope, and B-137. The design is now v2.1, *Horus Mock AI mode, v2.1: a mock model server, and no model at all*.

Mock mode now replaces every model, not only the language model. A mock install loads none:

- **The language model:** `llm-mock` answers the chat calls, as decided above.
- **The two embedding models:** MiniLM in MAS (skill matching and the router's first stage) and bge-base in the knowledge store (search). `llm-mock` also serves `/v1/embeddings`, with vectors hashed from the words of each text. MAS and the knowledge store get a generic OpenAI-compatible embeddings client, used when an embeddings URL is set; unset, FastEmbed runs in the service as today.
- **spaCy:** turned off by a setting, not faked. The knowledge store and the agent use the regex extraction they already have for installs without spaCy.
- **Monitoring:** Prometheus, Loki, Tempo and Alloy do not run in mock mode unless `HORUS_MONITORING=on`.

**Why:** demos and tests on machines with no GPU and little memory, and a quick install. With the language model mocked, a mock install still loaded MiniLM, bge-base and spaCy and ran four monitoring containers.

**What it costs:**

- **Search becomes word matching.** A question finds the passages that share its words, and a synonym finds nothing ("leave" does not match "vacation"). Search quality is now judged, like answer quality, on real models only, and the CI end-to-end job no longer runs the real search: the knowledge store's tests keep one test on FastEmbed.
- **A switch between modes re-embeds the stored documents.** The knowledge store already re-embeds at start every passage stored with another embedder than the running one. Towards mock it is quick; towards local it takes the CPU embedding time of the whole corpus. The installer says how many documents it will re-embed and waits for the re-index before its smoke test.

**What does not change:** the fakes still live only in `llm-mock`. The services get settings and a generic client, nothing that knows it talks to a mock. B-73 needs no provider package and no collections named per embedder; B-74 needs no provider.

This update replaces, for mock mode, the first point of the Decision ("Only the language model is mocked") and the reasons under "Mocking the embeddings", and it reopens B-73 and B-74, which the Consequences dropped.
