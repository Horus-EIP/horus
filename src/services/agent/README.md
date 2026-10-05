# Agent Service

> For the development team. Paths such as `tests/` and `scripts/dev/` are
> relative to the git checkout and are not part of the beta archive.

The Agent service is an autonomous AI worker that registers with the MAS orchestrator, consumes tasks from a **shared RabbitMQ work queue per specialization** (e.g. `horus.work.general`), processes them through a RAG (Retrieval-Augmented Generation) pipeline, and returns results back to MAS. Multiple instances of the same `AGENT_TYPE` form a pool; MAS still records a concrete assignee on each `Task`, and workers submit results using that assignee id in the JSON body while authenticating with their own API key.

## Architecture

The service is a **FastAPI** application (port 8001) with background threads for:

1. **Registration** -- On startup the agent registers itself with MAS via `POST /agents/register` and receives an `agent_id` and `api_key`.
2. **Heartbeat** -- A daemon thread sends a heartbeat to MAS every 30 seconds.
3. **RabbitMQ task worker** -- One thread pulls from `{HORUS_WORK_QUEUE_PREFIX}.{type}` for every registered type (default `horus.work.general`, etc.), one message at a time and only when one of the `AGENT_MAX_CONCURRENT_TASKS` worker threads is free. It claims the task in MAS (`POST /tasks/{task_id}/claim`), acknowledges the message, and runs the task in a worker thread, so a long answer never blocks the connection's heartbeat and a task never runs twice: a message delivered again, or a task cancelled while it waited, is refused by the claim and dropped, and the worker never starts the same task twice in one run even when MAS confirms a repeated claim (a claim whose answer was lost is sent again and confirmed). A claim MAS cannot answer puts the message back in the queue; one it will never accept (403, 422) drops it. Task messages include `assigned_agent_id` so `/tasks/task-result/` matches the orchestrator’s `Task.agent_id`. At start-up the worker asks MAS to fail the tasks an earlier run of the same worker left unfinished (`POST /tasks/abandoned-claims`); they are not run again.
4. **Inter-agent messaging** -- A second consumer handles delegation requests from other agents routed through MAS.

### RAG Pipeline

The default (`general`) agent type uses `RAGPipeline`, which chains:

- **KnowledgeRetrievalAgent** -- Fetches context from the Knowledge Store service via HTTP.
- **DecisionMakingAgent** -- Runs a Hugging Face causal instruct model (default `Qwen/Qwen3-4B-Instruct-2507`, or `app/models/Qwen3_instruct_4B/` when complete) to answer from retrieved context.

The pipeline also supports a **ReAct** reasoning mode (`ReactAgent`) that performs multi-step THOUGHT, ACTION, OBSERVATION loops for complex queries.

### Answer contract

Every RAG answer is one JSON object (`ai_agents/answer_contract.py`):

```json
{"status": "ok | not_found | failed", "answer": "...", "sources": [{"doc_id": "...", "chunk_id": "...:12", "title": "...", "page": 3}], "reason": "only when status is not ok"}
```

The retrieved passages are shown to the model with short labels (`[S1] title, page 3`); attached files are labelled first, in the order they were attached. The model only writes `status` (`ok` or `not_found`), `answer` and the labels it used. On the OpenAI-compatible backend (llama-server, vLLM) the request carries `response_format: {"type": "json_schema", ...}` whose `sources` items are an enum of the labels it was given, so the model can only cite retrieved passages; with no passage to cite the schema has no `sources`. The in-process transformers backend (and an injected model) is asked for the same JSON in the prompt and read leniently: a code fence, text around the object, trailing commas, a status such as `"found"`, or a source given by its `chunk_id` are accepted. The agent then turns each label into the passage's `doc_id`, `chunk_id`, `title` and `page`, and drops a cited label or id that was not retrieved. The answer text is NFKC-normalised (full-width digits, `。`), an answer that is a self-correction spiral fails, and an `ok` answer that cites nothing and reads like a refusal (the phrases the response cache already refuses to store, such as "does not contain this information") counts as `not_found`.

| `status` | Sent to MAS as | `reason` |
|---|---|---|
| `ok` | `completed`, with `sources` | -- |
| `not_found` | `not_found`, `sources: []` | `not_in_documents` |
| `failed` | `failed` | `invalid_output` (no readable JSON, a truncated object, an unknown status, an empty answer), `degenerate_output` (a spiral), `retrieval_error` (the knowledge store could not be searched; the model is not asked), `timeout`, `error` |

The agent answers only the request it was given and never asks the model twice; MAS decides what to try next (see "Agent answers" in the MAS README). A specialist that runs a tool sends its output as `completed` with no sources. The response cache stores only `ok` answers, with their sources, keyed on the labelled passages, so a hit cites what the first answer cited.

With `AGENT_STREAM_TOKENS=1` the model writes the JSON as a stream; `reasoning.delta` steps carry only the decoded text of the `answer` field (escapes and `\uXXXX` split across chunks are put back together), after the same 500-character check for a spiral. Each answer's steps count `index` from 0, so a client can tell a second attempt from the rest of the first.

When one answer takes longer than `REACT_TIMEOUT_SECONDS` (default 900 s on CPU, 120 s on GPU), the pipeline asks the generation to stop and the task is reported to MAS with `status: "failed"` and `reason: "timeout"`, not as an answer. On the OpenAI-compatible backend (llama-server, vLLM) the answer is then read as a stream, which is closed at the next chunk so the server cancels the generation; on the transformers backend a stopping criterion ends it at the next token. Any other pipeline error is reported as `failed` with `reason: "error"`. A message for a second attempt of a task (`attempt: 2` in its payload) is run even when this worker already ran the first one.

## Agent Types

| Type         | Class              | Description                                              |
|--------------|--------------------|----------------------------------------------------------|
| `general`    | `RAGPipeline`      | Full retrieve-then-decide pipeline with tool support     |
| `researcher` | `ResearcherAgent`  | Specialized in knowledge retrieval and research tasks    |
| `analyst`    | `AnalystAgent`     | Specialized in data analysis                             |
| `writer`     | `WriterAgent`      | Specialized in text generation using the decision model  |

Set the agent type with the `AGENT_TYPE` environment variable. Keep `HORUS_WORK_QUEUE_PREFIX` in sync with MAS `agent_work_queue_prefix` (default `horus.work`).

## Agent identities

One worker registers five identities with MAS (`agent_server/profiles.py`, `DEFAULT_PROFILES`). An identity is a name, a type (its work queue), skills and a description (what the router sees), a system prompt and at most five tools:

| Identity | Type | Tools |
|---|---|---|
| General-Assistant | `general` | `search_knowledge`, `extract_data`, `calc`, `delegate` |
| Finance-Analyst | `analyst` | `search_knowledge`, `analyze_payments`, `calc`, `delegate` |
| Compliance-Officer | `analyst` | `search_knowledge`, `extract_data`, `delegate` |
| HR-Assistant | `general` | `search_knowledge`, `calc`, `delegate` |
| Researcher | `researcher` | `search_knowledge`, `extract_data`, `delegate` |

Each system prompt only scopes the identity to its documents and style, and stays under 300 tokens (`SYSTEM_PROMPT_TOKEN_BUDGET`; 50 to 137 tokens today with the Qwen3-4B-Instruct-2507 tokenizer). How to answer, cite and say "not found" belongs to the answer contract, so a persona never repeats or contradicts it. `tests/agent/unit/test_agent_identities.py` enforces both limits: it counts with the model's `tokenizer.json` when the model is on disk (`MODEL_DIR` or `app/models/*/`) and otherwise with a conservative estimate of one token per 3 characters, which the same test checks never undercounts the tokenizer on these prompts. An identity defined another way (`AGENT_PROFILES_JSON`, `AGENT_NAME`, or adopted from MAS) has no system prompt and the tools `search_knowledge`, `extract_data`, `calc`, `delegate`; listing more than five tools, an unknown tool or one tool twice raises an error. The consumer binds the identity of each task (`current_persona`, `current_tools`), and the ReAct loop describes and runs only that identity's tools; with no identity bound (a delegated request) it offers all five.

### Prompt layout

Every prompt puts what never changes first and what changes last, so llama-server's prompt cache reuses the start of the previous prompt:

| Call (`call` label) | System message (fixed for an identity) | User message |
|---|---|---|
| `answer` (RAG answer) | identity system prompt, `---`, the answer contract rules | the labelled passages, then `Request: ...` |
| `react_step` | identity system prompt, `---`, the ReAct format with the identity's tool definitions | `User query: ...`, the reasoning so far (only ever extended), the step line |
| `grounded` (`decide` with context) | the grounded-answer rules | the retrieved content, then `Task: ...` |
| `instruction` (`decide` without context, the writer) | a one-line instruction | the request |

No system message holds a timestamp, an id or the request, so two calls for one identity send byte-identical system messages (`tests/agent/unit/test_prompt_layout.py`). The request appears once: a chain step's request carries the whole chain transcript, and repeating it before and after the passages doubled it.

### Prompt tokens

Every successful LLM call logs `LLM prompt tokens: call=... prompt_tokens=... source=... budget=...` and observes the histogram `agent_llm_prompt_tokens{call,source}`, so the average per call is `sum by (call) (rate(agent_llm_prompt_tokens_sum[5m])) / sum by (call) (rate(agent_llm_prompt_tokens_count[5m]))` (the "Agent Prompt Tokens per Call" panel on `/admin/metrics`). `source` says how the tokens were counted: `usage` is `usage.prompt_tokens` of the OpenAI-compatible response (llama-server, vLLM; a stream asks for it with `stream_options.include_usage`), `tokenizer` the length of the tokenized prompt on the in-process transformers backend, `estimate` one token per 3 characters when neither exists (an injected model, a server that sends no usage). A prompt longer than `AGENT_PROMPT_TOKEN_BUDGET` tokens (default 4096, half of the 8192-token context llama-server runs with) logs a warning and counts in `agent_llm_prompts_over_budget_total{call}`. `scripts/perf/prompt-tokens.py` checks the averages of a run against the budget.

## Tool Registry

The RAG pipeline ships with a set of built-in tools that can be invoked by setting the `operation` field on a task:

| Tool                | Aliases                                         | Description                            |
|---------------------|--------------------------------------------------|----------------------------------------|
| `calculator`        | `calc`, `calculator`                             | Evaluate mathematical expressions      |
| `file_parser`       | `parse`, `file_parse`, `file`                    | Parse and extract text from files      |
| `summarizer`        | `summary`, `summarize_text`                      | Summarize a block of text              |
| `data_extractor`    | `data_extractor`, `extract_data`, `data`, `extract` | Extract structured data from text   |
| `payment_analyzer`  | `payment_analysis`, `analyze_payments`, `payment`, `analyze` | Analyze payment/invoice data |

## Directory Structure

```
agent/
  requirements.txt              # CPU image: no torch, transformers or en_core_web_trf
  requirements-gpu.txt          # GPU image: requirements.txt plus the in-process model stack
  app/
    main.py                     # Entry point (uvicorn agent_server.server:app)
    run_agent.sh                # Local development launcher
    config/
      settings.py               # Environment-based configuration
    agent_server/
      server.py                 # FastAPI app, registration, heartbeat, RabbitMQ consumers
      profiles.py               # The five identities: system prompts and tools
    ai_agents/
      rag_pipeline.py           # RAGPipeline (retrieve + decide + tools)
      react_agent.py            # Multi-step ReAct reasoning agent
      agent_tools.py            # ReAct tool definitions and the five-tool limit
      prompt_tokens.py          # Prompt token logging, histogram and budget
      knowledge_retrieval_agent.py
      decision_making_agent.py
      knowledge_store_client.py # HTTP client for the Knowledge Store service
      tool_registry.py          # Tool protocol and in-memory registry
      calculator_tool.py
      file_parser_tool.py
      summarizer_tool.py
      data_extractor_tool.py
      payment_analyzer_tool.py
      delegation_handler.py     # Inter-agent delegation logic
    specialized/
      researcher_agent.py
      analyst_agent.py
      writer_agent.py
    core/
      logger.py                 # Structured logging with correlation IDs
      metrics.py                # Prometheus metric definitions
      tracing.py                # OpenTelemetry setup
```

Pytest suite: `tests/agent/` at the repository root (`tests/agent/pytest.ini`).

## API Endpoints

| Method | Path            | Description                                  |
|--------|-----------------|----------------------------------------------|
| `POST` | `/task`         | Receive and process a task from MAS           |
| `GET`  | `/health`       | Liveness probe used by the Compose healthcheck, with the release `version`; no auth, no model or downstream call |
| `GET`  | `/capabilities` | Return agent skills and capabilities          |
| `GET`  | `/metrics`      | Prometheus metrics                            |

In practice, most tasks arrive through the RabbitMQ consumer rather than the HTTP endpoint.

## Environment Variables

| Variable                  | Description                                | Default                   |
|---------------------------|--------------------------------------------|---------------------------|
| `ORCHESTRATOR_URL`        | MAS base URL                               | `http://localhost:8000`   |
| `ORCHESTRATOR_TOKEN`      | Direct bearer token for MAS (optional)     | --                        |
| `ORCHESTRATOR_USERNAME`   | MAS login username (used if no token)      | --                        |
| `ORCHESTRATOR_PASSWORD`   | MAS login password                         | --                        |
| `AGENT_TYPE`              | Agent specialization                       | `general`                 |
| `AGENT_DESCRIPTION`       | Human-readable agent description           | `Autonomous MAS agent`    |
| `MODEL_NAME`              | Hugging Face model id (or local mirror) for decision agent | `Qwen/Qwen3-4B-Instruct-2507` |
| `MODEL_DEVICE`            | PyTorch device (`auto`, `cpu`, `cuda`)     | `auto`                    |
| `AGENT_LAZY_DECISION_MODEL` | `1`/`true` = load Qwen on first `decide()`; `0` = load at process start (Compose default `0`) | `0` |
| `KNOWLEDGE_STORE_URL`     | Knowledge Store service URL                | `http://localhost:8080`   |
| `KNOWLEDGE_STORE_TIMEOUT` | HTTP timeout for knowledge store requests  | `10.0`                    |
| `KNOWLEDGE_STORE_MAX_RETRIES` | Max retries for knowledge store calls  | `3`                       |
| `RABBITMQ_HOST`           | RabbitMQ host                              | `localhost`               |
| `RABBITMQ_USER`           | RabbitMQ username                          | `guest`                   |
| `RABBITMQ_PASSWORD`       | RabbitMQ password                          | `guest`                   |
| `WORK_QUEUE_MAX_LENGTH`   | `x-max-length` used when the agent creates a work queue that does not exist yet (MAS reads the same variable) | `10` |
| `AGENT_MAX_CONCURRENT_TASKS` | Tasks this process runs at a time; the worker takes no message while they are all busy | `1` |
| `AGENT_WORKER_ID`         | Stable worker name for task claims. It must differ between agent containers | the host name |
| `REACT_TIMEOUT_SECONDS`   | Limit on one answer; past it the task fails with `reason: "timeout"` | `900` on CPU, `120` on GPU |
| `AGENT_PROMPT_TOKEN_BUDGET` | Prompt tokens one LLM call may use before it logs a warning and counts in `agent_llm_prompts_over_budget_total` | `4096` |
| `DELEGATION_TIMEOUT`      | Timeout for delegation requests (seconds)  | `30.0`                    |
| `MAX_DELEGATION_DEPTH`    | Maximum inter-agent delegation chain depth | `5`                       |

### CPU and GPU images

The Dockerfile installs `requirements.txt` when the build argument `TORCH_INDEX_URL` is the CPU wheel index (`https://download.pytorch.org/whl/cpu`, set by `docker-compose.cpu.yml`): the CPU image has no torch, transformers, accelerate, bitsandbytes or `en_core_web_trf`, and the data extractor uses `en_core_web_sm`. On the CPU profiles the agent generates through llama-server (`LLM_BACKEND=vllm`), so it starts and answers without them; with `LLM_BACKEND=transformers` a CPU image stops at start with a message that names the missing packages and points at `LLM_BACKEND=vllm`. Any other index (the default `https://pypi.org/simple`) builds the GPU image from `requirements-gpu.txt`, which installs the pinned torch from that index first and keeps the in-process decision model as a fallback.

## Local Development

### Prerequisites

- Python 3.13+
- Running MAS orchestrator, RabbitMQ, and Knowledge Store instances

### Setup

```bash
cd src/services/agent
python -m venv venv
source venv/bin/activate
pip install -r requirements-gpu.txt --extra-index-url https://download.pytorch.org/whl/cpu
```

### Run

Use the helper script (sets env vars and starts Uvicorn on port 8001):

```bash
cd app
bash run_agent.sh
```

Or manually:

```bash
cd app
uvicorn agent_server.server:app --host 0.0.0.0 --port 8001
```

## Running Tests

```bash
# From repository root
bash scripts/test/run-agent.sh
```

Or directly:

```bash
pytest -c tests/agent/pytest.ini tests/agent -v
```

Tests run in offline mode (`TRANSFORMERS_OFFLINE=1`, `HF_HUB_OFFLINE=1`) to avoid network calls during CI.
