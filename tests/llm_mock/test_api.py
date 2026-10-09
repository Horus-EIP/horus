import json
import logging

import jsonschema
from clients import answer_body, route_body, sse_events, structured_body, text_body

from llm_mock.replies import NEUTRAL_TEXT

QUESTION = [{"role": "system", "content": "s"}, {"role": "user", "content": "What was our Q4 revenue?"}]


def test_health_answers_ok(server):
    status, headers, raw = server.request("GET", "/health")
    assert status == 200
    assert headers["Content-Type"] == "application/json"
    assert json.loads(raw) == {"status": "ok"}


def test_models_lists_one_model_owned_by_horus_mock(mock_server):
    running = mock_server(model="horus-mock")
    status, _, raw = running.request("GET", "/v1/models")
    assert status == 200
    assert json.loads(raw) == {
        "object": "list",
        "data": [{"id": "horus-mock", "object": "model", "created": 0, "owned_by": "horus-mock"}],
    }


def test_unknown_routes_are_404_with_an_openai_error(server):
    for method, path in (("GET", "/v1/nothing"), ("POST", "/v1/completions")):
        status, _, raw = server.request(method, path, {} if method == "POST" else None)
        assert status == 404
        assert json.loads(raw)["error"]["code"] == 404


def test_requests_it_cannot_read_are_400(server):
    for body in (b"not json", b"[]", json.dumps({"messages": []}).encode(),
                 json.dumps({"messages": ["text"]}).encode(),
                 json.dumps({"messages": QUESTION, "response_format": {"type": "json_schema"}}).encode()):
        status, _, raw = server.request("POST", "/v1/chat/completions", body)
        assert status == 400, body
        assert json.loads(raw)["error"]["type"] == "invalid_request_error"


def test_a_request_without_a_body_is_400(server):
    status, _, _ = server.request("POST", "/v1/chat/completions", b"")
    assert status == 400


def test_a_completion_has_the_fields_our_clients_read(server):
    reply = server.complete(text_body(QUESTION))
    assert reply["object"] == "chat.completion"
    assert reply["model"] == "qwen3-4b"
    choice = reply["choices"][0]
    assert choice["message"]["role"] == "assistant"
    assert isinstance(choice["message"]["content"], str) and choice["message"]["content"]
    assert choice["finish_reason"] == "stop"
    usage = reply["usage"]
    assert usage["prompt_tokens"] > 0 and usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


def test_the_model_defaults_to_the_mock_s_own_name(mock_server):
    body = text_body(QUESTION)
    del body["model"]
    assert mock_server(model="horus-mock").complete(body)["model"] == "horus-mock"


def test_message_content_given_as_parts_is_read(server):
    parts = [{"type": "text", "text": "USER INPUT:\n"}, {"type": "image_url"}, {"type": "text", "text": "hello"}]
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": parts}]
    reply = json.loads(server.content(text_body(messages), "intent"))
    assert reply["classification"] == "DIRECT_ANSWER"


def test_the_same_request_always_gets_the_same_response(server):
    body = route_body("Compare our Q4 spend against the expense policy")
    first = server.request("POST", "/v1/chat/completions", body)[2]
    second = server.request("POST", "/v1/chat/completions", body)[2]
    assert first == second
    stream = answer_body("[S1] a.md\nRevenue was $4.2M.", "What was revenue?")
    assert (server.request("POST", "/v1/chat/completions", stream)[2]
            == server.request("POST", "/v1/chat/completions", stream)[2])


def test_the_stream_is_server_sent_events_ending_with_usage_and_done(server):
    body = route_body("What was our Q4 2025 revenue?")
    expected = server.content(body)
    body.update(stream=True, stream_options={"include_usage": True})
    status, headers, raw = server.request("POST", "/v1/chat/completions", body)
    assert status == 200
    assert headers["Content-Type"] == "text/event-stream"
    events = sse_events(raw)
    assert events[-1] == "[DONE]"
    chunks = [json.loads(event) for event in events[:-1]]
    assert all(chunk["object"] == "chat.completion.chunk" for chunk in chunks)
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    text = "".join(chunk["choices"][0]["delta"].get("content", "")
                   for chunk in chunks if chunk["choices"])
    assert text == expected
    assert chunks[-2]["choices"][0] == {"index": 0, "delta": {}, "finish_reason": "stop"}
    assert chunks[-1]["choices"] == []
    assert chunks[-1]["usage"]["completion_tokens"] > 0
    assert len({chunk["id"] for chunk in chunks}) == 1


def test_the_stream_carries_usage_only_when_asked(server):
    body = text_body(QUESTION)
    body["stream"] = True
    chunks = [json.loads(event) for event in sse_events(
        server.request("POST", "/v1/chat/completions", body, {"X-Horus-Purpose": "announce"})[2])[:-1]]
    assert all("usage" not in chunk for chunk in chunks)
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_a_long_reply_streams_in_several_chunks_that_add_up_to_it(server):
    body = answer_body("", "x")
    body["stream"] = False
    full = server.content(body)
    body["stream"] = True
    chunks = [json.loads(event) for event in sse_events(
        server.request("POST", "/v1/chat/completions", body)[2])[:-1]]
    pieces = [chunk["choices"][0]["delta"]["content"]
              for chunk in chunks[1:-2] if chunk["choices"]]
    assert len(pieces) > 1
    assert "".join(pieces) == full


def test_an_unknown_text_call_gets_a_neutral_text_and_a_warning(server, caplog):
    with caplog.at_level(logging.WARNING, logger="llm_mock"):
        assert server.content(text_body(QUESTION), "summary") == NEUTRAL_TEXT
        assert server.content(text_body(QUESTION)) == NEUTRAL_TEXT
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert any("'summary'" in message for message in warnings)
    assert any("purpose None" in message for message in warnings)


def test_an_unknown_structured_call_gets_json_valid_against_its_schema(server, caplog):
    schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["yes", "no"]},
            "notes": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "score": {"type": "integer", "minimum": 1},
            "ratio": {"type": "number"},
            "flag": {"type": "boolean"},
            "empty": {"type": "null"},
            "either": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
            "fixed": {"const": 3},
            "maybe": {"type": ["null", "string"]},
            "nested": {"properties": {"name": {"type": "string", "minLength": 80}}},
            "short": {"type": "string", "maxLength": 4},
            "anything": {},
        },
        "required": ["verdict", "notes", "score", "ratio", "flag", "empty", "either", "fixed",
                     "maybe", "nested", "short", "anything"],
        "additionalProperties": False,
    }
    with caplog.at_level(logging.WARNING, logger="llm_mock"):
        reply = json.loads(server.content(structured_body(QUESTION, "grade", schema, 64)))
    jsonschema.validate(reply, schema)
    assert any("'grade'" in record.getMessage() for record in caplog.records)
