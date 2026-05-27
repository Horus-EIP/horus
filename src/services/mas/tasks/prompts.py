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
            "content": (
                "You are an expert intent router for a MULTI-AGENT orchestration "
                "platform. Each agent in the list below owns a distinct domain "
                "(e.g. Finance-Analyst owns financial reports, Compliance-Officer "
                "owns regulatory and IT-security policy, HR-Assistant owns the "
                "Employee Handbook). The platform is designed for agents to "
                "COLLABORATE on cross-domain requests, not for one agent to do "
                "everything. Default to COMPLEX_TASK whenever the request "
                "touches more than ONE agent's domain.\n\n"
                "Classify the USER INPUT as exactly one of:\n"
                " - DIRECT_ANSWER: only for greetings, small talk, arithmetic, "
                "or trivial questions that need no document retrieval.\n"
                " - SINGLE_AGENT: the request falls cleanly inside ONE agent's "
                "domain (e.g. 'what was Q4 revenue?' → Finance-Analyst alone).\n"
                " - COMPLEX_TASK: the request needs information or analysis from "
                "TWO OR MORE agents' domains (e.g. 'review Q4 financials AND IT "
                "security policy', 'how do the new compliance rules affect HR "
                "policy AND finance reporting?'). A separate planner will then "
                "decompose it into per-agent subtasks. PREFER this when "
                "uncertain — it's better to over-decompose than to have one "
                "agent guess outside its scope."
            ),
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


    - If one agent can handle the request entirely: set "classification": "SINGLE_AGENT", fill "agent_name" and "rewritten_input".
    - If the request touches 2+ agents' domains, or needs multiple distinct retrievals (finance + compliance, finance + HR, IT security + finance, etc.): set "classification": "COMPLEX_TASK".
    - If no agent is needed (e.g. "hi", "what's 2+2"): set "classification": "DIRECT_ANSWER", fill "final_answer".
    - When the request mentions multiple document types ("financial report AND policy", "report AND handbook"), it is ALWAYS COMPLEX_TASK.
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


def get_manager_announcement_prompt(user_demand: str, planned_steps: list[dict]) -> list[dict]:
    """Build the prompt that turns a decomposition plan into a Manager chat message.

    The plan is a list of ``{agent_type, description}`` entries returned by the
    planner. The Manager LLM writes a 2-4 sentence friendly summary the user
    sees in chat BEFORE any specialist starts — sets expectations and makes
    the orchestration visible.
    """
    steps_block = "\n".join(
        f"  {i + 1}. {s.get('agent_type', '?')}: {s.get('description', '')}"
        for i, s in enumerate(planned_steps)
    )
    return [
        {
            "role": "system",
            "content": (
                "You are the Manager — the orchestrator of a multi-agent platform. "
                "Specialists answer the user; your job is to plan their order, "
                "set expectations, and route the work. Write in first person as "
                "'I'. Be concise (2-4 sentences). Address the user directly. "
                "Don't list every step verbatim — summarise the plan in plain "
                "language. Don't promise outcomes; describe the approach."
            ),
        },
        {
            "role": "user",
            "content": (
                f"USER DEMAND:\n{user_demand}\n\n"
                f"PLANNED STEPS:\n{steps_block}\n\n"
                "Write the chat message you'd send to the user announcing how "
                "you'll handle this. Plain text, no JSON, no code fences."
            ),
        },
    ]


def get_manager_review_prompt(
    user_demand: str,
    transcript: str,
    remaining_steps: list[dict],
    available_agent_types: list[str],
) -> list[dict]:
    """Build the prompt that decides what happens after each subtask completes.

    The Manager LLM looks at: the user's original demand, the chain transcript
    so far, the remaining planned steps, and which agent types are available.
    It returns a structured decision:

    - ``CONTINUE``: the chain is on track; dispatch the next planned step as-is.
    - ``INSERT``: an earlier specialist needs to be invoked again before the
      next planned step (cyclic re-routing — Agent 4 asked "I need more
      research", Manager re-dispatches Researcher).
    - ``DONE``: the chain has fully answered the user; skip remaining planned
      steps and return the aggregated result.

    Returns a list of OpenAI-style chat messages ready for ``ask_llm``.
    """
    types_block = ", ".join(available_agent_types) if available_agent_types else "general"
    remaining_block = (
        "\n".join(
            f"  - {s.get('agent_type', '?')}: {s.get('description', '')}"
            for s in remaining_steps
        )
        if remaining_steps
        else "  (none — this was the last planned step)"
    )
    schema = (
        '{"decision": "CONTINUE" | "INSERT" | "DONE",'
        ' "next_agent_type": "<agent_type if INSERT>",'
        ' "next_action": "<the new subtask demand if INSERT>",'
        ' "reasoning": "<one short sentence>"}'
    )
    schema_literal = schema.replace("{", "{{").replace("}", "}}")
    return [
        {
            "role": "system",
            "content": (
                "You are the Manager reviewing a chain of specialist outputs. "
                "Decide whether the chain has answered the user's demand, "
                "should continue to the next planned step, or needs an extra "
                "step BEFORE the next planned one (cyclic re-routing). Be "
                "conservative — prefer CONTINUE unless an explicit gap exists."
            ),
        },
        {
            "role": "user",
            "content": (
                f"USER DEMAND:\n{user_demand}\n\n"
                f"CHAIN TRANSCRIPT SO FAR:\n{transcript}\n\n"
                f"REMAINING PLANNED STEPS:\n{remaining_block}\n\n"
                f"AVAILABLE AGENT TYPES (for INSERT): {types_block}\n\n"
                "DECISION RULES:\n"
                " - DONE: the transcript already answers the user's demand. "
                "Skip remaining steps.\n"
                " - INSERT: a prior specialist explicitly flagged a gap "
                "(e.g. 'I'd need more research on X'), or the next planned "
                "step would fail without info that's missing. Set "
                "next_agent_type and next_action.\n"
                " - CONTINUE: the chain is on track and the next planned "
                "step is appropriate.\n\n"
                "Return ONLY a JSON object matching this schema, no prose:\n"
                f"{schema_literal}"
            ),
        },
    ]


def clean_json_output(json_input: str) -> str:
    """Best-effort extract a JSON object from a messy LLM response.

    Handles the common failure modes of smaller instruct models (1.5B class):
    - Markdown code fences (``` / ```json).
    - Prose preamble ("Here is the plan: { ... }") or trailing text after the
      closing brace ("{ ... } Let me know if you need anything else").
    - Stray whitespace / stop tokens.

    Returns the original (stripped) text when no ``{...}`` block can be found —
    ``json.loads`` will then surface the real error to the caller, so we don't
    silently mask issues that aren't formatting-related.
    """
    output = json_input.strip()

    # Strip markdown fences if the model wrapped its answer in ```json ... ```.
    if output.startswith("```"):
        if output.startswith("```json"):
            output = output[7:]
        else:
            output = output[3:]
        if output.endswith("```"):
            output = output[:-3]
        output = output.strip()

    # Sometimes the model emits its own EOS-like tokens as text.
    for stop in ("<|im_end|>", "<|endoftext|>", "<|eot_id|>"):
        if stop in output:
            output = output.split(stop, 1)[0].strip()

    # Find the first balanced { ... } object. Walk the string tracking string
    # state so braces inside string literals don't confuse depth counting.
    start = output.find("{")
    if start == -1:
        return output

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(output)):
        ch = output[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return output[start : i + 1]
    # Unbalanced — return what we have so json.loads can complain meaningfully.
    return output
