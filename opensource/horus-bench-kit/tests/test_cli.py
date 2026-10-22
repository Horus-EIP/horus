# SPDX-License-Identifier: Apache-2.0
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import horus_bench_kit
from horus_bench_kit import __version__
from horus_bench_kit.candidates import written_report as reported_path
from horus_bench_kit.cli.eval import endpoint_origin, main
from horus_bench_kit.files import read_json, write_json
from horus_bench_kit.report import blank_review

QUESTION_KEYS = [
    "id",
    "category",
    "difficulty",
    "question",
    "expected_answer",
    "expected_source",
    "expected_route",
    "status",
    "error",
    "observed_route",
    "models",
    "timing_source",
    "ttft_s",
    "total_s",
    "usage",
    "answer",
    "retrieval_steps",
    "retrieved_sources",
    "cited_sources",
    "fallback",
    "answer_correct_auto",
    "missing_patterns",
    "source_basis",
    "source_ranks",
    "source_correct_auto",
    "route_correct",
    "review",
]


@pytest.fixture
def copied_examples(tmp_path, examples):
    target = tmp_path / "examples"
    shutil.copytree(examples, target)
    return target


@pytest.fixture
def run_args(copied_examples, fake_openai, tmp_path):
    def build(*extra):
        return [
            "run",
            "--base-url",
            fake_openai.base_url,
            "--model",
            "harbour-7b",
            "--testset",
            str(copied_examples / "testset.json"),
            "--context-dir",
            str(copied_examples / "context"),
            "--label",
            "garden run",
            "--out-dir",
            str(tmp_path / "results"),
            *extra,
        ]

    return build


def written_report(output):
    line = next(line for line in output.splitlines() if line.startswith("[done] wrote "))
    return read_json(line.removeprefix("[done] wrote "))


class TestValidate:
    def test_the_json_example_is_valid(self, examples, capsys):
        assert main(["validate", str(examples / "testset.json")]) == 0
        assert (
            capsys.readouterr().out
            == "[ok] testset.json: version 1.0.0, 9 questions, 3 corpus documents\n"
        )

    def test_the_yaml_example_is_valid(self, examples, capsys):
        pytest.importorskip("yaml")
        assert main(["validate", str(examples / "testset.yaml")]) == 0
        assert capsys.readouterr().out.startswith("[ok] testset.yaml")

    def test_a_broken_test_set_lists_its_problems(self, copied_examples, capsys):
        path = copied_examples / "testset.json"
        testset = read_json(path)
        testset["items"][0]["expected_answer"] = "At noon."
        testset["items"][1]["context_file"] = "context/missing.txt"
        write_json(path, testset)
        assert main(["validate", str(path)]) == 2
        assert capsys.readouterr().out.splitlines() == [
            "[error] testset: fg-01: expected_answer fails its own answer_patterns",
            "[error] testset: fg-02: context_file 'context/missing.txt' does not exist",
        ]

    def test_a_file_that_is_not_a_test_set_is_refused(self, tmp_path, capsys):
        empty = tmp_path / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        assert main(["validate", str(empty)]) == 2
        assert (
            capsys.readouterr().out
            == "[error] testset: empty.json does not hold a test set object\n"
        )
        assert main(["validate", str(tmp_path / "missing.json")]) == 2
        assert capsys.readouterr().out.startswith("[error] testset: cannot read missing.json")

    def test_schema_problems_stop_before_the_corpus_is_read(self, tmp_path, capsys):
        path = tmp_path / "t.json"
        path.write_text(json.dumps({"items": []}), encoding="utf-8")
        assert main(["validate", str(path)]) == 2
        assert (
            "[error] testset: missing top-level key 'corpus_dir'"
            in capsys.readouterr().out.splitlines()
        )

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"items": ["fg-01"]}, "item #0: must be a mapping of fields"),
            ({"items": {"fg-01": {}}}, "items must be a list of questions"),
            (
                {"corpus": ["garden-handbook.txt"]},
                "corpus must map document file names to their SHA-256",
            ),
        ],
    )
    def test_a_test_set_of_the_wrong_shape_is_reported_not_raised(
        self, copied_examples, capsys, change, message
    ):
        path = copied_examples / "testset.json"
        write_json(path, {**read_json(path), **change})
        assert main(["validate", str(path)]) == 2
        assert capsys.readouterr().out == f"[error] testset: {message}\n"

    def test_an_expected_source_of_the_wrong_type_is_reported_not_raised(
        self, copied_examples, capsys
    ):
        path = copied_examples / "testset.json"
        testset = read_json(path)
        testset["items"][0]["expected_source"] = 5
        write_json(path, testset)
        assert main(["validate", str(path)]) == 2
        expected = "[error] testset: fg-01: expected_source must be null, a file name or a list of file names\n"
        assert capsys.readouterr().out == expected


class TestRun:
    def test_a_run_writes_a_kit_report_and_prints_the_headline(
        self, run_args, fake_openai, example_answers, capsys
    ):
        fake_openai.answer = example_answers(fg_04="It costs $80.")
        assert main(run_args("--warmup", "Say hello.")) == 0
        output = capsys.readouterr().out
        report = written_report(output)
        today = datetime.now(timezone.utc).date().isoformat()
        assert output.splitlines()[0] == "[info] warmup (not scored): Say hello."
        assert output.splitlines()[1].endswith(f"garden-run-{today}.json")
        assert list(report) == [
            "kind",
            "schema_version",
            "label",
            "run",
            "testset",
            "summary",
            "questions",
        ]
        assert (report["kind"], report["schema_version"], report["label"]) == (
            "horus-bench-kit-eval",
            1,
            "garden run",
        )
        assert [question["id"] for question in report["questions"]] == [
            f"fg-0{n}" for n in range(1, 10)
        ]
        assert list(report["questions"][0]) == QUESTION_KEYS
        assert report["summary"]["answer_correct_auto"] == {"n": 9, "correct": 8, "pct": 88.9}
        assert report["summary"]["status"] == {"ok": 9}
        assert report["summary"]["ttft_s"]["n"] == 9
        assert report["summary"]["source_basis"] == {"not_observable": 7}
        assert report["questions"][3]["missing_patterns"] == ["\\b72\\b"]
        assert len(fake_openai.requests) == 10

    def test_the_run_section_records_settings_but_no_path_or_key(
        self, run_args, fake_openai, example_answers, capsys, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("HBK_RUN_KEY", "test-key-not-a-secret")
        fake_openai.answer = example_answers()
        assert main(run_args("--api-key-env", "HBK_RUN_KEY", "--no-stream")) == 0
        report = written_report(capsys.readouterr().out)
        run = report["run"]
        assert list(run) == [
            "target",
            "endpoint",
            "model",
            "started_at",
            "finished_at",
            "completed",
            "kit_version",
            "warmup",
            "settings",
            "observed_models",
        ]
        assert (
            run["endpoint"]
            == "http://127.0.0.1:" + fake_openai.base_url.split(":")[2].split("/")[0]
        )
        assert (run["target"], run["model"], run["completed"], run["kit_version"]) == (
            "openai",
            "harbour-7b",
            True,
            __version__,
        )
        assert run["settings"]["stream"] is False
        assert run["settings"]["context_files"] == 8
        assert run["settings"]["system_prompt"] == "default"
        assert run["observed_models"] == ["fake-model-1"]
        assert report["testset"]["path"] == "testset.json"
        assert report["testset"]["filters"] == {"ids": None, "categories": None, "limit": None}
        text = json.dumps(report)
        assert "test-key-not-a-secret" not in text
        assert str(tmp_path) not in text and tmp_path.name not in text
        assert fake_openai.requests[0]["headers"]["Authorization"] == "Bearer test-key-not-a-secret"

    def test_context_files_are_sent_only_for_the_questions_that_have_one(
        self, run_args, fake_openai, capsys
    ):
        assert main(run_args("--ids", "fg-01,fg-09")) == 0
        users = [request["body"]["messages"][1]["content"] for request in fake_openai.requests]
        assert users[0].startswith("Context:\n[garden-handbook.txt]\nOpening hours")
        assert users[1] == "What is 15 multiplied by 4?"

    def test_an_item_context_file_wins_over_the_context_folder(
        self, run_args, copied_examples, fake_openai, capsys
    ):
        path = copied_examples / "testset.json"
        testset = read_json(path)
        testset["items"][0]["context_file"] = "corpus/tool-shed.txt"
        write_json(path, testset)
        assert main(run_args("--ids", "fg-01")) == 0
        assert "[tool-shed.txt]" not in fake_openai.requests[0]["body"]["messages"][1]["content"]
        assert "Hand tools" in fake_openai.requests[0]["body"]["messages"][1]["content"]

    def test_a_system_prompt_file_replaces_the_default(
        self, run_args, fake_openai, tmp_path, capsys
    ):
        prompt = tmp_path / "prompt.txt"
        prompt.write_text("Answer in one word.", encoding="utf-8")
        assert main(run_args("--ids", "fg-09", "--system-prompt-file", str(prompt))) == 0
        report = written_report(capsys.readouterr().out)
        assert fake_openai.requests[0]["body"]["messages"][0]["content"] == "Answer in one word."
        assert report["run"]["settings"]["system_prompt"] == "file"

    def test_filters_are_recorded(self, run_args, capsys):
        assert main(run_args("--category", "lookup", "--limit", "2")) == 0
        report = written_report(capsys.readouterr().out)
        assert [question["id"] for question in report["questions"]] == ["fg-01", "fg-02"]
        assert report["testset"]["items_run"] == 2
        assert report["testset"]["filters"] == {"ids": None, "categories": ["lookup"], "limit": 2}

    def test_an_unreachable_server_fails_the_run_and_keeps_the_report(
        self, run_args, fake_openai, capsys
    ):
        fake_openai.status = 500
        assert main(run_args("--ids", "fg-01")) == 1
        output = capsys.readouterr().out
        assert "[error] no question got an answer from http://127.0.0.1:" in output
        assert "[done]" not in output

    def test_a_failed_warmup_stops_before_the_questions(self, run_args, fake_openai, capsys):
        fake_openai.status = 500
        assert main(run_args("--warmup", "Say hello.")) == 1
        output = capsys.readouterr().out
        assert "[error] warmup failed: HTTP 500" in output
        assert reported_path(output.splitlines()) is None
        assert len(fake_openai.requests) == 1

    @pytest.mark.parametrize(
        ("extra", "message"),
        [
            (
                ["--category", "trivia"],
                "--category must be among lookup, numeric, multi_hop, not_in_corpus, direct",
            ),
            (["--limit", "0"], "--limit must be at least 1"),
            (["--label", "///"], "--label: label must contain at least one letter or digit"),
            (["--base-url", "localhost:8080"], "--base-url must start with http:// or https://"),
            (
                ["--base-url", "http://127.0.0.1:abc/v1"],
                "--base-url: Port could not be cast to integer value as 'abc'",
            ),
            (["--base-url", "http://127.0.0.1:99999/v1"], "--base-url: Port out of range 0-65535"),
            (["--max-tokens", "0"], "--max-tokens must be at least 1"),
            (["--timeout", "0"], "--timeout must be more than 0"),
            (["--context-dir", "nowhere"], "--context-dir 'nowhere' is not a folder"),
            (
                ["--system-prompt-file", "nowhere.txt"],
                "--system-prompt-file 'nowhere.txt' does not exist",
            ),
        ],
    )
    def test_bad_options_exit_with_2(self, run_args, capsys, extra, message):
        assert main(run_args(*extra)) == 2
        assert f"[error] {message}" in capsys.readouterr().out.splitlines()

    def test_required_options_are_named(self, capsys):
        assert main(["run"]) == 2
        assert capsys.readouterr().out.splitlines() == [
            "[error] --testset is required",
            "[error] --base-url is required",
            "[error] --model is required",
            "[error] --label is required",
        ]

    def test_filters_that_match_nothing_exit_with_2(self, run_args, capsys):
        assert main(run_args("--ids", "nope")) == 2
        assert "[error] no test items match the filters" in capsys.readouterr().out

    def test_the_endpoint_keeps_only_scheme_host_and_port(self):
        assert (
            endpoint_origin("https://user:pw@Models.Example:8443/v1?x=1")
            == "https://models.example:8443"
        )
        assert endpoint_origin("http://[::1]:8080/v1") == "http://[::1]:8080"
        assert endpoint_origin("http://127.0.0.1/v1") == "http://127.0.0.1"


class TestResummarizeAndCompare:
    @pytest.fixture
    def report_path(self, run_args, example_answers, fake_openai, capsys):
        fake_openai.answer = example_answers(fg_02="Ten hours.")
        assert main(run_args()) == 0
        line = next(
            line for line in capsys.readouterr().out.splitlines() if line.startswith("[done]")
        )
        return Path(line.removeprefix("[done] wrote "))

    def test_resummarize_counts_the_reviews(self, report_path, capsys):
        report = read_json(report_path)
        for question in report["questions"]:
            question["review"] = blank_review()
            for slot, reviewer in zip(question["review"], ("ana", "ben"), strict=True):
                slot.update(reviewer=reviewer, answer_correct=question["id"] != "fg-03")
        write_json(report_path, report)
        assert main(["resummarize", str(report_path)]) == 0
        printed = json.loads(capsys.readouterr().out)
        assert printed == read_json(report_path)["summary"]["manual_review"]
        assert printed["reviewed"] == 9 and printed["agreed_correct"] == 8

    def test_resummarize_refuses_another_kind(self, tmp_path, capsys):
        other = tmp_path / "other.json"
        write_json(other, {"kind": "acme-eval", "questions": []})
        assert main(["resummarize", str(other)]) == 2
        assert "not a horus-bench-kit-eval report (kind='acme-eval')" in capsys.readouterr().out

    def test_compare_prints_markdown_or_writes_a_file(self, report_path, tmp_path, capsys):
        assert main(["compare", str(report_path)]) == 0
        printed = capsys.readouterr().out
        assert printed.startswith("# Evaluation\n")
        assert "| Label | garden run |" in printed
        out = tmp_path / "compare.md"
        assert main(["compare", str(report_path), str(report_path), "--out", str(out)]) == 0
        assert capsys.readouterr().out == f"[done] wrote {out}\n"
        assert out.read_text(encoding="utf-8").startswith("# Evaluation comparison\n")

    def test_compare_takes_one_or_two_readable_reports(self, report_path, tmp_path, capsys):
        assert main(["compare", *[str(report_path)] * 3]) == 2
        assert capsys.readouterr().out == "[error] compare takes one or two reports\n"
        broken = tmp_path / "broken.json"
        broken.write_text("{", encoding="utf-8")
        assert main(["compare", str(broken)]) == 2


class TestEntryPoints:
    def run_module(self, *argv):
        source = Path(horus_bench_kit.__file__).resolve().parents[1]
        environment = {**os.environ, "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(
            [sys.executable, "-m", "horus_bench_kit.cli.eval", *argv],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            check=False,
        )

    def test_the_cli_runs_as_a_module(self, examples):
        result = self.run_module("validate", str(examples / "testset.json"))
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("[ok] testset.json")

    def test_version_and_help(self):
        assert self.run_module("--version").stdout.strip() == f"hbk-eval {__version__}"
        assert "validate" in self.run_module("--help").stdout

    def test_a_missing_command_is_an_argument_error(self, capsys):
        with pytest.raises(SystemExit) as raised:
            main([])
        assert raised.value.code == 2
