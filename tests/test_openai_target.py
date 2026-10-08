# SPDX-License-Identifier: Apache-2.0
import asyncio
import json
import socket

import pytest

from conftest import question_of
from horus_bench_kit.openai_target import (
    SYSTEM_PROMPT,
    OpenAITarget,
    ServerReplyError,
    read_body,
    read_stream,
)
from horus_bench_kit.target import Target

KEY_VARIABLE = "HBK_TEST_API_KEY"
KEY_VALUE = "test-key-not-a-secret"


def ask(target, question="How many lanterns hang on the north pier?", files=()):
    return asyncio.run(target.ask(question, item_id="t-01", files=files))


@pytest.fixture
def target(fake_openai, monkeypatch):
    monkeypatch.delenv(KEY_VARIABLE, raising=False)
    fake_openai.answer = lambda body: f"Fourteen lanterns ({question_of(body)})"
    return OpenAITarget(base_url=fake_openai.base_url + "/", model="harbour-7b", api_key_env=KEY_VARIABLE)


class TestRequest:
    def test_the_target_is_a_kit_target_posting_to_chat_completions(self, target, fake_openai):
        assert isinstance(target, Target)
        assert target.endpoint == fake_openai.base_url + "/chat/completions"
        ask(target)
        assert fake_openai.requests[0]["path"] == "/v1/chat/completions"

    def test_the_payload_carries_the_model_settings_and_both_messages(self, target, fake_openai):
        ask(target)
        body = fake_openai.requests[0]["body"]
        assert body == {
            "model": "harbour-7b",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "How many lanterns hang on the north pier?"},
            ],
            "max_tokens": 512,
            "temperature": 0.0,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

    def test_context_files_are_joined_before_the_question(self, target, fake_openai, tmp_path):
        first, second = tmp_path / "a.txt", tmp_path / "b.txt"
        first.write_text("Fourteen lanterns hang on the north pier.", encoding="utf-8")
        second.write_text("Mooring costs $12.", encoding="utf-8")
        ask(target, files=[first, second])
        content = fake_openai.requests[0]["body"]["messages"][1]["content"]
        assert content == (
            "Context:\nFourteen lanterns hang on the north pier.\n\nMooring costs $12.\n\n"
            "Question: How many lanterns hang on the north pier?"
        )

    def test_the_api_key_comes_from_the_environment_and_never_reaches_the_outcome(
        self, target, fake_openai, monkeypatch
    ):
        ask(target)
        assert "Authorization" not in fake_openai.requests[0]["headers"]
        monkeypatch.setenv(KEY_VARIABLE, KEY_VALUE)
        outcome = ask(target)
        assert fake_openai.requests[1]["headers"]["Authorization"] == f"Bearer {KEY_VALUE}"
        assert KEY_VALUE not in json.dumps(outcome)

    def test_stream_usage_can_be_left_out_for_servers_that_refuse_it(self, target, fake_openai):
        target.stream_usage = False
        outcome = ask(target)
        assert "stream_options" not in fake_openai.requests[0]["body"]
        assert outcome["usage"] is None
        assert outcome["status"] == "ok"


class TestReplies:
    def test_a_streamed_reply_has_a_time_to_first_token(self, target):
        outcome = ask(target)
        assert outcome["mode"] == "chat"
        assert outcome["status"] == "ok"
        assert outcome["error"] is None
        assert outcome["answer"] == "Fourteen lanterns (How many lanterns hang on the north pier?)"
        assert outcome["models"] == ["fake-model-1"]
        assert outcome["timing_source"] == "http"
        assert outcome["usage"] == {"prompt_tokens": 40, "completion_tokens": 10}
        assert 0 <= outcome["ttft_s"] <= outcome["total_s"]

    def test_a_whole_reply_has_no_time_to_first_token(self, target, fake_openai):
        target.stream = False
        outcome = ask(target)
        assert fake_openai.requests[0]["body"]["stream"] is False
        assert "stream_options" not in fake_openai.requests[0]["body"]
        assert outcome["answer"].startswith("Fourteen lanterns")
        assert outcome["ttft_s"] is None
        assert outcome["total_s"] >= 0
        assert outcome["usage"]["prompt_tokens"] == 40

    def test_an_http_error_keeps_the_start_of_the_body(self, target, fake_openai):
        fake_openai.status = 503
        outcome = ask(target)
        assert outcome["status"] == "error"
        assert outcome["error"].startswith("HTTP 503: ")
        assert "the model is not loaded" in outcome["error"]
        assert "answer" not in outcome

    def test_an_error_inside_the_stream_is_an_error(self, target, fake_openai):
        fake_openai.stream_error = {"message": "context size exceeded"}
        outcome = ask(target)
        assert outcome["status"] == "error"
        assert "context size exceeded" in outcome["error"]

    def test_a_slow_server_is_a_timeout(self, target, fake_openai):
        fake_openai.delay = 1.0
        target.timeout = 0.2
        outcome = ask(target)
        assert outcome["status"] == "timeout"

    def test_an_unreachable_server_is_an_error(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        outcome = ask(OpenAITarget(base_url=f"http://127.0.0.1:{port}/v1", model="m", timeout=5))
        assert outcome["status"] == "error"
        assert outcome["error"].startswith("URLError")


class TestReadStream:
    def test_comments_and_blank_lines_are_skipped_and_done_ends_the_stream(self):
        lines = [
            b": ping\n",
            b"\n",
            b'data: {"model": "m", "choices": [{"delta": {"content": "Four"}}]}\n',
            b'data:{"choices": [{"delta": {"content": "teen"}}]}\n',
            b"data: [DONE]\n",
            b'data: {"choices": [{"delta": {"content": "ignored"}}]}\n',
        ]
        reply = read_stream(lines, 0.0)
        assert (reply.answer, reply.model, reply.usage) == ("Fourteen", "m", None)
        assert reply.ttft_s is not None

    def test_reasoning_starts_the_clock_but_is_not_part_of_the_answer(self):
        lines = [
            b'data: {"choices": [{"delta": {"reasoning_content": "Counting."}}]}\n',
            b'data: {"choices": [{"delta": {"content": "14"}}]}\n',
        ]
        reply = read_stream(lines, 0.0)
        assert reply.answer == "14"
        assert reply.ttft_s is not None

    def test_a_server_that_ignores_streaming_is_an_error_not_an_empty_answer(self):
        body = json.dumps({"choices": [{"message": {"content": "14"}}]}).encode("utf-8")
        with pytest.raises(ServerReplyError, match="did not stream"):
            read_stream([body], 0.0)

    @pytest.mark.parametrize(
        "chunk",
        [[1, 2], {"choices": ["x"]}, {"choices": [{"delta": "x"}]}, {"choices": [{"delta": {"content": 5}}]}],
    )
    def test_a_chunk_of_the_wrong_shape_is_a_reply_error(self, chunk):
        with pytest.raises(ServerReplyError, match="unexpected stream chunk"):
            read_stream([f"data: {json.dumps(chunk)}".encode("utf-8")], 0.0)


class TestReadBody:
    def test_a_whole_reply_gives_its_answer_usage_and_model(self):
        body = {"model": "m", "choices": [{"message": {"content": "14"}}], "usage": {"prompt_tokens": 3}}
        reply = read_body(body)
        assert (reply.answer, reply.ttft_s, reply.usage, reply.model) == ("14", None, {"prompt_tokens": 3}, "m")
        assert read_body({"choices": []}).answer == ""

    @pytest.mark.parametrize(
        ("body", "what"),
        [
            ([1], "reply"),
            ({"choices": ["x"]}, "choices"),
            ({"choices": [{"message": "x"}]}, "message"),
            ({"choices": [{"message": {"content": ["x"]}}]}, "message"),
        ],
    )
    def test_a_reply_of_the_wrong_shape_is_a_reply_error(self, body, what):
        assert issubclass(ServerReplyError, ValueError)
        with pytest.raises(ServerReplyError, match=f"unexpected {what}"):
            read_body(body)
