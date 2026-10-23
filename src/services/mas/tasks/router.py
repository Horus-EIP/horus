import json
import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

import numpy as np
import yaml
from opentelemetry import trace
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from agents.registry_tool_functions import is_available_worker
from core.embedding_setup import embed_texts
from core.llm_setup import ask_llm_with_json_schema, llm_server_backend
from core.logger import get_logger
from core.metrics import observe_routing_decision
from db.models import Agents
from tasks.decomposition import choose_route_with_llm, decompose_task
from tasks.demo_log import pretty_log
from tasks.direct_answers import direct_answer
from tasks.intent_rules import classify_trivial_intent, find_complex_cue

logger = get_logger("task_router")
tracer = trace.get_tracer(__name__)

ROUTER_EXAMPLES_PATH = Path(__file__).with_name("router_examples.yaml")
DEFAULT_MIN_SCORE = 0.40
DEFAULT_MIN_MARGIN = 0.10
DEFAULT_LLM_MAX_TOKENS = 32
SCORED_EXAMPLES_PER_AGENT = 2
ROUTE_SCHEMA_NAME = "task_route"
LLM_QUESTION_MAX_CHARS = 2000
LOGGED_SCORES = 3
SUB_QUESTION_MIN_WORDS = 3
SUB_QUESTION_MAX_COUNT = 6
SUB_QUESTIONS_CUE = "sub_questions"

_SUB_QUESTION_BOUNDARY = re.compile(
    r";\s*|,?\s+and\s+(?=(?:what|how|who|whom|whose|when|where|which|why|is|are|was|were"
    r"|does|do|did|can|could|should|must|within)\b)",
    re.IGNORECASE,
)

RoutingOutcome = tuple[str | None, str | None, str | None, list]


class Route(str, Enum):
    DIRECT_ANSWER = "DIRECT_ANSWER"
    SINGLE_AGENT = "SINGLE_AGENT"
    COMPLEX_TASK = "COMPLEX_TASK"
    UNROUTED = "UNROUTED"


class RouteMethod(str, Enum):
    RULES = "rules"
    EMBEDDING = "embedding"
    LLM = "llm"
    NONE = "none"


LLM_ROUTES = (Route.SINGLE_AGENT, Route.COMPLEX_TASK)


@dataclass(frozen=True)
class RosterAgent:
    agent_id: str
    name: str
    description: str = ""
    agent_type: str = "general"
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentScore:
    agent: RosterAgent
    score: float


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    method: RouteMethod
    agent: RosterAgent | None = None
    direct_answer: str | None = None
    cue: str | None = None
    scores: tuple[AgentScore, ...] = ()

    def logged_scores(self) -> dict[str, float]:
        return {entry.agent.name: round(entry.score, 3) for entry in self.scores[:LOGGED_SCORES]}


@dataclass(frozen=True)
class RouterSettings:
    min_score: float = DEFAULT_MIN_SCORE
    min_margin: float = DEFAULT_MIN_MARGIN
    llm_max_tokens: int = DEFAULT_LLM_MAX_TOKENS

    @classmethod
    def from_env(cls) -> "RouterSettings":
        return cls(
            min_score=_env_number("ROUTER_MIN_SCORE", DEFAULT_MIN_SCORE, float),
            min_margin=_env_number("ROUTER_MIN_MARGIN", DEFAULT_MIN_MARGIN, float),
            llm_max_tokens=_env_number("ROUTER_LLM_MAX_TOKENS", DEFAULT_LLM_MAX_TOKENS, int),
        )


@dataclass(frozen=True)
class ExampleGroup:
    agent_name: str
    skills: tuple[str, ...]
    examples: tuple[str, ...]


@dataclass(frozen=True)
class RouterExamples:
    version: str
    groups: tuple[ExampleGroup, ...]


def _env_number(name: str, default, kind):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return kind(raw)
    except ValueError:
        logger.warning("Ignoring %s=%r: not a number; using %s", name, raw, default)
        return default


def load_router_examples(path: Path = ROUTER_EXAMPLES_PATH) -> RouterExamples:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    groups = tuple(
        ExampleGroup(
            agent_name=entry["agent"],
            skills=tuple(entry.get("skills") or ()),
            examples=tuple(entry["examples"]),
        )
        for entry in document["agents"]
    )
    return RouterExamples(version=str(document["version"]), groups=groups)


def embed_for_routing(texts: list[str]) -> np.ndarray:
    return embed_texts(texts)


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0.0, 1.0, norms)


class ExampleIndex:
    def __init__(
        self,
        examples: RouterExamples,
        embed: Callable[[list[str]], np.ndarray] = embed_for_routing,
    ):
        self.examples = examples
        self._embed = embed
        self._vectors: np.ndarray | None = None
        self._group_rows: list[slice] = []
        self._lock = threading.Lock()

    def embed(self, texts: list[str]) -> np.ndarray:
        return _unit_rows(np.asarray(self._embed(texts), dtype=np.float32))

    def warm(self) -> None:
        self._example_vectors()

    def _example_vectors(self) -> np.ndarray:
        if self._vectors is None:
            with self._lock:
                if self._vectors is None:
                    texts = [text for group in self.examples.groups for text in group.examples]
                    started = time.perf_counter()
                    vectors = self.embed(texts)
                    rows, start = [], 0
                    for group in self.examples.groups:
                        rows.append(slice(start, start + len(group.examples)))
                        start += len(group.examples)
                    self._group_rows = rows
                    self._vectors = vectors
                    logger.info(
                        "Router examples embedded",
                        version=self.examples.version,
                        examples=len(texts),
                        seconds=round(time.perf_counter() - started, 3),
                    )
        return self._vectors

    def agent_scores(
        self, query: np.ndarray, owners: dict[int, RosterAgent]
    ) -> tuple[AgentScore, ...]:
        similarities = self._example_vectors() @ query
        agents: dict[str, RosterAgent] = {}
        rows: dict[str, list[np.ndarray]] = {}
        for group_index, agent in owners.items():
            agents[agent.name] = agent
            rows.setdefault(agent.name, []).append(similarities[self._group_rows[group_index]])
        scores = [
            AgentScore(agents[name], _closest_examples_mean(np.concatenate(agent_rows)))
            for name, agent_rows in rows.items()
        ]
        return tuple(sorted(scores, key=lambda entry: entry.score, reverse=True))


def _closest_examples_mean(similarities: np.ndarray) -> float:
    return float(np.sort(similarities)[-SCORED_EXAMPLES_PER_AGENT:].mean())


def assign_example_groups(
    groups: Sequence[ExampleGroup], roster: Sequence[RosterAgent]
) -> dict[int, RosterAgent]:
    by_name = {agent.name: agent for agent in roster}
    owners: dict[int, RosterAgent] = {}
    for index, group in enumerate(groups):
        owner = by_name.get(group.agent_name) or _agent_sharing_most_skills(group, roster)
        if owner is not None:
            owners[index] = owner
    return owners


def _agent_sharing_most_skills(
    group: ExampleGroup, roster: Sequence[RosterAgent]
) -> RosterAgent | None:
    wanted = set(group.skills)
    chosen, chosen_overlap = None, 0
    for agent in roster:
        overlap = len(wanted.intersection(agent.skills))
        if overlap > chosen_overlap:
            chosen, chosen_overlap = agent, overlap
    return chosen


def split_sub_questions(question: str) -> list[str]:
    parts = [part.strip(" \t\n,;?.") for part in _SUB_QUESTION_BOUNDARY.split(question)]
    parts = [part for part in parts if part]
    if not 2 <= len(parts) <= SUB_QUESTION_MAX_COUNT:
        return []
    if any(len(part.split()) < SUB_QUESTION_MIN_WORDS for part in parts):
        return []
    return parts


def confident_agent(scores: Sequence[AgentScore], settings: RouterSettings) -> RosterAgent | None:
    if not scores:
        return None
    runner_up = scores[1].score if len(scores) > 1 else 0.0
    best = scores[0]
    if best.score >= settings.min_score and best.score - runner_up >= settings.min_margin:
        return best.agent
    return None


def rule_decision(question: str, roster: Sequence[RosterAgent]) -> RouteDecision | None:
    intent = classify_trivial_intent(question)
    if intent is not None:
        reply = direct_answer(question, [agent.name for agent in roster])
        if reply is not None:
            return RouteDecision(
                Route.DIRECT_ANSWER, RouteMethod.RULES, direct_answer=reply, cue=intent.value
            )
    cue = find_complex_cue(question)
    if cue is not None:
        return RouteDecision(Route.COMPLEX_TASK, RouteMethod.RULES, cue=cue.value)
    return None


def embedding_decision(
    question: str,
    roster: Sequence[RosterAgent],
    index: ExampleIndex,
    settings: RouterSettings,
) -> tuple[RouteDecision | None, tuple[AgentScore, ...]]:
    owners = assign_example_groups(index.examples.groups, roster)
    if not owners:
        return None, ()
    sub_questions = split_sub_questions(question)
    vectors = index.embed([question, *sub_questions])
    scores = index.agent_scores(vectors[0], owners)
    if not sub_questions:
        agent = confident_agent(scores, settings)
        if agent is None:
            return None, scores
        return RouteDecision(
            Route.SINGLE_AGENT, RouteMethod.EMBEDDING, agent, scores=scores
        ), scores
    part_agents = [
        confident_agent(index.agent_scores(vector, owners), settings) for vector in vectors[1:]
    ]
    if any(agent is None for agent in part_agents):
        return None, scores
    if len({agent.name for agent in part_agents}) > 1:
        return (
            RouteDecision(
                Route.COMPLEX_TASK, RouteMethod.EMBEDDING, cue=SUB_QUESTIONS_CUE, scores=scores
            ),
            scores,
        )
    return (
        RouteDecision(Route.SINGLE_AGENT, RouteMethod.EMBEDDING, part_agents[0], scores=scores),
        scores,
    )


def prompt_roster(roster: Sequence[RosterAgent]) -> list[RosterAgent]:
    return sorted(roster, key=lambda agent: (agent.name, agent.description))


def llm_route_schema(roster: Sequence[RosterAgent]) -> dict:
    return {
        "type": "object",
        "properties": {
            "route": {"type": "string", "enum": [route.value for route in LLM_ROUTES]},
            "agent": {"type": "string", "enum": sorted({agent.name for agent in roster})},
        },
        "required": ["route", "agent"],
        "additionalProperties": False,
    }


def llm_route_messages(question: str, roster: Sequence[RosterAgent]) -> list[dict]:
    agents_block = "\n".join(_roster_line(agent) for agent in prompt_roster(roster))
    return [
        {
            "role": "system",
            "content": (
                "You route requests inside a multi-agent assistant. Reply with JSON only.\n"
                "route: SINGLE_AGENT for almost every request, including any question "
                "about one topic, however it is phrased.\n"
                "route: COMPLEX_TASK only when the request asks two or more separate things "
                "that belong to different agents' domains.\n"
                "agent: the agent whose domain best fits the request, or its first part.\n"
                f"Agents:\n{agents_block}"
            ),
        },
        {"role": "user", "content": question[:LLM_QUESTION_MAX_CHARS]},
    ]


def _roster_line(agent: RosterAgent) -> str:
    if agent.description:
        return f"- {agent.name}: {agent.description}"
    return f"- {agent.name}"


def llm_decision(
    question: str,
    roster: Sequence[RosterAgent],
    settings: RouterSettings,
    ask: Callable[[list, str, dict, int], str] = ask_llm_with_json_schema,
) -> RouteDecision:
    reply = ask(
        llm_route_messages(question, roster),
        ROUTE_SCHEMA_NAME,
        llm_route_schema(roster),
        settings.llm_max_tokens,
    )
    choice = json.loads(reply)
    route = Route(choice["route"])
    if route not in LLM_ROUTES:
        raise ValueError(f"The LLM router chose {route.value}, which it may not choose")
    agent = next((agent for agent in roster if agent.name == choice.get("agent")), None)
    if route is Route.SINGLE_AGENT and agent is None:
        raise ValueError(f"The LLM router chose an unknown agent: {choice.get('agent')!r}")
    return RouteDecision(route, RouteMethod.LLM, agent)


class TaskRouter:
    def __init__(self, index: ExampleIndex):
        self.index = index

    def decide_without_llm(
        self, question: str, roster: Sequence[RosterAgent], settings: RouterSettings
    ) -> tuple[RouteDecision | None, tuple[AgentScore, ...]]:
        try:
            decision = rule_decision(question, roster)
        except Exception:
            logger.exception("Rule routing failed; trying the embeddings instead")
            decision = None
        if decision is not None:
            return decision, ()
        try:
            return embedding_decision(question, roster, self.index, settings)
        except Exception:
            logger.exception("Embedding routing failed; asking the LLM router instead")
            return None, ()

    def decide_with_llm(
        self,
        question: str,
        roster: Sequence[RosterAgent],
        settings: RouterSettings,
        scores: tuple[AgentScore, ...] = (),
        ask: Callable[[list, str, dict, int], str] = ask_llm_with_json_schema,
    ) -> RouteDecision:
        try:
            decision = llm_decision(question, roster, settings, ask)
        except Exception:
            logger.exception("The constrained LLM router failed; leaving the task unrouted")
            return RouteDecision(Route.UNROUTED, RouteMethod.LLM, scores=scores)
        return replace(decision, scores=scores)


_task_router: TaskRouter | None = None
_task_router_lock = threading.Lock()


def task_router() -> TaskRouter:
    global _task_router
    if _task_router is None:
        with _task_router_lock:
            if _task_router is None:
                _task_router = TaskRouter(ExampleIndex(load_router_examples()))
    return _task_router


def warm_router_examples() -> None:
    task_router().index.warm()


def available_roster(db: Session) -> list[RosterAgent]:
    try:
        agents = db.query(Agents).all()
    except SQLAlchemyError:
        logger.exception("Could not read the agent roster for routing")
        db.rollback()
        return []
    return [
        RosterAgent(
            agent_id=agent.id,
            name=agent.name,
            description=agent.description or "",
            agent_type=str(getattr(agent.type, "value", agent.type) or "general"),
            skills=tuple(agent.skills) if isinstance(agent.skills, list) else (),
        )
        for agent in agents
        if is_available_worker(agent)
    ]


@tracer.start_as_current_span("route_task")
def route_task(user_input: str, db: Session, *, task_id: str | None = None) -> RoutingOutcome:
    started = time.perf_counter()
    roster = available_roster(db)
    settings = RouterSettings.from_env()
    router = task_router()
    decision, scores = router.decide_without_llm(user_input, roster, settings)
    if decision is None and not roster:
        decision = RouteDecision(Route.UNROUTED, RouteMethod.NONE)
    if decision is None and llm_server_backend():
        decision = router.decide_with_llm(
            user_input, roster, settings, scores, ask_llm_with_json_schema
        )
    full_router_outcome = None
    if decision is None:
        classification, full_router_outcome = _route_with_the_full_llm_router(user_input, db)
        decision = _decision_from_full_llm_router(
            classification, full_router_outcome, roster, scores
        )
    _record_decision(decision, task_id, time.perf_counter() - started)
    if full_router_outcome is None or decision.route is Route.COMPLEX_TASK:
        return _outcome(decision, user_input, db)
    return full_router_outcome


def _route_with_the_full_llm_router(
    user_input: str, db: Session
) -> tuple[str | None, RoutingOutcome]:
    try:
        return choose_route_with_llm(user_input, db)
    except Exception:
        logger.exception("The LLM router failed; leaving the task to the fallback agents")
        return None, _unrouted()


def _decision_from_full_llm_router(
    classification: str | None,
    outcome: RoutingOutcome,
    roster: Sequence[RosterAgent],
    scores: tuple[AgentScore, ...],
) -> RouteDecision:
    if classification == Route.COMPLEX_TASK.value:
        return RouteDecision(Route.COMPLEX_TASK, RouteMethod.LLM, scores=scores)
    agent_id, _demand, direct_response, _remaining = outcome
    agent = next((agent for agent in roster if agent.agent_id == agent_id), None)
    if direct_response:
        return RouteDecision(
            Route.DIRECT_ANSWER, RouteMethod.LLM, direct_answer=direct_response, scores=scores
        )
    if agent_id:
        return RouteDecision(Route.SINGLE_AGENT, RouteMethod.LLM, agent, scores=scores)
    return RouteDecision(Route.UNROUTED, RouteMethod.LLM, scores=scores)


def _outcome(decision: RouteDecision, user_input: str, db: Session) -> RoutingOutcome:
    if decision.route is Route.DIRECT_ANSWER:
        return None, None, decision.direct_answer, []
    if decision.route is Route.SINGLE_AGENT and decision.agent is not None:
        return decision.agent.agent_id, user_input, None, []
    if decision.route is Route.COMPLEX_TASK:
        return _plan(user_input, db)
    return _unrouted()


def _plan(user_input: str, db: Session) -> RoutingOutcome:
    try:
        first_action, actions = decompose_task(user_input, db)
    except Exception:
        logger.exception("The planner failed for a complex task")
        return _unrouted()
    if not first_action:
        return _unrouted()
    first_agent, first_demand = first_action
    return first_agent, first_demand, None, actions


def _unrouted() -> RoutingOutcome:
    return None, None, None, []


def _record_decision(decision: RouteDecision, task_id: str | None, seconds: float) -> None:
    observe_routing_decision(decision.method.value, decision.route.value, seconds)
    agent_name = decision.agent.name if decision.agent is not None else None
    span = trace.get_current_span()
    span.set_attribute("horus.routing.method", decision.method.value)
    span.set_attribute("horus.routing.route", decision.route.value)
    if agent_name:
        span.set_attribute("horus.routing.agent", agent_name)
    logger.info(
        "Routing decision",
        task_id=task_id,
        method=decision.method.value,
        route=decision.route.value,
        agent=agent_name,
        cue=decision.cue,
        scores=decision.logged_scores(),
        latency_ms=round(seconds * 1000, 1),
    )
    target = f" -> {agent_name}" if agent_name else ""
    pretty_log(
        f"ROUTED BY {decision.method.value.upper()}: {decision.route.value}{target} "
        f"in {seconds * 1000:.0f} ms",
        "🧭",
    )
