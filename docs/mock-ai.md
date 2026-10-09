# Mock AI mode

Mock AI mode runs Horus with no AI model at all: no language model, no embedding model, no spaCy. A small server, `llm-mock`, takes the place of the model server (llama.cpp on a CPU install, vLLM on a GPU install). It answers every model call MAS and the agent make, from the documents the knowledge store retrieved, and it computes the embeddings MAS and the knowledge store search with, from the words of each text. Monitoring is off too, unless `HORUS_MONITORING=on`. It needs no GPU, little memory and no model download.

The decision and the options we did not take are in [ADR-008](adr/ADR-008-mock-ai-mode.md) (update of 09/10/2026: no model at all).

**The answers and the search are simulated.** The answers are sentences copied from your documents, or a refusal; search finds the passages that share the question's words. Use mock mode to test Horus, for demos on a machine that cannot run the models, and for the end-to-end test in CI. Never use it to judge answer quality, search quality or speed: that is done on real models only.

---

## What runs, and what does not

| Part | Local mode | Mock mode |
|---|---|---|
| Language model | llama-server (`llm`) on a CPU, vLLM on a GPU | `llm-mock` answers every chat call |
| Embeddings | FastEmbed in MAS (MiniLM, 384 values) and in the knowledge store (bge-base, 768 values) | `llm-mock`'s `/v1/embeddings`: each text becomes a hashed bag of its words and word pairs |
| Names, dates, amounts | spaCy in the knowledge store and the agent, plus regular expressions | Regular expressions only (`HORUS_SPACY=off`) |
| Monitoring | Prometheus, Loki, Tempo and Alloy, and the services' traces | Off, unless `HORUS_MONITORING=on` |
| Everything else | Real | Real: sign-in, permissions, uploads, routing, tasks, the WebSocket and the admin pages |

The services hold no mock code: MAS and the knowledge store get an OpenAI-compatible embeddings client used when an embeddings URL is set, the knowledge store and the agent a setting that turns spaCy off, and the Compose files say which is on. Every fake lives in `llm-mock`.

---

## What it is for

| For | Not for |
|---|---|
| The end-to-end test in CI (`e2e-mock`, which repays ADR-005 B1) | A product mode for customers |
| Testers whose machine is under the `cpu-lean` minimum, and demos without the hardware | A cloud model as a fallback: Horus stays offline (ADR-004) |
| Every ATP scenario that is not about answer or search quality | Measuring answer quality, search quality or speed |

### Limits

- **Search is word matching.** A question finds the passages that share its words. A synonym finds nothing: "leave" does not match "vacation", and a question worded unlike the documents finds nothing. Demo questions should use the documents' words.
- **Routing.** MAS's router first compares the question with example questions by embedding. On hashed vectors that stage decides almost nothing (0 of 116 questions of `tests/mas/data/router_testset.yaml` at the default thresholds), so routing falls to `llm-mock`'s keyword rules: 70.7 % of the test set right, against 94 % with MiniLM and Qwen3-4B.
- **No people or companies.** Without spaCy the knowledge store keeps amounts, dates and word-frequency topics only, and the agent's payment extraction finds a payee only in comma-separated rows, never in running text. A switch does not recompute this: documents uploaded in mock mode keep it after `--ai local` until they are uploaded again, and the reverse.
- **Monitoring off.** The logs, metrics and traces pages say "Monitoring is off on this install" until `HORUS_MONITORING=on`.

---

## Turning it on and off

### With the installer

| Command | What it does |
|---|---|
| `START-HERE --ai mock` | Says how many documents the knowledge store holds and that they will be re-embedded (it asks first above 100, or when the knowledge store does not answer; `--yes` answers). Backs up `src/infra/.env`, stops `llm` (or `vllm`), and the monitoring services unless `HORUS_MONITORING=on`, writes `COMPOSE_FILE` with `docker-compose.mock.yml` (and `docker-compose.monitoring-off.yml`), sets `HORUS_AI_MODE=mock`, restarts Horus, waits for every service and for the re-embedding, and runs the smoke test. If anything fails it puts the old `.env` back and restarts the previous mode, which re-embeds the documents back. |
| `START-HERE --ai local` | Checks the machine (memory, disk, network, ports, the same checks as an install), says how many documents will be re-embedded and how long that takes on the processor (asks first above 100), downloads and checks the model of the profile it picks, writes that profile's settings, turns monitoring back on unless `HORUS_MONITORING=off`, restarts Horus, waits for the re-embedding and runs the smoke test. If anything fails, mock mode comes back. |
| `START-HERE --ai status` | Prints `AI: Mock` or `AI: Local`, the model server and whether monitoring is on. It warns when `HORUS_AI_MODE` or `HORUS_MONITORING` disagree with `COMPOSE_FILE` (`--restart` applies a changed `HORUS_MONITORING`), or when `COMPOSE_FILE` is set in the shell (Docker Compose then ignores the one in `.env`). |

`START-HERE` is `START-HERE-Windows.bat`, `./START-HERE-Linux.sh` or `START-HERE-macOS.command`; from a checkout, `python installer/horus_install.py`.

A first install can be a mock install: `--profile mock`. On a machine under the `cpu-lean` minimum without a usable NVIDIA GPU, an interactive install offers mock mode instead of stopping; a run with `--non-interactive` still stops, and its screen lists `--profile mock` among the alternatives.

### What a switch costs

Users and conversations are untouched. The stored documents are re-embedded, because their vectors come from the other mode's embeddings: the knowledge store records the embedder of every passage (`fastembed-0.8.1:BAAI/bge-base-en-v1.5` locally, `http:horus-mock:768` in mock mode), and its startup re-index re-embeds every passage stored with another one. Until it ends, search mixes the two kinds of vectors, so the installer waits for it, with its progress, before the smoke test. With `KNOWLEDGE_STORE_REINDEX_ON_STARTUP=0` the installer starts it itself.

- **Towards mock** it takes seconds: `llm-mock` hashes words.
- **Towards local** it takes the CPU embedding time of the whole corpus, about 4 passages per second (measured in the knowledge store container on the development laptop); a passage is about 800 new characters of text. The installer says the time before it starts.

Measured on 09/10/2026, in a throwaway Docker-in-Docker on the development laptop (`cpu-standard`, the demo corpus: 5 documents, 22 passages):

| Step | Time |
|---|---|
| `--ai mock` | 62 s, of which the re-embedding 0.45 s and the smoke test 2 s |
| `--ai local` | 167 s, of which the re-embedding 5.8 s and the smoke test, on the real model, 1 min 16 s |

A GPU install switched to mock mode runs the CPU images, so a prebuilt install downloads them, and an install built from source rebuilds them.

### By hand

Mock mode is two more Compose files on top of the CPU stack, in `src/infra/.env`:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.cpu.yml:docker-compose.mock.yml:docker-compose.monitoring-off.yml
HORUS_AI_MODE=mock
```

(`;` instead of `:` on Windows; leave out the last file to keep monitoring.) Stop `llm`, and `loki alloy tempo prometheus` when you drop monitoring, first (`docker compose stop llm`): a service the files no longer start keeps running until it is stopped. Then `docker compose up -d`.

`docker-compose.mock.yml`:

- adds `llm-mock` (no published port; the services reach it on `horus-net` as `http://llm-mock:8080/v1`);
- turns off `llm`, `llm-model` and `vllm`;
- points MAS and the agent at `llm-mock` under the model name `horus-mock`, so the agent's answer cache, whose key includes the model name, never serves a mock answer to a real model or the reverse;
- points MAS's and the knowledge store's embeddings at `llm-mock` (`MAS_EMBED_URL`, `KNOWLEDGE_STORE_EMBED_URL`, model `horus-mock`), and makes the knowledge store wait for it;
- turns spaCy off (`HORUS_SPACY=off`) in the knowledge store and the agent, and tells MAS so for `/system/ai`;
- replaces Prometheus's `llm` scrape target with an empty one, so monitoring, when on, shows no target that cannot exist;
- makes MAS and the agent wait for `llm-mock` instead of `llm`;
- tells MAS, the agent and the knowledge store `HORUS_AI_MODE=mock`, whatever `.env` says.

`docker-compose.monitoring-off.yml` gives Prometheus, Loki, Tempo and Alloy a profile nobody enables and 0 replicas, lets the web client start without them, turns the services' traces off (`OTEL_SDK_DISABLED=true`, `OTEL_ENABLED=false`), and tells the web client and MAS `HORUS_MONITORING=off`.

### Settings (`src/infra/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `HORUS_AI_MODE` | `local` | `mock` or `local`. The installer keeps it in step with `COMPOSE_FILE`; the Compose files are what the services follow. |
| `HORUS_MONITORING` | off in mock mode, on in local mode | `on` or `off`. The installer adds or drops `docker-compose.monitoring-off.yml` from it on an install, a switch, `--start` and `--restart`. |
| `HORUS_MOCK_LATENCY_MS` | `300` | Milliseconds `llm-mock` waits before each chat answer; embeddings never wait. CI uses 0. |
| `HORUS_MOCK_SCENARIO` | `normal` | `normal`; `slow` (5 to 40 s per chat call, the same for the same request); `invalid_json` (every JSON reply cut in half); `refuse` (every answer is the refusal); `error` (every model call fails with HTTP 500, embeddings included, while `/health` and `/v1/models` stay up: the services start, say so in a WARNING, and each call fails). |
| `HORUS_MOCK_MIN_SCORE` | `0.2` | Below this score no sentence is an answer, and the agent gets the refusal. |

The overlay sets these, and a local install may use them too:

| Variable | Default | Meaning |
|---|---|---|
| `MAS_EMBED_URL`, `MAS_EMBED_MODEL` | unset; `sentence-transformers/all-MiniLM-L6-v2` | An OpenAI-compatible embeddings server for MAS (`POST <url>/embeddings`, 384 values per vector). Unset, FastEmbed runs MiniLM in MAS. |
| `KNOWLEDGE_STORE_EMBED_URL`, `KNOWLEDGE_STORE_EMBED_MODEL` | unset; `BAAI/bge-base-en-v1.5` | The same for the knowledge store (768 values). Questions go without the BGE prefix. Setting or clearing the URL, or naming another model, re-embeds the stored documents at the next start; a new URL for the same model does not. |
| `HORUS_SPACY` | `on` | `off` turns spaCy off in the knowledge store and the agent. |

The embeddings client waits up to 60 s at start for a server that is not up yet, sends at most 32 texts per request, sends `dimensions` only to a server whose own size is wrong (`llm-mock` for MAS), and stops with a clear error on vectors of the wrong size.

---

## Seeing that it is on

- `GET /system/ai` on MAS, public: `{"mode": "mock", "model": "horus-mock", "server": "horus-mock", "simulated": true, "embeddings": "mock", "spacy": "off", "monitoring": "off"}`. MAS asks the model server for `/v1/models` when it starts, and its embeddings server the first time it needs to say; `owned_by: "horus-mock"` means mock, so the mode is the one of the server actually answering.
- The web client shows a banner on every page, "Mock AI mode: no AI model runs. Answers and search are simulated from the words of your documents.", and a **Simulated** badge on each answer whose `ai_provider` is `mock`. MAS stores `ai_provider` (`mock` or `local`) with each answer, in the conversation history and the task result.
- The desktop app's status screen shows `AI: Mock - no AI model runs. Answers and search are simulated from the words of your documents.` or `AI: Local`.
- MAS, the agent, the knowledge store and `llm-mock` each write one WARNING line at start that says what is faked or off in them: the answers, the embeddings (MAS, the knowledge store), spaCy (the agent, the knowledge store) and the traces.
- No service logs a model load: MAS and the knowledge store log "no embedding model is loaded", and the knowledge store and the agent "spaCy is off".

---

## How llm-mock answers

`src/services/llm-mock` is a Python server with no dependency outside the standard library. It serves `GET /health`, `GET /v1/models`, `POST /v1/chat/completions`, plain and streamed (Server-Sent Events, with `usage` and `finish_reason`), and `POST /v1/embeddings`. Every reply is deterministic: the same request gets the same reply.

It knows which call it is answering from the request:

- a structured call carries `response_format.json_schema`, whose `name` says which call it is: `task_route` (MAS's router) or `agent_answer` (the agent). The reply is valid against the schema in the request;
- a text call carries the `X-Horus-Purpose` header that MAS and the agent send with every model request: `intent`, `plan`, `announce`, `review`, `aggregate`, `answer`, `react_step`, `grounded`, `instruction`;
- anything else gets a short neutral text, or an object valid against its schema, and a WARNING line in `llm-mock`'s log, so a new or renamed call shows up.

| Call | Reply |
|---|---|
| `task_route` | `SINGLE_AGENT` or `COMPLEX_TASK` and an agent from the schema's own list. The agent is chosen by a keyword map (finance, hr, compliance, it_security, expenses) matched against the agents' names and descriptions, then by word overlap, then the general agent. Two domains, or a comparison (compare, versus, vs, against), make a complex task. |
| `intent` | `DIRECT_ANSWER` only for greetings and small talk ("Hello! Horus is running in mock AI mode."). A factual question is never answered directly (F20). |
| `plan` | One step per agent, "From the {agent} documents: {question}", chained. |
| `announce` | "I'm asking {agent 1} then {agent 2} to work on this." |
| `review` | `DONE` when no planned step remains, otherwise `CONTINUE`. |
| `aggregate` | "## Answer", one section per step with its result, then the sources. |
| `agent_answer` | The 1 to 3 sentences of the passages that best match the question, each followed by `[Source: <file>]`, with their labels in `sources`. Words are weighted by how rare they are among the sentences, and a question whose words the passages do not hold scores low: below `HORUS_MOCK_MIN_SCORE` the reply is `not_found` with "I don't have that information yet." MAS shows its own "The documents don't contain this information." after one retry. |
| `react_step`, `grounded` | The search tool first, then the same rule on the observations. |
| `/v1/embeddings` | For each text: its lower-cased words and word pairs, common English words dropped, each hashed with SHA-256 to a position and a sign, counts damped (1 + log of the count), then the vector normalised to unit length. `input` is a string or a list, `dimensions` is honoured (768 when absent), and a text with no word gets a fixed vector. |

With the demo corpus, "What was our Q4 2025 revenue?" finds the Q4 report and gets "FinCorp closed Q4 2025 with total revenue of **$4.2M**, up 12% year-over-year. [Source: 1_Q4_2025_Financial_Report.md]", and "What is the capital of Peru?" gets the refusal. The answer is often not the one a model would give: the mock matches words.

---

## What machine is enough

Mock mode needs no GPU and downloads no model. Measured on 09/10/2026 on the development laptop (AMD Ryzen AI 9 HX 370, Docker Desktop 29.2.1 on WSL 2), in a throwaway Docker-in-Docker daemon with nothing cached: a `--profile mock --build-from-source` install with the demo corpus, then the smoke test.

| | Monitoring off (the mock default) | Monitoring on | Real embeddings and spaCy, for comparison |
|---|---|---|---|
| Containers | 8 | 12 | 8 |
| Peak memory of the whole stack | 0.82 GiB | 0.94 GiB | 1.53 GiB |
| Disk, prebuilt images | 4.2 GiB | 5.7 GiB | the same images |
| Disk, built from source (with the build cache) | 9.9 GiB | 11.4 GiB | the same images |

The memory is the sum of each container's own peak, from the start of the stack to the end of the smoke test; sampled every 4 s, the stack as a whole peaked at 0.59, 0.71 and 1.44 GiB. The images keep the BGE and MiniLM weights and spaCy's small English model, 0.3 GiB that mock mode never loads, so `--ai local` downloads no embedding or spaCy model. It still downloads the rest of local mode: on a CPU profile the language model and the llama-server image, on a GPU profile the GPU images (or rebuilds them) and vLLM, which then downloads its model. The disk is `/var/lib/docker` on the containerd image store at its peak, which is the end of the install; the built-from-source figure with monitoring on adds the monitoring images' 1.5 GiB to the measured one.

The cold install took 8 min 33 s: 39 s to pull the database and queue images, 7 min 04 s to build, 43 s to start until every service was healthy; the smoke test then took 4 s. Turning monitoring on took 88 s, its images' download included.

---

## Tests

| Where | What |
|---|---|
| `tests/llm_mock` | The server: determinism, the SSE format, every reply checked with `jsonschema` against the schema sent, MAS's calls built with MAS's own prompt code, the demo-corpus answers, every scenario, and the embeddings (the same vector in two processes, the size asked for, unit length, a passage closer to a question that shares its words). CI job `test-llm-mock`. |
| `tests/contract` | The same assertions on the mock (in CI) and on a real model server (by hand): valid JSON for every schema, no factual question answered directly, answers cite a source, out-of-corpus questions refused. The requests are the ones MAS and the agent send: `tests/contract/requests/*.json`, which `tests/mas/unit/test_contract_requests.py` and `tests/agent/unit/test_contract_requests.py` keep equal to what the code builds. |
| `tests/mas`, `tests/knowledge_store`, `tests/agent` | The embeddings client against a local HTTP server, no FastEmbed import when the URL is set, spaCy never imported when it is off (in a fresh process too), and the local path unchanged. |
| `e2e-mock` (CI) | Builds the CPU images and `llm-mock`, starts the stack with `docker-compose.mock.yml`, uploads `demo_assets/`, runs `installer/smoke.py`, and fails unless its 9 steps pass. |

Running the contract on a real model, for example the GPU stack's vLLM:

```bash
HORUS_CONTRACT_LLM_URL=http://127.0.0.1:18000/v1 pytest -c tests/contract/pytest.ini tests/contract -m real_llm
```

The CPU stack's `llm` publishes no port: run the tests from a container on the stack's network and point them at `http://llm:8080/v1`.

First run on a real model, 09/10/2026: Qwen3-4B-Instruct-2507 Q4_K_M on llama-server (`cpu-standard`, development laptop), 19 of 20 in 2.5 minutes. The one failure is the `intent` prompt: the model answers "What is the capital of Peru?" with `DIRECT_ANSWER` and "The capital of Peru is Lima.", the F20 behaviour. Users do not see it: MAS re-routes a `DIRECT_ANSWER` to an agent unless the question is a greeting, small talk or arithmetic (`tasks/decomposition.py`), and with `LLM_BACKEND=vllm`, which every profile uses, MAS routes with `task_route` and never makes the `intent` call. The test stays as it is, because it is the model's own answer that it checks. `HORUS_CONTRACT_LLM_MODEL` overrides the model name in the requests. When MAS or the agent change a prompt or a schema, their contract-request tests fail until the requests are recorded again:

```bash
HORUS_UPDATE_CONTRACT_REQUESTS=1 pytest -c tests/mas/pytest.ini tests/mas/unit/test_contract_requests.py
HORUS_UPDATE_CONTRACT_REQUESTS=1 pytest -c tests/agent/pytest.ini tests/agent/unit/test_contract_requests.py
```

---

## ATP v8: F18 to F20 in mock mode

The acceptance test plan in the repository is v7 (`docs/eip_pool_tek5/Horus_ATP_v7.xlsx`); there is no v8 yet. For v8, every scenario can run in mock mode. F18 to F20, the three answer scenarios, then check the path, not the quality of the answer:

| Scenario | In mock mode, pass when |
|---|---|
| F18 – grounded answer ("What was our Q4 2025 revenue?") | The answer arrives in a few seconds with the **Simulated** badge, contains $4.2M and cites `1_Q4_2025_Financial_Report.md`, in the text and in the sources panel. |
| F19 – several documents ("Compare our Q4 spend against what the expense policy allows…") | The Manager announces two agents, both steps run and the final answer is the aggregate with a section per step. The answer itself is not judged: the mock refuses questions it cannot match word for word. |
| F20 – outside the corpus ("What is the capital of Peru?") | The answer is "The documents don't contain this information.", never "Lima". |

Answer and search quality, for F18 to F20, is still tested on real models (GPU) before a release.
