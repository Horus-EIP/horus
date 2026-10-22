"""In-memory cache of agent-skill embeddings for fast similarity ranking.

The cache stores one embedding per ``(agent_id, skill)`` pair built from a
short context string (agent name + skill + agent description). Ranking a
query against the cache is a single dot product against all rows.

Lifecycle:
- Warmed by ``warm_skill_cache()`` at service startup (from the embedder
  preload thread, so it never blocks the event loop).
- Mutated by ``upsert_agent()`` and ``evict_agent()`` from the agent
  registration / deletion paths.
- Read by ``rank_skills(demand, top_k)`` from the ``/tasks/suggest-skills``
  route. Returns a deduplicated list of ``(skill, score, agent_id, agent_name)``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from core.embedding_setup import embed_text, embed_texts
from core.logger import get_logger
from db.database import SessionLocal
from db.models import Agents

logger = get_logger("skill_cache")


@dataclass
class _SkillRow:
    agent_id: str
    agent_name: str
    skill: str
    vector: np.ndarray  # shape (D,), L2-normalised


_rows: list[_SkillRow] = []
_lock = threading.Lock()


def _agent_skill_text(agent_name: str, skill: str, description: str) -> str:
    """Build the short context string that gets embedded for ranking.

    Format: "<skill> — used by agent <name>: <description>". Putting the
    skill first means demands phrased like the skill name ("summarize this")
    score highly without depending on the description quality.
    """
    desc = (description or "").strip()
    base = f"{skill.replace('_', ' ')} — used by agent {agent_name}"
    if desc:
        base += f": {desc}"
    return base


def _build_rows_for_agent(
    agent_id: str, agent_name: str, skills: list[str], description: str
) -> list[_SkillRow]:
    if not skills:
        return []
    texts = [_agent_skill_text(agent_name, s, description) for s in skills]
    vecs = embed_texts(texts)
    return [
        _SkillRow(agent_id=agent_id, agent_name=agent_name, skill=s, vector=v)
        for s, v in zip(skills, vecs, strict=False)
    ]


def warm_skill_cache() -> None:
    """Load every active agent's skills from the DB and embed them in-place."""
    global _rows
    db = SessionLocal()
    try:
        agents = db.query(Agents).all()
    finally:
        db.close()

    new_rows: list[_SkillRow] = []
    for a in agents:
        skills = list(a.skills or [])
        new_rows.extend(_build_rows_for_agent(a.id, a.name, skills, a.description or ""))

    with _lock:
        _rows = new_rows
    logger.info(
        "Skill-cache warm: %d agents, %d (agent,skill) rows",
        len(agents),
        len(new_rows),
    )


def upsert_agent(agent_id: str, agent_name: str, skills: list[str], description: str) -> None:
    """Replace all rows for ``agent_id`` with freshly-embedded rows."""
    new_rows = _build_rows_for_agent(agent_id, agent_name, skills, description or "")
    with _lock:
        kept = [r for r in _rows if r.agent_id != agent_id]
        kept.extend(new_rows)
        _rows[:] = kept
    logger.info(
        "Skill-cache upsert: agent=%s name=%s skills=%d",
        agent_id,
        agent_name,
        len(new_rows),
    )


def evict_agent(agent_id: str) -> None:
    with _lock:
        before = len(_rows)
        _rows[:] = [r for r in _rows if r.agent_id != agent_id]
        removed = before - len(_rows)
    if removed:
        logger.info("Skill-cache evict: agent=%s removed=%d rows", agent_id, removed)


def rank_skills(demand: str, top_k: int = 3, min_score: float = 0.25) -> list[dict]:
    """Return the top-N matching skills for ``demand``, dedup'd by skill name.

    Each result: ``{"skill": str, "score": float, "agent_id": str, "agent_name": str}``.
    ``score`` is cosine similarity in ``[-1, 1]``; rows below ``min_score`` are dropped.
    """
    if not demand or not demand.strip():
        return []
    with _lock:
        if not _rows:
            return []
        matrix = np.stack([r.vector for r in _rows])
        snapshot = list(_rows)

    q = embed_text(demand)
    scores = matrix @ q  # cosine since both sides are L2-normalised

    order = np.argsort(-scores)
    seen: set[str] = set()
    out: list[dict] = []
    for idx in order:
        s = float(scores[idx])
        if s < min_score:
            break
        row = snapshot[int(idx)]
        if row.skill in seen:
            continue
        seen.add(row.skill)
        out.append(
            {
                "skill": row.skill,
                "score": s,
                "agent_id": row.agent_id,
                "agent_name": row.agent_name,
            }
        )
        if len(out) >= top_k:
            break
    return out
