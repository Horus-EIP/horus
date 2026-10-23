import json

import jsonschema
import pytest
from clients import ROSTER, mas_prompts, route_body, text_body

from llm_mock.mas_calls import SMALL_TALK_REPLY

PROMPTS = mas_prompts()
NAMES = {name for _, name, _, _ in ROSTER}
FACTUAL = (
    "What was our Q4 2025 revenue?",
    "What is the capital of Peru?",
    "How many days of annual leave do employees get?",
    "What does the IT security policy say about passwords?",
    "Which GDPR obligations apply to client data?",
    "What is the hotel cap per night?",
    "Who signed the attestation?",
    "Compare our Q4 spend against what the expense policy allows and flag anything out of policy.",
    "Review the Q4 financials and the GDPR audit findings",
    "Summarise everything",
)
GREETINGS = ("Hello!", "hi there", "Thanks!", "Thank you very much", "good morning", "How are you?")


def route(server, question, roster=ROSTER):
    body = route_body(question, roster)
    reply = json.loads(server.content(body, "task_route"))
    jsonschema.validate(reply, body["response_format"]["json_schema"]["schema"])
    return reply


def intent(server, question):
    body = text_body(PROMPTS.get_prompt(question, list(ROSTER)), 1024)
    return json.loads(server.content(body, "intent"))


@pytest.mark.parametrize("question", FACTUAL + GREETINGS)
def test_every_route_is_valid_against_the_schema_sent(server, question):
    route(server, question)


@pytest.mark.parametrize(
    "question, agent",
    [
        ("What was our Q4 2025 revenue?", "Finance-Analyst"),
        ("How many days of annual leave do employees get?", "HR-Assistant"),
        ("What does the IT security policy say about passwords?", "Compliance-Officer"),
        ("Which GDPR obligations apply to client data?", "Compliance-Officer"),
        ("What is the hotel cap per night?", "Finance-Analyst"),
        ("What is the capital of Peru?", "General-Assistant"),
        ("Who signed the attestation?", "General-Assistant"),
    ],
)
def test_one_domain_goes_to_its_agent(server, question, agent):
    assert route(server, question) == {"route": "SINGLE_AGENT", "agent": agent}


@pytest.mark.parametrize(
    "question, first",
    [
        (
            "Compare our Q4 spend against what the expense policy allows and flag anything out of policy.",
            "Finance-Analyst",
        ),
        ("Review the Q4 financials and the GDPR audit findings", "Finance-Analyst"),
        ("How does Q4 revenue stack up versus the 2024 figures?", "Finance-Analyst"),
    ],
)
def test_two_domains_or_a_comparison_are_a_complex_task(server, question, first):
    assert route(server, question) == {"route": "COMPLEX_TASK", "agent": first}


def test_the_agent_always_comes_from_the_schema_s_list(server):
    roster = [agent for agent in ROSTER if agent[1] in ("Researcher", "HR-Assistant")]
    assert route(server, "What was our Q4 2025 revenue?", roster)["agent"] in {
        "Researcher",
        "HR-Assistant",
    }
    no_descriptions = [(agent_id, name, "", kind) for agent_id, name, _, kind in roster]
    assert route(server, "What is the capital of Peru?", no_descriptions)["agent"] == "HR-Assistant"


def test_a_route_schema_of_another_shape_still_gets_valid_json(server):
    body = route_body("What was our Q4 2025 revenue?")
    schema = {"type": "object", "properties": {"route": {"type": "string"}}, "required": ["route"]}
    body["response_format"]["json_schema"]["schema"] = schema
    jsonschema.validate(json.loads(server.content(body)), schema)


@pytest.mark.parametrize("greeting", GREETINGS)
def test_greetings_are_answered_directly(server, greeting):
    reply = intent(server, greeting)
    assert reply["classification"] == "DIRECT_ANSWER"
    assert reply["final_answer"] == SMALL_TALK_REPLY


@pytest.mark.parametrize("question", FACTUAL)
def test_a_factual_question_is_never_answered_directly(server, question):
    reply = intent(server, question)
    assert reply["classification"] in ("SINGLE_AGENT", "COMPLEX_TASK")
    assert reply["final_answer"] == ""
    assert reply["agent_name"] in NAMES
    assert reply["rewritten_input"] == question


def test_the_intent_call_names_the_agent_and_the_route(server):
    assert intent(server, "What is the capital of Peru?")["agent_name"] == "General-Assistant"
    complex_task = intent(server, "Review the Q4 financials and the GDPR audit findings")
    assert complex_task["classification"] == "COMPLEX_TASK"
    assert complex_task["agent_name"] == "Finance-Analyst"


def test_the_plan_chains_one_step_per_agent_named_by_agent(server):
    question = "Compare our Q4 spend against what the expense policy allows and flag anything out of policy."
    body = text_body(PROMPTS.get_decomposition_prompt(question, list(ROSTER)), 2048)
    plan = json.loads(PROMPTS.clean_json_output(server.content(body, "plan")))
    assert plan == {
        "sub_tasks": [
            {
                "id": "1",
                "agent_type": "Finance-Analyst",
                "description": f"From the Finance-Analyst documents: {question}",
                "depends_on": [],
                "status": "pending",
            },
            {
                "id": "2",
                "agent_type": "HR-Assistant",
                "description": f"From the HR-Assistant documents: {question}",
                "depends_on": ["1"],
                "status": "pending",
            },
        ]
    }


def test_a_plan_for_one_domain_has_one_step(server):
    body = text_body(PROMPTS.get_decomposition_prompt("What is the capital of Peru?", list(ROSTER)))
    steps = json.loads(server.content(body, "plan"))["sub_tasks"]
    assert [step["agent_type"] for step in steps] == ["General-Assistant"]


def wrapped(description: str) -> str:
    return (
        "You are ONE specialist in a multi-step team. Do ONLY the task assigned to you below "
        "— other specialists handle the rest and the results are combined at the end. Stay in "
        f"your lane and be concise.\n\n=== Your assigned task ===\n{description}"
    )


def test_the_announcement_names_the_agents_in_order(server):
    steps = [
        {"agent_type": "analyst", "description": wrapped("From the Finance-Analyst documents: q")},
        {"agent_type": "general", "description": wrapped("From the HR-Assistant documents: q")},
    ]
    body = text_body(PROMPTS.get_manager_announcement_prompt("q", steps))
    assert server.content(body, "announce") == (
        "I'm asking Finance-Analyst then HR-Assistant to work on this."
    )


def test_an_announcement_without_named_agents_uses_their_types(server):
    steps = [
        {"agent_type": "analyst", "description": "Handle the numbers"},
        {"agent_type": "researcher", "description": "Read around"},
    ]
    body = text_body(PROMPTS.get_manager_announcement_prompt("q", steps))
    assert server.content(body, "announce") == "I'm asking analyst then researcher to work on this."


def review(server, remaining):
    prompt = PROMPTS.get_manager_review_prompt(
        "Compare Q4 spend with the policy",
        "=== Chain transcript (in order) ===\n...",
        remaining,
        ["researcher", "analyst"],
    )
    return json.loads(PROMPTS.clean_json_output(server.content(text_body(prompt, 384), "review")))


def test_the_review_continues_while_steps_remain_and_is_done_after(server):
    remaining = [{"agent_type": "general", "description": "From the HR-Assistant documents: q"}]
    assert review(server, remaining)["decision"] == "CONTINUE"
    done = review(server, [])
    assert done["decision"] == "DONE"
    assert done["next_agent_type"] is None and done["next_action"] is None
    assert done["reasoning"]


def test_the_aggregate_has_one_section_per_step_and_the_sources(server):
    history = [
        {"role": "user", "message": "Compare Q4 spend with the policy"},
        {
            "role": "assistant",
            "message": "Q4 spend was $3.1M. [Source: 1_Q4_2025_Financial_Report.md]",
        },
        {
            "role": "assistant",
            "message": "first try",
            "status": "failed",
            "reason": "error",
            "attempt": 1,
        },
        {
            "role": "assistant",
            "message": "Hotels are capped at $250. [Source: 4_Expense_Policy.md]\n\nMore.",
        },
        {
            "role": "assistant",
            "message": "Hotels are capped at $250. [Source: 4_Expense_Policy.md]\n\nMore.",
        },
    ]
    body = text_body(
        PROMPTS.get_prompt_final_answer_generation(history, history[-1]["message"]), 3072
    )
    assert server.content(body, "aggregate") == (
        "## Answer\n\n"
        "### Step 1\n\nQ4 spend was $3.1M. [Source: 1_Q4_2025_Financial_Report.md]\n\n"
        "### Step 2\n\nHotels are capped at $250. [Source: 4_Expense_Policy.md]\n\nMore.\n\n"
        "**Sources:** 1_Q4_2025_Financial_Report.md, 4_Expense_Policy.md"
    )


def test_an_aggregate_with_an_unreadable_history_keeps_the_final_output(server):
    body = text_body(PROMPTS.get_prompt_final_answer_generation("not a list(", "Only this."))
    assert server.content(body, "aggregate") == "## Answer\n\n### Step 1\n\nOnly this."
    body = text_body(PROMPTS.get_prompt_final_answer_generation({"role": "user"}, "Still this."))
    assert server.content(body, "aggregate") == "## Answer\n\n### Step 1\n\nStill this."
