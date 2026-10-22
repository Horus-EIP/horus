# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from horus_bench_kit.contract import FAILURE_REQUEST, FAILURE_RETRIEVAL, FAILURE_SCHEMA
from horus_bench_kit.probe import (
    REPORT_KIND,
    ContractProfile,
    Template,
    build_contract_report,
    completion_payload,
    contract_summary,
    http_reply,
    item_context,
    item_problems,
    load_items,
    load_template,
    post_json,
    prepared_items,
    probe_job,
    probe_records,
    read_reply_lines,
    render_user,
    reply_record,
    response_format_for,
    response_schema,
    run_prepared_probe,
    run_template_probe,
    select_probe_items,
    split_command,
)

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["supported", "refuted", "not_stated"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


def claim(item_id="c-01", **extra):
    return {
        "id": item_id,
        "category": "supported",
        "question": "Fourteen lanterns hang on the north pier.",
        "expected": {"verdict": "supported"},
        "patterns": {"reason": [r"\b(?:14|fourteen)\b"]},
        **extra,
    }


def reply(content, **extra):
    return {"id": "c-01", "schema": SCHEMA, "content": content, "finish_reason": "stop", **extra}


def verdict(value="supported", reason="The pier has fourteen lanterns."):
    return json.dumps({"verdict": value, "reason": reason})


class TestItems:
    def test_json_jsonl_and_yaml_files(self, tmp_path):
        items = [claim(), claim("c-02")]
        (tmp_path / "a.json").write_text(json.dumps({"items": items}), encoding="utf-8")
        (tmp_path / "b.json").write_text(json.dumps(items), encoding="utf-8")
        (tmp_path / "c.jsonl").write_text(
            "\n".join(json.dumps(item) for item in items) + "\n\n", encoding="utf-8"
        )
        for name in ("a.json", "b.json", "c.jsonl"):
            assert load_items(tmp_path / name) == items
        yaml = pytest.importorskip("yaml")
        (tmp_path / "d.yaml").write_text(yaml.safe_dump({"items": items}), encoding="utf-8")
        assert load_items(tmp_path / "d.yaml") == items

    def test_the_example_items_are_valid(self, examples):
        items = load_items(examples / "probe" / "items.json")
        assert item_problems(items) == []
        assert len(items) == 8
        assert {item["category"] for item in items} == {"supported", "refuted", "not_stated"}

    def test_problems_are_named(self):
        problems = item_problems(
            [
                {"id": "a", "question": "q", "patterns": {"reason": ["("]}},
                {"id": "a", "question": "q"},
                {"id": "", "question": 3},
                {"question": "q", "expected": []},
                "text",
            ]
        )
        assert any(
            problem.startswith("item a: patterns.reason '(' is not a valid regular expression")
            for problem in problems
        )
        assert "item a: the id is used twice" in problems
        assert "item 3: id must be a non-empty string" in problems
        assert "item 3: question must be a non-empty string" in problems
        assert "item 4: expected must map field names to values" in problems
        assert "item 5 must be an object" in problems
        assert item_problems([]) == [
            "the file holds no items: give a non-empty list, or an object with an items list"
        ]

    def test_prepared_requests_need_a_payload(self):
        assert item_problems([{"id": "p-1", "payload": {"messages": []}}], prepared=True) == []
        assert item_problems([{"id": "p-1"}], prepared=True) == [
            "item p-1: payload must be a chat completion request with messages"
        ]

    def test_selection_tolerates_items_without_a_category(self):
        items = [claim(), {"id": "c-02", "question": "q"}, claim("c-03", category="refuted")]
        assert [i["id"] for i in select_probe_items(items, categories=["refuted"])] == ["c-03"]
        assert [i["id"] for i in select_probe_items(items, ids=["c-02", "c-03"], limit=1)] == [
            "c-02"
        ]

    def test_context_comes_from_the_item_then_its_file_then_the_folder(self, tmp_path):
        (tmp_path / "ctx").mkdir()
        (tmp_path / "ctx" / "c-01.txt").write_text("from the folder", encoding="utf-8")
        (tmp_path / "pier.txt").write_text("from the file", encoding="utf-8")
        assert item_context(claim(context="inline"), tmp_path, tmp_path / "ctx") == "inline"
        assert (
            item_context(claim(context_file="pier.txt"), tmp_path, tmp_path / "ctx")
            == "from the file"
        )
        assert item_context(claim(), tmp_path, tmp_path / "ctx") == "from the folder"
        assert item_context(claim(), tmp_path) == ""


class TestRequests:
    def test_response_formats_nested_and_flat(self):
        nested = response_format_for(SCHEMA)
        assert nested == {
            "type": "json_schema",
            "json_schema": {"name": "reply", "strict": True, "schema": SCHEMA},
        }
        assert response_schema(nested) == SCHEMA
        assert response_schema({"type": "json_schema", "schema": SCHEMA}) == SCHEMA
        assert response_schema({"type": "json_object"}) is None
        assert response_schema(None) is None

    def test_the_user_template_is_filled_in_one_pass(self):
        assert render_user(
            "Excerpt:\n{context}\n\nClaim: {question}", "q {context}", "c {question}"
        ) == ("Excerpt:\nc {question}\n\nClaim: q {context}")
        assert render_user('{"keep": "braces"} {question}', "q", "") == '{"keep": "braces"} q'

    def test_payload_keys_in_order(self):
        payload = completion_payload("m", "sys", "user", 64, response_format_for(SCHEMA))
        assert list(payload) == [
            "model",
            "messages",
            "max_tokens",
            "temperature",
            "stream",
            "response_format",
        ]
        assert payload["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "user"},
        ]
        assert (payload["temperature"], payload["stream"]) == (0.0, False)

    def test_templates_load_from_files(self, examples, tmp_path):
        probe = examples / "probe"
        template = load_template(
            probe / "system.txt",
            probe / "user.txt",
            schema_path=probe / "schema.json",
            max_tokens=99,
        )
        assert template.schema["required"] == ["verdict", "reason"]
        payload = template.payload("m", "A claim.", "An excerpt.")
        assert payload["max_tokens"] == 99
        assert payload["messages"][1]["content"] == "Excerpt:\nAn excerpt.\n\nClaim: A claim.\n"
        flat = tmp_path / "format.json"
        flat.write_text(json.dumps({"type": "json_schema", "schema": SCHEMA}), encoding="utf-8")
        assert (
            load_template(
                probe / "system.txt", probe / "user.txt", response_format_path=flat
            ).schema
            == SCHEMA
        )
        flat.write_text(json.dumps({"type": "json_object"}), encoding="utf-8")
        with pytest.raises(ValueError, match="holds no JSON schema"):
            load_template(probe / "system.txt", probe / "user.txt", response_format_path=flat)
        user = tmp_path / "user.txt"
        user.write_text("no placeholder", encoding="utf-8")
        with pytest.raises(ValueError, match=r"no \{question\} placeholder"):
            load_template(probe / "system.txt", user, schema_path=probe / "schema.json")


class TestHttp:
    def test_post_json_and_http_errors(self, fake_openai):
        body = post_json(
            fake_openai.base_url + "/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}]},
            5,
        )
        assert body["choices"][0]["message"]["content"] == "The documents do not say."
        fake_openai.status = 503
        with pytest.raises(RuntimeError, match="HTTP 503: .*not loaded"):
            post_json(fake_openai.base_url + "/chat/completions", {"messages": []}, 5)

    def test_a_reply_line_from_a_response_or_an_error(self):
        clock = iter([1.0, 3.5]).__next__
        body = {
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 9},
        }
        payload = completion_payload("m", "s", "u", 64, response_format_for(SCHEMA))
        assert http_reply("c-01", "url", payload, 5, post=lambda *a: body, clock=clock) == {
            "id": "c-01",
            "schema": SCHEMA,
            "max_tokens": 64,
            "content": "{}",
            "reasoning_content": None,
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 9},
            "timings": None,
            "wall_s": 2.5,
        }

        def refuse(*args):
            raise RuntimeError("HTTP 500: boom")

        failed = http_reply(
            "c-01",
            "url",
            payload,
            5,
            meta={"labels": ["E1"]},
            post=refuse,
            clock=iter([0.0, 0.25]).__next__,
        )
        assert failed["labels"] == ["E1"]
        assert (failed["error_stage"], failed["error"], failed["wall_s"]) == (
            "llm",
            "RuntimeError: HTTP 500: boom",
            0.25,
        )

    def test_template_probe_against_a_server(self, fake_openai, tmp_path):
        (tmp_path / "pier.txt").write_text(
            "Fourteen lanterns hang on the north pier.", encoding="utf-8"
        )
        fake_openai.answer = lambda body: verdict()
        template = Template(
            "Check the claim.",
            "Excerpt:\n{context}\n\nClaim: {question}",
            response_format_for(SCHEMA),
        )
        lines = []
        replies = run_template_probe(
            [claim(context_file="pier.txt"), claim("c-02")],
            template,
            model="alpha",
            url=fake_openai.base_url + "/chat/completions",
            timeout=5,
            base=tmp_path,
            warmup="Is this on?",
            progress=lines.append,
        )
        assert list(replies) == ["c-01", "c-02"]
        assert replies["c-01"]["schema"] == SCHEMA
        assert json.loads(replies["c-01"]["content"])["verdict"] == "supported"
        sent = [request["body"] for request in fake_openai.requests]
        assert len(sent) == 3
        assert sent[0]["messages"][1]["content"] == "Excerpt:\n\n\nClaim: Is this on?"
        assert "Fourteen lanterns hang" in sent[1]["messages"][1]["content"]
        assert sent[1]["response_format"]["json_schema"]["schema"] == SCHEMA
        assert lines == [
            "[info] warmup (not scored): Is this on?",
            "[  1/2] c-01 stop",
            "[  2/2] c-02 stop",
        ]

    def test_prepared_requests_keep_their_meta(self, fake_openai):
        fake_openai.answer = lambda body: verdict()
        request = {
            "id": "p-1",
            "payload": completion_payload("own", "s", "Claim: x", 32, response_format_for(SCHEMA)),
            "meta": {
                "labels": ["E1"],
                "sources_by_label": {"E1": {"title": "pier.md"}},
                "ignored": 1,
            },
        }
        replies = run_prepared_probe(
            [request],
            url=fake_openai.base_url + "/chat/completions",
            timeout=5,
            model="alpha",
            progress=lambda line: None,
        )
        assert replies["p-1"]["labels"] == ["E1"]
        assert "ignored" not in replies["p-1"]
        assert fake_openai.requests[0]["body"]["model"] == "alpha"
        assert prepared_items([request])[0]["question"] == "Claim: x"
        assert (
            prepared_items([{**request, "question": "own question"}])[0]["question"]
            == "own question"
        )


class TestProtocol:
    def test_the_job_holds_ids_questions_and_context_only(self):
        job = probe_job([claim(context="excerpt"), claim("c-02")], "warm")
        assert job == {
            "items": [
                {
                    "id": "c-01",
                    "question": "Fourteen lanterns hang on the north pier.",
                    "context": "excerpt",
                },
                {"id": "c-02", "question": "Fourteen lanterns hang on the north pier."},
            ],
            "warmup": "warm",
        }

    def test_reply_lines_skip_noise_and_keep_the_last_reply_per_id(self):
        lines = [
            "[info] starting",
            "not json",
            '{"no": "id"}',
            '{"id": "a", "content": "1"}',
            '{"id": "a", "content": "2"}',
            "[1, 2]",
        ]
        assert read_reply_lines(lines) == {"a": {"id": "a", "content": "2"}}

    def test_commands_split_like_a_shell_or_from_json(self):
        assert split_command("python probe.py --x 'a b'") == ["python", "probe.py", "--x", "a b"]
        assert split_command('"C:\\Program Files\\py.exe" probe.py') == [
            "C:\\Program Files\\py.exe",
            "probe.py",
        ]
        assert split_command('["docker", "exec", "-i", "box", "probe"]') == [
            "docker",
            "exec",
            "-i",
            "box",
            "probe",
        ]
        for bad in ("", "[]", '["a", 1]'):
            with pytest.raises(ValueError):
                split_command(bad)


class TestScoring:
    def test_a_correct_reply(self):
        record = reply_record(claim(), reply(verdict()))
        assert list(record) == [
            "id",
            "category",
            "question",
            "expected",
            "json_valid",
            "failure",
            "violations",
            "expected_correct",
            "patterns_correct",
            "missing_patterns",
            "error",
            "finish_reason",
            "thought_first",
            "labels",
            "retrieved_titles",
            "wall_s",
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "prompt_n",
            "prompt_ms",
            "predicted_n",
            "predicted_ms",
            "prompt_tps",
            "generation_tps",
            "content",
            "reasoning_chars",
        ]
        assert (record["json_valid"], record["expected_correct"], record["patterns_correct"]) == (
            True,
            True,
            True,
        )
        assert record["missing_patterns"] == {}

    def test_wrong_values_and_missing_patterns(self):
        record = reply_record(claim(), reply(verdict("refuted", "It says twelve.")))
        assert (record["json_valid"], record["expected_correct"], record["patterns_correct"]) == (
            True,
            False,
            False,
        )
        assert record["missing_patterns"] == {"reason": [r"\b(?:14|fourteen)\b"]}

    def test_an_invalid_reply_scores_nothing_right(self):
        record = reply_record(claim(), reply(json.dumps({"verdict": "maybe", "reason": "x"})))
        assert (record["json_valid"], record["failure"]) == (False, FAILURE_SCHEMA)
        assert record["violations"] == [
            "$.verdict: 'maybe' is not one of ['supported', 'refuted', 'not_stated']"
        ]
        assert (record["expected_correct"], record["patterns_correct"]) == (False, False)

    def test_items_without_expectations_are_not_scored_on_them(self):
        record = reply_record({"id": "c-01", "question": "q"}, reply(verdict()))
        assert (record["category"], record["expected"], record["expected_correct"]) == (
            None,
            None,
            None,
        )
        assert (record["patterns_correct"], record["missing_patterns"]) == (None, None)

    def test_request_and_retrieval_failures(self):
        failed = reply_record(
            claim(), {"id": "c-01", "error_stage": "llm", "error": "boom", "wall_s": 1.0}
        )
        assert (failed["failure"], failed["json_valid"], failed["error"]) == (
            FAILURE_REQUEST,
            False,
            "boom",
        )
        retrieval = reply_record(
            claim(), {"id": "c-01", "error_stage": "retrieval", "error": "store down"}
        )
        assert (retrieval["failure"], retrieval["json_valid"], retrieval["expected_correct"]) == (
            FAILURE_RETRIEVAL,
            None,
            None,
        )

    def test_booleans_are_not_numbers_in_expectations(self):
        item = {"id": "b", "question": "q", "expected": {"ok": 1}}
        schema = {"type": "object"}
        assert (
            reply_record(item, {"id": "b", "schema": schema, "content": '{"ok": true}'})[
                "expected_correct"
            ]
            is False
        )
        assert (
            reply_record(item, {"id": "b", "schema": schema, "content": '{"ok": 1.0}'})[
                "expected_correct"
            ]
            is True
        )


class TestSummary:
    def records(self):
        replies = {
            "c-01": reply(
                verdict(),
                usage={"prompt_tokens": 100, "completion_tokens": 20},
                timings={
                    "prompt_n": 100,
                    "prompt_ms": 1000.0,
                    "predicted_n": 20,
                    "predicted_ms": 2000.0,
                },
                wall_s=3.0,
            ),
            "c-02": reply(
                verdict("refuted", "It says twelve."),
                finish_reason="length",
                reasoning_content="Thinking.",
                wall_s=5.0,
            ),
            "c-03": {"id": "c-03", "error_stage": "llm", "error": "boom", "wall_s": 1.0},
        }
        items = [claim(), claim("c-02", category="refuted"), claim("c-03"), claim("c-04")]
        return probe_records(items, replies)

    def test_records_follow_the_items_that_got_a_reply(self):
        assert [r["id"] for r in self.records()] == ["c-01", "c-02", "c-03"]

    def test_summary_rates_counts_and_categories_in_first_seen_order(self):
        summary = contract_summary(self.records())
        assert list(summary) == [
            "replies",
            "json_valid",
            "expected_correct",
            "patterns_correct",
            "failures",
            "thought_first",
            "truncated",
            "wall_s",
            "prompt_tokens",
            "completion_tokens",
            "prompt_tps",
            "generation_tps",
            "by_category",
        ]
        assert summary["json_valid"] == {"n": 3, "correct": 2, "pct": 66.7}
        assert summary["expected_correct"] == {"n": 3, "correct": 1, "pct": 33.3}
        assert summary["failures"] == {FAILURE_REQUEST: 1}
        assert (summary["thought_first"], summary["truncated"]) == (1, 1)
        assert summary["wall_s"]["median"] == 3.0
        assert (summary["prompt_tps"], summary["generation_tps"]) == (100.0, 10.0)
        assert list(summary["by_category"]) == ["supported", "refuted"]
        assert summary["by_category"]["refuted"] == {
            "replies": 1,
            "json_valid": {"n": 1, "correct": 1, "pct": 100.0},
            "expected_correct": {"n": 1, "correct": 0, "pct": 0.0},
            "patterns_correct": {"n": 1, "correct": 0, "pct": 0.0},
        }

    def test_a_product_profile_scores_its_own_fields(self):
        profile = ContractProfile(
            kind="acme-contract-probe",
            schema_version=4,
            head=lambda item: {"expected_verdict": item["expected"]["verdict"]},
            scores=lambda item, reply: {
                "json_valid": True,
                "failure": None,
                "long": len(reply.get("content") or "") > 75,
            },
            rate_fields=("json_valid", "long"),
            counts=lambda records: {"long_replies": sum(1 for r in records if r["long"])},
            categories=("refuted", "supported", "unused"),
        )
        records = probe_records(
            [claim(), claim("c-02", category="refuted")],
            {"c-01": reply(verdict()), "c-02": reply("x" * 80)},
            profile,
        )
        assert list(records[0])[:6] == [
            "id",
            "category",
            "question",
            "expected_verdict",
            "json_valid",
            "failure",
        ]
        report = build_contract_report(
            label="acme",
            run={},
            model={"name": "alpha"},
            llama_server=None,
            records=records,
            profile=profile,
        )
        assert (report["kind"], report["schema_version"]) == ("acme-contract-probe", 4)
        summary = report["summary"]
        assert list(summary)[:7] == [
            "replies",
            "json_valid",
            "long",
            "failures",
            "thought_first",
            "truncated",
            "long_replies",
        ]
        assert summary["long_replies"] == 1
        assert list(summary["by_category"]) == ["refuted", "supported"]

    def test_the_default_report(self):
        report = build_contract_report(
            label="probe",
            run={"mode": "template"},
            model={"name": "alpha"},
            llama_server=None,
            records=self.records(),
        )
        assert list(report) == [
            "kind",
            "schema_version",
            "label",
            "run",
            "model",
            "llama_server",
            "summary",
            "replies",
        ]
        assert (report["kind"], report["schema_version"]) == (REPORT_KIND, 1)
        assert REPORT_KIND == "horus-contract-probe"
