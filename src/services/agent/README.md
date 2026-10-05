# Agent Service

> For the development team. Paths such as `tests/` and `scripts/dev/` are
> relative to the git checkout and are not part of the beta archive.

The Agent service is an autonomous AI worker that registers with the MAS orchestrator, consumes tasks from a **shared RabbitMQ work queue per specialization** (e.g. `horus.work.general`), processes them through a RAG (Retrieval-Augmented Generation) pipeline, and returns results back to MAS. Multiple instances of the same `AGENT_TYPE` form a pool; MAS still records a concrete assignee on each `Task`, and workers submit results using that assignee id in the JSON body while authenticating with their own API key.

## Architecture

The service is a **FastAPI** application (port 8001) with background threads for:

1. **Registration** -- On startup the agent registers itself with MAS via `POST /agents/register` and receives an `agent_id` and `api_key`.
2. **Heartbeat** -- A daemon thread sends a heartbeat to MAS every 30 seconds.
3. **RabbitMQ consumer** -- A blocking consumer listens on `{HORUS_WORK_QUEUE_PREFIX}.{AGENT_TYPE}` (default `horus.work.general`, etc.). Task messages include `assigned_agent_id` so `/tasks/task-result/` matches the orchestrator’s `Task.agent_id`.
4. **Inter-agent messaging** -- A second consumer handles delegation requests from other agents routed through MAS.

### RAG Pipeline

The default (`general`) agent type uses `RAGPipeline`, which chains:

- **KnowledgeRetrievalAgent** -- Fetches context from the Knowledge Store service via HTTP.
- **DecisionMakingAgent** -- Runs a Hugging Face causal instruct model (default `Qwen/Qwen3-4B-Instruct-2507`, or `app/models/Qwen3_instruct_4B/` when complete) to answer from retrieved context.

The pipeline also supports a **ReAct** reasoning mode (`ReactAgent`) that performs multi-step THOUGHT, ACTION, OBSERVATION loops for complex queries.

## Agent Types

| Type         | Class              | Description                                              |
|--------------|--------------------|----------------------------------------------------------|
| `general`    | `RAGPipeline`      | Full retrieve-then-decide pipeline with tool support     |
| `researcher` | `ResearcherAgent`  | Specialized in knowledge retrieval and research tasks    |
| `analyst`    | `AnalystAgent`     | Specialized in data analysis                             |
| `writer`     | `WriterAgent`      | Specialized in text generation using the decision model  |

Set the agent type with the `AGENT_TYPE` environment variable. Keep `HORUS_WORK_QUEUE_PREFIX` in sync with MAS `agent_work_queue_prefix` (default `horus.work`).

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
  requirements.txt
  app/
    main.py                     # Entry point (uvicorn agent_server.server:app)
    run_agent.sh                # Local development launcher
    config/
      settings.py               # Environment-based configuration
    agent_server/
      server.py                 # FastAPI app, registration, heartbeat, RabbitMQ consumers
    ai_agents/
      rag_pipeline.py           # RAGPipeline (retrieve + decide + tools)
      react_agent.py            # Multi-step ReAct reasoning agent
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
| `GET`  | `/health`       | Liveness probe used by the Compose healthcheck; no auth, no model or downstream call |
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
| `DELEGATION_TIMEOUT`      | Timeout for delegation requests (seconds)  | `30.0`                    |
| `MAX_DELEGATION_DEPTH`    | Maximum inter-agent delegation chain depth | `5`                       |

## Local Development

### Prerequisites

- Python 3.13+
- Running MAS orchestrator, RabbitMQ, and Knowledge Store instances

### Setup

```bash
cd src/services/agent
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
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
