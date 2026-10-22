"""Agent profile registry — multi-identity in a single worker process.

One ``agent`` container registers under N identities with MAS so the UI shows
N "active" named agents out of the box, while only one Qwen instance is
loaded into memory. Each profile owns its own ``agent_id``/``api_key`` so
result POSTs authenticate as the right identity for proper attribution.

Default lineup mirrors the historical seed (``mas/db/seed_agents.py``):
General-Assistant, Finance-Analyst, Compliance-Officer, Document-Writer,
Researcher. Operators can override by setting ``AGENT_PROFILES_JSON`` in the
environment — a JSON array of ``{name, type, skills, description}`` objects
— to register a different mix (e.g. one specialised container).

Threading: registered identities live in module-level ``PROFILES``. Reads are
unsynchronised (only mutated once at startup); the heartbeat + result paths
just read by ``agent_id`` lookup.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from ai_agents.agent_tools import invalid_tool_selection
from core.logger import get_logger

SYSTEM_PROMPT_TOKEN_BUDGET = 300
DEFAULT_TOOLS: tuple[str, ...] = ("search_knowledge", "extract_data", "calc", "delegate")

# Per-task active persona. The consumer sets this before running the pipeline
# so :meth:`DecisionMakingAgent.decide` can read it and tailor the system
# message without every intermediate function having to accept a new arg.
# Defaults to ``None`` (vanilla helpful-assistant prompt).
current_persona: ContextVar[str | None] = ContextVar("current_persona", default=None)
current_agent_name: ContextVar[str | None] = ContextVar("current_agent_name", default=None)
current_tools: ContextVar[tuple[str, ...] | None] = ContextVar("current_tools", default=None)
# Per-task "thought process" emitter. The consumer sets it to a closure that
# POSTs a step JSON envelope to MAS; pipeline helpers call it through
# ``ai_agents.step_emitter.emit_step`` so we don't have to thread an emitter
# argument through every method. ``None`` (default) means no-op — keeps the
# unit tests that exercise the pipeline directly happy.
current_step_emitter: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "current_step_emitter", default=None
)

logger = get_logger("agent_profiles")


@dataclass
class AgentProfile:
    name: str
    type: str  # general | analyst | writer | researcher
    skills: list[str]
    description: str
    status: str = field(default="Pending")
    # Optional persona injected into the LLM system prompt for this profile.
    # When None, the pipeline uses its built-in default. Specialists set it
    # to scope behaviour to their domain documents.
    system_prompt: str | None = field(default=None)
    tools: tuple[str, ...] = field(default=DEFAULT_TOOLS)
    # Populated at registration time:
    agent_id: str | None = field(default=None)
    api_key: str | None = field(default=None)

    def __post_init__(self) -> None:
        self.tools = tuple(self.tools)
        problem = invalid_tool_selection(self.tools)
        if problem:
            raise ValueError(f"Agent identity {self.name!r} has {problem}")


DEFAULT_PROFILES: list[AgentProfile] = [
    AgentProfile(
        name="General-Assistant",
        type="general",
        skills=["knowledge_retrieval", "decision_making", "rag_pipeline"],
        description=(
            "General-purpose RAG assistant. Default fallback when no "
            "specialised agent matches the demand."
        ),
        system_prompt=(
            "You are FinCorp's General Assistant. You answer questions that no specialist "
            "owns, from any document in the knowledge store.\n"
            "- Give the direct answer first, then only the detail the question needs.\n"
            "- Keep names, dates and figures exactly as the documents write them."
        ),
        tools=("search_knowledge", "extract_data", "calc", "delegate"),
    ),
    AgentProfile(
        name="Finance-Analyst",
        type="analyst",
        # Skills tuned to the demo corpus: Q4 2025 Financial Report (revenue,
        # margins, segment breakdown, SOC2 status) + Expense Policy (caps,
        # categories). Users pick any of these from the task form's skill
        # MultiSelect and routing lands here.
        skills=[
            "financial_analysis",
            "quarterly_report_qa",
            "revenue_breakdown",
            "expense_review",
            "budget_summary",
            "knowledge_retrieval",
        ],
        description=(
            "Financial analysis specialist. Grounded in the Q4 2025 "
            "Financial Report and the Expense Policy."
        ),
        system_prompt=(
            "You are FinCorp's Finance Analyst. You answer questions about company "
            "finances from the finance documents: quarterly reports, the Expense Policy "
            "and budgets.\n"
            "- The reporting corpus covers Q4 2025 (1 October to 31 December 2025). "
            "Read 'Q4' without a year as Q4 2025 and never put another year in its "
            "place; if the question names a year the documents do not cover, say so.\n"
            "- Lead with the figure, and quote revenue, margins and expense caps exactly "
            "as the document writes them.\n"
            "- HR, IT security and compliance questions are outside finance: say so and "
            "name the specialist who owns them."
        ),
        tools=("search_knowledge", "analyze_payments", "calc", "delegate"),
    ),
    AgentProfile(
        name="Compliance-Officer",
        type="analyst",
        # Skills tuned to the Compliance Guidelines (SOX, GDPR, MiCA, FINRA,
        # MAS) + IT Security Policy (passwords, access control, data
        # classification, incident response).
        skills=[
            "compliance_check",
            "policy_review",
            "audit",
            "gdpr",
            "sox",
            "mica",
            "finra",
            "data_protection",
            "it_security_policy",
            "access_control",
            "incident_response",
            "knowledge_retrieval",
        ],
        description=(
            "Policy and compliance reviewer. Grounded in the Compliance "
            "Guidelines and the IT Security Policy."
        ),
        system_prompt=(
            "You are FinCorp's Compliance Officer. You answer from the compliance, audit "
            "and IT security policy documents.\n"
            "- Name the regime the question falls under (SOX, GDPR, MiCA, FINRA, MAS or "
            "internal policy) before the answer.\n"
            "- Quote the clause or section number when the document gives one, and state "
            "deadlines and statutory obligations explicitly.\n"
            "- Questions outside compliance and IT security: say so and name the "
            "specialist who owns them."
        ),
        tools=("search_knowledge", "extract_data", "delegate"),
    ),
    AgentProfile(
        name="HR-Assistant",
        type="general",
        # Skills tuned to the Employee Handbook (working hours, remote work,
        # leave, benefits, code of conduct) + Expense Policy (expense
        # workflow). Overlaps Finance-Analyst on ``expense_review`` so
        # routing picks whichever side fits the question style.
        skills=[
            "hr_policy",
            "employee_handbook",
            "leave_policy",
            "benefits_qa",
            "remote_work_policy",
            "code_of_conduct",
            "expense_review",
            "knowledge_retrieval",
        ],
        description=("HR specialist. Grounded in the Employee Handbook and the Expense Policy."),
        system_prompt=(
            "You are FinCorp's HR Assistant. You answer employees' questions from the "
            "Employee Handbook and the Expense Policy.\n"
            "- Be warm and speak to the employee directly ('you', 'your manager').\n"
            "- Quote the handbook section when you state a rule, and take expense caps "
            "and per-diems from the Expense Policy.\n"
            "- Strategy, compliance enforcement and IT security belong to other "
            "specialists: say so and name the one who owns them."
        ),
        tools=("search_knowledge", "calc", "delegate"),
    ),
    AgentProfile(
        name="Researcher",
        type="researcher",
        skills=["research", "literature_review", "citation_lookup", "knowledge_retrieval"],
        description=(
            "Multi-source researcher. Pulls and synthesises information across the knowledge store."
        ),
        system_prompt=(
            "You are FinCorp's Researcher. You gather information across several "
            "documents of the knowledge store and bring it together.\n"
            "- Say what each document contributes, and keep figures exactly as written.\n"
            "- Point out where documents disagree or where they leave a gap."
        ),
        tools=("search_knowledge", "extract_data", "delegate"),
    ),
]


def _load_profiles() -> list[AgentProfile]:
    """Resolve the runtime profile list from env, falling back to defaults.

    Env precedence:
    - ``AGENT_PROFILES_JSON`` — JSON array of profile dicts (full override).
    - ``AGENT_NAME`` + ``AGENT_TYPE`` + ``AGENT_SKILLS`` — single-profile mode
      (legacy single-container behaviour). When ``AGENT_NAME`` is set we
      register only that one identity.
    - otherwise → ``DEFAULT_PROFILES``.
    """
    raw_json = os.environ.get("AGENT_PROFILES_JSON", "").strip()
    if raw_json:
        try:
            entries = json.loads(raw_json)
            return [
                AgentProfile(
                    name=e["name"],
                    type=e.get("type", "general"),
                    skills=list(e.get("skills") or []),
                    description=e.get("description", ""),
                )
                for e in entries
            ]
        except Exception:
            logger.exception(
                "AGENT_PROFILES_JSON did not parse as a list of profile dicts; "
                "falling back to defaults"
            )

    single_name = os.environ.get("AGENT_NAME", "").strip()
    if single_name:
        single_type = os.environ.get("AGENT_TYPE", "general").strip() or "general"
        raw_skills = os.environ.get("AGENT_SKILLS", "").strip()
        skills = (
            [s.strip() for s in raw_skills.split(",") if s.strip()]
            if raw_skills
            else ["knowledge_retrieval", "decision_making", "rag_pipeline"]
        )
        description = os.environ.get("AGENT_DESCRIPTION", "Autonomous MAS agent")
        return [
            AgentProfile(
                name=single_name,
                type=single_type,
                skills=skills,
                description=description,
            )
        ]

    return list(DEFAULT_PROFILES)


# Module-level runtime registry. Mutated once during startup.
PROFILES: list[AgentProfile] = _load_profiles()


def unique_agent_types() -> list[str]:
    """De-duplicated list of agent types across all registered profiles.

    Used to figure out which work queues the consumer needs to subscribe to —
    e.g. Finance-Analyst and Compliance-Officer are both ``analyst`` so they
    share one queue.
    """
    seen: list[str] = []
    for p in PROFILES:
        if p.type and p.type not in seen:
            seen.append(p.type)
    return seen


def get_profile_by_agent_id(agent_id: str | None) -> AgentProfile | None:
    if not agent_id:
        return None
    for p in PROFILES:
        if p.agent_id == agent_id:
            return p
    return None


def get_primary_profile() -> AgentProfile:
    """First registered profile — used for legacy ``AGENT_ID`` aliases."""
    return PROFILES[0]


def upsert_external_profile(
    agent_id: str,
    api_key: str,
    name: str,
    agent_type: str,
    skills: list[str],
    description: str = "",
) -> AgentProfile:
    """Add or update a profile we didn't register ourselves.

    Used by the consumer when MAS dispatches a task with credentials for a
    newly-minted specialist agent — the worker adopts that identity so
    subsequent heartbeats keep it active and result POSTs authenticate as it.
    Returns the profile (existing or newly added).
    """
    for p in PROFILES:
        if p.agent_id == agent_id:
            # Refresh metadata in case the user renamed / re-skilled later.
            p.api_key = api_key or p.api_key
            p.name = name or p.name
            p.type = agent_type or p.type
            if skills:
                p.skills = list(skills)
            if description:
                p.description = description
            return p
    new_profile = AgentProfile(
        name=name or f"AutoAgent-{agent_id[:8]}",
        type=agent_type or "general",
        skills=list(skills or []),
        description=description or "Worker-adopted specialist",
        agent_id=agent_id,
        api_key=api_key,
    )
    PROFILES.append(new_profile)
    logger.info(
        "Adopted external profile: name=%s id=%s skills=%s",
        new_profile.name,
        new_profile.agent_id,
        new_profile.skills,
    )
    return new_profile
