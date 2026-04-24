"""Agent server: registers with MAS, runs heartbeat + queue consumers, serves HTTP.

Handlers dispatch incoming tasks to the active agent (general RAG
pipeline or one of the specialized agents) and POST results back to the
orchestrator. See ``docs/architecture/agent_service.md`` for the full
lifecycle.

The implementation is split across this package:

- :mod:`agent_server.server` — module-level state, auth helpers,
  registration + heartbeat, ``send_result``, lifespan + FastAPI app + routes.
- :mod:`agent_server.consumers` — RabbitMQ consumer loops (task queue,
  inter-agent comms).
- :mod:`agent_server.delegation_bridge` — delegation request handling and
  result posting.

The consumer/delegation helpers are re-imported here so existing callers and
tests using ``from agent_server.server import _consume_messages`` (etc.)
continue to work.
"""

import asyncio
import threading
import time
import uuid
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, Request
from prometheus_client import make_asgi_app

from agent_server.consumers import _consume_agent_messages, _consume_messages
from agent_server.delegation_bridge import (_format_delegation_context,
                                            _process_delegation_message,
                                            _send_delegation_result)
from agent_server.middleware import CorrelationIDMiddleware
from agent_server.models import Result, Task
from ai_agents.decision_making_agent import DecisionMakingAgent
from ai_agents.knowledge_retrieval_agent import KnowledgeRetrievalAgent
from ai_agents.knowledge_store_client import KnowledgeStoreClient
from ai_agents.rag_pipeline import RAGPipeline
from config.settings import (AGENT_DESCRIPTION, AGENT_TYPE, DELEGATION_TIMEOUT,
                             MAX_DELEGATION_DEPTH, MODEL_DEVICE, MODEL_NAME,
                             ORCHESTRATOR_PASSWORD, ORCHESTRATOR_TOKEN,
                             ORCHESTRATOR_URL, ORCHESTRATOR_USERNAME)
from core.logger import get_correlation_id, get_logger, set_correlation_id
from core.metrics import (agent_errors_total, agent_heartbeat_total,
                          agent_registered, task_processing_duration,
                          task_processing_total)
from specialized.analyst_agent import AnalystAgent
from specialized.researcher_agent import ResearcherAgent
from specialized.writer_agent import WriterAgent

logger = get_logger("agent_server")


# Agent details
# Will be set after successful registration with MAS
AGENT_ID = None
AGENT_API_KEY = None  # Plain API key returned at registration, used for agent auth
AGENT_NAME = "HorusAgent"
SKILLS = ["knowledge_retrieval", "decision_making", "rag_pipeline"]
AGENT_CAPABILITIES = {
    "knowledge_retrieval": "Search and retrieve information from knowledge stores",
    "decision_making": "Analyze data and make informed decisions",
    "rag_pipeline": "Full retrieval-augmented generation pipeline",
    "delegation": "Can delegate sub-tasks to other agents",
}

# Initialize the RAG pipeline components
knowledge_store_client = KnowledgeStoreClient()
retrieval_agent = KnowledgeRetrievalAgent(store_interface=knowledge_store_client)
decision_agent = DecisionMakingAgent(model_name=MODEL_NAME, device=MODEL_DEVICE)
# None → RAGPipeline builds the default registry (parse, calc, extract_data, etc.).
# An empty ToolRegistry() breaks ReAct tools that call tool_registry.run("parse", ...).

if AGENT_TYPE == "researcher":
    active_agent = ResearcherAgent(retrieval_agent)
elif AGENT_TYPE == "analyst":
    active_agent = AnalystAgent()
elif AGENT_TYPE == "writer":
    active_agent = WriterAgent(decision_agent)
else:
    active_agent = RAGPipeline(
        retrieval_agent,
        decision_agent,
        tool_registry=None,
    )

rag_pipeline: RAGPipeline | None = (
    active_agent if isinstance(active_agent, RAGPipeline) else None
)

_AUTH_TOKEN = None  # cached bearer token for orchestrator requests


def _invalidate_cached_mas_token():
    """Drop cached JWT so the next call re-logins (password grant) or re-reads env token."""
    global _AUTH_TOKEN
    _AUTH_TOKEN = None


def _get_orchestrator_token():
    """Return a bearer token to talk to MAS (from env or by logging in)."""
    global _AUTH_TOKEN
    if _AUTH_TOKEN:
        return _AUTH_TOKEN

    if ORCHESTRATOR_TOKEN:
        _AUTH_TOKEN = ORCHESTRATOR_TOKEN
        return _AUTH_TOKEN

    if ORCHESTRATOR_USERNAME and ORCHESTRATOR_PASSWORD:
        try:
            response = requests.post(
                f"{ORCHESTRATOR_URL}/auth/token",
                data={"username": ORCHESTRATOR_USERNAME, "password": ORCHESTRATOR_PASSWORD},
                timeout=5,
            )
            if response.status_code == 200:
                _AUTH_TOKEN = response.json().get("access_token")
                return _AUTH_TOKEN
            logger.warning(f"Failed to obtain MAS auth token: {response.status_code} - {response.text}")
        except Exception as exc:  # network/login errors shouldn't crash the agent
            logger.warning(f"Error fetching MAS auth token: {exc}")
    return None


def _build_headers(include_api_key: bool = False) -> dict:
    """Return MAS request headers; optionally adds ``X-API-Key``/``Agent-ID``."""
    headers: dict = {}
    token = _get_orchestrator_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if include_api_key and AGENT_ID and AGENT_API_KEY:
        headers["X-API-Key"] = f"{AGENT_ID}:{AGENT_API_KEY}"
        headers["Agent-ID"] = AGENT_ID
    return headers


def register_agent():
    """Register the agent with MAS. Keep retrying until successful.

    Uses a simple backoff to handle MAS not being ready at container start.
    """
    global AGENT_ID, AGENT_API_KEY
    url = f"{ORCHESTRATOR_URL}/agents/register"
    base_name = AGENT_NAME
    name_variant = base_name
    backoff_seconds = 1
    while not AGENT_ID:
        try:
            payload = {
                "name": name_variant,
                "skills": SKILLS,
                "description": AGENT_DESCRIPTION,
                "type": AGENT_TYPE
            }
            response = requests.post(
                url, json=payload, headers=_build_headers(), timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                AGENT_ID = data.get("agent_id")
                AGENT_API_KEY = data.get("api_key")
                logger.info(f"Agent registered successfully with id: {AGENT_ID}")
                agent_registered.set(1)
                if not AGENT_API_KEY:
                    logger.warning("MAS did not return api_key; agent auth will fail.")
                break
            if response.status_code == 409:
                # A stale entry with this name is sitting in the DB from a previous
                # container run. Try to find it, delete it, then re-register with
                # the original name so ghost agents never accumulate.
                logger.warning(
                    f"Agent name '{name_variant}' already registered. "
                    "Attempting to delete stale entry and re-register..."
                )
                try:
                    list_resp = requests.get(
                        f"{ORCHESTRATOR_URL}/agents/details/",
                        headers=_build_headers(),
                        timeout=5,
                    )
                    if list_resp.status_code == 200:
                        agents = list_resp.json()
                        stale = next(
                            (
                                a for a in agents
                                if a.get("name") == name_variant
                                and a.get("status") == "inactive"
                            ),
                            None,
                        )
                        if stale:
                            del_resp = requests.delete(
                                f"{ORCHESTRATOR_URL}/agents/unregister/{stale['id']}",
                                headers=_build_headers(),
                                timeout=5,
                            )
                            if del_resp.status_code == 200:
                                logger.info(
                                    f"Deleted stale agent '{name_variant}' "
                                    f"({stale['id']}). Retrying registration."
                                )
                                continue  # retry immediately with same name
                            else:
                                logger.warning(
                                    f"Could not delete stale agent {stale['id']}: "
                                    f"{del_resp.status_code}"
                                )
                        else:
                            logger.warning(
                                f"No inactive agent named '{name_variant}' found "
                                "to clean up (may be genuinely active). "
                                "Falling back to unique name."
                            )
                except Exception as cleanup_err:
                    logger.warning(f"Stale agent cleanup failed: {cleanup_err}")
                # Fallback: unique suffix so we at least register successfully
                name_variant = f"{base_name}-{uuid.uuid4().hex[:6]}"
                logger.warning(f"Falling back to name '{name_variant}'")
            else:
                logger.error(f"Agent registration failed: {response.status_code} - {response.text}")
                agent_errors_total.labels(error_type="registration").inc()
        except Exception as e:
            logger.error(f"Error registering agent (will retry): {e}", exc_info=True)
            agent_errors_total.labels(error_type="registration").inc()
        time.sleep(backoff_seconds)
        backoff_seconds = min(backoff_seconds * 2, 30)


def send_heartbeat():
    """POST ``/agents/heartbeat/{id}`` and refresh the cached token on 401."""
    if not AGENT_ID:
        return
    url = f"{ORCHESTRATOR_URL}/agents/heartbeat/{AGENT_ID}"
    try:
        response = requests.post(url, headers=_build_headers(include_api_key=True))
        # MAS JWTs expire (~20m). Cached token never refreshed → endless 401 without this.
        if response.status_code == 401 and not ORCHESTRATOR_TOKEN:
            _invalidate_cached_mas_token()
            response = requests.post(url, headers=_build_headers(include_api_key=True))
        if response.status_code != 200:
            logger.warning(f"Heartbeat failed: {response.status_code} - {response.text}")
            agent_heartbeat_total.labels(status="error").inc()
            agent_errors_total.labels(error_type="heartbeat").inc()
        else:
            logger.debug(f"Heartbeat sent successfully: {response.json()}")
            agent_heartbeat_total.labels(status="success").inc()
    except Exception as e:
        logger.error(f"Error sending heartbeat: {e}", exc_info=True)
        agent_heartbeat_total.labels(status="error").inc()
        agent_errors_total.labels(error_type="heartbeat").inc()


def heartbeat_task():
    """Background loop: send a heartbeat every 30 seconds."""
    while True:
        send_heartbeat()
        time.sleep(30)  # Adjust the interval as needed.


def send_result(result: str, conversation_id: str, task_id: str):
    """POST the task result to MAS ``/tasks/task-result/``."""
    url = f"{ORCHESTRATOR_URL}/tasks/task-result/"
    payload = {
        "agent_id": AGENT_ID,
        "result": result,
        "conversation_id": str(conversation_id),
        "task_id": task_id,
    }
    try:
        response = requests.post(
            url, json=payload, headers=_build_headers(include_api_key=True)
        )
        if response.status_code != 200:
            logger.warning(f"Failed to send result: {response.status_code} - {response.text}")
        else:
            logger.debug(f"Result sent successfully: {response.json()}")
    except Exception as e:
        logger.error(f"Error sending result: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown (replaces deprecated on_event)."""
    logger.info("Agent service starting up...")
    register_agent()
    heartbeat_thread = threading.Thread(target=heartbeat_task, daemon=True)
    heartbeat_thread.start()
    logger.info("Heartbeat thread started")
    consumer_thread = threading.Thread(target=_consume_messages, daemon=True)
    consumer_thread.start()
    agent_msg_thread = threading.Thread(target=_consume_agent_messages, daemon=True)
    agent_msg_thread.start()
    logger.info("Agent-to-agent message consumer started")
    logger.info("Agent service startup complete")
    yield


app = FastAPI(title="Horus Agent Service", version="1.0.0", lifespan=lifespan)

# OpenTelemetry auto-instrumentation is handled by opentelemetry-instrument wrapper
# See Dockerfile CMD for details

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

app.add_middleware(CorrelationIDMiddleware)


@app.get(
    "/capabilities",
    summary="Get agent capabilities",
    description="Returns the capabilities and skills this agent supports, including delegation.",
    tags=["Agent Info"],
)
def get_capabilities():
    return {
        "agent_id": AGENT_ID,
        "agent_name": AGENT_NAME,
        "skills": SKILLS,
        "capabilities": AGENT_CAPABILITIES,
        "supports_delegation": True,
        "max_delegation_depth": MAX_DELEGATION_DEPTH,
    }


@app.post(
    "/task",
    response_model=Result,
    summary="Process a generic task",
    description="Receives a task from the MAS Orchestrator, processes it via the RAG pipeline, and returns the result.",
    tags=["Agent Tasks"],
    responses={
        200: {"description": "Task processed successfully"},
        500: {"description": "Internal server error during task processing"}
    }
)
async def receive_task(task: Task, request: Request):
    """Process a task via HTTP, POST the result back to MAS, and return it."""
    if not task.task_id:
        task.task_id = "task_" + uuid.uuid4().hex

    # Extract correlation ID from request headers
    corr_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
    if corr_id:
        set_correlation_id(corr_id)

    logger.info(
        f"Received task via HTTP: task_id={task.task_id}, conversation_id={task.conversation_id}, "
        f"correlation_id={get_correlation_id()}"
    )

    # Process the task using the RAG pipeline (async) with metrics
    import time as time_module
    start_time = time_module.time()
    try:
        task_dict = task.model_dump()
        if AGENT_TYPE == "general":
            result_pipeline = await active_agent.process_task(task_dict)
            final_result_text = result_pipeline["response"]
        elif AGENT_TYPE in ["researcher", "analyst", "writer"]:
            final_result_text = await active_agent.process_request(
                task_type=task_dict.get("operation"),
                data=task_dict.get("query"),
                extra_parameters=task_dict,
            )
        else:
            raise ValueError(f"Unsupported AGENT_TYPE: {AGENT_TYPE}")

        processing_duration = time_module.time() - start_time

        task_processing_duration.observe(processing_duration)
        task_processing_total.labels(status="success").inc()

        logger.info(
            f"Task processed successfully via HTTP: task_id={task.task_id}, "
            f"duration={processing_duration:.2f}s, correlation_id={get_correlation_id()}"
        )

        # Send the result back to the orchestrator.
        send_result(final_result_text, task.conversation_id, task.task_id)

        # Return the result in the format expected by the response_model
        return Result(
            agent_id=AGENT_ID if AGENT_ID else "unknown",
            result=final_result_text
        )
    except Exception as e:
        processing_duration = time_module.time() - start_time
        task_processing_duration.observe(processing_duration)
        task_processing_total.labels(status="error").inc()
        agent_errors_total.labels(error_type="task_processing").inc()
        logger.error(
            f"Task processing failed via HTTP: task_id={task.task_id}, error={str(e)}, "
            f"correlation_id={get_correlation_id()}",
            exc_info=True
        )
        raise
