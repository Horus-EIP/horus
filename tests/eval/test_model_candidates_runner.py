import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from model_candidates import CANDIDATE_CONTAINER, Variant, load_catalog

BENCH_DIR = Path(__file__).resolve().parents[2] / "scripts" / "benchmarks"
STACK_ARGS = ["--model", "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf", "--alias", "qwen3-4b", "--host", "0.0.0.0", "--port", "8080", "--threads", "4", "--metrics"]
AGENT_ENV = ("PATH=/usr/local/bin:/usr/bin:/bin", "LLM_BACKEND=vllm", "LLM_VLLM_MODEL=qwen3-4b")
CACHE_REFUSAL = (
    ". Set AGENT_RESPONSE_CACHE=0 in src/infra/.env, recreate the agent (cd src/infra && docker compose up -d agent) "
    "and run again, or pass --allow-response-cache"
)


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location("run_model_candidates", BENCH_DIR / "run-model-candidates.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_model_candidates"] = module
    spec.loader.exec_module(module)
    return module


def parse(runner, *argv):
    return runner.build_parser().parse_args(list(argv))


def run_main(runner, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["run-model-candidates.py", *argv])
    return runner.main()


def inspect_json(name, *, running=True, args=STACK_ARGS, networks=("infra_horus-net",), memory=6 * 2**30, oom=False, env=()):
    return json.dumps(
        [
            {
                "Name": f"/{name}",
                "RestartCount": 0,
                "State": {"Running": running, "OOMKilled": oom},
                "Config": {"Image": "ghcr.io/ggml-org/llama.cpp:server-b11382", "Cmd": list(args), "Env": list(env)},
                "HostConfig": {"Memory": memory},
                "NetworkSettings": {"Networks": {network: {} for network in networks}},
                "Mounts": [],
            }
        ]
    )


class FakeStack:
    def __init__(self, tmp_path, *, stack=True, healthy=True, probe_ids=None, agent_env=AGENT_ENV, stop_fails=False, start_fails=False):
        self.tmp_path = tmp_path
        self.stack = stack
        self.healthy = healthy
        self.probe_ids = probe_ids
        self.agent_env = agent_env
        self.stop_fails = stop_fails
        self.start_fails = start_fails
        self.llm_running = stack
        self.docker_calls = []
        self.commands = []
        self.candidate_running = False
        self.jobs = []

    def docker_text(self, argv, timeout=60.0):
        self.docker_calls.append(list(argv))
        verb = argv[0]
        if verb == "inspect" and argv[1] == "llm":
            return inspect_json("llm", running=self.llm_running) if self.stack else None
        if verb == "inspect" and argv[1] == "agent":
            return None if self.agent_env is None else inspect_json("agent", env=self.agent_env)
        if verb == "inspect" and argv[1] == CANDIDATE_CONTAINER:
            return inspect_json(CANDIDATE_CONTAINER, running=self.candidate_running) if self.candidate_running or not self.healthy else None
        if verb == "rm":
            self.candidate_running = False
            return ""
        if verb == "stop":
            self.llm_running = self.llm_running and self.stop_fails
            return None if self.stop_fails else ""
        if verb == "start":
            self.llm_running = self.llm_running or not self.start_fails
            return None if self.start_fails else ""
        if verb == "cp":
            return ""
        if verb == "exec":
            command = argv[2:]
            if command[0] == "curl" and command[-1].endswith("/health"):
                return '{"status":"ok"}' if self.healthy else None
            if command[0] == "curl" and command[-1].endswith("/props"):
                return json.dumps({"build_info": "b11382-11fe0215", "model_path": "/models/x.gguf", "default_generation_settings": {"n_ctx": 8192}})
            if command[:2] == ["cat", "/proc/1/status"]:
                return "Name:\tllama-server\nVmHWM:\t 3145728 kB\nVmRSS:\t 3000000 kB\nRssAnon:\t 500000 kB\nRssFile:\t 2500000 kB\n"
            if command[:2] == ["cat", "/sys/fs/cgroup/memory.peak"]:
                return "4294967296\n"
            if command[:2] == ["cat", "/sys/fs/cgroup/memory.events"]:
                return "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n"
        return None

    def run_and_echo(self, command, stdin_text=None):
        self.commands.append(list(command))
        joined = " ".join(command)
        if command[:3] == ["docker", "run", "-d"]:
            self.candidate_running = self.healthy
            return 0, ["c0ffee"]
        if "run-llama-bench.py" in joined:
            out_dir = Path(command[command.index("--out-dir") + 1])
            label = command[command.index("--label") + 1]
            model = command[command.index("--model") + 1]
            path = out_dir / f"{label}-2026-10-06.json"
            out_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(bench_report(model)), encoding="utf-8")
            return 0, [f"[done] wrote {path}"]
        if "run-eval.py" in joined:
            out_dir = Path(command[command.index("--out-dir") + 1])
            label = command[command.index("--label") + 1]
            path = out_dir / f"{label}-2026-10-06.json"
            out_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(eval_report()), encoding="utf-8")
            return 0, [f"[info] 2 question(s), writing {path}", f"[done] wrote {path}"]
        if command[:3] == ["docker", "exec", "-i"]:
            job = json.loads(stdin_text)
            self.jobs.append(job)
            ids = self.probe_ids if self.probe_ids is not None else [item["id"] for item in job["items"]]
            lines = ["not json"]
            for item_id in ids:
                content = json.dumps({"status": "ok", "answer": "$250 per night.", "sources": ["S1"]})
                lines.append(json.dumps(probe_reply(item_id, content)))
            return 0, lines
        return 1, []


def probe_reply(item_id, content):
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["ok", "not_found"]},
            "answer": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "string", "enum": ["S1"]}},
        },
        "required": ["status", "answer", "sources"],
        "additionalProperties": False,
    }
    return {
        "id": item_id,
        "labels": ["S1"],
        "sources_by_label": {"S1": {"title": "4_Expense_Policy.md"}},
        "schema": schema,
        "content": content,
        "finish_reason": "stop",
        "usage": {"prompt_tokens": 700, "completion_tokens": 20},
        "timings": {"prompt_n": 700, "prompt_ms": 14000.0, "predicted_n": 20, "predicted_ms": 2000.0},
        "wall_s": 16.0,
    }


def bench_report(model):
    return {
        "kind": "horus-llama-bench",
        "llama_cpp": {"build": "b11382"},
        "models": [{"file": model, "sha256": None}],
        "summary": [{"model": model, "test": "tg128", "n_depth": 0, "type_k": "f16", "type_v": "f16", "n_threads": 4, "avg_ts": 9.0, "stddev_ts": 0.1}],
    }


def eval_report():
    return {
        "kind": "horus-eval",
        "run": {"completed": True},
        "summary": {"questions": 2, "answer_correct_auto": {"n": 2, "correct": 1, "pct": 50.0}, "total_s": {"n": 2, "median": 40.0}},
        "resources": {"stack_peak_mem_bytes": 8 * 2**30, "container_peak_mem_bytes": {CANDIDATE_CONTAINER: 3 * 2**30}},
    }


class FakeInstallError(Exception):
    def __init__(self, code, headline, detail="", fix=""):
        super().__init__(headline)
        self.code, self.headline, self.detail, self.fix = code, headline, detail, fix


def fake_installer(fail_for=()):
    downloads = []

    class Log:
        def __init__(self, path):
            self.path = path
            self.closed = None

        def close(self, code):
            self.closed = code

    class ModelDownload:
        def __init__(self, log, entry, models_dir, mirrors, token=None):
            self.entry, self.models_dir, self.mirrors = entry, Path(models_dir), mirrors

        def run(self):
            downloads.append(self.entry)
            if self.entry.file in fail_for:
                raise FakeInstallError(44, "The language model could not be downloaded.", "HTTP 404 Not Found")
            target = self.models_dir / self.entry.file
            target.write_bytes(b"GGUF")
            return target

    manager = SimpleNamespace(ModelEntry=lambda **fields: SimpleNamespace(**fields), ModelDownload=ModelDownload)
    common = SimpleNamespace(Log=Log, InstallError=FakeInstallError)
    return SimpleNamespace(common=common, manager=manager), downloads


@pytest.fixture
def quiet_host(runner, monkeypatch):
    monkeypatch.setattr(runner, "docker_facts", lambda: None)
    monkeypatch.setattr(runner, "collect_host", lambda path: {"cpu_model": ("Test CPU", "test"), "ram_total_bytes": (16 * 2**30, "test")})
    monkeypatch.setattr(runner, "git_commit", lambda: "abc1234")


def install_fakes(runner, monkeypatch, stack, installer=None):
    monkeypatch.setattr(runner, "docker_text", stack.docker_text)
    monkeypatch.setattr(runner, "run_and_echo", stack.run_and_echo)
    monkeypatch.setattr(runner, "docker_output", lambda argv, timeout=60.0: "llama_model_load: error loading model architecture: unknown model architecture: 'x'")
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    modules, downloads = installer or fake_installer()
    monkeypatch.setattr(runner, "installer_modules", lambda: modules)
    return downloads


def models_with(tmp_path, *files):
    folder = tmp_path / "models"
    folder.mkdir(exist_ok=True)
    for name in files:
        (folder / name).write_bytes(b"GGUF")
    return str(folder)


def summary_files(out_dir):
    summaries = sorted(out_dir.glob("model-candidates-*.json"))
    assert len(summaries) == 1
    return summaries[0], json.loads(summaries[0].read_text(encoding="utf-8"))


class TestArguments:
    def test_defaults(self, runner):
        args = parse(runner)
        assert args.steps == ["fetch", "bench", "probe", "eval"]
        assert args.reasoning == "off"
        assert args.reference == "cpu16"
        assert runner.argument_errors(args) == []

    def test_errors(self, runner):
        args = parse(runner, "--steps", "fetch,serve", "--category", "lookup,poetry", "--limit", "0", "--llm-mem-limit", "lots", "--start-timeout", "0")
        assert runner.argument_errors(args) == [
            "--steps: unknown serve; choose among fetch, bench, probe, eval",
            "--category must be among lookup, numeric, multi_hop, not_in_corpus, direct",
            "--limit must be at least 1",
            "--llm-mem-limit must look like 6g, 6144m or a number of bytes",
            "--start-timeout must be positive",
        ]

    def test_an_unknown_only_id_stops_before_anything_runs(self, runner, monkeypatch, capsys):
        assert run_main(runner, monkeypatch, "--only", "phi-5", "--dry-run") == 2
        assert "unknown candidate or gguf id: phi-5" in capsys.readouterr().out


def test_dry_run_prints_the_plan_without_docker(runner, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(runner, "docker_text", lambda *a, **k: pytest.fail("docker was called"))
    monkeypatch.setattr(runner, "run_and_echo", lambda *a, **k: pytest.fail("a tool was started"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("a process was started"))
    status = run_main(runner, monkeypatch, "--dry-run", "--only", "ling-3.0-tiny", "--out-dir", str(tmp_path), "--limit", "3")
    assert status == 0
    out = capsys.readouterr().out
    assert "ling-3.0-tiny-q4km: Ling-3.0-tiny Q4_K_M (MIT)" in out
    assert "inclusionAI/Ling-3.0-tiny-GGUF/resolve/01b850e29ed5b44e2b810160ff980a9bb353296f/Ling-3.0-tiny-Q4_K_M.gguf" in out
    assert "--label ling-3.0-tiny-q4km-llama-bench" in out
    assert "--cache-types-k f16" in out
    assert "--model /models/ling-3.0-tiny-Q4_K_M.gguf --reasoning off" in out
    assert "probe: 3 questions" in out
    assert "--llm-container llm-candidate --model-name ling-3.0-tiny-q4km" in out
    assert "--sample-resources" in out
    assert not list(tmp_path.iterdir())


class TestRun:
    def test_every_step_runs_and_the_stack_llm_is_restored(self, runner, monkeypatch, tmp_path, quiet_host):
        stack = FakeStack(tmp_path)
        downloads = install_fakes(runner, monkeypatch, stack)
        out_dir = tmp_path / "benchmarks"
        status = run_main(
            runner, monkeypatch,
            "--only", "qwen3-4b-q4km,neohorse-1-4b", "--models-dir", str(tmp_path / "models"),
            "--out-dir", str(out_dir), "--ids", "exp-01,exp-02,direct-01", "--reasoning", "auto",
        )
        assert status == 0
        assert [entry.file for entry in downloads] == ["qwen3-4b-instruct-2507-Q4_K_M.gguf", "neohorse-1-4b-Q4_K_M.gguf"]
        assert downloads[1].mirrors == ("https://huggingface.co/TokenRhythm/NeoHorse-1-4B-GGUF/resolve/3c5d58ca82e580b5b0b3ce6eeffd34ac7d0fd95a/NeoHorse-1-4B-Q4_K_M.gguf",)

        verbs = [call[0] for call in stack.docker_calls]
        assert stack.docker_calls.index(["inspect", "agent"]) < verbs.index("stop")
        assert verbs.index("stop") < next(i for i, c in enumerate(stack.docker_calls) if c[0] == "cp")
        assert stack.docker_calls[-1] == ["start", "llm"]
        assert stack.llm_running
        runs = [c for c in stack.commands if c[:3] == ["docker", "run", "-d"]]
        assert len(runs) == 2
        assert runs[1][runs[1].index("--network") + 1] == "infra_horus-net"
        assert runs[1][runs[1].index("--memory") + 1] == str(6 * 2**30)
        assert runs[1][-2:] == ["--reasoning", "auto"]
        assert "/models/neohorse-1-4b-Q4_K_M.gguf" in runs[1]

        assert [item["id"] for item in stack.jobs[0]["items"]] == ["exp-01", "exp-02"]
        assert stack.jobs[0]["warmup"]
        evals = [c for c in stack.commands if "run-eval.py" in " ".join(c)]
        assert evals[0][evals[0].index("--ids") + 1] == "exp-01,exp-02,direct-01"

        summary_path, summary = summary_files(out_dir)
        assert summary["kind"] == "horus-model-candidates"
        assert summary["run"]["completed"] is True
        assert summary["run"]["reasoning"] == "auto"
        assert summary["run"]["stack_llm"]["memory_bytes"] == 6 * 2**30
        assert summary["catalog"]["version"] == "1.0.0"
        assert summary["machine"]["cpu_model"] == "Test CPU"
        first = summary["variants"][0]
        assert first["fetch"]["status"] == "verified"
        assert first["problems"] == []
        assert first["llama_bench"]["speeds"][0]["tps"] == 9.0
        assert first["contract"]["json_valid"] == {"n": 2, "correct": 2, "pct": 100.0}
        assert first["eval"]["answer_correct_auto"]["pct"] == 50.0
        assert first["server"]["build"] == "b11382"
        assert first["memory"]["after_eval"]["process"]["vm_hwm_bytes"] == 3 * 2**30
        assert first["memory"]["after_probe"]["cgroup_peak_bytes"] == 4 * 2**30
        assert first["memory"]["after_probe"]["oom_kills"] == 0
        run_dir = summary_path.with_suffix("")
        for kind in ("llama_bench", "contract", "eval"):
            assert (out_dir / first["reports"][kind]).is_file()
            assert (out_dir / first["reports"][kind]).parent == run_dir
        contract = json.loads((out_dir / first["reports"]["contract"]).read_text(encoding="utf-8"))
        assert contract["kind"] == "horus-contract-probe"
        assert contract["llama_server"]["container"] == CANDIDATE_CONTAINER
        markdown = summary_path.with_suffix(".md").read_text(encoding="utf-8")
        assert "| Qwen3-4B-Instruct-2507 (baseline) | Q4_K_M, community | Apache-2.0 | 2/2 (100.0%)" in markdown

    def test_a_failed_download_skips_the_model_for_every_later_step(self, runner, monkeypatch, tmp_path, quiet_host):
        stack = FakeStack(tmp_path)
        install_fakes(runner, monkeypatch, stack, fake_installer(fail_for={"neohorse-1-4b-Q4_K_M.gguf"}))
        out_dir = tmp_path / "benchmarks"
        run_main(runner, monkeypatch, "--only", "neohorse-1-4b", "--models-dir", str(tmp_path), "--out-dir", str(out_dir), "--limit", "1")
        assert stack.commands == []
        assert ["stop", "llm"] not in stack.docker_calls
        _path, summary = summary_files(out_dir)
        variant = summary["variants"][0]
        assert variant["fetch"]["status"] == "failed"
        assert variant["problems"] == ["download failed: The language model could not be downloaded. HTTP 404 Not Found"]

    def test_without_the_stack_llm_the_serving_steps_are_reported(self, runner, monkeypatch, tmp_path, quiet_host):
        stack = FakeStack(tmp_path, stack=False)
        install_fakes(runner, monkeypatch, stack)
        out_dir = tmp_path / "benchmarks"
        run_main(runner, monkeypatch, "--only", "qwen3-4b-q4km", "--steps", "probe,eval", "--models-dir", models_with(tmp_path), "--out-dir", str(out_dir))
        assert not [c for c in stack.docker_calls if c[0] in ("stop", "start")]
        _path, summary = summary_files(out_dir)
        assert summary["variants"][0]["problems"] == [
            "not served: no running llama-server container 'llm': start the CPU stack first "
            "(after an interrupted run: docker rm -f llm-candidate && docker start llm)"
        ]
        assert summary["variants"][0]["fetch"] is None

    def test_a_model_that_does_not_load_is_reported_with_its_log_and_the_stack_comes_back(self, runner, monkeypatch, tmp_path, quiet_host):
        stack = FakeStack(tmp_path, healthy=False)
        install_fakes(runner, monkeypatch, stack)
        out_dir = tmp_path / "benchmarks"
        models = models_with(tmp_path, "qwen3-4b-instruct-2507-Q4_K_M.gguf", "spark-x2.5-4b-Q4_K_M.gguf")
        run_main(runner, monkeypatch, "--only", "qwen3-4b-q4km,spark-x2.5-4b", "--steps", "probe", "--models-dir", models, "--out-dir", str(out_dir))
        assert stack.jobs == []
        assert stack.docker_calls[-1] == ["start", "llm"]
        _path, summary = summary_files(out_dir)
        for variant in summary["variants"]:
            assert variant["problems"][0].startswith("llama-server stopped while loading the model:\n")
            assert "unknown model architecture" in variant["problems"][0]

    def test_a_model_that_was_never_fetched_is_not_served(self, runner, monkeypatch, tmp_path, quiet_host):
        stack = FakeStack(tmp_path)
        install_fakes(runner, monkeypatch, stack)
        out_dir = tmp_path / "benchmarks"
        models = models_with(tmp_path)
        run_main(runner, monkeypatch, "--only", "qwen3-4b-q4km", "--steps", "bench,probe", "--models-dir", models, "--out-dir", str(out_dir))
        assert stack.commands == []
        assert stack.docker_calls[-1] == ["start", "llm"]
        _path, summary = summary_files(out_dir)
        missing = f"qwen3-4b-instruct-2507-Q4_K_M.gguf is not in {Path(models).resolve()}: run the fetch step first"
        assert summary["variants"][0]["problems"] == [missing, missing]

    def test_a_probe_that_stops_early_keeps_what_it_answered(self, runner, monkeypatch, tmp_path, quiet_host):
        stack = FakeStack(tmp_path, probe_ids=["exp-01"])
        install_fakes(runner, monkeypatch, stack)
        out_dir = tmp_path / "benchmarks"
        models = models_with(tmp_path, "qwen3-4b-instruct-2507-Q4_K_M.gguf")
        run_main(runner, monkeypatch, "--only", "qwen3-4b-q4km", "--steps", "probe", "--ids", "exp-01,exp-02", "--models-dir", models, "--out-dir", str(out_dir))
        _path, summary = summary_files(out_dir)
        variant = summary["variants"][0]
        assert variant["problems"] == ["the contract probe answered 1 of 2 questions (exit 0)"]
        assert variant["contract"]["replies"] == 1

    @pytest.mark.parametrize(
        ("agent_env", "finding"),
        [
            (
                ["AGENT_RESPONSE_CACHE=1"],
                "the agent's response cache is on (AGENT_RESPONSE_CACHE=1): its key does not change with the model, "
                "so the evaluation could score answers cached for another model",
            ),
            (
                ["AGENT_RESPONSE_CACHE= True"],
                "the agent's response cache is on (AGENT_RESPONSE_CACHE= True): its key does not change with the model, "
                "so the evaluation could score answers cached for another model",
            ),
            (None, "could not read the environment of the 'agent' container to see whether its response cache is off"),
        ],
    )
    def test_the_eval_is_refused_before_the_stack_is_touched_unless_the_response_cache_is_off(
        self, runner, monkeypatch, tmp_path, quiet_host, agent_env, finding
    ):
        stack = FakeStack(tmp_path, agent_env=agent_env)
        install_fakes(runner, monkeypatch, stack)
        out_dir = tmp_path / "benchmarks"
        models = models_with(tmp_path, "qwen3-4b-instruct-2507-Q4_K_M.gguf")
        run_main(runner, monkeypatch, "--only", "qwen3-4b-q4km", "--steps", "probe,eval", "--models-dir", models, "--out-dir", str(out_dir))
        assert stack.commands == []
        assert not [c for c in stack.docker_calls if c[0] in ("stop", "start", "rm")]
        summary_path, summary = summary_files(out_dir)
        assert summary["variants"][0]["problems"] == ["not served: " + finding + CACHE_REFUSAL]
        assert not any(summary["variants"][0]["reports"].values())

        stack.agent_env = AGENT_ENV
        assert run_main(runner, monkeypatch, "--resume", str(summary_path), "--steps", "probe,eval", "--models-dir", models) == 0
        _same_path, resumed = summary_files(out_dir)
        assert resumed["variants"][0]["problems"] == []
        assert all(resumed["variants"][0]["reports"][kind] for kind in ("contract", "eval"))

    def test_a_response_cache_that_is_off_or_a_probe_alone_runs(self, runner, monkeypatch, tmp_path, quiet_host):
        out_dir = tmp_path / "benchmarks"
        models = models_with(tmp_path, "qwen3-4b-instruct-2507-Q4_K_M.gguf")
        for steps, agent_env in (("eval", ["AGENT_RESPONSE_CACHE=0"]), ("probe", ["AGENT_RESPONSE_CACHE=1"])):
            stack = FakeStack(tmp_path, agent_env=agent_env)
            install_fakes(runner, monkeypatch, stack)
            run_main(runner, monkeypatch, "--only", "qwen3-4b-q4km", "--steps", steps, "--models-dir", models, "--out-dir", str(out_dir / steps))
            _path, summary = summary_files(out_dir / steps)
            assert summary["variants"][0]["problems"] == []
            written = {kind for kind, path in summary["variants"][0]["reports"].items() if path}
            assert written == {"eval" if steps == "eval" else "contract"}

    def test_allow_response_cache_runs_the_eval_and_flags_every_model(self, runner, monkeypatch, tmp_path, quiet_host):
        stack = FakeStack(tmp_path, agent_env=["AGENT_RESPONSE_CACHE=1"])
        install_fakes(runner, monkeypatch, stack)
        out_dir = tmp_path / "benchmarks"
        models = models_with(tmp_path, "qwen3-4b-instruct-2507-Q4_K_M.gguf", "neohorse-1-4b-Q4_K_M.gguf")
        run_main(
            runner, monkeypatch,
            "--only", "qwen3-4b-q4km,neohorse-1-4b", "--steps", "eval", "--allow-response-cache",
            "--models-dir", models, "--out-dir", str(out_dir),
        )
        summary_path, _first = summary_files(out_dir)
        run_main(runner, monkeypatch, "--resume", str(summary_path), "--steps", "eval", "--allow-response-cache", "--models-dir", models)
        assert len([c for c in stack.commands if "run-eval.py" in " ".join(c)]) == 4
        _same_path, summary = summary_files(out_dir)
        for variant in summary["variants"]:
            assert variant["problems"] == [
                "the agent's response cache is on (AGENT_RESPONSE_CACHE=1): its key does not change with the model, "
                "so the evaluation could score answers cached for another model (--allow-response-cache)"
            ]
            assert variant["eval"]["answer_correct_auto"]["pct"] == 50.0

    def test_an_llm_that_does_not_stop_never_shares_its_alias_with_a_candidate(self, runner, monkeypatch, tmp_path, quiet_host):
        stack = FakeStack(tmp_path, stop_fails=True)
        install_fakes(runner, monkeypatch, stack)
        out_dir = tmp_path / "benchmarks"
        models = models_with(tmp_path, "qwen3-4b-instruct-2507-Q4_K_M.gguf")
        run_main(runner, monkeypatch, "--only", "qwen3-4b-q4km", "--steps", "probe,eval", "--models-dir", models, "--out-dir", str(out_dir))
        assert stack.commands == []
        assert stack.jobs == []
        assert stack.llm_running
        _path, summary = summary_files(out_dir)
        assert summary["variants"][0]["problems"] == [
            "not served: could not stop 'llm': a candidate started next to it under the alias 'llm' would split the requests between two models"
        ]

    def test_an_llm_that_does_not_start_again_is_reported(self, runner, monkeypatch, tmp_path, quiet_host, capsys):
        stack = FakeStack(tmp_path, start_fails=True)
        install_fakes(runner, monkeypatch, stack)
        out_dir = tmp_path / "benchmarks"
        models = models_with(tmp_path, "qwen3-4b-instruct-2507-Q4_K_M.gguf")
        run_main(runner, monkeypatch, "--only", "qwen3-4b-q4km", "--steps", "probe", "--models-dir", models, "--out-dir", str(out_dir))
        assert not stack.llm_running
        assert "[error] could not start 'llm' again: the stack has no llama-server until `docker start llm`" in capsys.readouterr().out


def test_resume_adds_the_serving_steps_to_the_benchmark_summary(runner, monkeypatch, tmp_path, quiet_host):
    stack = FakeStack(tmp_path)
    install_fakes(runner, monkeypatch, stack)
    out_dir = tmp_path / "benchmarks"
    common = ["--models-dir", str(tmp_path / "models"), "--limit", "1"]
    run_main(runner, monkeypatch, "--only", "qwen3-4b-q4km,agents-a1-4b-q5km", "--steps", "fetch,bench", "--out-dir", str(out_dir), *common)
    summary_path, first = summary_files(out_dir)
    assert first["run"]["steps"] == ["fetch", "bench"]
    assert stack.jobs == []

    assert run_main(runner, monkeypatch, "--resume", str(summary_path), "--steps", "probe,eval", *common) == 0
    _same_path, resumed = summary_files(out_dir)
    assert [v["id"] for v in resumed["variants"]] == ["qwen3-4b-q4km", "agents-a1-4b-q5km"]
    assert resumed["run"]["steps"] == ["fetch", "bench", "probe", "eval"]
    assert resumed["run"]["started_at"] == first["run"]["started_at"]
    assert [s["steps"] for s in resumed["run"]["sessions"]] == [["fetch", "bench"], ["probe", "eval"]]
    for variant in resumed["variants"]:
        assert variant["fetch"]["status"] == "verified"
        assert set(variant["reports"]) == {"llama_bench", "contract", "eval"}
        assert all(variant["reports"].values())
    assert len(stack.jobs) == 2


def test_resume_retries_a_download_that_failed(runner, monkeypatch, tmp_path, quiet_host):
    stack = FakeStack(tmp_path)
    install_fakes(runner, monkeypatch, stack, fake_installer(fail_for={"neohorse-1-4b-Q4_K_M.gguf"}))
    out_dir = tmp_path / "benchmarks"
    common = ["--models-dir", str(tmp_path / "models"), "--steps", "fetch"]
    run_main(runner, monkeypatch, "--only", "qwen3-4b-q4km,neohorse-1-4b", "--out-dir", str(out_dir), *common)
    summary_path, first = summary_files(out_dir)
    assert [v["fetch"]["status"] for v in first["variants"]] == ["verified", "failed"]
    assert first["variants"][1]["problems"] == ["download failed: The language model could not be downloaded. HTTP 404 Not Found"]

    downloads = install_fakes(runner, monkeypatch, stack)
    assert run_main(runner, monkeypatch, "--resume", str(summary_path), *common) == 0
    _same_path, resumed = summary_files(out_dir)
    assert [entry.file for entry in downloads] == ["qwen3-4b-instruct-2507-Q4_K_M.gguf", "neohorse-1-4b-Q4_K_M.gguf"]
    assert [v["fetch"]["status"] for v in resumed["variants"]] == ["verified", "verified"]
    assert [v["problems"] for v in resumed["variants"]] == [[], []]


def test_resume_refuses_a_file_that_is_not_a_summary(runner, monkeypatch, tmp_path, capsys):
    other = tmp_path / "eval.json"
    other.write_text(json.dumps({"kind": "horus-eval"}), encoding="utf-8")
    assert run_main(runner, monkeypatch, "--resume", str(other)) == 2
    assert "is not a horus-model-candidates summary" in capsys.readouterr().out


def test_resummarize_rebuilds_from_the_sub_reports(runner, monkeypatch, tmp_path, quiet_host):
    stack = FakeStack(tmp_path)
    install_fakes(runner, monkeypatch, stack)
    out_dir = tmp_path / "benchmarks"
    models = models_with(tmp_path, "qwen3-4b-instruct-2507-Q4_K_M.gguf")
    run_main(runner, monkeypatch, "--only", "qwen3-4b-q4km", "--steps", "eval", "--models-dir", models, "--out-dir", str(out_dir), "--limit", "2")
    summary_path, summary = summary_files(out_dir)
    eval_path = out_dir / summary["variants"][0]["reports"]["eval"]
    reviewed = json.loads(eval_path.read_text(encoding="utf-8"))
    reviewed["summary"]["manual_review"] = {"answer_correct_pct": 55.0, "pending": 0}
    eval_path.write_text(json.dumps(reviewed), encoding="utf-8")
    summary_path.with_suffix(".md").unlink()
    assert run_main(runner, monkeypatch, "--resummarize", str(summary_path)) == 0
    refreshed = json.loads(summary_path.read_text(encoding="utf-8"))
    assert refreshed["variants"][0]["eval"]["answer_correct_reviewed_pct"] == 55.0
    assert refreshed["variants"][0]["memory"] == summary["variants"][0]["memory"]
    assert "| 55.0% |" in summary_path.with_suffix(".md").read_text(encoding="utf-8")


def test_the_installer_downloader_is_reused_and_adopts_a_verified_file(runner, tmp_path):
    modules = runner.installer_modules()
    assert modules is not None
    content = b"GGUF candidate bytes"
    gguf = {
        "id": "tiny-q4",
        "file": "tiny-Q4_K_M.gguf",
        "quant": "Q4_K_M",
        "repo": "example/tiny-GGUF",
        "revision": "0" * 40,
        "upstream_file": "tiny-Q4_K_M.gguf",
        "publisher": "model author",
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "default": True,
    }
    variant = Variant({"id": "tiny", "licence": "MIT", "plan_name": "Tiny"}, gguf)
    (tmp_path / gguf["file"]).write_bytes(content)
    outcome = runner.fetch_with_installer(modules, variant, tmp_path, tmp_path / "download.log", "1.0.0")
    assert outcome == {"status": "verified", "method": "installer", "path": "<models-dir>/tiny-Q4_K_M.gguf"}
    assert (tmp_path / "tiny-Q4_K_M.gguf.sha256").read_text(encoding="ascii").strip() == gguf["sha256"]


def test_without_the_installer_the_docker_fetch_script_is_used(runner, monkeypatch, tmp_path):
    catalog = load_catalog(BENCH_DIR / "model-candidates.yaml")
    candidate = catalog["candidates"][1]
    variant = Variant(candidate, candidate["ggufs"][0])
    seen = []
    monkeypatch.setattr(runner, "run_and_echo", lambda command, stdin_text=None: seen.append(command) or (0, []))
    outcome = runner.fetch_with_docker(variant, tmp_path, "ghcr.io/ggml-org/llama.cpp:server-b11382")
    assert outcome["status"] == "verified"
    command = seen[0]
    assert f"LLM_GGUF_FILE={variant.file}" in command
    assert f"LLM_GGUF_SHA256={variant.gguf['sha256']}" in command
    assert f"LLM_GGUF_URL={variant.url}" in command


class HostFolderStack(FakeStack):
    def __init__(self, tmp_path, folder):
        super().__init__(tmp_path)
        self.folder = folder

    def docker_text(self, argv, timeout=60.0):
        text = super().docker_text(argv, timeout)
        if argv[:2] == ["inspect", "llm"] and text:
            inspected = json.loads(text)
            inspected[0]["Mounts"] = [{"Type": "bind", "Source": self.folder, "Destination": "/models"}]
            text = json.dumps(inspected)
        return text


def test_no_part_of_the_host_models_folder_reaches_the_reports(
    runner, monkeypatch, tmp_path, quiet_host, host_folder, host_folder_leaks
):
    stack = HostFolderStack(tmp_path, host_folder)
    install_fakes(runner, monkeypatch, stack)
    monkeypatch.setattr(runner.CandidateRun, "model_missing", lambda self, variant: False)
    out_dir = tmp_path / "benchmarks"
    run_main(
        runner, monkeypatch,
        "--only", "qwen3-4b-q4km", "--steps", "probe", "--ids", "exp-01",
        "--models-dir", host_folder, "--out-dir", str(out_dir),
    )
    started = next(c for c in stack.commands if c[:3] == ["docker", "run", "-d"])
    assert host_folder_leaks(" ".join(started)) != []

    _summary_path, summary = summary_files(out_dir)
    assert summary["run"]["sessions"][-1]["models_dir"] == "<models-dir>"
    assert summary["run"]["stack_llm"]["models_source"] == "<models-dir>"
    variant = summary["variants"][0]
    assert "<models-dir>:/models:ro" in variant["server"]["command"]
    contract = json.loads((out_dir / variant["reports"]["contract"]).read_text(encoding="utf-8"))
    assert "<models-dir>:/models:ro" in contract["llama_server"]["command"]
    written = sorted(path for path in out_dir.rglob("*") if path.is_file())
    assert len(written) == 3
    for path in written:
        assert host_folder_leaks(path.read_text(encoding="utf-8")) == [], path.name


def test_a_fetched_model_is_recorded_inside_the_models_folder(runner, monkeypatch, host_folder, host_folder_leaks):
    catalog = load_catalog(BENCH_DIR / "model-candidates.yaml")
    candidate = catalog["candidates"][1]
    variant = Variant(candidate, candidate["ggufs"][0])
    monkeypatch.setattr(runner, "run_and_echo", lambda command, stdin_text=None: (0, []))
    outcome = runner.fetch_with_docker(variant, Path(host_folder), "ghcr.io/ggml-org/llama.cpp:server-b11382")
    assert outcome == {"status": "verified", "method": "docker", "path": f"<models-dir>/{variant.file}"}
    assert host_folder_leaks(json.dumps(outcome)) == []


def test_a_file_outside_the_repo_is_recorded_by_its_name(runner, host_folder, host_folder_leaks):
    assert runner.relative_to(runner.REPO_ROOT / "tests" / "eval" / "testset.yaml", runner.REPO_ROOT) == "tests/eval/testset.yaml"
    recorded = runner.relative_to(f"{host_folder}/own-testset.yaml", runner.REPO_ROOT)
    assert recorded == "own-testset.yaml"
    assert host_folder_leaks(recorded) == []
