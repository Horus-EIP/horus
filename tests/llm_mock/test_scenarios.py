import json

import jsonschema
import pytest
from clients import answer_body, mas_prompts, route_body, sse_events, text_body

from llm_mock.agent_calls import REFUSAL
from llm_mock.replies import ERROR_TEXT

PROMPTS = mas_prompts()
PASSAGES = "[S1] 1_Q4_2025_Financial_Report.md\nFinCorp closed Q4 2025 with total revenue of $4.2M."


def json_calls():
    question = "Compare our Q4 spend against the expense policy"
    roster = [("id-1", "Finance-Analyst", "Financial analysis specialist.", "analyst")]
    review = PROMPTS.get_manager_review_prompt("q", "t", [], ["analyst"])
    return [
        (route_body(question), None),
        (answer_body(PASSAGES, "What was our Q4 2025 revenue?", stream=False), "answer"),
        (text_body(PROMPTS.get_prompt(question, roster)), "intent"),
        (text_body(PROMPTS.get_decomposition_prompt(question, roster)), "plan"),
        (text_body(review), "review"),
    ]


def test_normal_waits_the_configured_latency(mock_server):
    running = mock_server(latency_ms=300)
    running.content(route_body("What was our Q4 2025 revenue?"))
    running.request("GET", "/health")
    assert running.slept == [0.3]


def test_slow_waits_5_to_40_seconds_the_same_for_the_same_request(mock_server):
    running = mock_server(scenario="slow", latency_ms=0)
    questions = [
        f"What was our Q{quarter} {year} revenue?"
        for quarter in (1, 2, 3, 4)
        for year in (2024, 2025)
    ]
    for question in questions + questions[:2]:
        running.content(route_body(question))
    assert all(5 <= seconds <= 40 for seconds in running.slept)
    assert running.slept[-2:] == running.slept[:2]
    assert len(set(running.slept)) > 1


def test_invalid_json_breaks_every_json_reply(mock_server):
    running = mock_server(scenario="invalid_json")
    for body, purpose in json_calls():
        content = running.content(body, purpose)
        assert content
        with pytest.raises(ValueError):
            json.loads(PROMPTS.clean_json_output(content))


def test_invalid_json_leaves_text_replies_alone(mock_server):
    steps = [{"agent_type": "analyst", "description": "From the Finance-Analyst documents: q"}]
    body = text_body(PROMPTS.get_manager_announcement_prompt("q", steps))
    assert mock_server(scenario="invalid_json").content(body, "announce") == (
        "I'm asking Finance-Analyst to work on this."
    )


def test_normal_replies_to_the_same_calls_are_valid_json(server):
    for body, purpose in json_calls():
        json.loads(PROMPTS.clean_json_output(server.content(body, purpose)))


@pytest.mark.parametrize("labels", [("S1",), ()])
def test_refuse_answers_every_question_with_the_refusal(mock_server, labels):
    body = answer_body(
        PASSAGES if labels else "", "What was our Q4 2025 revenue?", labels, stream=False
    )
    reply = json.loads(mock_server(scenario="refuse").content(body, "answer"))
    jsonschema.validate(reply, body["response_format"]["json_schema"]["schema"])
    assert reply["status"] == "not_found"
    assert reply["answer"] == REFUSAL


def test_refuse_still_routes(mock_server, server):
    body = route_body("What was our Q4 2025 revenue?")
    assert mock_server(scenario="refuse").content(body) == server.content(body)


@pytest.mark.parametrize("stream", [False, True])
def test_error_fails_every_model_call(mock_server, stream):
    running = mock_server(scenario="error")
    body = answer_body(PASSAGES, "What was our Q4 2025 revenue?", stream=stream)
    status, headers, raw = running.request("POST", "/v1/chat/completions", body)
    assert status == 500
    assert headers["Content-Type"] == "application/json"
    assert json.loads(raw) == {
        "error": {"message": ERROR_TEXT, "type": "server_error", "code": 500}
    }


def test_error_keeps_the_health_check_and_the_model_list_up(mock_server):
    running = mock_server(scenario="error")
    assert running.request("GET", "/health")[0] == 200
    assert running.request("GET", "/v1/models")[0] == 200


def test_the_stream_of_a_refusal_adds_up_to_the_refusal(mock_server):
    running = mock_server(scenario="refuse")
    body = answer_body(PASSAGES, "What was our Q4 2025 revenue?")
    chunks = [
        json.loads(event)
        for event in sse_events(running.request("POST", "/v1/chat/completions", body)[2])[:-1]
    ]
    text = "".join(
        chunk["choices"][0]["delta"].get("content", "") for chunk in chunks if chunk["choices"]
    )
    assert json.loads(text)["answer"] == REFUSAL
