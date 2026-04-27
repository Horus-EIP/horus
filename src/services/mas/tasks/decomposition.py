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
            pretty_log("NO SUB-TASKS GENERATED", "⚠️")
            return None, []

        pretty_log(f"GENERATED {len(json_output['sub_tasks'])} SUB-TASKS", "📋")
        for st in json_output["sub_tasks"]:
            pretty_log(
                f"  [{st['id']}] {st['agent_type'].upper()}: {st['description']}", "🔹"
            )

        entity = CollaborativeTask(**json_output)

        for element in json_output["sub_tasks"]:
            if element["status"] != "pending":
                logger.error(f"Failed to decode LLM decomposition output: {output}")
                return None, []

        actions_list = build_subtask_list(entity, available_agents, db)

        if actions_list:
            first_action = actions_list[0]
            pretty_log(f"STARTING FIRST ACTION WITH AGENT ID: {first_action[0]}", "🚀")
            actions_list.pop(0)
            return first_action, actions_list
        else:
            return None, []

    except json.JSONDecodeError:
        logger.error(f"Failed to decode LLM decomposition output: {output}")
        pretty_log("FAILED TO PARSE PLAN JSON", "❌")
        return None, []
    except Exception as e:
        logger.error(f"Validation error in task decomposition: {e}")
        pretty_log(f"VALIDATION ERROR: {e}", "❌")
        return None, []


def select_agent_for_task(user_input: str, db: Session = None):
    """Route a user query to the right agent via the LLM intent router.

    Returns ``(first_agent_id, action_text, direct_response, remaining_actions)``.
    Only one of ``first_agent_id`` or ``direct_response`` is set; all-None means
    the caller should fall back to ``decompose_task``.
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
        logger.info("LLM requested DECOMPOSITION. Returning control to pipeline.")
        pretty_log("COMPLEX TASK DETECTED -> DELEGATING TO PLANNER", "🔨")
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
