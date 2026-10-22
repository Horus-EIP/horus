import json

import jsonschema
import pytest
from clients import answer_body, text_body
from corpus import demo_context, smoke

from llm_mock.agent_calls import REFUSAL

Q4_REPORT = "1_Q4_2025_Financial_Report.md"
QUESTIONS = (
    "What was our Q4 2025 revenue?",
    "What is the capital of Peru?",
    "How many vacation days can be carried over?",
    "What is the minimum password length?",
    "When must personal data breaches be reported?",
    "What is the hotel cap per night?",
)


def ask(server, question, context=None, labels=None, stream=True, purpose="answer"):
    if context is None:
        context, labels = demo_context()
    body = answer_body(context, question, labels if labels is not None else (), stream=stream)
    if stream:
        raw = server.request("POST", "/v1/chat/completions", body, {"X-Horus-Purpose": purpose})[2]
        events = raw.decode("utf-8").strip().split("\n\n")
        chunks = [json.loads(event[len("data: ") :]) for event in events[:-1]]
        content = "".join(
            c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"]
        )
    else:
        content = server.content(body, purpose)
    reply = json.loads(content)
    jsonschema.validate(reply, body["response_format"]["json_schema"]["schema"])
    return reply


def test_the_q4_revenue_answer_passes_the_smoke_test(server):
    reply = ask(server, smoke.QUESTION)
    assert reply["status"] == "ok"
    passed, why = smoke.check_answer(reply["answer"])
    assert passed, (why, reply["answer"])
    assert reply["answer"].startswith(
        "FinCorp closed Q4 2025 with total revenue of **$4.2M**, up 12% year-over-year. "
        f"[Source: {Q4_REPORT}]"
    )


def test_the_capital_of_peru_is_refused(server):
    reply = ask(server, smoke.NEGATIVE_QUESTION)
    assert reply == {"status": "not_found", "answer": REFUSAL, "sources": []}
    assert not smoke.NEGATIVE_RE.search(reply["answer"])


@pytest.mark.parametrize("question", QUESTIONS)
@pytest.mark.parametrize("stream", [True, False])
def test_every_answer_is_valid_against_the_answer_contract(server, question, stream):
    ask(server, question, stream=stream)


@pytest.mark.parametrize("question", [q for q in QUESTIONS if "Peru" not in q])
def test_every_answer_cites_the_passages_it_uses(server, question):
    context, labels = demo_context()
    reply = ask(server, question, context, labels)
    assert reply["status"] == "ok"
    assert reply["sources"] and set(reply["sources"]) <= set(labels)
    sentences = reply["answer"].split("] ")
    assert 1 <= len(sentences) <= 3
    assert all("[Source: " in sentence for sentence in sentences)


def test_each_sentence_names_the_document_it_comes_from(server):
    reply = ask(server, "How many vacation days can be carried over?")
    assert reply["answer"] == (
        "Unused vacation may be carried over up to a **maximum of 5 days** into the next calendar "
        "year. [Source: 2_Employee_Handbook.md]"
    )
    reply = ask(server, "What is the minimum password length?")
    assert reply["answer"] == "**Minimum length:** 14 characters. [Source: 5_IT_Security_Policy.md]"
    reply = ask(server, "When must personal data breaches be reported?")
    assert "[Source: 3_Compliance_Guidelines.md]" in reply["answer"]
    assert "[Source: 5_IT_Security_Policy.md]" in reply["answer"]


def test_without_passages_every_question_is_refused(server):
    for context in (
        "",
        "Semantic search did not return close excerpts for this question. "
        "Documents currently in the knowledge store:\n\n- 1_Q4.md (id=1)",
    ):
        reply = ask(server, smoke.QUESTION, context, ())
        assert reply == {"status": "not_found", "answer": REFUSAL}


def test_the_minimum_score_decides_between_an_answer_and_the_refusal(mock_server):
    question = "What was our Q4 2025 revenue in Lima?"
    assert ask(mock_server(min_score=0.2), question)["status"] == "ok"
    assert ask(mock_server(min_score=0.6), question) == {
        "status": "not_found",
        "answer": REFUSAL,
        "sources": [],
    }


def test_table_headers_and_separators_are_never_answers(server):
    context = (
        "[S1] t.md\n| Segment | Q4 2025 Revenue | % of Total |\n|---------|-----:|------|\n"
        "| **Total** | **$4,200,000** | **100%** |"
    )
    reply = ask(server, "Which segment had the biggest Q4 2025 revenue?", context, ("S1",))
    assert reply["status"] == "not_found"
    reply = ask(server, "What was the total?", context, ("S1",))
    assert reply["answer"] == "**Total**: **$4,200,000**, **100%** [Source: t.md]"


def test_a_chain_step_answers_its_own_task_not_the_whole_transcript(server):
    request = (
        "=== Original user demand ===\nCompare Q4 spend with the policy\n\n"
        "=== Chain transcript (in order) ===\n\n[Step 1 — Finance-Analyst (analyst)]\n"
        "Action: x\nResult:\nThe capital of Peru is Lima.\n\n=== End chain transcript ===\n\n"
        "=== Your task (HR-Assistant's turn) ===\nYou are ONE specialist in a multi-step team.\n\n"
        "=== Your assigned task ===\nFrom the HR-Assistant documents: How many vacation days can "
        "be carried over?\n\nGround your answer in the chain transcript above. Flag gaps."
    )
    reply = ask(server, request)
    assert reply["status"] == "ok"
    assert "2_Employee_Handbook.md" in reply["answer"]


def test_attached_files_are_cited_by_their_file_name(server):
    context = (
        "--- Attached Files ---\n[S1] [file: Expense_Policy.pdf (source=knowledge_store)]\n"
        "[Indexed file: Expense_Policy.pdf | id: d1]\n\nHotels are capped at $250 per night.\n"
        "[S2] [file: notes.txt (source=inline)]\nRemember the offsite.\n--- End Attached Files ---\n\n"
        "--- Other Knowledge Store Passages ---\n[S3] Q4_2025_Financial_Report.pdf, page 1\n"
        "Q4 revenue was $4.2M."
    )
    reply = ask(server, "What is the hotel cap?", context, ("S1", "S2", "S3"))
    assert reply == {
        "status": "ok",
        "answer": "Hotels are capped at $250 per night. [Source: Expense_Policy.pdf]",
        "sources": ["S1"],
    }


def test_a_passage_without_a_title_is_cited_by_its_label(server):
    reply = ask(
        server, "What is the hotel cap?", "[S1]\nHotels are capped at $250 per night.", ("S1",)
    )
    assert reply["answer"] == "Hotels are capped at $250 per night. [Source: S1]"


def react_body(query: str, trace: list[str], step: int) -> dict:
    sections = [f"User query: {query}"]
    if trace:
        sections.append("Reasoning so far:\n" + "\n".join(trace))
    sections.append(f"Step {step}: Provide your next THOUGHT and ACTION (or FINAL_ANSWER).")
    messages = [
        {"role": "system", "content": "You are an advanced reasoning agent."},
        {"role": "user", "content": "\n\n".join(sections)},
    ]
    return text_body(messages, 1024)


def test_react_searches_first_with_a_query_the_parser_reads_whole(server):
    reply = server.content(react_body("What was Q4 (2025) revenue, in total?", [], 1), "react_step")
    assert reply == (
        "THOUGHT: I need to search the knowledge store.\n"
        "ACTION: search_knowledge(What was Q4 2025 revenue in total?)"
    )


def test_react_answers_from_the_observations_with_their_sources(server):
    observation, _ = demo_context({Q4_REPORT}, header="[Source: {title}, page {n}]")
    trace = [
        "THOUGHT: THOUGHT: I need to search the knowledge store.\n"
        "ACTION: search_knowledge(What was our Q4 2025 revenue?)",
        "ACTION: search_knowledge(What was our Q4 2025 revenue?)",
        f"OBSERVATION: {observation}",
    ]
    reply = server.content(react_body(smoke.QUESTION, trace, 2), "react_step")
    thought, final = reply.split("\nFINAL_ANSWER: ")
    assert thought == "THOUGHT: I now have enough information to answer."
    assert smoke.check_answer(final)[0]
    assert f"[Source: {Q4_REPORT}]" in final


def test_react_refuses_what_the_observations_do_not_hold(server):
    trace = ["OBSERVATION: No relevant information found in the knowledge store."]
    reply = server.content(react_body(smoke.NEGATIVE_QUESTION, trace, 2), "react_step")
    assert reply.endswith(f"FINAL_ANSWER: {REFUSAL}")


def test_the_grounded_call_answers_from_the_retrieved_content(server):
    content, _ = demo_context({Q4_REPORT}, header="[Source: {title}]")
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": f"Retrieved Content:\n{content}\n\nTask: {smoke.QUESTION}"},
    ]
    assert smoke.check_answer(server.content(text_body(messages), "grounded"))[0]
    messages[1]["content"] = f"Retrieved Content:\n{content}\n\nTask: {smoke.NEGATIVE_QUESTION}"
    assert server.content(text_body(messages), "grounded") == REFUSAL
    messages[1]["content"] = "No task here."
    assert server.content(text_body(messages), "grounded") == REFUSAL


def test_an_instruction_returns_the_data_it_was_given(server):
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "Format the following text as markdown: Q4 was good."},
    ]
    assert server.content(text_body(messages), "instruction") == "Q4 was good."
    messages[1]["content"] = "No colon"
    assert server.content(text_body(messages), "instruction") == "No colon"


def test_refuse_makes_react_give_up_at_once(mock_server):
    reply = mock_server(scenario="refuse").content(react_body(smoke.QUESTION, [], 1), "react_step")
    assert reply == f"THOUGHT: I now have enough information to answer.\nFINAL_ANSWER: {REFUSAL}"


def test_refuse_turns_the_grounded_call_into_the_refusal(mock_server):
    content, _ = demo_context({Q4_REPORT}, header="[Source: {title}]")
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": f"Retrieved Content:\n{content}\n\nTask: {smoke.QUESTION}"},
    ]
    assert mock_server(scenario="refuse").content(text_body(messages), "grounded") == REFUSAL
