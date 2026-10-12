"""Agent server: registers with MAS, runs heartbeat + queue consumers, serves HTTP.

Handlers dispatch incoming tasks to the active agent (general RAG
pipeline or one of the specialized agents) and POST results back to the
orchestrator. See ``docs/architecture.md`` for the full
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

import os
import socket
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import requests
from fastapi import FastAPI, Request
from prometheus_client import make_asgi_app

from agent_server.consumers import (
    RESULT_STATUS_BY_ANSWER,
    TaskClaim,
    _consume_agent_messages,
    _consume_messages,
)
from agent_server.middleware import CorrelationIDMiddleware
from agent_server.models import Result, Task
from agent_server.profiles import (
    PROFILES,
    get_primary_profile,
    get_profile_by_agent_id,
)
from ai_agents.answer_contract import answer_of
from ai_agents.data_extractor_tool import spacy_is_off
from ai_agents.decision_making_agent import DecisionMakingAgent
from ai_agents.knowledge_retrieval_agent import KnowledgeRetrievalAgent
from ai_agents.knowledge_store_client import KnowledgeStoreClient
from ai_agents.rag_pipeline import RAGPipeline
from config.settings import (
    MAX_DELEGATION_DEPTH,
    MODEL_DEVICE,
    MODEL_NAME,
    ORCHESTRATOR_PASSWORD,
    ORCHESTRATOR_TOKEN,
    ORCHESTRATOR_URL,
    ORCHESTRATOR_USERNAME,
)
from core.logger import get_correlation_id, get_logger, set_correlation_id
from core.metrics import (
    agent_errors_total,
    agent_heartbeat_total,
    agent_registered,
    task_processing_duration,
    task_processing_total,
)
from core.version import HORUS_VERSION
from specialized.analyst_agent import AnalystAgent
from specialized.researcher_agent import ResearcherAgent
from specialized.writer_agent import WriterAgent

logger = get_logger("agent_server")


# Multi-identity worker: a single container registers under N profiles (see
# agent_server.profiles). The module-level ``AGENT_ID`` / ``AGENT_API_KEY`` /
# ``AGENT_NAME`` / ``SKILLS`` aliases below point at the primary (first)
# profile for backward compatibility — older callers and tests that imported
# them keep working. Multi-profile-aware code paths read from
# :mod:`agent_server.profiles` directly.
AGENT_ID: str | None = None
AGENT_API_KEY: str | None = None
AGENT_NAME: str = get_primary_profile().name
SKILLS: list[str] = list(get_primary_profile().skills)
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

# Build one pipeline per agent type up front so the multi-queue consumer can
# dispatch the right one for each incoming task. All pipelines share the same
# ``decision_agent`` (and therefore the same Qwen instance) — only the wrapper
# class differs. This is what lets a single container act as 5 named agents
# without loading 5 LLMs.
pipelines: dict[str, object] = {
    "general": RAGPipeline(retrieval_agent, decision_agent, tool_registry=None),
    "researcher": ResearcherAgent(retrieval_agent),
    "analyst": AnalystAgent(),
    "writer": WriterAgent(decision_agent),
}

# Legacy single-pipeline aliases — kept so older callers that imported
# ``active_agent`` keep working. Points at whatever the primary profile is.
active_agent = pipelines.get(get_primary_profile().type, pipelines["general"])
rag_pipeline: RAGPipeline | None = (
    active_agent if isinstance(active_agent, RAGPipeline) else None
)


def get_pipeline_for_type(agent_type: str):
    """Return the pipeline instance to run for a given type (general by default)."""
    return pipelines.get((agent_type or "general").lower(), pipelines["general"])

# Shared RabbitMQ work-queue prefix (aligned with MAS ``agent_work_queue_prefix``).
# The consumer subscribes to ``{prefix}.{type}`` for every unique type across
# registered profiles, so one process can serve general + analyst + writer +
# researcher tasks concurrently. The single-type ``WORK_QUEUE_NAME`` alias is
# preserved for legacy callers that imported it; resolves to the primary
# profile's queue.
_wq_prefix = os.getenv("HORUS_WORK_QUEUE_PREFIX", "horus.work").strip().rstrip(".")


def work_queue_name_for_type(agent_type: str) -> str:
    at = (agent_type or "general").lower()
    if "." in at:
        at = at.split(".")[-1]
    return f"{_wq_prefix}.{at}"


WORK_QUEUE_NAME = work_queue_name_for_type(get_primary_profile().type)

WORKER_ID = os.getenv("AGENT_WORKER_ID", "").strip() or socket.gethostname()
WORKER_RUN_ID = uuid.uuid4().hex
_CLAIM_TIMEOUT_SECONDS = 10


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


def _build_headers(
    include_api_key: bool = False,
    *,
    agent_id: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Return MAS request headers; optionally adds ``X-API-Key``/``Agent-ID``.

    Callers can pass an explicit ``agent_id``/``api_key`` to authenticate as a
    specific registered profile (so result POSTs for "Finance-Analyst" are
    signed with that profile's credentials rather than the primary's).
    """
    headers: dict = {}
    token = _get_orchestrator_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if include_api_key:
        # Default to the primary profile's credentials when nothing is passed.
        aid = agent_id or AGENT_ID
        akey = api_key or AGENT_API_KEY
        if aid and akey:
            headers["X-API-Key"] = f"{aid}:{akey}"
            headers["Agent-ID"] = aid
    return headers


def _register_one_profile(profile) -> bool:
    """Register a single profile with MAS. Returns True on success.

    Handles the 409 case by cleaning up any inactive entry with the same name
    (e.g. from a previous container run) and retrying.
    """
    url = f"{ORCHESTRATOR_URL}/agents/register"
    base_name = profile.name
    name_variant = base_name
    while True:
        try:
            payload = {
                "name": name_variant,
                "skills": profile.skills,
                "description": profile.description,
                "type": profile.type,
            }
            response = requests.post(
                url, json=payload, headers=_build_headers(), timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                profile.agent_id = data.get("agent_id")
                profile.api_key = data.get("api_key")
                logger.info(
                    "Profile registered: name=%s id=%s type=%s",
                    profile.name,
                    profile.agent_id,
                    profile.type,
                )
                return True
            if response.status_code == 409:
                # The worker is the canonical owner of its default profile
                # names — any row in MAS with this name is from a previous
                # container run and must be evicted, regardless of whether
                # MAS still thinks it's active (a heartbeat 25s ago wins
                # against MAS's 30s staleness check on a quick redeploy).
                # Delete all rows matching the name, then retry with the same
                # label so the UI never accumulates ``Foo-abc123`` ghosts.
                logger.warning(
                    "Profile '%s' already registered; reclaiming the name",
                    name_variant,
                )
                deleted_any = False
                try:
                    list_resp = requests.get(
                        f"{ORCHESTRATOR_URL}/agents/details/",
                        headers=_build_headers(),
                        timeout=5,
                    )
                    if list_resp.status_code == 200:
                        ghosts = [
                            a for a in list_resp.json()
                            if a.get("name") == name_variant
                        ]
                        for ghost in ghosts:
                            del_resp = requests.delete(
                                f"{ORCHESTRATOR_URL}/agents/unregister/{ghost['id']}",
                                headers=_build_headers(),
                                timeout=5,
                            )
                            if del_resp.status_code == 200:
                                logger.info(
                                    "Evicted stale row name=%s id=%s",
                                    name_variant,
                                    ghost.get("id"),
                                )
                                deleted_any = True
                            else:
                                logger.warning(
                                    "Could not delete %s: %s - %s",
                                    ghost.get("id"),
                                    del_resp.status_code,
                                    del_resp.text,
                                )
                except Exception as cleanup_err:
                    logger.warning("Stale cleanup failed: %s", cleanup_err)
                if deleted_any:
                    continue  # retry with the same name
                # Cleanup couldn't free the name (permissions, race) — fall
                # back to a unique suffix so registration at least succeeds.
                name_variant = f"{base_name}-{uuid.uuid4().hex[:6]}"
                continue
            logger.error(
                "Registration failed for %s: %s - %s",
                profile.name,
                response.status_code,
                response.text,
            )
            agent_errors_total.labels(error_type="registration").inc()
            return False
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            # Expected while MAS is still starting up; register_profiles() retries
            # with backoff. Log without a traceback to avoid boot-time spam.
            logger.warning(
                "MAS not reachable yet for %s, will retry: %s", profile.name, exc
            )
            agent_errors_total.labels(error_type="registration").inc()
            return False
        except Exception as exc:
            logger.error(
                "Error registering %s (will retry): %s", profile.name, exc, exc_info=True
            )
            agent_errors_total.labels(error_type="registration").inc()
            return False


def register_profiles():
    """Register every profile with MAS; keeps retrying until at least one succeeds.

    Backward-compat: ``AGENT_ID`` / ``AGENT_API_KEY`` module globals are aliased
    to the first successfully registered profile so older imports keep working.
    """
    global AGENT_ID, AGENT_API_KEY
    backoff_seconds = 1
    while True:
        any_success = False
        for profile in PROFILES:
            if profile.agent_id:
                continue
            if _register_one_profile(profile):
                any_success = True
        if any(p.agent_id for p in PROFILES):
            primary = get_primary_profile()
            AGENT_ID = primary.agent_id
            AGENT_API_KEY = primary.api_key
            agent_registered.set(1)
            registered = [p.name for p in PROFILES if p.agent_id]
            logger.info("Registered %d profile(s): %s", len(registered), ", ".join(registered))
            return
        if not any_success:
            time.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, 30)


# Legacy alias for any caller still importing ``register_agent``.
register_agent = register_profiles


def _heartbeat_for_profile(profile) -> None:
    if not profile.agent_id or not profile.api_key:
        return
    url = f"{ORCHESTRATOR_URL}/agents/heartbeat/{profile.agent_id}"
    try:
        headers = _build_headers(
            include_api_key=True, agent_id=profile.agent_id, api_key=profile.api_key
        )
        response = requests.post(url, headers=headers, timeout=5)
        if response.status_code == 401 and not ORCHESTRATOR_TOKEN:
            # JWT expired — drop the cache and retry once with a fresh token.
            _invalidate_cached_mas_token()
            headers = _build_headers(
                include_api_key=True,
                agent_id=profile.agent_id,
                api_key=profile.api_key,
            )
            response = requests.post(url, headers=headers, timeout=5)
        if response.status_code != 200:
            logger.warning(
                "Heartbeat for %s failed: %s - %s",
                profile.name,
                response.status_code,
                response.text,
            )
            agent_heartbeat_total.labels(status="error").inc()
        else:
            agent_heartbeat_total.labels(status="success").inc()
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        # MAS briefly unreachable (e.g. a restart); the loop retries next cycle.
        logger.warning(
            "Heartbeat for %s deferred (MAS unreachable): %s", profile.name, exc
        )
        agent_heartbeat_total.labels(status="error").inc()
    except Exception as exc:
        logger.error("Heartbeat error for %s: %s", profile.name, exc, exc_info=True)
        agent_heartbeat_total.labels(status="error").inc()


def send_heartbeat():
    """Send a heartbeat for every registered profile."""
    for profile in PROFILES:
        _heartbeat_for_profile(profile)


def heartbeat_task():
    """Background loop: heartbeat every 30 seconds."""
    while True:
        send_heartbeat()
        time.sleep(30)


def _post_as_profile(path: str, body: dict, profile) -> requests.Response:
    url = f"{ORCHESTRATOR_URL}{path}"

    def _post() -> requests.Response:
        return requests.post(
            url,
            json=body,
            headers=_build_headers(
                include_api_key=True,
                agent_id=profile.agent_id,
                api_key=profile.api_key,
            ),
            timeout=_CLAIM_TIMEOUT_SECONDS,
        )

    response = _post()
    if response.status_code == 401 and not ORCHESTRATOR_TOKEN:
        _invalidate_cached_mas_token()
        response = _post()
    return response


def _detail(response: requests.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("detail") if isinstance(body, dict) else None


def claim_task(task_id: str, assigned_agent_id: str | None) -> TaskClaim:
    profile = get_profile_by_agent_id(assigned_agent_id) or get_primary_profile()
    body = {
        "agent_id": assigned_agent_id or profile.agent_id,
        "worker_id": WORKER_ID,
        "run_id": WORKER_RUN_ID,
    }
    try:
        response = _post_as_profile(f"/tasks/{task_id}/claim", body, profile)
    except requests.exceptions.RequestException as exc:
        logger.warning("Claim of task %s did not reach MAS: %s", task_id, exc)
        return TaskClaim.UNAVAILABLE
    if response.status_code == 200:
        return TaskClaim.CLAIMED
    if response.status_code == 404 and _detail(response) == "Not Found":
        logger.warning(
            "MAS has no claim endpoint (older release); task %s runs unclaimed", task_id
        )
        return TaskClaim.CLAIMED
    if response.status_code in (404, 409):
        logger.info(
            "MAS refused the claim of task %s: %s - %s",
            task_id,
            response.status_code,
            response.text[:200],
        )
        return TaskClaim.REFUSED
    if response.status_code in (403, 422):
        logger.warning(
            "MAS will never accept the claim of task %s, so its message is dropped: %s - %s",
            task_id,
            response.status_code,
            response.text[:200],
        )
        return TaskClaim.REFUSED
    logger.warning(
        "Claim of task %s failed: %s - %s",
        task_id,
        response.status_code,
        response.text[:200],
    )
    return TaskClaim.UNAVAILABLE


def fail_abandoned_claims() -> list[str]:
    profile = get_primary_profile()
    body = {"worker_id": WORKER_ID, "run_id": WORKER_RUN_ID}
    try:
        response = _post_as_profile("/tasks/abandoned-claims", body, profile)
    except requests.exceptions.RequestException as exc:
        logger.warning("Could not report the tasks an earlier run left unfinished: %s", exc)
        return []
    if response.status_code != 200:
        logger.warning(
            "MAS did not fail the tasks an earlier run left unfinished: %s - %s",
            response.status_code,
            response.text[:200],
        )
        return []
    try:
        failed = list(response.json().get("failed") or [])
    except (ValueError, AttributeError):
        failed = []
    if failed:
        logger.warning(
            "MAS failed %d task(s) an earlier run of worker %s left unfinished",
            len(failed),
            WORKER_ID,
        )
    return failed


def send_result(
    result: str,
    conversation_id: str,
    task_id: str,
    assigned_agent_id: str | None = None,
    skill_used: str | None = None,
    status: str = "completed",
    reason: str | None = None,
    sources: list[dict] | None = None,
):
    """
    Sends the processed task result to the MAS Orchestrator using the /tasks/task-result/ endpoint.

    Args:
        result: The result string generated by the RAG pipeline.
        conversation_id: The conversation ID for this task.
        task_id: The unique task ID.
        assigned_agent_id: Task assignee UUID. The matching registered profile
            authenticates the POST so MAS sees the result coming from the
            expected identity and the chat UI shows the right attribution.
        skill_used: Optional skill the worker exercised for this task (e.g.
            ``financial_analysis``).
    """
    url = f"{ORCHESTRATOR_URL}/tasks/task-result/"

    # Pick the profile that matches the assigned agent so the X-API-Key header
    # and ``agent_name`` both belong to the identity MAS expects. Falls back
    # to the primary profile (legacy single-agent flow).
    profile = get_profile_by_agent_id(assigned_agent_id) or get_primary_profile()
    body_agent_id = assigned_agent_id or profile.agent_id
    effective_skill = skill_used or (profile.skills[0] if profile.skills else None)

    payload = {
        "agent_id": body_agent_id,
        "agent_name": profile.name,
        "skill_used": effective_skill,
        "result": result,
        "conversation_id": str(conversation_id),
        "task_id": task_id,
        "status": status,
    }
    if reason:
        payload["reason"] = reason
    if sources is not None:
        payload["sources"] = [dict(source) for source in sources]
    try:
        response = requests.post(
            url,
            json=payload,
            headers=_build_headers(
                include_api_key=True,
                agent_id=profile.agent_id,
                api_key=profile.api_key,
            ),
        )
        if response.status_code != 200:
            logger.warning(
                "Failed to send result (as %s): %s - %s",
                profile.name,
                response.status_code,
                response.text,
            )
        else:
            logger.debug("Result sent successfully as %s", profile.name)
    except Exception as e:
        logger.error(f"Error sending result: {e}", exc_info=True)


def send_step(
    step: dict,
    conversation_id: str,
    task_id: str,
    assigned_agent_id: str | None = None,
) -> None:
    """Fire-and-forget POST of a thought-process step to MAS.

    Steps are best-effort: if MAS is slow or down the call short-circuits and
    the task continues. Authenticated as the profile that owns the task so
    MAS sees a step coming from the same identity as the eventual result.
    """
    url = f"{ORCHESTRATOR_URL}/tasks/task-step/"
    profile = get_profile_by_agent_id(assigned_agent_id) or get_primary_profile()
    body_agent_id = assigned_agent_id or profile.agent_id
    ts = step.get("timestamp") or datetime.now(UTC).isoformat()
    payload = {
        "task_id": task_id,
        "conversation_id": str(conversation_id) if conversation_id else None,
        "agent_id": body_agent_id,
        "agent_name": profile.name,
        "step_type": step.get("step_type"),
        "title": step.get("title"),
        "detail": step.get("detail"),
        "timestamp": ts,
        "metadata": step.get("metadata") or {},
    }
    try:
        response = requests.post(
            url,
            json=payload,
            headers=_build_headers(
                include_api_key=True,
                agent_id=profile.agent_id,
                api_key=profile.api_key,
            ),
            timeout=3,
        )
        if response.status_code >= 400:
            # 404 / 405 here means MAS doesn't expose the endpoint yet — that's
            # fine, the result path still works. Log quietly.
            logger.debug(
                "Step POST returned %s (%s): %s",
                response.status_code,
                step.get("step_type"),
                response.text[:200],
            )
    except Exception as e:
        logger.debug("Step POST failed (%s): %s", step.get("step_type"), e)


def mock_ai_mode() -> bool:
    return os.getenv("HORUS_AI_MODE", "").strip().lower() == "mock"


def mock_ai_warning() -> str:
    message = ("Mock AI mode: llm-mock answers this agent's model calls, so its answers "
               "are simulated from the documents, not written by a language model")
    if spacy_is_off():
        message += "; spaCy is off, so payments are extracted with regular expressions"
    if os.getenv("OTEL_SDK_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        message += "; monitoring is off, so the agent exports no trace"
    return message


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown (replaces deprecated on_event)."""
    logger.info("Agent service starting up...")
    if mock_ai_mode():
        logger.warning(mock_ai_warning())
    register_agent()
    fail_abandoned_claims()
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


app = FastAPI(title="Horus Agent Service", version=HORUS_VERSION, lifespan=lifespan)

# OpenTelemetry auto-instrumentation is handled by opentelemetry-instrument wrapper
# See Dockerfile CMD for details

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

app.add_middleware(CorrelationIDMiddleware)


@app.get(
    "/health",
    summary="Liveness probe",
    description="Answers once startup has finished. Loads no model and calls no other service.",
    tags=["Health"],
)
async def health_check():
    return {"status": "healthy", "service": "agent", "version": HORUS_VERSION}


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

    # Process the task using the RAG pipeline (async) with metrics. The HTTP
    # path always runs the primary profile's pipeline; the RabbitMQ consumer
    # path is multi-queue-aware and dispatches per task type.
    import time as time_module
    start_time = time_module.time()
    try:
        task_dict = task.model_dump()
        primary_type = get_primary_profile().type
        primary_pipeline = get_pipeline_for_type(primary_type)
        if primary_type == "general":
            answer = answer_of(await primary_pipeline.process_task(task_dict))
        elif primary_type in ("researcher", "analyst", "writer"):
            answer = answer_of(
                await primary_pipeline.process_request(
                    task_type=task_dict.get("operation"),
                    data=task_dict.get("query"),
                    extra_parameters=task_dict,
                )
            )
        else:
            raise ValueError(f"Unsupported primary type: {primary_type}")

        processing_duration = time_module.time() - start_time

        task_processing_duration.observe(processing_duration)
        task_processing_total.labels(status="success").inc()

        logger.info(
            f"Task processed successfully via HTTP: task_id={task.task_id}, "
            f"duration={processing_duration:.2f}s, correlation_id={get_correlation_id()}"
        )

        # Send the result back to the orchestrator.
        send_result(
            answer.answer,
            task.conversation_id,
            task.task_id,
            assigned_agent_id=task_dict.get("assigned_agent_id"),
            skill_used=task_dict.get("skill_used") or task_dict.get("operation"),
            status=RESULT_STATUS_BY_ANSWER[answer.status],
            reason=answer.reason,
            sources=answer.sources,
        )

        # Return the result in the format expected by the response_model
        return Result(
            agent_id=AGENT_ID if AGENT_ID else "unknown",
            result=answer.answer
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
