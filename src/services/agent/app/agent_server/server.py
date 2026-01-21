"""
server.py
---------
This module implements the agent server that integrates with the MAS Orchestrator API.
The agent registers itself with the orchestrator, periodically sends heartbeat signals,
and exposes an endpoint to receive tasks.
When a task is received, it processes the task using the RAG pipeline and sends the result
back to the MAS via the /agents/result endpoint.
"""

import uuid
import threading
import time
import json
import os
import requests
import pika
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import make_asgi_app
from pydantic import BaseModel
from contextlib import contextmanager
from ai_agents.knowledge_retrieval_agent import KnowledgeRetrievalAgent
from ai_agents.decision_making_agent import DecisionMakingAgent
from ai_agents.rag_pipeline import RAGPipeline
from ai_agents.tool_registry import ToolRegistry
from ai_agents.knowledge_store_client import KnowledgeStoreClient
from config.settings import (
    ORCHESTRATOR_URL,
    ORCHESTRATOR_USERNAME,
    ORCHESTRATOR_PASSWORD,
    ORCHESTRATOR_TOKEN,
    AGENT_DESCRIPTION,
    MODEL_NAME,
    MODEL_DEVICE,
)
from core.logger import get_logger, set_correlation_id, get_correlation_id
from core.metrics import (
    task_processing_total,
    task_processing_duration,
    rag_query_total,
    rag_query_duration,
    model_inference_total,
    model_inference_duration,
    knowledge_store_requests_total,
    knowledge_store_request_duration,
    agent_registered,
    agent_heartbeat_total,
    agent_errors_total,
)

logger = get_logger("agent_server")

app = FastAPI(title="Horus Agent Service", version="1.0.0")

# OpenTelemetry auto-instrumentation is handled by opentelemetry-instrument wrapper
# See Dockerfile CMD for details

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Middleware to extract and set correlation ID from headers."""
    
    async def dispatch(self, request: Request, call_next):
        # Extract correlation ID from headers
        corr_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
        if corr_id:
            set_correlation_id(corr_id)
        else:
            # Generate new correlation ID if not present
            new_corr_id = str(uuid.uuid4())
            set_correlation_id(new_corr_id)
        
        response = await call_next(request)
        
        # Add correlation ID to response headers
        if corr_id := get_correlation_id():
            response.headers["X-Request-ID"] = corr_id
        
        return response

app.add_middleware(CorrelationIDMiddleware)

# Agent details
# Will be set after successful registration with MAS
AGENT_ID = None
AGENT_API_KEY = None  # Plain API key returned at registration, used for agent auth
AGENT_NAME = "HorusAgent"
SKILLS = ["knowledge_retrieval", "decision_making", "rag_pipeline"]

# Initialize the RAG pipeline components
knowledge_store_client = KnowledgeStoreClient()
retrieval_agent = KnowledgeRetrievalAgent(store_interface=knowledge_store_client)
decision_agent = DecisionMakingAgent(model_name=MODEL_NAME, device=MODEL_DEVICE)
tool_registry = ToolRegistry()  # default tools will be added by pipeline if empty
rag_pipeline = RAGPipeline(
    retrieval_agent,
    decision_agent,
    tool_registry=tool_registry,
)

class Task(BaseModel):
    """
    Model for tasks received from the MAS Orchestrator.
    """
    task_id: str = None  # Auto-generated if not provided.
    query: str | None = None
    conversation_id: str
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
    """
    Construct headers for MAS requests.

    - Always tries to attach Authorization if available.
    - Optionally attaches X-API-Key (agent_id:api_key) for agent-auth endpoints.
    """
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
                name_variant = f"{base_name}-{uuid.uuid4().hex[:6]}"
                logger.warning(f"Agent name conflict. Retrying with name '{name_variant}'")
            else:
                logger.error(f"Agent registration failed: {response.status_code} - {response.text}")
                agent_errors_total.labels(error_type="registration").inc()
        except Exception as e:
            logger.error(f"Error registering agent (will retry): {e}", exc_info=True)
            agent_errors_total.labels(error_type="registration").inc()
        time.sleep(backoff_seconds)
        backoff_seconds = min(backoff_seconds * 2, 30)

def send_heartbeat():
    """
    Sends a heartbeat to the MAS Orchestrator using the /agents/heartbeat endpoint.
    """
    if not AGENT_ID:
        return
    url = f"{ORCHESTRATOR_URL}/agents/heartbeat/{AGENT_ID}"
    try:
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
    """
    Background task that sends a heartbeat every 30 seconds.
    """
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
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300,
            )
        )
        channel = connection.channel()
        # Declare a durable queue to avoid RabbitMQ 'transient_nonexcl_queues' deprecation
        channel.queue_declare(
            queue=AGENT_ID,
            passive=False,
            durable=True,
            exclusive=False,
            auto_delete=False,
        )

        def _on_message(ch, method, properties, body):
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                # Fallback: treat body as plain text demand
                payload = {"demand": body.decode("utf-8")}

            demand = payload.get("demand", "")
            conversation_id = payload.get("conversation_id", "")
            task_id = payload.get("task_id") or ("task_" + uuid.uuid4().hex)
            
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
            }
            
            # Process task asynchronously (pika is sync, but pipeline is async)
            # Create new event loop for this thread if needed
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Run async pipeline processing with metrics
            import time as time_module
            start_time = time_module.time()
            try:
                result_dict = loop.run_until_complete(rag_pipeline.process_task(task_dict))
                processing_duration = time_module.time() - start_time
                
                task_processing_duration.observe(processing_duration)
                task_processing_total.labels(status="success").inc()
                
                logger.info(
                    f"Task processed successfully: task_id={task_id}, "
                    f"duration={processing_duration:.2f}s, correlation_id={get_correlation_id()}"
                )

                # Send result back to MAS (requires conversation_id and task_id)
                if conversation_id and task_id:
                    send_result(result_dict["response"], conversation_id, task_id)
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
                raise

            # Acknowledge the message
            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=AGENT_ID, on_message_callback=_on_message)
        logger.info(f"RabbitMQ consumer started, listening on queue '{AGENT_ID}'")
        channel.start_consuming()
    except Exception as e:
        logger.error(f"Error in RabbitMQ consumer: {e}", exc_info=True)
        agent_errors_total.labels(error_type="rabbitmq").inc()

def send_result(result: str, conversation_id: str, task_id: str):
    """
    Sends the processed task result to the MAS Orchestrator using the /tasks/task-result/ endpoint.

    Args:
        result: The result string generated by the RAG pipeline.
        conversation_id: The conversation ID for this task.
        task_id: The unique task ID.
    """
    url = f"{ORCHESTRATOR_URL}/tasks/task-result/"
    payload = {
        "agent_id": AGENT_ID,
        "result": result,
        "conversation_id": conversation_id,
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

@app.on_event("startup")
async def startup_event():
    """
    On startup, register the agent with the MAS Orchestrator and start the heartbeat thread.
    """
    logger.info("Agent service starting up...")
    register_agent()
    # Start heartbeat if registration succeeded and we have an id
    heartbeat_thread = threading.Thread(target=heartbeat_task, daemon=True)
    heartbeat_thread.start()
    logger.info("Heartbeat thread started")

    # Start RabbitMQ consumer in background
    consumer_thread = threading.Thread(target=_consume_messages, daemon=True)
    consumer_thread.start()
    logger.info("Agent service startup complete")

@app.post("/task")
async def receive_task(task: Task, request: Request):
    """
    Endpoint to receive a task from the MAS Orchestrator.

    When a POST request with a task payload is received, the agent:
      1. Auto-generates a task_id if one isn't provided.
      2. Processes the task using the RAG pipeline (async).
      3. Sends the result back to the MAS Orchestrator.
      4. Returns the task result.
    """
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
        result_dict = await rag_pipeline.process_task(task.dict())
        processing_duration = time_module.time() - start_time
        
        task_processing_duration.observe(processing_duration)
        task_processing_total.labels(status="success").inc()
        
        logger.info(
            f"Task processed successfully via HTTP: task_id={task.task_id}, "
            f"duration={processing_duration:.2f}s, correlation_id={get_correlation_id()}"
        )

        # Send the result back to the orchestrator.
        send_result(result_dict["response"], task.conversation_id, task.task_id)

        return result_dict
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