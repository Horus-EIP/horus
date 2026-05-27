"""Task decomposition and agent selection — the planning layer.

Calls the LLM via :mod:`tasks.prompts` to either route a single query to a
suitable agent (``select_agent_for_task``) or break a complex request into a
dependency-ordered list of sub-tasks (``decompose_task``). Also exposes the
synthesis helper (``aggregate_results``) that consolidates sub-task output.
"""

import json
from graphlib import TopologicalSorter

from sqlalchemy.orm import Session

from agents.registry_tool_functions import (
    _is_agent_recently_alive,
    get_agent_by_type,
    get_agent_id,
    get_available_agents,
)
from core.llm_setup import ask_llm
from core.logger import get_logger
from core.rabbitmq_tool import rabbitmq_instance
from db.database import SessionLocal
from db.models import Agents
from tasks.collaborative_task import CollaborativeTask
from tasks.demo_log import pretty_log
from tasks.prompts import (
    clean_json_output,
    get_decomposition_prompt,
    get_prompt,
    get_prompt_final_answer_generation,
)

logger = get_logger("task_tool_functions")


def build_action_list(actions_dict, agents_available, db: Session = None):
    """Resolve agent names to IDs and return ``(agent_id, input)`` tuples.

    Raises ``ValueError`` on empty/unknown agent names or empty inputs.
    Also ensures a RabbitMQ queue exists for each agent.
    """
    action_list = []

    if db is None:
        db = SessionLocal()

    for dict in actions_dict:
        agent_id = ""
        question = ""
        for key, value in dict.items():

            if key == "agent":
                if value == "":
                    raise ValueError(
                        f"Agent name to attribute agent tasks must not be empty"
                    )
                agent_id = get_agent_id(value, db)
                if agent_id is None:
                    raise ValueError(
                        f"Agent mentionned by orchestrator doesn't exists: {value}"
                    )

            elif key == "input":
                if value == "":
                    raise ValueError(f"Input for the agents task must not be empty")
                question = value

        action_list.append((agent_id, question))

        rabbitmq_instance.create_queue(agent_id)
    return action_list


def sort_subtasks_by_dependency(subtask_entity):
    """Return sub-tasks topologically sorted by their ``depends_on`` graph."""
    task_map = {t.id: t for t in subtask_entity}
    dependency_graph = {}

    for element in subtask_entity:
        dependency_graph.setdefault(element.id, set())
        for dependance_id in element.depends_on:
            dependency_graph[element.id].add(dependance_id)

    result = TopologicalSorter(dependency_graph)

    sorted_ids = list(result.static_order())

    return [task_map[tid] for tid in sorted_ids if tid in task_map]


def build_subtask_list(subtask_entity, agents_available, db: Session = None):
    """Convert a decomposition into an ordered execution list.

    Sorts by dependency, resolves each ``agent_type`` to a concrete agent ID,
    and ensures its RabbitMQ queue exists. Raises ``ValueError`` on empty or
    unresolvable fields.
    """
    action_list = []

    if db is None:
        db = SessionLocal()

    try:
        sorted_subtasks = sort_subtasks_by_dependency(subtask_entity.sub_tasks)
    except Exception as e:
        logger.error(f"Cycle detected or sorting error: {e}")
        sorted_subtasks = subtask_entity.sub_tasks

    for element in sorted_subtasks:
        agent_id = ""
        question = ""

        if element.agent_type == "":
            raise ValueError(f"Agent type to attribute agent tasks must not be empty")

        logger.info("Building subtask", agent_type=element.agent_type)
        agent_id = get_agent_by_type(element.agent_type, db)

        if agent_id is None:
            logger.error(
                "Agent type yielded None from registry", agent_type=element.agent_type
            )
            raise ValueError(
                f"Agent type '{element.agent_type}' not found or no agents available."
            )

        if element.description == "":
            raise ValueError(f"Input for the agents task must not be empty")

        question = element.description

        action_list.append((agent_id, question))

        rabbitmq_instance.create_queue(agent_id)

    return action_list


def _heuristic_decompose(user_input: str, db: Session) -> tuple:
    """Skill-embedding fallback when the LLM planner produces no usable plan.

    Uses the in-memory ``skill_cache`` (MiniLM cosine similarity over every
    registered agent's skills) to pick the top 2-4 unique specialists for the
    demand, then builds a deterministic sequential chain — one subtask per
    agent. Each subtask asks that agent to address the demand from their
    domain angle; the chain transcript machinery from Gap 2 then makes sure
    later agents see earlier outputs.

    Two-pass agent selection so seeded-but-not-yet-heartbeated specialists
    are still usable for demos:

    1. Pass A — prefer agents with ``status='active'`` (worker has heartbeated
       recently). Real production routing.
    2. Pass B — if Pass A finds < 2 specialists, fall back to any non-Manager
       agent in the directory. The RabbitMQ queues are type-keyed; a worker
       running on that type's queue will pick the work up regardless of
       whether MAS's heartbeat clock has caught up.

    Returns ``(first_action, actions_list)`` in the same shape as
    ``decompose_task``. Returns ``(None, [])`` only if the skill cache is
    cold or the directory has zero non-Manager rows.
    """
    from db.models import Agents
    from core.skill_cache import rank_skills

    try:
        # Wider net + lower floor than before so under-resourced demos
        # (fewer agents seeded, looser embeddings) still produce a plan.
        ranked = rank_skills(user_input, top_k=12, min_score=0.05)
    except Exception as exc:
        logger.warning("Heuristic decomposition: skill cache rank failed: %s", exc)
        ranked = []

    def _build(active_only: bool) -> list[dict]:
        seen: set = set()
        out: list[dict] = []
        for r in ranked:
            agent_id = r.get("agent_id")
            if not agent_id or agent_id in seen:
                continue
            agent_row = db.query(Agents).filter(Agents.id == agent_id).first()
            if agent_row is None:
                continue
            if agent_row.name == "Manager":
                continue
            if active_only and (agent_row.status or "").lower() != "active":
                continue
            seen.add(agent_id)
            out.append(
                {
                    "agent_id": agent_id,
                    "agent_name": agent_row.name,
                    "agent_type": (
                        agent_row.type.value if agent_row.type else "general"
                    ),
                    "skill": r.get("skill", ""),
                    "score": r.get("score", 0.0),
                }
            )
            if len(out) >= 4:
                break
        return out

    chosen = _build(active_only=True)
    if len(chosen) < 2:
        logger.info(
            "Heuristic decomposition: only %d active specialist(s) match; "
            "widening to all directory rows.",
            len(chosen),
        )
        chosen = _build(active_only=False)

    if len(chosen) < 2:
        # Last-ditch effort: ignore the skill ranker entirely and pick the
        # first two non-Manager agents from the directory. Better than
        # giving the user a flat 'no plan' error — even an under-matched
        # chain demonstrates orchestration.
        any_agents = (
            db.query(Agents)
            .filter(Agents.name != "Manager")
            .order_by(Agents.last_heartbeat.desc())
            .limit(4)
            .all()
        )
        chosen = [
            {
                "agent_id": a.id,
                "agent_name": a.name,
                "agent_type": a.type.value if a.type else "general",
                "skill": (a.skills[0] if a.skills else "knowledge_retrieval"),
                "score": 0.0,
            }
            for a in any_agents
        ]
        if len(chosen) < 2:
            logger.warning(
                "Heuristic decomposition: directory has only %d non-Manager agent(s); "
                "cannot build a multi-agent chain.",
                len(chosen),
            )
            return None, []

    action_list: list[tuple[str, str]] = []
    for step in chosen:
        skill_label = (step.get("skill") or "knowledge retrieval").replace("_", " ")
        sub_demand = (
            f"Focus on the {skill_label} aspects of this request: "
            f"{user_input}"
        )
        action_list.append((step["agent_id"], sub_demand))

    pretty_log(
        f"HEURISTIC PLAN: {len(action_list)} step(s) — "
        + " → ".join(c["agent_name"] for c in chosen),
        "🧮",
    )

    first_action = action_list[0]
    actions_list = action_list[1:]
    return first_action, actions_list


def decompose_task(user_input: str, db: Session = None):
    pretty_log(f"INITIATING TASK DECOMPOSITION FOR: '{user_input}'", "🔨")

    if db is None:
        db = SessionLocal()

    available_agents = get_available_agents(db)

    if not available_agents:
        pretty_log("NO AGENTS AVAILABLE FOR DECOMPOSITION", "❌")
        return None, []

    pretty_log("GENERATING DECOMPOSITION PLAN WITH LLM...", "🧠")
    prompt = get_decomposition_prompt(user_input, available_agents)
    output = ask_llm(prompt, max_new_tokens=2048)
    logger.debug(f"LLM decomposition raw output: {output}")

    output = clean_json_output(output)

    try:
        json_output = json.loads(output)
        if not json_output.get("sub_tasks"):
            pretty_log("NO SUB-TASKS GENERATED — TRYING HEURISTIC FALLBACK", "⚠️")
            return _heuristic_decompose(user_input, db)

        pretty_log(f"GENERATED {len(json_output['sub_tasks'])} SUB-TASKS", "📋")
        # Be lenient about the ``status`` field — the 1.5B planner often omits
        # it or types it wrong. Default to "pending" so an otherwise-valid plan
        # isn't thrown away over a missing key.
        for st in json_output["sub_tasks"]:
            if isinstance(st, dict) and "status" not in st:
                st["status"] = "pending"
            elif isinstance(st, dict) and st.get("status") != "pending":
                st["status"] = "pending"
            if isinstance(st, dict) and "depends_on" not in st:
                st["depends_on"] = []
        for st in json_output["sub_tasks"]:
            pretty_log(
                f"  [{st['id']}] {st['agent_type'].upper()}: {st['description']}", "🔹"
            )

        entity = CollaborativeTask(**json_output)

        actions_list = build_subtask_list(entity, available_agents, db)

        if actions_list:
            first_action = actions_list[0]
            pretty_log(f"STARTING FIRST ACTION WITH AGENT ID: {first_action[0]}", "🚀")
            actions_list.pop(0)
            return first_action, actions_list
        else:
            pretty_log("PLANNER MAPPED TO NO ACTIONS — TRYING HEURISTIC FALLBACK", "⚠️")
            return _heuristic_decompose(user_input, db)

    except json.JSONDecodeError:
        logger.error(f"Failed to decode LLM decomposition output: {output}")
        pretty_log("FAILED TO PARSE PLAN JSON — TRYING HEURISTIC FALLBACK", "❌")
        return _heuristic_decompose(user_input, db)
    except Exception as e:
        logger.error(f"Validation error in task decomposition: {e}")
        pretty_log(f"VALIDATION ERROR: {e} — TRYING HEURISTIC FALLBACK", "❌")
        return _heuristic_decompose(user_input, db)


def get_manager_agent(db: Session):
    """Return the seeded ``Manager`` agent row, or ``None`` if missing.

    Used by chat broadcasts so the Manager's plan announcement and per-step
    review decisions are attributed to a real ``Agents`` row in the UI.
    """
    from db.models import Agents

    return (
        db.query(Agents)
        .filter(Agents.name == "Manager")
        .first()
    )


def _planned_steps_from_actions(action_list: list, db: Session) -> list[dict]:
    """Re-derive a ``[{agent_type, description}]`` view from the planner's action list.

    The planner internally returns ``[(agent_id, demand), ...]`` after mapping
    agent types to concrete IDs in ``build_subtask_list``. For the Manager's
    announcement prompt we need the human-readable type, so we look each agent
    up in the directory once.
    """
    from db.models import Agents

    out: list[dict] = []
    if not action_list:
        return out
    agent_ids = list({a[0] for a in action_list if a and a[0]})
    rows = db.query(Agents).filter(Agents.id.in_(agent_ids)).all() if agent_ids else []
    by_id = {r.id: r for r in rows}
    for agent_id, demand in action_list:
        row = by_id.get(agent_id)
        out.append(
            {
                "agent_type": (
                    row.type.value if (row and row.type) else "general"
                ),
                "agent_name": row.name if row else "?",
                "description": demand,
            }
        )
    return out


def manager_announce_plan(
    user_demand: str, action_list: list, db: Session
) -> str:
    """Ask the Manager LLM to draft the chat message that announces a plan.

    Returns plain text (no JSON, no code fences) — the message is fanned out
    to chat clients as an attributed Manager turn before the first specialist
    starts. Failures are non-fatal: returns a deterministic fallback string so
    the user always sees *something* from the Manager.
    """
    from tasks.prompts import get_manager_announcement_prompt

    steps = _planned_steps_from_actions(action_list, db)
    if not steps:
        return "I'm dispatching this work to a specialist now."

    try:
        prompt = get_manager_announcement_prompt(user_demand, steps)
        text = ask_llm(prompt, max_new_tokens=256).strip()
        # Strip markdown/code fences a small model sometimes adds despite
        # being told plain text.
        for fence in ("```text", "```markdown", "```"):
            if text.startswith(fence):
                text = text[len(fence):].lstrip()
            if text.endswith("```"):
                text = text[:-3].rstrip()
        if not text:
            raise ValueError("empty LLM response")
        return text
    except Exception as exc:
        logger.warning("Manager announcement LLM call failed: %s", exc)
        # Deterministic fallback that still demonstrates orchestration.
        listing = "; ".join(
            f"{s['agent_name']} ({s['description'][:80]})" for s in steps[:4]
        )
        return (
            f"I'll handle this in {len(steps)} step(s). Dispatching: {listing}."
        )


def manager_review_step(
    user_demand: str,
    transcript: str,
    remaining_actions: list,
    available_agent_types: list[str],
    db: Session,
) -> dict:
    """Ask the Manager LLM what to do after a subtask completes.

    Returns a dict with ``decision`` ∈ {``CONTINUE``, ``INSERT``, ``DONE``}.
    For ``INSERT`` decisions, ``next_agent_type`` and ``next_action`` are
    populated and the caller should resolve ``next_agent_type`` to an agent ID
    and prepend the new action to the chain. Failure (LLM parse error, etc.)
    returns ``{"decision": "CONTINUE"}`` so the existing pipeline keeps moving.
    """
    from tasks.prompts import get_manager_review_prompt

    remaining_view = _planned_steps_from_actions(remaining_actions, db)
    try:
        prompt = get_manager_review_prompt(
            user_demand=user_demand,
            transcript=transcript,
            remaining_steps=remaining_view,
            available_agent_types=available_agent_types,
        )
        raw = ask_llm(prompt, max_new_tokens=384)
        cleaned = clean_json_output(raw)
        parsed = json.loads(cleaned)
    except Exception as exc:
        logger.warning("Manager review LLM call failed: %s — defaulting to CONTINUE", exc)
        return {"decision": "CONTINUE"}

    decision = (parsed.get("decision") or "CONTINUE").upper()
    if decision not in ("CONTINUE", "INSERT", "DONE"):
        decision = "CONTINUE"
    return {
        "decision": decision,
        "next_agent_type": (parsed.get("next_agent_type") or "").lower() or None,
        "next_action": parsed.get("next_action") or None,
        "reasoning": parsed.get("reasoning") or "",
    }


def select_agent_for_task(user_input: str, db: Session = None):
    """Route a user query to the right agent via the LLM intent router.

    Returns ``(first_agent_id, action_text, direct_response, remaining_actions)``.

    Three router classifications drive the return shape:

    - ``SINGLE_AGENT`` → ``(agent_id, rewritten_input, None, [])`` — caller
      dispatches to that one agent.
    - ``DIRECT_ANSWER`` → ``(None, None, "Response for user : ...", [])`` —
      caller returns the orchestrator's answer immediately.
    - ``COMPLEX_TASK`` → runs the planner inline and returns
      ``(first_agent_id, first_demand, None, remaining_actions)`` so the
      existing single-agent dispatch + subtask-chaining path handles it.
      Multi-agent collaboration fires automatically here without the caller
      needing to know whether the request was single- or multi-agent.

    All-None ``(None, None, None, [])`` means the router couldn't decide
    (JSON parse failure, unknown classification, or the planner produced no
    plan) and the caller should fall back to its skill-match / catch-all paths.
    """
    pretty_log(f"ANALYZING USER INPUT: '{user_input}'", "🔍")

    if db is None:
        db = SessionLocal()

    available_agents = get_available_agents(db)
    logger.debug(
        "Available agents count: %d", len(available_agents) if available_agents else 0
    )

    if not available_agents:
        pretty_log("NO AGENTS AVAILABLE", "❌")
        return None, None, None, []

    pretty_log(f"FOUND {len(available_agents)} ACTIVE AGENTS", "🤖")

    pretty_log("ROUTING TASK TO INTELLIGENT PLANNER...", "🧠")

    prompt = get_prompt(user_input, available_agents)
    logger.info("Calling ask_llm from select_agent_for_task...")
    output = ask_llm(prompt, max_new_tokens=1024)
    logger.info(f"Received LLM output (length: {len(output)}): {output[:100]}...")

    output = clean_json_output(output)

    logger.info(f"Raw LLM output in select_agent_for_task: '{output}'")

    try:
        json_output = json.loads(output)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from LLM: {e}. Output was: '{output}'")
        pretty_log(
            "SELECTOR FAILED TO PARSE JSON - FALLING BACK TO DECOMPOSITION", "⚠️"
        )
        return None, None, None, []

    classification = json_output.get("classification", "UNKNOWN")
    pretty_log(f"ROUTER CLASSIFICATION: {classification.upper()}", "🎯")

    if classification == "COMPLEX_TASK":
        # Multi-agent collaboration is the headline feature of this platform —
        # when the router flags a request as COMPLEX_TASK, hand it straight to
        # the planner here so the caller doesn't fall back to single-agent
        # paths (skill-match, auto-create-specialist, catch-all) that would
        # capture the request before decomposition could ever fire. Returning
        # the planner's output through the existing 4-tuple lets the regular
        # subtask-chaining in routes.py + tasks-result/ kick in unchanged.
        logger.info("LLM requested DECOMPOSITION. Inlining planner.")
        pretty_log("COMPLEX TASK DETECTED -> RUNNING PLANNER INLINE", "🔨")
        try:
            first_action, actions_list = decompose_task(user_input, db)
        except Exception as exc:
            logger.exception("Inline decomposition raised: %s", exc)
            return None, None, None, []
        if first_action:
            first_agent, first_demand = first_action
            pretty_log(
                f"PLAN READY: {len(actions_list) + 1} subtask(s), first -> {first_agent}",
                "🗺️",
            )
            return first_agent, first_demand, None, actions_list
        # Planner produced no plan — fall through to the legacy all-None
        # return so the caller's downstream fallbacks (skill-match → auto-
        # create → catch-all) still get a chance to dispatch something.
        return None, None, None, []

    if classification == "DIRECT_ANSWER":
        pretty_log("RESPONDING DIRECTLY TO USER", "💬")
        return (
            None,
            None,
            f"Response for user : {json_output.get('final_answer', '')}",
            [],
        )

    if classification == "SINGLE_AGENT":
        agent_name = json_output.get("agent_name")
        rewritten_input = json_output.get("rewritten_input") or user_input

        if not agent_name:
            logger.error("SINGLE_AGENT classification but no agent_name provided.")
            return None, None, None, []

        agent_id = get_agent_id(agent_name, db)
        if not agent_id:
            logger.error(f"Agent '{agent_name}' not found.")
            return None, None, None, []

        pretty_log(f"SELECTED SINGLE AGENT: {agent_name}", "✅")
        return agent_id, rewritten_input, None, []

    logger.warning(
        f"Unknown classification '{classification}'. Falling back to decomposition."
    )
    return None, None, None, []


def select_agent_by_mode(
    demand: str,
    skills_required: list,
    mode: str | None,
    agent_id: str | None,
    db: Session,
):
    """Pick an agent according to the explicit dispatch mode.

    Returns the same 4-tuple shape as :func:`select_agent_for_task` so the
    route can fall through to the existing decomposition flow when the mode
    fails to resolve.

    Modes:
        - ``specific_agent``: ``agent_id`` is required and must match a row in
          the agents table. Returns it as-is so RabbitMQ can queue-on-busy
          when the worker is offline.
        - ``any_with_skill``: returns the first agent whose ``skills`` JSON
          contains ``skills_required[0]``. Live agents preferred; seeded
          (inactive) ones used as a fallback so the demo can dispatch even
          before a real worker has registered.
        - any other value (or ``auto``/``None``): returns ``(None, None, None, [])``
          and the caller should fall back to :func:`select_agent_for_task`.
    """
    if mode == "specific_agent":
        if not agent_id:
            logger.warning(
                "specific_agent mode requested but agent_id missing; falling back to auto."
            )
            return None, None, None, []
        agent = db.query(Agents).filter(Agents.id == agent_id).first()
        if not agent:
            logger.warning(
                f"specific_agent mode: agent_id={agent_id} not found; falling back to auto."
            )
            return None, None, None, []
        pretty_log(f"DISPATCH: SPECIFIC AGENT -> {agent.name} ({agent_id})", "🎯")
        return agent_id, demand, None, []

    if mode == "any_with_skill":
        if not skills_required:
            logger.warning(
                "any_with_skill mode requested but skills_required is empty; falling back to auto."
            )
            return None, None, None, []
        target_skill = skills_required[0]
        agents = db.query(Agents).all()
        # Live agents first; seeded (inactive) only if nothing else matches —
        # keeps the demo working even before a real worker container boots.
        live_match = None
        seeded_match = None
        for agent in agents:
            skills = agent.skills or []
            if target_skill not in skills:
                continue
            if _is_agent_recently_alive(agent):
                live_match = agent
                break
            if seeded_match is None:
                seeded_match = agent

        chosen = live_match or seeded_match
        if not chosen:
            logger.warning(
                f"any_with_skill mode: no agent advertises '{target_skill}'; falling back to auto."
            )
            return None, None, None, []
        pretty_log(
            f"DISPATCH: ANY_WITH_SKILL[{target_skill}] -> {chosen.name} ({chosen.id})",
            "🎯",
        )
        return chosen.id, demand, None, []

    # auto / None / unknown → caller falls back to LLM router
    return None, None, None, []


def aggregate_results(history, result):
    """Synthesize a final user-facing answer from sub-task history + output."""
    prompt = get_prompt_final_answer_generation(history, result)
    output = ask_llm(prompt, max_new_tokens=512)
    return output
