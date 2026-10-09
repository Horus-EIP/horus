# Mock AI mode

Mock AI mode runs Horus without a language model. A small server, `llm-mock`, takes the place of the model server (llama.cpp on a CPU install, vLLM on a GPU install) and answers every model call MAS and the agent make, from the documents the knowledge store retrieved. Since the update of 09/10/2026 no model runs at all: `llm-mock` also computes the embeddings MAS and the knowledge store search with, from the words of each text, and spaCy is off. Search is then word matching, and a switch between modes re-embeds the stored documents. Sign-in, permissions, uploads, routing, tasks, the WebSocket and the admin pages are real.

The decision and the options we did not take are in [ADR-008](adr/ADR-008-mock-ai-mode.md).

**The answers are simulated.** They are sentences copied from your documents, or a refusal. Use mock mode to test Horus, to run it on a machine that cannot run the model, and for the end-to-end test in CI. Never use it to judge answer quality or speed: that is done on real models only.

---

## What it is for

| For | Not for |
|---|---|
| The end-to-end test in CI (`e2e-mock`, which repays ADR-005 B1) | A product mode for customers |
| Testers whose machine is under the `cpu-lean` minimum, and demos without the hardware | A cloud model as a fallback: Horus stays offline (ADR-004) |
| Every ATP scenario that is not about answer quality | Measuring answer quality or speed |

---

## Turning it on and off

### With the installer

| Command | What it does |
|---|---|
| `START-HERE --ai mock` | Backs up `src/infra/.env`, stops `llm` (or `vllm`), adds `docker-compose.mock.yml` to `COMPOSE_FILE`, sets `HORUS_AI_MODE=mock`, restarts Horus, waits for every service and runs the smoke test. If anything fails it puts the old `.env` back and restarts the previous mode. |
| `START-HERE --ai local` | Checks the machine (memory, disk, network, ports, the same checks as an install), downloads and checks the model of the profile it picks, writes that profile's settings, restarts Horus and runs the smoke test. If anything fails, mock mode comes back. |
| `START-HERE --ai status` | Prints `AI: Mock` or `AI: Local` and the model server. It warns when `HORUS_AI_MODE` and `COMPOSE_FILE` disagree, or when `COMPOSE_FILE` is set in the shell (Docker Compose then ignores the one in `.env`). |

`START-HERE` is `START-HERE-Windows.bat`, `./START-HERE-Linux.sh` or `START-HERE-macOS.command`; from a checkout, `python installer/horus_install.py`.

A first install can be a mock install: `--profile mock`. On a machine under the `cpu-lean` minimum without a usable NVIDIA GPU, an interactive install offers mock mode instead of stopping; a run with `--non-interactive` still stops, and its screen lists `--profile mock` among the alternatives.

Users, conversations and documents are untouched by a switch. A GPU install switched to mock mode runs the CPU images, so a prebuilt install downloads them, and an install built from source rebuilds them.

### By hand

Mock mode is one more Compose file on top of the CPU stack, in `src/infra/.env`:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.cpu.yml:docker-compose.mock.yml
HORUS_AI_MODE=mock
```

(`;` instead of `:` on Windows.) Stop `llm` first (`docker compose stop llm`): a service the files no longer start keeps running until it is stopped. Then `docker compose up -d`.

`docker-compose.mock.yml`:

- adds `llm-mock` (no published port; MAS and the agent reach it on `horus-net` as `http://llm-mock:8080/v1`);
- turns off `llm`, `llm-model` and `vllm`;
- points MAS and the agent at `llm-mock` under the model name `horus-mock`, so the agent's answer cache, whose key includes the model name, never serves a mock answer to a real model or the reverse;
- makes MAS and the agent wait for `llm-mock` instead of `llm`;
- tells MAS, the agent and the knowledge store `HORUS_AI_MODE=mock`, whatever `.env` says.

### Settings (`src/infra/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `HORUS_AI_MODE` | `local` | `mock` or `local`. The installer keeps it in step with `COMPOSE_FILE`; the Compose files are what the services follow. |
| `HORUS_MOCK_LATENCY_MS` | `300` | Milliseconds `llm-mock` waits before each answer; CI uses 0. |
| `HORUS_MOCK_SCENARIO` | `normal` | `normal`; `slow` (5 to 40 s per call, the same for the same request); `invalid_json` (every JSON reply cut in half); `refuse` (every answer is the refusal); `error` (every model call fails with HTTP 500, while `/health` and `/v1/models` stay up). |
| `HORUS_MOCK_MIN_SCORE` | `0.2` | Below this score no sentence is an answer, and the agent gets the refusal. |

---

## Seeing that it is on

- `GET /system/ai` on MAS, public: `{"mode": "mock", "model": "horus-mock", "server": "horus-mock", "simulated": true}`. MAS asks the model server for `/v1/models` when it starts; `owned_by: "horus-mock"` means mock. The mode is the one of the server actually answering.
- The web client shows a banner on every page, and a **Simulated** badge on each answer whose `ai_provider` is `mock`. MAS stores `ai_provider` (`mock` or `local`) with each answer, in the conversation history and the task result.
- The desktop app's status screen shows `AI: Mock` or `AI: Local`.
- MAS, the agent, the knowledge store and `llm-mock` each write one WARNING line at start.

---

## How llm-mock answers

`src/services/llm-mock` is a Python server with no dependency outside the standard library. It serves `GET /health`, `GET /v1/models` and `POST /v1/chat/completions`, plain and streamed (Server-Sent Events, with `usage` and `finish_reason`). Every reply is deterministic: the same request gets the same reply.

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

With the demo corpus, "What was our Q4 2025 revenue?" gets "FinCorp closed Q4 2025 with total revenue of **$4.2M**, up 12% year-over-year. [Source: 1_Q4_2025_Financial_Report.md]" and "What is the capital of Peru?" gets the refusal. The answer is often not the one a model would give: the mock matches words, so it does not know that "leave" means "vacation".

---

## Tests

| Where | What |
|---|---|
| `tests/llm_mock` | The server: determinism, the SSE format, every reply checked with `jsonschema` against the schema sent, MAS's calls built with MAS's own prompt code, the demo-corpus answers, every scenario. CI job `test-llm-mock`. |
| `tests/contract` | The same assertions on the mock (in CI) and on a real model server (by hand): valid JSON for every schema, no factual question answered directly, answers cite a source, out-of-corpus questions refused. The requests are the ones MAS and the agent send: `tests/contract/requests/*.json`, which `tests/mas/unit/test_contract_requests.py` and `tests/agent/unit/test_contract_requests.py` keep equal to what the code builds. |
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

Answer quality, for F18 to F20, is still tested on a real model (GPU) before a release.
