"""Seed the agent directory with the demo lineup.

Five named agents — one per business function the demo references. They are
inserted with ``status="inactive"`` and a dummy bcrypt-hashed api_key so the
UI dropdowns and ``select_agent_for_task`` have something to point at on a
fresh boot, even before any worker container has registered. A real worker
container that registers under a different name (``HorusAgent``-derived,
per ``AGENT_TYPE``) will not collide with these rows.

The seed is idempotent: rows are matched by ``name``; existing entries are
left untouched so re-running ``init_db()`` is safe.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from bcrypt import gensalt, hashpw
from sqlalchemy.orm import Session

from core.logger import get_logger, log_db_operation, log_success
from db.models import Agents
from db.models.agent_types import AgentTypes

logger = get_logger("seed_agents")

DEFAULT_AGENTS: list[dict] = [
    {
        # Orchestrator agent. Lives only in MAS — no worker container runs as
        # Manager. The row exists so chain dispatch + cyclic review can be
        # attributed to a stable identity in the chat UI, and so the Manager
        # has skills / description users can see in the agent directory.
        "name": "Manager",
        "type": AgentTypes.MANAGER,
        "skills": [
            "orchestration",
            "planning",
            "task_decomposition",
            "review",
            "delegation",
        ],
        "description": (
            "Multi-agent orchestrator. Plans which specialists answer a "
            "user demand, dispatches them in order, reviews each result, and "
            "re-routes back to earlier specialists when an intermediate "
            "answer is incomplete. Runs server-side, not on a worker."
        ),
    },
    {
        "name": "General-Assistant",
        "type": AgentTypes.GENERAL,
        "skills": ["knowledge_retrieval", "decision_making", "rag_pipeline"],
        "description": "General-purpose RAG assistant. Default fallback when no specialised agent matches the demand.",
    },
    {
        "name": "Finance-Analyst",
        "type": AgentTypes.ANALYST,
        "skills": ["financial_analysis", "expense_review", "budget_summary", "knowledge_retrieval"],
        "description": "Financial analysis specialist. Reads quarterly reports, expense data, and budget figures.",
    },
    {
        "name": "Compliance-Officer",
        "type": AgentTypes.ANALYST,
        "skills": ["compliance_check", "policy_review", "audit", "knowledge_retrieval"],
        "description": "Policy and compliance reviewer. Checks documents against SOX, GDPR, and internal policies.",
    },
    {
        "name": "Document-Writer",
        "type": AgentTypes.WRITER,
        "skills": ["document_writing", "summarization", "report_drafting"],
        "description": "Drafts structured documents — memos, summaries, executive briefs.",
    },
    {
        "name": "Researcher",
        "type": AgentTypes.RESEARCHER,
        "skills": ["research", "literature_review", "citation_lookup", "knowledge_retrieval"],
        "description": "Multi-source researcher. Pulls and synthesises information across the knowledge store.",
    },
]


def seed_default_agents(db: Session) -> int:
    """Insert any missing default agents. Returns the number of rows added.

    Args:
        db: Active database session.

    Returns:
        Count of newly inserted agents.
    """
    log_db_operation("SEED", "agents", "Seeding default agent directory...")

    existing_names = {
        name for (name,) in db.query(Agents.name).all() if name
    }
    inserted = 0
    # Stagger heartbeat in the past so the UI's "stale" indicator visibly fires
    # — these are placeholders until a real worker registers and overrides them.
    stale_at = datetime.now(UTC) - timedelta(days=1)

    for entry in DEFAULT_AGENTS:
        if entry["name"] in existing_names:
            continue
        # Manager lives only in MAS (no worker process), so seed it active
        # with a fresh heartbeat. Every other seeded row is a placeholder
        # waiting for its real worker to register and override it.
        is_manager = entry["type"] == AgentTypes.MANAGER
        try:
            password_sha = hashlib.sha256(secrets.token_urlsafe(32).encode('utf-8')).hexdigest()
            salt = gensalt()
            agent = Agents(
                id=str(uuid.uuid4()),
                name=entry["name"],
                skills=entry["skills"],
                status="active" if is_manager else "inactive",
                description=entry["description"],
                last_heartbeat=datetime.now(UTC) if is_manager else stale_at,
                type=entry["type"],
                # Unguessable hash so the seeded row can't authenticate; a
                # registering worker will replace this entry via the existing
                # stale-cleanup path in the agent's register_agent() loop.
                api_key=hashpw(password_sha.encode('utf-8'), salt),
            )
            db.add(agent)
            inserted += 1
        except Exception as exc:
            db.rollback()
            logger.error(
                f"Failed to seed agent '{entry['name']}': {exc}", exc_info=True
            )
            continue

    if inserted:
        try:
            db.commit()
            log_success(
                "seed_agents",
                f"Seeded {inserted} default agent(s): "
                + ", ".join(
                    e["name"] for e in DEFAULT_AGENTS if e["name"] not in existing_names
                ),
            )
        except Exception as exc:
            db.rollback()
            logger.error(f"Failed to commit seeded agents: {exc}", exc_info=True)
            return 0
    else:
        logger.info("Default agents already present; skipping seed.")

    return inserted


def seed_manager_agent(db: Session) -> int:
    """Insert the server-side ``Manager`` agent if missing. Returns rows added.

    The five specialist agents register themselves from the worker container as
    real, heartbeating identities, so they are intentionally NOT seeded at
    startup. The Manager is the exception: it runs only inside MAS (no worker
    process), so without this seed the orchestrator identity never exists and
    ``_create_chain_root`` skips chain-root creation on every multi-agent task
    (the recurring "Manager agent not found in directory" warning). Idempotent —
    matched by name.
    """
    manager_entry = next(
        (e for e in DEFAULT_AGENTS if e["type"] == AgentTypes.MANAGER), None
    )
    if manager_entry is None:
        return 0
    if db.query(Agents.id).filter(Agents.name == manager_entry["name"]).first():
        return 0
    try:
        password_sha = hashlib.sha256(secrets.token_urlsafe(32).encode('utf-8')).hexdigest()
        salt = gensalt()
        db.add(
            Agents(
                id=str(uuid.uuid4()),
                name=manager_entry["name"],
                skills=manager_entry["skills"],
                status="active",
                description=manager_entry["description"],
                last_heartbeat=datetime.now(UTC),
                type=manager_entry["type"],
                api_key=hashpw(password_sha.encode('utf-8'), salt),
            )
        )
        db.commit()
        log_success("seed_agents", "Seeded server-side Manager agent")
        return 1
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to seed Manager agent: {exc}", exc_info=True)
        return 0
