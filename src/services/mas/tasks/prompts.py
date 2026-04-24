"""LLM prompt templates used by the MAS task pipeline.

Three prompts live here:

- ``get_prompt_final_answer_generation`` — synthesis prompt that turns
  accumulated sub-task history into a single user-facing answer.
- ``get_prompt`` — intent router that classifies a user query as
  ``DIRECT_ANSWER`` / ``SINGLE_AGENT`` / ``COMPLEX_TASK``.
- ``get_decomposition_prompt`` — planner prompt that breaks a complex
  request into a dependency graph of sub-tasks.

``clean_json_output`` lives here because every prompt in this module
returns JSON that needs the same markdown-fence strip.
"""


def get_prompt_final_answer_generation(history, final_result):
    """Build the synthesis prompt used to consolidate sub-task outputs."""
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
    """Build the intent-router prompt (DIRECT_ANSWER/SINGLE_AGENT/COMPLEX_TASK)."""
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
    """Build the planner prompt that decomposes a request into dependent sub-tasks."""
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


def clean_json_output(json_input: str) -> str:
    """Strip markdown code fences (``` or ```json) from an LLM response."""
    output = json_input.strip()
    if output.startswith("```"):
        if output.startswith("```json"):
            output = output[7:]
        else:
            output = output[3:]

        if output.endswith("```"):
            output = output[:-3]

        output = output.strip()
    return output
