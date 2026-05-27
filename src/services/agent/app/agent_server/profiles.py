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
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.logger import get_logger

# Per-task active persona. The consumer sets this before running the pipeline
# so :meth:`DecisionMakingAgent.decide` can read it and tailor the system
# message without every intermediate function having to accept a new arg.
# Defaults to ``None`` (vanilla helpful-assistant prompt).
current_persona: ContextVar[Optional[str]] = ContextVar(
    "current_persona", default=None
)
current_agent_name: ContextVar[Optional[str]] = ContextVar(
    "current_agent_name", default=None
)
# Per-task "thought process" emitter. The consumer sets it to a closure that
# POSTs a step JSON envelope to MAS; pipeline helpers call it through
# ``ai_agents.step_emitter.emit_step`` so we don't have to thread an emitter
# argument through every method. ``None`` (default) means no-op — keeps the
# unit tests that exercise the pipeline directly happy.
current_step_emitter: ContextVar[Optional[Callable[[dict[str, Any]], None]]] = ContextVar(
    "current_step_emitter", default=None
)

logger = get_logger("agent_profiles")


@dataclass
class AgentProfile:
    name: str
    type: str  # general | analyst | writer | researcher
    skills: list[str]
    description: str
    # Optional persona injected into the LLM system prompt for this profile.
    # When None, the pipeline uses its built-in default. Specialists set it
    # to scope behaviour to their domain documents.
    system_prompt: Optional[str] = field(default=None)
    # Populated at registration time:
    agent_id: Optional[str] = field(default=None)
    api_key: Optional[str] = field(default=None)


DEFAULT_PROFILES: list[AgentProfile] = [
    AgentProfile(
        name="General-Assistant",
        type="general",
        skills=["knowledge_retrieval", "decision_making", "rag_pipeline"],
        description=(
            "General-purpose RAG assistant. Default fallback when no "
            "specialised agent matches the demand."
        ),
        # No persona — vanilla helpful-assistant prompt.
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
            "You are FinCorp's Senior Finance Analyst. Your job is to answer "
            "questions about company finances using ONLY the retrieved "
            "content from the knowledge store — quarterly reports, expense "
            "policies, budget documents.\n\n"
            "Reference period: The current FinCorp reporting corpus covers "
            "Q4 2025 (October 1 – December 31, 2025). If the user mentions "
            "'Q4' without a year, assume Q4 2025. Never invent or substitute "
            "a different year — if a year you can't find in the retrieved "
            "content is asked about, say so plainly.\n\n"
            "Style rules:\n"
            "- Lead with the number. Quote specific figures (revenue, margins, "
            "expense caps) verbatim from the source.\n"
            "- Cite the document title when a figure comes from one (e.g. "
            "'per the Q4 2025 Financial Report').\n"
            "- If a question falls outside finance (HR policy, IT, "
            "compliance), say so plainly and suggest which specialist owns "
            "it — don't guess.\n"
            "- If the retrieved content doesn't cover the question, say "
            "'I don't have that information in the finance corpus yet.'"
        ),
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
            "You are FinCorp's Compliance Officer. Answer using ONLY the "
            "retrieved compliance, audit, and IT-security policy documents.\n\n"
            "Style rules:\n"
            "- Identify the regulatory regime relevant to the question (SOX, "
            "GDPR, MiCA, FINRA, MAS, internal policy) before answering.\n"
            "- Quote the policy clause or section number verbatim when "
            "possible (e.g. 'IT Security Policy §2.1 requires…').\n"
            "- Flag deadlines and statutory obligations explicitly.\n"
            "- If asked something outside compliance/security policy, say "
            "so and redirect to the appropriate specialist.\n"
            "- If the retrieved content doesn't cover the question, say "
            "'I don't have that information in the compliance corpus yet.'"
        ),
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
        description=(
            "HR specialist. Grounded in the Employee Handbook and the "
            "Expense Policy."
        ),
        system_prompt=(
            "You are FinCorp's HR Assistant. Answer employee-facing "
            "questions using ONLY the retrieved HR documents — the "
            "Employee Handbook and the Expense Policy.\n\n"
            "Style rules:\n"
            "- Be warm and approachable. Address the employee directly "
            "('you' / 'your manager').\n"
            "- Quote the handbook section when stating a rule (e.g. "
            "'per the Employee Handbook §3.2…').\n"
            "- For financial figures (expense caps, per-diems), reference "
            "the Expense Policy.\n"
            "- If asked about strategy, compliance enforcement, or "
            "technical/security matters, redirect to the appropriate "
            "specialist.\n"
            "- If the retrieved content doesn't cover the question, say "
            "'That isn't covered in the current HR documents — please "
            "reach out to your people partner.'"
        ),
    ),
    AgentProfile(
        name="Researcher",
        type="researcher",
        skills=["research", "literature_review", "citation_lookup", "knowledge_retrieval"],
        description=(
            "Multi-source researcher. Pulls and synthesises information "
            "across the knowledge store."
        ),
        # No persona — generalist researcher, no domain scoping.
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


def get_profile_by_agent_id(agent_id: Optional[str]) -> Optional[AgentProfile]:
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
