# SPDX-License-Identifier: Apache-2.0
import json
import shlex
import shutil
import sys

import pytest

from conftest import RecordingShell, run_module
from horus_bench_kit.cli.contract_probe import main
from horus_bench_kit.files import read_json

REASON = "The excerpt says 7:00 am, 12 hours, Saturday mornings and a 10% discount."


@pytest.fixture
def probe_dir(tmp_path, examples):
    target = tmp_path / "examples"
    shutil.copytree(examples, target)
    return target / "probe"


@pytest.fixture
def verdicts(examples):
    items = json.loads((examples / "probe" / "items.json").read_text(encoding="utf-8"))["items"]
    expected = {item["question"]: item["expected"]["verdict"] for item in items}

    def factory(**wrong):
        def answer(body):
            claim = body["messages"][-1]["content"].rsplit("Claim: ", 1)[-1].strip()
            item_id = next((item["id"] for item in items if item["question"] == claim), None)
            verdict = wrong.get((item_id or "").replace("-", "_")) or expected.get(claim, "not_stated")
            return json.dumps({"verdict": verdict, "reason": REASON})

        return answer

    return factory


def template_args(probe_dir, fake_openai, out_dir, *extra):
    return [
        "--label", "probe-run",
        "--out-dir", str(out_dir),
        "--items", str(probe_dir / "items.json"),
        "--base-url", fake_openai.base_url,
        "--model", "alpha-1b",
        "--system", str(probe_dir / "system.txt"),
        "--user-template", str(probe_dir / "user.txt"),
        "--schema", str(probe_dir / "schema.json"),
        *extra,
    ]


def only_report(folder):
    [saved] = list(folder.glob("*.json"))
    return saved, read_json(saved)


class TestTemplateMode:
    def test_every_item_is_asked_checked_and_scored(self, probe_dir, fake_openai, verdicts, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("HBK_TEST_KEY", "secret-value")
        fake_openai.answer = verdicts(cl_05="supported")
        out_dir = tmp_path / "results"
        assert main(template_args(probe_dir, fake_openai, out_dir, "--api-key-env", "HBK_TEST_KEY", "--warmup", "Ready?")) == 0
        saved, report = only_report(out_dir)
        assert saved.name.startswith("probe-run-")
        assert (report["kind"], report["schema_version"], report["label"]) == ("horus-contract-probe", 1, "probe-run")
        run = report["run"]
        assert list(run) == ["mode", "started_at", "finished_at", "completed", "endpoint", "kit_version", "warmup", "items", "settings"]
        assert (run["mode"], run["completed"], run["items"], run["warmup"]) == ("template", True, 8, "Ready?")
        assert run["endpoint"].startswith("http://127.0.0.1:") and "/v1" not in run["endpoint"]
        assert len(run["settings"]["response_format_sha256"]) == 64
        assert report["model"] == {"name": "alpha-1b"}
        summary = report["summary"]
        assert summary["json_valid"] == {"n": 8, "correct": 8, "pct": 100.0}
        assert summary["expected_correct"] == {"n": 8, "correct": 7, "pct": 87.5}
        assert summary["patterns_correct"] == {"n": 4, "correct": 4, "pct": 100.0}
        assert list(summary["by_category"]) == ["supported", "refuted", "not_stated"]
        wrong = next(record for record in report["replies"] if record["id"] == "cl-05")
        assert (wrong["expected"], wrong["expected_correct"]) == ({"verdict": "refuted"}, False)
        bodies = [request["body"] for request in fake_openai.requests]
        assert len(bodies) == 9
        assert "Opening hours" in bodies[1]["messages"][1]["content"]
        assert bodies[1]["response_format"]["json_schema"]["schema"]["required"] == ["verdict", "reason"]
        assert fake_openai.requests[1]["headers"]["Authorization"] == "Bearer secret-value"
        assert "secret-value" not in saved.read_text(encoding="utf-8")
        output = capsys.readouterr().out
        assert "[info] 8 item(s), template mode, writing" in output
        assert f"[done] wrote {saved}" in output

    def test_filters_choose_the_items(self, probe_dir, fake_openai, verdicts, tmp_path):
        fake_openai.answer = verdicts()
        assert main(template_args(probe_dir, fake_openai, tmp_path / "out", "--category", "refuted", "--limit", "2")) == 0
        _saved, report = only_report(tmp_path / "out")
        assert [record["id"] for record in report["replies"]] == ["cl-02", "cl-03"]

    def test_a_server_that_answers_nothing_fails_the_run_but_keeps_the_report(self, probe_dir, fake_openai, tmp_path, capsys):
        fake_openai.status = 500
        assert main(template_args(probe_dir, fake_openai, tmp_path / "out", "--ids", "cl-01")) == 1
        _saved, report = only_report(tmp_path / "out")
        assert report["summary"]["failures"] == {"request_error": 1}
        assert "[error] no item got a reply" in capsys.readouterr().out

    def test_a_schema_with_a_boolean_subschema_is_checked_not_crashed(self, probe_dir, fake_openai, verdicts, tmp_path):
        schema = json.loads((probe_dir / "schema.json").read_text(encoding="utf-8"))
        schema["properties"]["reason"] = True
        schema["properties"]["verdict"]["minLength"] = "3"
        (probe_dir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
        fake_openai.answer = verdicts()
        assert main(template_args(probe_dir, fake_openai, tmp_path / "out", "--ids", "cl-01")) == 0
        _saved, report = only_report(tmp_path / "out")
        assert report["replies"][0]["violations"] == ["$.verdict: the checker does not support minLength '3'"]


class TestPreparedMode:
    def test_prepared_requests_are_sent_as_they_are(self, fake_openai, tmp_path, verdicts):
        fake_openai.answer = verdicts()
        schema = {"type": "object", "required": ["verdict"]}
        lines = [
            {
                "id": "p-1",
                "category": "supported",
                "question": "The garden gate opens at 7:00 am on weekdays.",
                "expected": {"verdict": "supported"},
                "payload": {
                    "model": "own",
                    "messages": [{"role": "user", "content": "Claim: The garden gate opens at 7:00 am on weekdays."}],
                    "max_tokens": 64,
                    "response_format": {"type": "json_schema", "schema": schema},
                },
                "meta": {"labels": ["E1"], "retrieved_titles": ["garden-handbook.txt"]},
            }
        ]
        prepared = tmp_path / "requests.jsonl"
        prepared.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
        status = main(["--label", "prepared", "--out-dir", str(tmp_path / "out"), "--prepared", str(prepared), "--base-url", fake_openai.base_url])
        assert status == 0
        _saved, report = only_report(tmp_path / "out")
        record = report["replies"][0]
        assert (record["json_valid"], record["expected_correct"]) == (True, True)
        assert (record["labels"], record["retrieved_titles"]) == (["E1"], ["garden-handbook.txt"])
        assert fake_openai.requests[0]["body"]["model"] == "own"
        assert report["run"]["mode"] == "prepared"


class TestCommandMode:
    def test_the_example_adapter_speaks_probe_v1(self, probe_dir, fake_openai, verdicts, tmp_path, capsys):
        fake_openai.answer = verdicts()
        command = shlex.join([sys.executable, str(probe_dir / "command_probe.py")])
        status = main(
            [
                "--label", "command-run", "--out-dir", str(tmp_path / "out"), "--items", str(probe_dir / "items.json"),
                "--probe-command", command, "--base-url", fake_openai.base_url, "--limit", "3",
            ]
        )
        assert status == 0
        _saved, report = only_report(tmp_path / "out")
        assert report["run"]["mode"] == "command"
        assert report["run"]["settings"] == {"protocol": 1}
        assert [record["json_valid"] for record in report["replies"]] == [True, True, True]
        assert report["summary"]["expected_correct"]["pct"] == 100.0
        assert "Opening hours" in fake_openai.requests[0]["body"]["messages"][1]["content"]
        assert "[info] " in capsys.readouterr().out

    def test_the_job_carries_context_and_endpoint_and_a_failed_setup_stops(self, probe_dir, tmp_path, capsys):
        class Fake(RecordingShell):
            def run_and_echo(self, argv, stdin_text=None):
                super().run_and_echo(argv, stdin_text)
                if argv[0] == "setup":
                    return 3, []
                job = json.loads(stdin_text)
                return 0, [json.dumps({"id": item["id"], "schema": {"type": "object"}, "content": '{"verdict": "supported"}'}) for item in job["items"]]

        shell = Fake()
        args = ["--label", "c", "--out-dir", str(tmp_path / "out"), "--items", str(probe_dir / "items.json"), "--probe-command", "probe --json", "--ids", "cl-01"]
        assert main([*args, "--base-url", "http://127.0.0.1:9/v1", "--warmup", "Ready?"], shell=shell) == 0
        job = json.loads(shell.inputs[-1])
        assert job["warmup"] == "Ready?"
        assert job["endpoint"] == "http://127.0.0.1:9/v1"
        assert job["items"][0]["id"] == "cl-01"
        assert job["items"][0]["context"].startswith("Fernhill Community Garden: member handbook")
        assert shell.calls[-1] == ["probe", "--json"]
        failing = Fake()
        assert main([*args, "--out-dir", str(tmp_path / "out2"), "--probe-setup", "setup now"], shell=failing) == 1
        assert "[error] the probe setup exited with 3; nothing was probed" in capsys.readouterr().out
        assert failing.calls == [["setup", "now"]]
        assert not (tmp_path / "out2").exists()

    def test_items_without_a_reply_line_are_reported(self, probe_dir, tmp_path, capsys):
        class Fake(RecordingShell):
            def run_and_echo(self, argv, stdin_text=None):
                return 1, ['{"id": "cl-01", "content": "{}", "schema": {"type": "object"}}']

        args = ["--label", "c", "--out-dir", str(tmp_path / "out"), "--items", str(probe_dir / "items.json"), "--probe-command", "probe", "--limit", "2"]
        assert main(args, shell=Fake()) == 0
        _saved, report = only_report(tmp_path / "out")
        assert report["run"]["completed"] is False
        assert len(report["replies"]) == 1
        assert "[warn] 1 of 2 items got no reply line (exit 1)" in capsys.readouterr().out


class TestInputs:
    @pytest.mark.parametrize(
        ("argv", "message"),
        [
            ([], "--label is required"),
            (["--label", "x"], "--items is required"),
            (["--label", "x", "--items", "i.json"], "--base-url is required"),
            (["--label", "x", "--items", "i.json", "--base-url", "ftp://x"], "--base-url must start with http:// or https://"),
            (["--label", "x", "--items", "i.json", "--base-url", "http://x:abc/v1"], "--base-url: Port could not be cast to integer value as 'abc'"),
            (["--label", "x", "--items", "i.json", "--base-url", "http://x"], "--system is required"),
            (["--label", "x", "--items", "i.json", "--base-url", "http://x", "--schema", "s", "--response-format", "r"], "give --schema or --response-format"),
            (["--label", "x", "--prepared", "p.jsonl", "--items", "i.json", "--base-url", "http://x"], "give --items or --prepared, not both"),
            (["--label", "x", "--prepared", "p.jsonl", "--base-url", "http://x", "--warmup", "w"], "--warmup works with --items, not with --prepared"),
            (["--label", "x", "--items", "i.json", "--probe-command", "p", "--limit", "0"], "--limit must be at least 1"),
        ],
    )
    def test_bad_options_are_named(self, argv, message, capsys):
        assert main(argv) == 2
        assert f"[error] {message}" in capsys.readouterr().out

    def test_a_broken_item_file_is_refused(self, tmp_path, capsys):
        items = tmp_path / "items.json"
        items.write_text(json.dumps([{"id": "a", "question": "q", "context_file": "missing.txt"}]), encoding="utf-8")
        assert main(["--label", "x", "--items", str(items), "--probe-command", "p"]) == 2
        assert "[error] items.json: item a: context_file 'missing.txt' does not exist" in capsys.readouterr().out

    def test_no_item_matching_the_filters(self, probe_dir, capsys):
        assert main(["--label", "x", "--items", str(probe_dir / "items.json"), "--probe-command", "p", "--ids", "none"]) == 2
        assert "[error] no probe item matches the filters" in capsys.readouterr().out


def test_the_tool_also_runs_as_a_module():
    completed = run_module("horus_bench_kit.cli.contract_probe", "--version")
    assert completed.returncode == 0
    assert completed.stdout.startswith("hbk-contract-probe ")
