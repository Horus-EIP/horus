import json
from graphlib import TopologicalSorter
from uuid import uuid4

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from agents.registry_tool_functions import (get_agent_by_type, get_agent_id,
                                            get_available_agents)
from core.llm_setup import ask_llm
from core.logger import get_logger
from core.rabbitmq_tool import rabbitmq_instance
from db.database import SessionLocal, get_db
from db.models import Task, TaskResult
from tasks.collaborative_task import CollaborativeTask
from tasks.status import TaskStatus

logger = get_logger("task_tool_functions")


def pretty_log(msg: str, icon: str = "ℹ️"):
    """Logs a message designed to be visible and clean for demo videos."""
    border = "=" * 60
    print(f"\n{border}\n {icon}  {msg}\n{border}\n")
    logger.info(f"[DEMO-VISUAL] {icon} {msg}")


def get_prompt_final_answer_generation(history, final_result):
    """
    Constructs the prompt for the final answer synthesis.

    Generates a prompt that instructs the LLM to provide a consolidated
    response based on the original request and the aggregated results
    from all executed sub-tasks.

    Args:
        history (str): The original user request and conversation context.
        final_result (str): The cumulative output from all agent executions.

    Returns:
        list: A list of message dictionaries for the LLM chat completion.
    """
    messages = [
        {
            "role": "system",
            "content": "You are an expert synthesizer. Your goal is to provide a final, comprehensive answer to the user's original request, based on the results from the executed sub-tasks.",
        },
        {
            "role": "user",
            "content": f"""
    ORIGINAL USER REQUEST:
    {history}

    FINAL AGENT OUTPUT (Containing cumulative results):
    {final_result}

    INSTRUCTIONS:
    - Synthesize the final answer clearly and concisely.
    - If the final output contains JSON or raw data, format it into a readable text summary.
    - Address the original user request directly.
    - Do not mention internal agent steps unless relevant to the answer.
    """,
        },
    ]
    return messages


def get_prompt(user_input, suitable_agents):
    """
    Constructs the prompt for the LLM intent router.

    Generates a structured prompt that instructs the LLM to classify user requests
    as either needing a direct answer, a single agent, or complex decomposition.

    Args:
        user_input (str): The natural language query from the user
        suitable_agents (list): List of tuples (id, name, description) of available agents

    Returns:
        list: A list of message dictionaries (system/user role) for the LLM chat completion
    """
    response_format = """{
      "classification": "DIRECT_ANSWER" | "SINGLE_AGENT" | "COMPLEX_TASK",
      "agent_name": "<agent_name_if_SINGLE_AGENT>",
      "rewritten_input": "<optimized_input_if_SINGLE_AGENT>",
      "final_answer": "<answer_if_DIRECT_ANSWER>"
    }"""

    agents_block = "\n".join(
        f"- {name}: {desc} (Type: {agent_type})"
        for _, name, desc, agent_type in suitable_agents
    )
    schema_literal = response_format.replace("{", "{{").replace("}", "}}")

    messages = [
        {
            "role": "system",
            "content": "You are an expert intent router. Your goal is to CLASSIFY the user input. Read USER INPUT. Either: "
            " - Route to a SINGLE AGENT if one agent can handle it alone,"
            " - Mark as COMPLEX_TASK if it requires multiple steps, research, or coordination (this will trigger a separate planner),"
            " - Answer DIRECTLY if it is a greeting, small talk, or simple question not needing tools.",
        },
        {
            "role": "user",
            "content": f"""        AVAILABLE AGENTS (name: description):
    {agents_block}

    USER INPUT:
    {user_input}

    OUTPUT RULES (CRITICAL):
    - Return ONLY a valid JSON object matching exactly this schema:


    {schema_literal}


    - If one agent can handle the request: set "classification": "SINGLE_AGENT", fill "agent_name" and "rewritten_input".
    - If the task is complex/multi-step: set "classification": "COMPLEX_TASK".
    - If no agent is needed (e.g. "hi"): set "classification": "DIRECT_ANSWER", fill "final_answer".
    - No text outside the JSON. No code fences, no explanations.
        """,
        },
    ]

    return messages


def get_decomposition_prompt(user_input, suitable_agents):
    """
    Constructs the prompt for the LLM Task Planner.

    Generates a structured prompt that instructs the LLM to break down a complex
    user request into a sequence of smaller, dependent sub-tasks executable by
    specialized agent types.

    Args:
        user_input (str): The complex request from the user.
        suitable_agents (list): List of available agent types and their descriptions.

    Returns:
        list: A list of message dictionaries for the LLM chat completion.
    """
    response_format = """
    {
      "sub_tasks": [
        {
          "id": "1",
          "agent_type": "<AGENT_TYPE_FROM_LIST>",
          "description": "<CLEAR_instruction_based_on_user_input>",
          "depends_on": [],
          "status": "pending"
        },
        {
          "id": "2",
          "agent_type": "<AGENT_TYPE_FROM_LIST>",
          "description": "<CLEAR_instruction_dependent_on_step_1>",
          "depends_on": ["<ID_OF_TASK_THIS_DEPENDS_ON>"],
          "status": "pending"
        }
      ]
    }
    """

    agents_block = "\n".join(
        f"- Type: {str(agent_type).split('.')[-1].lower() if '.' in str(agent_type) else str(agent_type).lower()} (Name: {name}): {desc}"
        for _, name, desc, agent_type in suitable_agents
    )
    schema = response_format.replace("{", "{{").replace("}", "}}")

    messages = [
        {
            "role": "system",
            "content": "You are an expert Task Planner. Your goal is to decompose a complex user request into a series of dependent sub-tasks executable by specialized agents.",
        },
        {
            "role": "user",
            "content": f"""        AVAILABLE AGENT TYPES:
    {agents_block}

    USER INPUT:
    {user_input}

    OUTPUT RULES (CRITICAL):
    - Analyze the request and break it down into logical steps based ONLY on USER INPUT.
    - Each step must be assigned to the most appropriate agent type from the list above.
    - Define dependencies: if step B needs output from step A, add A's ID to B's "depends_on".
    - Return ONLY a valid JSON object matching exactly this schema template:


    {schema}


    - No text outside the JSON. No code fences, no explanations.
    - Ensure strict JSON syntax. All keys and string values must be double-quoted.
    - Use EXACTLY the field names from the schema (e.g., use "agent_type", NOT "agent").
    - Do NOT copy the example placeholders. Fill them with real steps derived from USER INPUT.
    - If the request cannot be decomposed or no suitable agent exists, return an empty "sub_tasks" list.
        """,
        },
    ]

    return messages


def build_action_list(actions_dict, agents_available, db: Session = None):
    """
    Validates and maps agent names to UUIDs for task execution.

    Takes a list of proposed actions from the LLM (using agent names),
    verifies the existence of each agent, creates necessary queues, and
    returns a list of (agent_id, input_text) tuples.

    Args:
        actions_dict (list): List of dicts [{"agent": name, "input": text}]
        agents_available (list): List of available agents (unused but kept for API consistency)
        db (Session): Database session (default: local session)

    Returns:
        list: List of tuples (agent_id, input_text)

    Raises:
        ValueError: If agent name is empty, agent doesn't exist, or input is empty.
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
    """
    Sorts a list of sub-tasks based on their dependency graph.

    Uses topological sorting to ensure that tasks are ordered such that
    all dependencies for a given task appear before the task itself.

    Args:
        subtask_entity (list[CollaborativeTask]): A list of CollaborativeTask objects.

    Returns:
        list[CollaborativeTask]: The sorted list of tasks.
    """
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
    """
    Converts a complex task decomposition into an actionable execution list.

    Sorts sub-tasks by dependency, resolves agent types to concrete agent IDs,
    validates inputs, and prepares the task queue environment.

    Args:
        subtask_entity (CollaborativeTask): Object containing list of sub-tasks
        agents_available (list): List of available agents (unused)
        db (Session, optional): Database session. Defaults to None (creates new one).

    Returns:
        list: Ordered list of (agent_id, input_description) tuples for execution.

    Raises:
        ValueError: If agent types are missing, unresolvable, or descriptions are empty.
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


def clean_json_output(json_input: str) -> str:
    """
    Cleans raw LLM response text, removing markdown code fences and whitespace.

    Specifically handles outputs wrapped in triple backticks (```json or ```).

    Args:
        json_input (str): Raw string output from the LLM

    Returns:
        str: Cleaned JSON string ready for parsing
    """
    output = json_input.strip()
    if output.startswith("```"):
        # Handle ```json case correctly
        if output.startswith("```json"):
            output = output[7:]
        else:
            output = output[3:]

        # Remove trailing backticks
        if output.endswith("```"):
            output = output[:-3]

        output = output.strip()
    return output


def decompose_task(user_input: str, db: Session = None):
    pretty_log(f"INITIATING TASK DECOMPOSITION FOR: '{user_input}'", "🔨")

    if db is None:
        from db.database import SessionLocal

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
    """
    Orchestrates the selection of an agent for a given user task.

    This function:
    1. Retrieves available agents
    2. Constructs a prompt for the LLM
    3. Queries the LLM to decide on an action (run_agents vs answer directly)
    4. Parsed the LLM response
    5. Returns the selected agent and action if applicable

    Args:
        user_input (str): The user's query or command
        db (Session, optional): Database session

    Returns:
        tuple: (first_agent_id, action_text, direct_response, remaining_actions)
               first_agent_id (str|None): ID of the first agent to execute
               action_text (str|None): Input for the first agent
               direct_response (str|None): Direct answer if no agent needed
               remaining_actions (list): List of subsequent actions
    """
    pretty_log(f"ANALYZING USER INPUT: '{user_input}'", "🔍")

    if db is None:
        from db.database import SessionLocal

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

    # Log raw output for debugging
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
        rewritten_input = (
            json_output.get("rewritten_input") or user_input
        )  # Fallback to original input

        if not agent_name:
            logger.error("SINGLE_AGENT classification but no agent_name provided.")
            return None, None, None, []

        agent_id = get_agent_id(agent_name, db)
        if not agent_id:
            logger.error(f"Agent '{agent_name}' not found.")
            return None, None, None, []

        pretty_log(f"SELECTED SINGLE AGENT: {agent_name}", "✅")
        # Return single agent, no remaining actions
        return agent_id, rewritten_input, None, []

    # Fallback
    logger.warning(
        f"Unknown classification '{classification}'. Falling back to decomposition."
    )
    return None, None, None, []


def insert_new_task(
    conversation_id: int,
    agent_id: str,
    query: str,
    history: list,
    future_actions: list,
    db: Session,
):
    pretty_log(f"SCHEDULING NEW TASK FOR AGENT {agent_id}", "📅")
    new_task_id = str(uuid4())
    task_result_id = str(uuid4())
    try:
        task = Task(
            id=new_task_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
            status=TaskStatus.RUNNING,
            query=query,
            parent_task_id=None,
            order=0,
        )
        db.add(task)
        db.commit()

        task_result = TaskResult(
            id=task_result_id,
            task_id=new_task_id,
            result_data=None,
            history=history,
            future_actions=future_actions,
        )
        db.add(task_result)
        db.commit()
        return new_task_id
    except Exception as e:
        db.rollback()
        logger.error(
            f"Failed to create agent task - Task ID: {new_task_id}, Error: {str(e)}"
        )
        return None


def validating_task_results(task_id: str, task_result: str, db: Session):
    pretty_log(f"VALIDATING RESULTS FOR TASK {task_id}", "📥")
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        current_task_result = task.result
        if not current_task_result:
            raise HTTPException(status_code=404, detail="TaskResult not found")
        history = current_task_result.history or []
        history.append({"role": "assistant", "message": task_result})
        task.status = TaskStatus.COMPLETED
        current_task_result.result_data = task_result
        current_task_result.history = history
        db.commit()
        pretty_log(f"TASK {task_id} COMPLETED SUCCESSFULLY. RESULT SAVED.", "✅")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(
            f"Failed to validate task results - Task ID: {task_id}, Error: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Error validating task results: {str(e)}"
        )


def interrupt_task(task_id: str, db: Session, reason: str | None = None):
    pretty_log(f"INTERRUPT SIGNAL RECEIVED FOR TASK {task_id}", "🛑")
    cancel_reason = reason or "User requested cancellation"
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status in [
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELED.value,
        ]:
            raise HTTPException(
                status_code=400, detail="Cannot interrupt a completed task"
            )
        task.status = TaskStatus.CANCELED
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to cancel task - Task ID: {task_id}, Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error Canceling task: {str(e)}")

    cancellation_message = json.dumps(
        {
            "type": "cancel",
            "task_id": task_id,
            "conversation_id": task.conversation_id,
            "reason": cancel_reason,
        }
    )
    rabbitmq_instance.publish(
        queue_name=task.agent_id, message=cancellation_message, priority_value=10
    )
    logger.info(f"Cancellation signal sent for task {task_id} to agent {task.agent_id}")
    return True


def _get_all_tasks_internal(db: Session, status_filter: TaskStatus = None):
    try:
        query = db.query(Task)
        if status_filter:
            query = query.filter(Task.status == status_filter)
        tasks = query.all()
        return tasks
    except Exception as e:
        logger.error(f"Failed to retrieve tasks - Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving tasks: {str(e)}")


def get_tasks_in_progress(db: Session):
    try:
        tasks_in_progress = _get_all_tasks_internal(
            db, status_filter=TaskStatus.RUNNING
        )
        return tasks_in_progress
    except Exception as e:
        logger.error(f"Failed to retrieve tasks in progress - Error: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error retrieving tasks in progress: {str(e)}"
        )


def aggregate_results(history, result):
    prompt = get_prompt_final_answer_generation(history, result)
    output = ask_llm(prompt, max_new_tokens=2048)
    return output
