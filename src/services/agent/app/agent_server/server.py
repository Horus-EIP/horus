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
import json
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager

import pika
import requests
from fastapi import FastAPI, Request
from prometheus_client import make_asgi_app
from pydantic import BaseModel

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
                             ORCHESTRATOR_URL, ORCHESTRATOR_USERNAME,
                             RABBITMQ_PORT)
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

# Shared RabbitMQ queue for this specialization (aligned with MAS ``agent_work_queue_prefix``).
_wq_prefix = os.getenv("HORUS_WORK_QUEUE_PREFIX", "horus.work").strip().rstrip(".")
_at = str(AGENT_TYPE).lower()
if "." in _at:
    _at = _at.split(".")[-1]
WORK_QUEUE_NAME = f"{_wq_prefix}.{_at}"


class Task(BaseModel):
    """
    Model for tasks received from the MAS Orchestrator.
    """
    task_id: str = None  # Auto-generated if not provided.
    query: str | None = None
    conversation_id: str
    assigned_agent_id: str | None = None  # Task assignee in DB; result payload must use this when pooled.
    operation: str | None = None
    expression: str | None = None
    file_url: str | None = None
    file_content: str | None = None  # base64/utf-8 text; small files only
    file_type: str | None = None
    filename: str | None = None
    text: str | None = None
    max_sentences: int | None = None

class Result(BaseModel):
    """
    Model for sending task results back to the MAS Orchestrator.
    """
    agent_id: str
    result: str


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


def _consume_messages():
    """
    Connect to RabbitMQ and consume tasks sent to this agent's queue. Each message
    is expected to be a JSON string with at least 'demand' and 'conversation_id'.
    It is transformed into the internal task format and processed by the RAG pipeline.
    Uses asyncio to handle async pipeline processing.
    """
    import asyncio

    if not AGENT_ID:
        logger.error("Cannot start consumer: AGENT_ID not set")
        return

    try:
        rabbit_host = os.getenv("RABBITMQ_HOST", "localhost")
        rabbit_user = os.getenv("RABBITMQ_USER", "guest")
        rabbit_pass = os.getenv("RABBITMQ_PASSWORD", "guest")
        credentials = pika.PlainCredentials(rabbit_user, rabbit_pass)
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=rabbit_host,
                port=RABBITMQ_PORT,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300,
            )
        )
        channel = connection.channel()
        # Declare a durable queue to avoid RabbitMQ 'transient_nonexcl_queues' deprecation
        channel.queue_declare(
            queue=WORK_QUEUE_NAME,
            passive=False,
            durable=True,
            exclusive=False,
            auto_delete=False,
            arguments={"x-max-priority": 10},
        )

        def _on_message(ch, method, properties, body):
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                # Fallback: treat body as plain text demand
                payload = {"demand": body.decode("utf-8")}

            if payload.get("type") == "cancel":
                logger.info(
                    "Received cancel control message on work queue (task_id=%s)",
                    payload.get("task_id"),
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            demand = payload.get("demand", "")
            conversation_id = payload.get("conversation_id", "")
            task_id = payload.get("task_id") or ("task_" + uuid.uuid4().hex)
            if not (demand or payload.get("query")):
                logger.warning(
                    "RabbitMQ task message has no demand/query (task_id=%s). "
                    "MAS must publish the task text in the message body.",
                    task_id,
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # Extract correlation ID from message properties if available
            corr_id = properties.headers.get("X-Request-ID") if properties.headers else None
            if corr_id:
                set_correlation_id(corr_id)

            logger.info(
                f"Received task: task_id={task_id}, conversation_id={conversation_id}, "
                f"demand_length={len(demand)}, correlation_id={get_correlation_id()}"
            )

            # Adapt to pipeline expected schema; include optional utility fields
            task_dict = {
                "task_id": task_id,
                "query": demand or payload.get("query", ""),
                "operation": payload.get("operation"),
                "expression": payload.get("expression"),
                "file_url": payload.get("file_url"),
                "file_content": payload.get("file_content"),
                "file_type": payload.get("file_type"),
                "filename": payload.get("filename"),
                "text": payload.get("text"),
                "max_sentences": payload.get("max_sentences"),
                "format": payload.get("format"),
                "extraction_type": payload.get("extraction_type"),
                "analysis_type": payload.get("analysis_type"),
            }
            
            # Process task asynchronously (pika is sync, but pipeline is async)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Run async pipeline processing with metrics
            import time as time_module
            start_time = time_module.time()
            try:
                if AGENT_TYPE == "general":
                    result_pipeline = loop.run_until_complete(active_agent.process_task(task_dict))
                    final_result_text = result_pipeline["response"]
                elif AGENT_TYPE in ["researcher", "analyst", "writer"]:
                    final_result_text = loop.run_until_complete(
                        active_agent.process_request(
                            task_type=task_dict.get("operation"),
                            data=task_dict.get("query"),
                            extra_parameters=task_dict,
                        )
                    )
                else:
                    raise ValueError(f"Unsupported AGENT_TYPE: {AGENT_TYPE}")

                processing_duration = time_module.time() - start_time

                task_processing_duration.observe(processing_duration)
                task_processing_total.labels(status="success").inc()

                logger.info(
                    f"Task processed successfully: task_id={task_id}, "
                    f"duration={processing_duration:.2f}s, correlation_id={get_correlation_id()}"
                )

                # Send result back to MAS (requires conversation_id and task_id)
                if conversation_id and task_id:
                    send_result(
                        final_result_text,
                        conversation_id,
                        task_id,
                        assigned_agent_id=payload.get("assigned_agent_id"),
                    )
            except Exception as e:
                processing_duration = time_module.time() - start_time
                task_processing_duration.observe(processing_duration)
                task_processing_total.labels(status="error").inc()
                agent_errors_total.labels(error_type="task_processing").inc()
                logger.error(
                    f"Task processing failed: task_id={task_id}, error={str(e)}, "
                    f"correlation_id={get_correlation_id()}",
                    exc_info=True
                )
                err_msg = f"Agent processing failed: {e}"
                if conversation_id and task_id:
                    try:
                        send_result(
                            err_msg,
                            str(conversation_id),
                            str(task_id),
                            assigned_agent_id=payload.get("assigned_agent_id"),
                        )
                    except Exception as send_exc:
                        logger.error(f"Failed to send error result to MAS: {send_exc}")
            else:
                # Acknowledge only after successful processing
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # Failed path: ack so the message is not redelivered forever
            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=WORK_QUEUE_NAME, on_message_callback=_on_message)
        logger.info(
            f"RabbitMQ consumer started, listening on pooled work queue '{WORK_QUEUE_NAME}' "
            f"(instance_id={AGENT_ID})"
        )
        channel.start_consuming()
    except Exception as e:
        logger.error(f"Error in RabbitMQ consumer: {e}", exc_info=True)
        agent_errors_total.labels(error_type="rabbitmq").inc()

def _consume_agent_messages():
    """
    Consume inter-agent messages from the agent's communication queue.
    Handles delegation requests from other agents routed through MAS.
    """
    import asyncio

    if not AGENT_ID:
        logger.error("Cannot start agent message consumer: AGENT_ID not set")
        return

    try:
        rabbit_host = os.getenv("RABBITMQ_HOST", "localhost")
        rabbit_user = os.getenv("RABBITMQ_USER", "guest")
        rabbit_pass = os.getenv("RABBITMQ_PASSWORD", "guest")
        credentials = pika.PlainCredentials(rabbit_user, rabbit_pass)
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=rabbit_host,
                port=RABBITMQ_PORT,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300,
            )
        )
        channel = connection.channel()
        queue_name = f"agent_comm_{AGENT_ID}"
        channel.queue_declare(
            queue=queue_name,
            passive=False,
            durable=True,
            exclusive=False,
            auto_delete=False,
            arguments={"x-max-priority": 10},
        )

        def _on_agent_message(ch, method, properties, body):
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                logger.error("Failed to decode agent message")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            message_type = payload.get("message_type", "")
            message_id = payload.get("id", "")
            sender = payload.get("sender_agent_id", "")

            logger.info(
                f"Received agent message: id={message_id}, type={message_type}, "
                f"from={sender}"
            )

            if message_type == "delegation":
                _process_delegation_message(payload)
            else:
                logger.warning(f"Unknown agent message type: {message_type}")

            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=queue_name, on_message_callback=_on_agent_message)
        logger.info(f"Agent message consumer started on queue '{queue_name}'")
        channel.start_consuming()
    except Exception as e:
        logger.error(f"Error in agent message consumer: {e}", exc_info=True)


def _format_delegation_context(context_entries: list) -> str:
    """Build a readable summary of accumulated delegation context."""
    if not context_entries:
        return ""
    parts = []
    for i, entry in enumerate(context_entries, 1):
        agent_id = entry.get("agent_id", "unknown")
        req = entry.get("request", "")
        data = entry.get("data", {})
        section = f"[Agent {i} — {agent_id}]\n  Request: {req}"
        if data:
            section += f"\n  Data: {json.dumps(data)}"
        parts.append(section)
    return "Prior delegation context:\n" + "\n".join(parts)


def _process_delegation_message(payload: dict):
    """Process a delegation request received from another agent via MAS."""
    import asyncio

    content = payload.get("content", {})
    request_text = content.get("request", "")
    data = content.get("data", {})
    message_id = payload.get("id", "")
    sender = payload.get("sender_agent_id", "")
    delegation_chain = payload.get("delegation_chain", [])
    delegation_context = payload.get("delegation_context", [])

    logger.info(
        f"Processing delegation from {sender}: {request_text[:100]}... "
        f"(chain depth={len(delegation_chain)}, context entries={len(delegation_context)})"
    )

    query = request_text
    if data:
        query = f"{request_text}\n\nData: {json.dumps(data)}"

    context_summary = _format_delegation_context(delegation_context)
    if context_summary:
        query = f"{context_summary}\n\n---\nCurrent request:\n{query}"

    task_dict = {
        "task_id": f"delegation_{message_id}",
        "query": query,
        "mode": "react",
    }

    if not rag_pipeline:
        _send_delegation_result(
            message_id,
            "Delegation is only supported when AGENT_TYPE=general (RAG pipeline).",
        )
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if hasattr(rag_pipeline, "react_agent") and rag_pipeline.react_agent:
        rag_pipeline.react_agent._incoming_delegation_context = delegation_context

    try:
        result_dict = loop.run_until_complete(rag_pipeline.process_task(task_dict))
        result_text = result_dict.get("response", "")
        logger.info(f"Delegation {message_id} completed successfully")
    except Exception as e:
        result_text = f"Delegation processing failed: {e}"
        logger.error(f"Delegation {message_id} failed: {e}", exc_info=True)
    finally:
        if hasattr(rag_pipeline, "react_agent") and rag_pipeline.react_agent:
            rag_pipeline.react_agent._incoming_delegation_context = None

    _send_delegation_result(message_id, result_text)


def _send_delegation_result(delegation_id: str, result: str):
    """Send delegation result back to MAS orchestrator."""
    url = f"{ORCHESTRATOR_URL}/rabbitmq/delegation-result"
    payload = {
        "delegation_id": delegation_id,
        "result": result,
        "agent_id": AGENT_ID,
    }
    try:
        response = requests.post(
            url, json=payload, headers=_build_headers(include_api_key=True), timeout=10
        )
        if response.status_code != 200:
            logger.warning(
                f"Failed to send delegation result: {response.status_code} - {response.text}"
            )
        else:
            logger.debug(f"Delegation result sent: {delegation_id}")
    except Exception as e:
        logger.error(f"Error sending delegation result: {e}", exc_info=True)


def send_result(
    result: str,
    conversation_id: str,
    task_id: str,
    assigned_agent_id: str | None = None,
):
    """
    Sends the processed task result to the MAS Orchestrator using the /tasks/task-result/ endpoint.

    Args:
        result: The result string generated by the RAG pipeline.
        conversation_id: The conversation ID for this task.
        task_id: The unique task ID.
        assigned_agent_id: Task assignee UUID (orchestrator); required for pooled workers so MAS
            matches Task.agent_id while headers authenticate the executing instance.
    """
    url = f"{ORCHESTRATOR_URL}/tasks/task-result/"
    body_agent_id = assigned_agent_id or AGENT_ID
    payload = {
        "agent_id": body_agent_id,
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
        "work_queue": WORK_QUEUE_NAME,
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
        send_result(
            final_result_text,
            task.conversation_id,
            task.task_id,
            assigned_agent_id=task_dict.get("assigned_agent_id"),
        )

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
