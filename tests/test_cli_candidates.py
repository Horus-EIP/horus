# SPDX-License-Identifier: Apache-2.0
import json
import re
import shutil
from pathlib import Path

import pytest

from conftest import GIB, RecordingShell, make_catalog, run_module
from horus_bench_kit import __version__
from horus_bench_kit.cli.candidates import (
    DEFAULT_RUNNER,
    CandidateRun,
    PublishedCandidateRun,
    RunnerProfile,
    argument_errors,
    build_parser,
    main,
)
from horus_bench_kit.llama_server import CANDIDATE_CONTAINER

REASON = "The excerpt says 7:00 am, 12 hours, Saturday mornings and a 10% discount."


def inspect_json(name, *, running=True):
    return json.dumps(
        [
            {
                "Name": f"/{name}",
                "RestartCount": 0,
                "State": {"Running": running, "OOMKilled": False},
                "Config": {"Image": "ghcr.io/ggml-org/llama.cpp:server-b11382", "Cmd": []},
                "HostConfig": {"Memory": 0},
                "NetworkSettings": {"Networks": {"bridge": {}}},
                "Mounts": [],
            }
        ]
    )


def bench_report(model):
    return {
        "kind": "horus-llama-bench",
        "schema_version": 1,
        "llama_cpp": {"build": "b11382"},
        "models": [{"file": model, "sha256": None}],
        "summary": [{"model": model, "test": "tg128", "n_depth": 0, "type_k": "f16", "type_v": "f16", "n_threads": 4, "avg_ts": 9.0, "stddev_ts": 0.1}],
    }


def eval_report():
    return {
        "kind": "horus-bench-kit-eval",
        "schema_version": 1,
        "run": {"completed": True},
        "summary": {
            "questions": 2,
            "answer_correct_auto": {"n": 2, "correct": 1, "pct": 50.0},
            "manual_review": {"answer_correct_pct": None, "pending": 2},
            "total_s": {"n": 2, "median": 4.0},
            "ttft_s": {"n": 2, "median": 0.5},
        },
    }


def option(command, name):
    return command[command.index(name) + 1]


class FakeServing(RecordingShell):
    def __init__(self, temp, *, healthy=True, fetch_fails=(), reply_ids=None):
        super().__init__(temp)
        self.healthy = healthy
        self.fetch_fails = set(fetch_fails)
        self.reply_ids = reply_ids
        self.candidate_running = False
        self.jobs = []

    def text(self, argv):
        if argv[:2] == ["docker", "inspect"] and argv[2] == CANDIDATE_CONTAINER:
            return inspect_json(CANDIDATE_CONTAINER, running=self.candidate_running) if self.candidate_running or not self.healthy else None
        if argv[:2] == ["docker", "rm"]:
            self.candidate_running = False
            return ""
        if argv[:2] == ["docker", "exec"]:
            command = argv[3:]
            if command[0] == "curl" and command[-1].endswith("/health"):
                return '{"status":"ok"}' if self.healthy else None
            if command[0] == "curl" and command[-1].endswith("/props"):
                return json.dumps({"build_info": "b11382-0a1b2c3d", "model_path": "/models/x.gguf", "default_generation_settings": {"n_ctx": 8192}})
            if command[:2] == ["cat", "/proc/1/status"]:
                return "Name:\tllama-server\nVmHWM:\t 3145728 kB\nVmRSS:\t 3000000 kB\nRssAnon:\t 500000 kB\nRssFile:\t 2500000 kB\n"
            if command[:2] == ["cat", "/sys/fs/cgroup/memory.peak"]:
                return "4294967296\n"
            if command[:2] == ["cat", "/sys/fs/cgroup/memory.events"]:
                return "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n"
        return super().text(argv)

    def docker_output(self, argv, timeout=60.0):
        return "llama_model_load: error loading model architecture: unknown model architecture: 'x'"

    def run_and_echo(self, argv, stdin_text=None):
        super().run_and_echo(argv, stdin_text)
        command = list(argv)
        joined = " ".join(command)
        if command[:3] == ["docker", "run", "-d"]:
            self.candidate_running = self.healthy
            return 0, ["c0ffee"]
        if command[:3] == ["docker", "run", "--rm"] and "/bin/sh" in command:
            file = next(part.split("=", 1)[1] for part in command if part.startswith("LLM_GGUF_FILE="))
            if file in self.fetch_fails:
                return 1, []
            folder = Path(option(command, "-v").rsplit(":/models", 1)[0])
            (folder / file).write_bytes(b"GGUF")
            return 0, []
        if "horus_bench_kit.cli.llama_bench" in joined:
            out_dir = Path(option(command, "--out-dir"))
            path = out_dir / f"{option(command, '--label')}-2026-10-08.json"
            out_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(bench_report(option(command, "--model"))), encoding="utf-8")
            return 0, [f"[done] wrote {path}"]
        if "horus_bench_kit.cli.eval" in joined:
            out_dir = Path(option(command, "--out-dir"))
            path = out_dir / f"{option(command, '--label')}-2026-10-08.json"
            out_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(eval_report()), encoding="utf-8")
            return 0, [f"[info] 2 question(s), writing {path}", f"[done] wrote {path}"]
        if command[0] == "prepare":
            return 0, []
        if stdin_text is not None:
            job = json.loads(stdin_text)
            self.jobs.append(job)
            ids = self.reply_ids if self.reply_ids is not None else [item["id"] for item in job["items"]]
            schema = {"type": "object", "required": ["verdict"]}
            content = json.dumps({"verdict": "supported", "reason": REASON})
            return 0, ["not json", *[json.dumps({"id": item_id, "schema": schema, "content": content}) for item_id in ids]]
        return 1, []


@pytest.fixture
def setup(tmp_path, examples):
    shutil.copytree(examples, tmp_path / "examples")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(make_catalog()), encoding="utf-8")
    return {"catalog": catalog, "probe": tmp_path / "examples" / "probe", "testset": tmp_path / "examples" / "testset.json"}


def probe_options(setup):
    probe = setup["probe"]
    return [
        "--probe-items", str(probe / "items.json"),
        "--probe-system", str(probe / "system.txt"),
        "--probe-user-template", str(probe / "user.txt"),
        "--probe-schema", str(probe / "schema.json"),
    ]


def summary_files(out_dir):
    summaries = sorted(out_dir.glob("model-candidates-*.json"))
    assert len(summaries) == 1
    return summaries[0], json.loads(summaries[0].read_text(encoding="utf-8"))


def models_with(tmp_path, *files):
    folder = tmp_path / "models"
    folder.mkdir(exist_ok=True)
    for name in files:
        (folder / name).write_bytes(b"GGUF")
    return str(folder)


def verdict_answers(body):
    claim = body["messages"][-1]["content"].rsplit("Claim: ", 1)[-1]
    verdict = "refuted" if "20 volunteer hours" in claim else "supported"
    return json.dumps({"verdict": verdict, "reason": REASON})


class TestArguments:
    def parse(self, *argv):
        parser = build_parser()
        PublishedCandidateRun.add_arguments(parser)
        return parser.parse_args(list(argv))

    def test_defaults(self):
        args = self.parse("--catalog", "c.json")
        assert args.steps == ["fetch", "bench"]
        assert (args.reasoning, args.reference, args.models_dir, args.out_dir) == ("off", None, "models", ".")
        assert (args.port, args.ctx_size) == (18080, 8192)
        assert argument_errors(args) + PublishedCandidateRun.argument_errors(args) == []

    def test_errors(self):
        args = self.parse(
            "--steps", "fetch,serve,eval,probe", "--limit", "0", "--llm-mem-limit", "lots", "--start-timeout", "0",
            "--port", "0", "--probe-schema", "s", "--probe-response-format", "r",
        )
        assert argument_errors(args) == [
            "--steps: unknown serve; choose among fetch, bench, probe, eval",
            "--limit must be at least 1",
            "--llm-mem-limit must look like 6g, 6144m or a number of bytes",
            "--start-timeout must be positive",
            "--catalog is required",
        ]
        assert PublishedCandidateRun.argument_errors(args) == [
            "--port must be between 1 and 65535",
            "--steps eval needs --testset",
            "--steps probe needs --probe-items",
            "--steps probe needs --probe-command, or --probe-system, --probe-user-template and --probe-schema "
            "(or --probe-response-format)",
            "give --probe-schema or --probe-response-format, not both",
        ]

    def test_a_product_can_restrict_the_categories(self):
        args = self.parse("--catalog", "c.json", "--category", "lookup,poetry")
        assert argument_errors(args, RunnerProfile(categories=("lookup", "numeric"))) == ["--category must be among lookup, numeric"]
        assert argument_errors(args) == []

    def test_an_unknown_only_id_stops_before_anything_runs(self, setup, capsys):
        shell = RecordingShell()
        assert main(["--catalog", str(setup["catalog"]), "--only", "delta-4b", "--dry-run"], shell=shell) == 2
        assert "unknown candidate or gguf id: delta-4b" in capsys.readouterr().out
        assert shell.calls == []

    def test_a_broken_catalog_is_reported(self, tmp_path, capsys):
        broken = tmp_path / "catalog.json"
        broken.write_text(json.dumps({"version": "1"}), encoding="utf-8")
        assert main(["--catalog", str(broken)]) == 2
        assert "[error] catalog: missing top-level llama_cpp" in capsys.readouterr().out

    def test_an_unreadable_catalog_is_reported_unless_the_product_lets_it_raise(self, tmp_path, capsys):
        missing = str(tmp_path / "missing.json")
        assert main(["--catalog", missing]) == 2
        assert capsys.readouterr().out.startswith("[error] catalog: cannot read missing.json: ")
        with pytest.raises(FileNotFoundError):
            main(["--catalog", missing], profile=RunnerProfile(input_errors=()))

    def test_every_option_has_help_and_a_product_can_change_it_and_place_its_own(self):
        helps = {a.option_strings[-1]: a.help for a in build_parser(DEFAULT_RUNNER, PublishedCandidateRun)._actions}
        assert all(helps.values())

        class Stacked(PublishedCandidateRun):
            @classmethod
            def add_serving_arguments(cls, parser):
                parser.add_argument("--stack-container")

        profile = RunnerProfile(option_help={"--catalog": "Which catalog."}, version_option=False)
        actions = {a.option_strings[-1]: a for a in build_parser(profile, Stacked)._actions}
        options = list(actions)
        assert options[options.index("--server-image") + 1] == "--stack-container"
        assert (actions["--catalog"].help, actions["--testset"].help) == ("Which catalog.", None)
        assert "--version" not in options and "--probe-command" in options


def test_dry_run_prints_the_plan_without_docker(setup, tmp_path, capsys):
    shell = RecordingShell()
    status = main(
        [
            "--catalog", str(setup["catalog"]), "--dry-run", "--only", "beta-2b", "--out-dir", str(tmp_path / "out"),
            "--steps", "fetch,bench,probe,eval", "--testset", str(setup["testset"]), "--limit", "3", *probe_options(setup),
        ],
        shell=shell,
    )
    assert status == 0
    assert shell.calls == []
    out = capsys.readouterr().out
    assert "beta-2b-q4km: Beta-2B Q4_K_M (MIT)" in out
    assert f"example/models-GGUF/resolve/{'1' * 40}/beta_2b_Q4_K_M.gguf" in out
    assert "-m horus_bench_kit.cli.llama_bench --known-models" in out
    assert "--label beta-2b-q4km-llama-bench" in out
    assert "--prompts 512 --generations 128 --depths 0" in out
    assert "  serve: docker run -d --name hbk-candidate -p 127.0.0.1:18080:8080" in out
    assert "--model /models/beta-2b-Q4_K_M.gguf --host 0.0.0.0 --port 8080 --ctx-size 8192 --reasoning off" in out
    assert "  probe: 3 items, template mode, on http://127.0.0.1:18080/v1" in out
    assert "-m horus_bench_kit.cli.eval run --base-url http://127.0.0.1:18080/v1 --model beta-2b-q4km" in out
    assert not (tmp_path / "out").exists()


class TestRun:
    def test_every_step_runs_and_the_candidate_is_removed(self, setup, tmp_path, fake_openai):
        fake_openai.answer = verdict_answers
        port = fake_openai.server.server_address[1]
        shell = FakeServing(tmp_path)
        out_dir = tmp_path / "results"
        status = main(
            [
                "--catalog", str(setup["catalog"]), "--only", "alpha-1b-q4km,beta-2b", "--steps", "fetch,bench,probe,eval",
                "--models-dir", str(tmp_path / "models"), "--out-dir", str(out_dir), "--reference", "bench-01",
                "--testset", str(setup["testset"]), "--port", str(port), "--llm-mem-limit", "6g", "--reasoning", "auto",
                "--ids", "cl-01,cl-02", *probe_options(setup),
            ],
            shell=shell,
        )
        assert status == 0
        fetches = [c for c in shell.calls if c[:3] == ["docker", "run", "--rm"]]
        assert [option(c, "-e") for c in fetches] == ["LLM_GGUF_FILE=alpha-1b-Q4_K_M.gguf", "LLM_GGUF_FILE=beta-2b-Q4_K_M.gguf"]
        assert any(part.endswith("fetch-model.sh:/opt/hbk/fetch-model.sh:ro") for part in fetches[0])
        runs = [c for c in shell.calls if c[:3] == ["docker", "run", "-d"]]
        assert len(runs) == 2
        assert option(runs[1], "-p") == f"127.0.0.1:{port}:8080"
        assert option(runs[1], "--memory") == str(6 * GIB)
        assert runs[1][-2:] == ["--reasoning", "auto"]
        assert [c for c in shell.calls if c[0] == "docker"][-1] == ["docker", "rm", "-f", CANDIDATE_CONTAINER]
        assert len(fake_openai.requests) == 4
        evals = [c for c in shell.calls if "horus_bench_kit.cli.eval" in " ".join(c)]
        assert option(evals[0], "--ids") == "cl-01,cl-02"

        summary_path, summary = summary_files(out_dir)
        assert (summary["kind"], summary["schema_version"], summary["label"]) == ("horus-model-candidates", 1, "model-candidates")
        run = summary["run"]
        assert (run["completed"], run["reasoning"], run["steps"]) == (True, "auto", ["fetch", "bench", "probe", "eval"])
        assert run["git_commit"] == "abc1234"
        assert run["stack_llm"] is None
        assert run["testset"]["path"] == "testset.json"
        assert run["sessions"][0]["llm_mem_limit_bytes"] == 6 * GIB
        assert summary["catalog"]["path"] == "catalog.json"
        assert summary["machine"]["reference"] == "bench-01"
        first = summary["variants"][0]
        assert first["fetch"] == {"status": "verified", "method": "docker", "path": "<models-dir>/alpha-1b-Q4_K_M.gguf"}
        assert first["problems"] == []
        assert first["llama_bench"]["speeds"][0]["tps"] == 9.0
        assert first["contract"]["json_valid"] == {"n": 2, "correct": 2, "pct": 100.0}
        assert first["contract"]["expected_correct"] == {"n": 2, "correct": 2, "pct": 100.0}
        assert first["eval"]["answer_correct_auto"]["pct"] == 50.0
        assert first["server"]["build"] == "b11382"
        assert first["server"]["command"][first["server"]["command"].index("-v") + 1] == "<models-dir>:/models:ro"
        assert first["memory"]["after_eval"]["process"]["vm_hwm_bytes"] == 3 * GIB
        assert first["memory"]["after_probe"]["cgroup_peak_bytes"] == 4 * GIB
        run_dir = summary_path.with_suffix("")
        for kind in ("llama_bench", "contract", "eval"):
            assert (out_dir / first["reports"][kind]).parent == run_dir
        contract = json.loads((out_dir / first["reports"]["contract"]).read_text(encoding="utf-8"))
        assert (contract["kind"], contract["run"]["mode"], contract["run"]["items"]) == ("horus-contract-probe", "template", 2)
        assert contract["llama_server"]["container"] == CANDIDATE_CONTAINER
        markdown = summary_path.with_suffix(".md").read_text(encoding="utf-8")
        assert "| Alpha-1B (baseline) | Q4_K_M, community | Apache-2.0 | 2/2 (100.0%) | 0 | 2/2 (100.0%) |" in markdown

    def test_a_failed_download_skips_the_model_for_every_later_step(self, setup, tmp_path):
        shell = FakeServing(tmp_path, fetch_fails={"beta-2b-Q4_K_M.gguf"})
        out_dir = tmp_path / "results"
        main(["--catalog", str(setup["catalog"]), "--only", "beta-2b", "--models-dir", str(tmp_path / "models"), "--out-dir", str(out_dir)], shell=shell)
        assert not any("horus_bench_kit.cli.llama_bench" in " ".join(c) for c in shell.calls)
        _path, summary = summary_files(out_dir)
        variant = summary["variants"][0]
        assert variant["fetch"]["status"] == "failed"
        assert variant["problems"] == ["download failed: fetch-model.sh exited with 1"]

    def test_a_model_that_does_not_load_is_reported_with_its_log(self, setup, tmp_path):
        shell = FakeServing(tmp_path, healthy=False)
        out_dir = tmp_path / "results"
        models = models_with(tmp_path, "alpha-1b-Q4_K_M.gguf", "beta-2b-Q4_K_M.gguf")
        main(
            ["--catalog", str(setup["catalog"]), "--only", "alpha-1b-q4km,beta-2b", "--steps", "probe", "--models-dir", models, "--out-dir", str(out_dir), *probe_options(setup)],
            shell=shell,
        )
        _path, summary = summary_files(out_dir)
        for variant in summary["variants"]:
            assert variant["problems"][0].startswith("llama-server stopped while loading the model:\n")
            assert "unknown model architecture" in variant["problems"][0]
            assert variant["reports"]["contract"] is None

    def test_a_model_that_was_never_fetched_is_not_served(self, setup, tmp_path):
        shell = FakeServing(tmp_path)
        out_dir = tmp_path / "results"
        models = models_with(tmp_path)
        main(["--catalog", str(setup["catalog"]), "--only", "alpha-1b-q4km", "--steps", "bench,probe", "--models-dir", models, "--out-dir", str(out_dir), *probe_options(setup)], shell=shell)
        assert not [c for c in shell.calls if c[:2] == ["docker", "run"]]
        _path, summary = summary_files(out_dir)
        missing = f"alpha-1b-Q4_K_M.gguf is not in {Path(models).resolve()}: run the fetch step first"
        assert summary["variants"][0]["problems"] == [missing, missing]

    def test_a_command_probe_gets_the_job_and_a_short_answer_is_flagged(self, setup, tmp_path):
        shell = FakeServing(tmp_path, reply_ids=["cl-01"])
        out_dir = tmp_path / "results"
        models = models_with(tmp_path, "alpha-1b-Q4_K_M.gguf")
        main(
            [
                "--catalog", str(setup["catalog"]), "--only", "alpha-1b-q4km", "--steps", "probe", "--models-dir", models,
                "--out-dir", str(out_dir), "--probe-items", str(setup["probe"] / "items.json"), "--ids", "cl-01,cl-02",
                "--probe-command", "probe --job -", "--probe-setup", "prepare probe", "--warmup", "Ready?",
            ],
            shell=shell,
        )
        assert ["prepare", "probe"] in shell.calls
        job = shell.jobs[0]
        assert job["endpoint"] == "http://127.0.0.1:18080/v1"
        assert job["warmup"] == "Ready?"
        assert [item["id"] for item in job["items"]] == ["cl-01", "cl-02"]
        assert job["items"][0]["context"].startswith("Fernhill Community Garden")
        _path, summary = summary_files(out_dir)
        variant = summary["variants"][0]
        assert variant["problems"] == ["the contract probe answered 1 of 2 questions (exit 0)"]
        assert variant["contract"]["replies"] == 1

    def test_a_product_plugs_its_own_serving_in(self, setup, tmp_path):
        events = []

        class SwappedRun(PublishedCandidateRun):
            def serving_trouble(self, serving):
                events.append(("check", [variant.id for variant in serving]))
                return None

            def announce_serving(self):
                events.append(("announce",))

            def take_over(self):
                events.append(("take over",))
                return None

            def give_back(self):
                events.append(("give back",))

            def server_command(self, variant):
                return ["docker", "run", "-d", "--name", self.container, "--network-alias", "model-server", "image", variant.file]

        shell = FakeServing(tmp_path)
        out_dir = tmp_path / "results"
        models = models_with(tmp_path, "alpha-1b-Q4_K_M.gguf")
        status = main(
            ["--catalog", str(setup["catalog"]), "--only", "alpha-1b-q4km", "--steps", "probe", "--models-dir", models, "--out-dir", str(out_dir), "--probe-items", str(setup["probe"] / "items.json"), "--probe-command", "probe", "--limit", "1"],
            run_class=SwappedRun,
            shell=shell,
        )
        assert status == 0
        assert events == [("check", ["alpha-1b-q4km"]), ("announce",), ("take over",), ("give back",)]
        assert ["docker", "run", "-d", "--name", CANDIDATE_CONTAINER, "--network-alias", "model-server", "image", "alpha-1b-Q4_K_M.gguf"] in shell.calls

    def test_a_refusal_marks_every_model_and_nothing_starts(self, setup, tmp_path):
        class Refused(PublishedCandidateRun):
            def serving_trouble(self, serving):
                return "the shared server is busy"

        shell = FakeServing(tmp_path)
        out_dir = tmp_path / "results"
        models = models_with(tmp_path, "alpha-1b-Q4_K_M.gguf", "beta-2b-Q4_K_M.gguf")
        main(
            ["--catalog", str(setup["catalog"]), "--only", "alpha-1b-q4km,beta-2b", "--steps", "probe", "--models-dir", models, "--out-dir", str(out_dir), "--probe-items", str(setup["probe"] / "items.json"), "--probe-command", "probe"],
            run_class=Refused,
            shell=shell,
        )
        assert not [c for c in shell.calls if c[:2] == ["docker", "run"]]
        _path, summary = summary_files(out_dir)
        assert [v["problems"] for v in summary["variants"]] == [["not served: the shared server is busy"]] * 2

    def test_the_base_engine_needs_a_serving_mode(self):
        assert CandidateRun.add_arguments(build_parser()) is None
        assert CandidateRun.argument_errors(None) == []


def test_resume_adds_the_serving_steps_to_the_benchmark_summary(setup, tmp_path):
    shell = FakeServing(tmp_path)
    out_dir = tmp_path / "results"
    common = ["--catalog", str(setup["catalog"]), "--models-dir", str(tmp_path / "models"), "--probe-items", str(setup["probe"] / "items.json"), "--probe-command", "probe", "--testset", str(setup["testset"]), "--limit", "1"]
    main([*common, "--only", "alpha-1b-q4km,gamma-3b-q8", "--steps", "fetch,bench", "--out-dir", str(out_dir)], shell=shell)
    summary_path, first = summary_files(out_dir)
    assert first["run"]["steps"] == ["fetch", "bench"]
    assert shell.jobs == []
    assert main([*common, "--resume", str(summary_path), "--steps", "probe,eval"], shell=shell) == 0
    _same_path, resumed = summary_files(out_dir)
    assert [v["id"] for v in resumed["variants"]] == ["alpha-1b-q4km", "gamma-3b-q8"]
    assert resumed["run"]["steps"] == ["fetch", "bench", "probe", "eval"]
    assert resumed["run"]["started_at"] == first["run"]["started_at"]
    assert [s["steps"] for s in resumed["run"]["sessions"]] == [["fetch", "bench"], ["probe", "eval"]]
    for variant in resumed["variants"]:
        assert variant["fetch"]["status"] == "verified"
        assert all(variant["reports"].values())
    assert len(shell.jobs) == 2


def test_resume_retries_a_download_that_failed(setup, tmp_path):
    out_dir = tmp_path / "results"
    common = ["--catalog", str(setup["catalog"]), "--models-dir", str(tmp_path / "models"), "--steps", "fetch"]
    main([*common, "--only", "alpha-1b-q4km,beta-2b", "--out-dir", str(out_dir)], shell=FakeServing(tmp_path, fetch_fails={"beta-2b-Q4_K_M.gguf"}))
    summary_path, first = summary_files(out_dir)
    assert [v["fetch"]["status"] for v in first["variants"]] == ["verified", "failed"]
    assert main([*common, "--resume", str(summary_path)], shell=FakeServing(tmp_path)) == 0
    _same_path, resumed = summary_files(out_dir)
    assert [v["fetch"]["status"] for v in resumed["variants"]] == ["verified", "verified"]
    assert [v["problems"] for v in resumed["variants"]] == [[], []]


def test_resume_refuses_a_file_that_is_not_a_summary_or_is_newer(setup, tmp_path, capsys):
    other = tmp_path / "eval.json"
    other.write_text(json.dumps({"kind": "horus-bench-kit-eval"}), encoding="utf-8")
    assert main(["--catalog", str(setup["catalog"]), "--resume", str(other)]) == 2
    assert "is not a horus-model-candidates summary" in capsys.readouterr().out
    newer = tmp_path / "newer.json"
    newer.write_text(json.dumps({"kind": "horus-model-candidates", "schema_version": 2}), encoding="utf-8")
    assert main(["--catalog", str(setup["catalog"]), "--resummarize", str(newer)]) == 2
    assert "has schema_version 2, newer than the 1 read here" in capsys.readouterr().out


def test_resummarize_rebuilds_from_the_sub_reports(setup, tmp_path):
    shell = FakeServing(tmp_path)
    out_dir = tmp_path / "results"
    models = models_with(tmp_path, "alpha-1b-Q4_K_M.gguf")
    main(["--catalog", str(setup["catalog"]), "--only", "alpha-1b-q4km", "--steps", "eval", "--models-dir", models, "--out-dir", str(out_dir), "--testset", str(setup["testset"])], shell=shell)
    summary_path, summary = summary_files(out_dir)
    eval_path = out_dir / summary["variants"][0]["reports"]["eval"]
    reviewed = json.loads(eval_path.read_text(encoding="utf-8"))
    reviewed["summary"]["manual_review"] = {"answer_correct_pct": 55.0, "pending": 0}
    eval_path.write_text(json.dumps(reviewed), encoding="utf-8")
    summary_path.with_suffix(".md").unlink()
    assert main(["--catalog", str(setup["catalog"]), "--resummarize", str(summary_path)]) == 0
    refreshed = json.loads(summary_path.read_text(encoding="utf-8"))
    assert refreshed["variants"][0]["eval"]["answer_correct_reviewed_pct"] == 55.0
    assert refreshed["variants"][0]["memory"] == summary["variants"][0]["memory"]
    assert "| 55.0% |" in summary_path.with_suffix(".md").read_text(encoding="utf-8")


def test_no_part_of_the_host_models_folder_reaches_the_reports(setup, tmp_path, monkeypatch, host_folder, host_folder_leaks):
    monkeypatch.setattr(PublishedCandidateRun, "model_missing", lambda self, variant: False)
    shell = FakeServing(tmp_path)
    out_dir = tmp_path / "results"
    main(
        ["--catalog", str(setup["catalog"]), "--only", "alpha-1b-q4km", "--steps", "probe", "--ids", "cl-01", "--models-dir", host_folder, "--out-dir", str(out_dir), "--probe-items", str(setup["probe"] / "items.json"), "--probe-command", "probe"],
        shell=shell,
    )
    started = next(c for c in shell.calls if c[:3] == ["docker", "run", "-d"])
    assert host_folder_leaks(" ".join(started)) != []
    _summary_path, summary = summary_files(out_dir)
    assert summary["run"]["sessions"][-1]["models_dir"] == "<models-dir>"
    assert "<models-dir>:/models:ro" in summary["variants"][0]["server"]["command"]
    written = sorted(path for path in out_dir.rglob("*") if path.is_file())
    assert len(written) == 3
    for path in written:
        assert host_folder_leaks(path.read_text(encoding="utf-8")) == [], path.name


def test_paths_are_recorded_relative_to_the_profile_root_or_by_name(setup, tmp_path):
    out_dir = tmp_path / "results"
    profile = RunnerProfile(base_dir=tmp_path)
    main(["--catalog", str(setup["catalog"]), "--only", "alpha-1b-q4km", "--steps", "fetch", "--models-dir", str(tmp_path / "models"), "--out-dir", str(out_dir), "--testset", str(setup["testset"])], profile=profile, shell=FakeServing(tmp_path))
    _path, summary = summary_files(out_dir)
    assert summary["catalog"]["path"] == "catalog.json"
    assert summary["run"]["testset"]["path"] == "examples/testset.json"
    assert re.fullmatch(r"[0-9a-f]{64}", summary["catalog"]["sha256"])


def test_resume_keeps_the_machine_reference_unless_another_is_given(setup, tmp_path):
    out_dir = tmp_path / "results"
    common = ["--catalog", str(setup["catalog"]), "--models-dir", str(tmp_path / "models"), "--steps", "fetch", "--only", "alpha-1b-q4km"]
    main([*common, "--out-dir", str(out_dir), "--reference", "my-laptop"], shell=FakeServing(tmp_path))
    summary_path, first = summary_files(out_dir)
    assert first["machine"]["reference"] == "my-laptop"
    assert main([*common, "--resume", str(summary_path)], shell=FakeServing(tmp_path)) == 0
    assert summary_files(out_dir)[1]["machine"]["reference"] == "my-laptop"
    assert main([*common, "--resume", str(summary_path), "--reference", "lab-box"], shell=FakeServing(tmp_path)) == 0
    assert summary_files(out_dir)[1]["machine"]["reference"] == "lab-box"


def test_the_tool_also_runs_as_a_module():
    completed = run_module("horus_bench_kit.cli.candidates", "--help")
    assert completed.returncode == 0
    assert "--probe-command" in completed.stdout
    version = run_module("horus_bench_kit.cli.candidates", "--version")
    assert (version.returncode, version.stdout.strip()) == (0, f"hbk-model-candidates {__version__}")
