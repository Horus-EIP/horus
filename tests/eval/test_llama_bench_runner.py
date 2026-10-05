import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

BENCH_DIR = Path(__file__).resolve().parents[2] / "scripts" / "benchmarks"
Q4 = "qwen3-4b-instruct-2507-Q4_K_M.gguf"
Q5 = "qwen3-4b-instruct-2507-Q5_K_M.gguf"
Q4_SHA256 = "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
Q5_SHA256 = "5bde5e9d883622acb02bf77fe7dcbc56a8b9a9ad4be78a72ca23a532658b4ecb"


@pytest.fixture(scope="module")
def bench_runner():
    spec = importlib.util.spec_from_file_location("run_llama_bench", BENCH_DIR / "run-llama-bench.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_llama_bench"] = module
    spec.loader.exec_module(module)
    return module


def bench_rows(model=Q4):
    rows = []
    for prompt, generated in ((512, 0), (0, 128)):
        rows.append(
            {
                "build_commit": "11fe0215",
                "build_number": 11382,
                "model_filename": f"/models/{model}",
                "model_type": "qwen3 4B Q4_K - Medium",
                "n_threads": 4,
                "type_k": "f16",
                "type_v": "f16",
                "n_prompt": prompt,
                "n_gen": generated,
                "n_depth": 0,
                "avg_ts": 55.0 if prompt else 9.0,
                "stddev_ts": 0.5,
            }
        )
    return rows


class FakeDocker:
    def __init__(self, listing):
        self.listing = listing
        self.commands = []

    def run_text(self, argv, timeout=60.0):
        self.commands.append(list(argv))
        if "find" in argv:
            return self.listing
        if "sha256sum" in argv:
            sums = {Q4: Q4_SHA256, Q5: Q5_SHA256}
            return "".join(f"{sums[path.rsplit('/', 1)[-1]]}  {path}\n" for path in argv if path.startswith("/models/"))
        if argv[:2] == ["docker", "image"]:
            return "ghcr.io/ggml-org/llama.cpp@sha256:" + "a" * 64 + "\n"
        if argv[:2] == ["docker", "ps"]:
            return "postgres\nllm\n"
        if argv[0] == "git":
            return "abc1234\n"
        return None


@pytest.fixture
def host_facts(bench_runner, monkeypatch):
    collected = {
        "cpu_model": ("AMD Ryzen 5 5600U", "/proc/cpuinfo"),
        "physical_cores": (6, "/proc/cpuinfo"),
        "avx2": (True, "/proc/cpuinfo"),
        "ram_total_bytes": (16 * 2**30, "/proc/meminfo"),
        "disk_type": ("NVMe SSD", "lsblk"),
    }
    paths = []

    def collect(path):
        paths.append(path)
        return collected

    monkeypatch.setattr(bench_runner, "collect_host", collect)
    monkeypatch.setattr(bench_runner, "docker_facts", lambda: {"mem_total_bytes": 16 * 2**30, "root_dir": "/var/lib/docker"})
    return paths


def run_main(bench_runner, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["run-llama-bench.py", *argv])
    return bench_runner.main()


class TestArguments:
    def parse(self, bench_runner, *argv):
        return bench_runner.build_parser().parse_args(list(argv))

    def test_defaults_are_the_plans_matrix_and_reference(self, bench_runner):
        args = self.parse(bench_runner, "--models-dir", "models")
        assert args.reference == "cpu16"
        assert args.image == "ghcr.io/ggml-org/llama.cpp:full-b11382"
        assert (args.prompts, args.generations, args.depths) == ("512,2048", "128", "0,4096")
        assert (args.cache_types_k, args.cache_types_v, args.threads) == ("f16,q8_0", "f16,q8_0", "4,8")
        assert bench_runner.argument_errors(args) == []

    def test_a_models_location_is_required_unless_enriching_a_saved_run(self, bench_runner):
        assert bench_runner.argument_errors(self.parse(bench_runner)) == [
            "give --models-dir or --models-volume (or --from-json to enrich a saved run)"
        ]
        assert bench_runner.argument_errors(self.parse(bench_runner, "--from-json", "raw.json")) == []

    def test_fetch_needs_a_location_and_repetitions_must_be_positive(self, bench_runner):
        args = self.parse(bench_runner, "--from-json", "raw.json", "--fetch", "--repetitions", "0")
        assert bench_runner.argument_errors(args) == [
            "--fetch needs --models-dir or --models-volume",
            "--repetitions must be at least 1",
        ]

    def test_dir_and_volume_are_exclusive(self, bench_runner):
        with pytest.raises(SystemExit):
            self.parse(bench_runner, "--models-dir", "m", "--models-volume", "v")


class TestDryRun:
    def test_prints_the_commands_without_running_docker(self, bench_runner, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(bench_runner, "run_text", lambda *a, **k: pytest.fail("docker was called"))
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("docker was called"))
        assert run_main(bench_runner, monkeypatch, "--models-dir", str(tmp_path), "--dry-run") == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[-1].endswith(f"--bench -m /models/{Q4} -m /models/{Q5} -p 512,2048 -n 128 -d 0,4096 "
                                  "-ctk f16,q8_0 -ctv f16,q8_0 -t 4,8 -r 5 -o json --progress")


class TestRun:
    def test_benchmark_is_run_and_saved_with_build_hashes_and_machine(
        self, bench_runner, monkeypatch, tmp_path, host_facts, capsys
    ):
        docker = FakeDocker(f"2497281120 {Q4}\n2889514080 {Q5}\n")
        monkeypatch.setattr(bench_runner, "run_text", docker.run_text)
        launched = []

        def fake_run(command, **kwargs):
            launched.append(command)
            rows = bench_rows(Q4) + bench_rows(Q5)
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(rows))

        monkeypatch.setattr(subprocess, "run", fake_run)
        out_dir = tmp_path / "benchmarks"
        models = tmp_path / "models"
        status = run_main(
            bench_runner, monkeypatch,
            "--models-dir", str(models), "--out-dir", str(out_dir), "--ram-speed", "3200 MT/s",
        )
        assert status == 0
        [saved] = list(out_dir.iterdir())
        assert saved.name.startswith("cpu16-") and saved.suffix == ".json"
        report = json.loads(saved.read_text(encoding="utf-8"))
        assert report["kind"] == "horus-llama-bench"
        assert report["llama_cpp"]["build"] == "b11382"
        assert report["llama_cpp"]["image_digest"].endswith("a" * 64)
        assert [model["sha256"] for model in report["models"]] == [Q4_SHA256, Q5_SHA256]
        assert all(model["matches_known_sha256"] for model in report["models"])
        assert report["models"][1]["size_bytes"] == 2889514080
        assert report["machine"]["cpu_model"] == "AMD Ryzen 5 5600U"
        assert report["machine"]["ram_speed"] == "3200 MT/s"
        assert report["machine"]["docker"]["mem_total_bytes"] == 16 * 2**30
        assert report["run"]["git_commit"] == "abc1234"
        assert report["run"]["command"] == launched[0]
        assert len(report["results"]) == 4
        assert host_facts == [models.resolve()]
        output = capsys.readouterr().out
        assert "Horus containers are running (llm)" in output
        assert "[done] wrote" in output

    def test_missing_model_stops_before_the_benchmark(self, bench_runner, monkeypatch, tmp_path, host_facts, capsys):
        monkeypatch.setattr(bench_runner, "run_text", FakeDocker(f"2497281120 {Q4}\n").run_text)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("llama-bench must not start"))
        status = run_main(bench_runner, monkeypatch, "--models-dir", str(tmp_path), "--out-dir", str(tmp_path / "out"))
        assert status == 1
        assert f"{Q5}: not found in" in capsys.readouterr().out
        assert not (tmp_path / "out").exists()

    def test_fetch_downloads_a_missing_known_model(self, bench_runner, monkeypatch, tmp_path, host_facts):
        listings = iter([f"2497281120 {Q4}\n", f"2497281120 {Q4}\n2889514080 {Q5}\n"])
        docker = FakeDocker("")
        monkeypatch.setattr(
            bench_runner, "run_text",
            lambda argv, timeout=60.0: next(listings) if "find" in argv else docker.run_text(argv, timeout),
        )
        launched = []

        def fake_run(command, **kwargs):
            launched.append(command)
            if "--bench" in command:
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps(bench_rows()))
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(subprocess, "run", fake_run)
        models = tmp_path / "new-models"
        status = run_main(
            bench_runner, monkeypatch, "--models-dir", str(models), "--fetch", "--out-dir", str(tmp_path / "out")
        )
        assert status == 0
        assert models.is_dir()
        assert f"LLM_GGUF_FILE={Q5}" in launched[0]
        assert "--bench" in launched[1]

    def test_unreadable_output_is_kept_for_diagnosis(self, bench_runner, monkeypatch, tmp_path, host_facts, capsys):
        monkeypatch.setattr(bench_runner, "run_text", FakeDocker(f"1 {Q4}\n1 {Q5}\n").run_text)
        monkeypatch.setattr(bench_runner.tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(
            subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout="oops")
        )
        status = run_main(bench_runner, monkeypatch, "--models-dir", str(tmp_path), "--out-dir", str(tmp_path / "out"))
        assert status == 1
        assert "llama-bench exited with 1" in capsys.readouterr().out
        assert [path.read_text() for path in tmp_path.glob("llama-bench-cpu16-*.txt")] == ["oops"]


class TestFromJson:
    def test_a_saved_raw_run_is_enriched_without_running_llama_bench(
        self, bench_runner, monkeypatch, tmp_path, host_facts
    ):
        raw = tmp_path / "raw.json"
        raw.write_text(json.dumps(bench_rows(Q4)), encoding="utf-8")
        monkeypatch.setattr(bench_runner, "run_text", FakeDocker(f"2497281120 {Q4}\n").run_text)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("llama-bench must not start"))
        status = run_main(
            bench_runner, monkeypatch,
            "--from-json", str(raw), "--models-volume", "infra_llm_models",
            "--label", "cpu16 q4 only", "--out-dir", str(tmp_path / "out"),
        )
        assert status == 0
        [saved] = list((tmp_path / "out").iterdir())
        assert saved.name.startswith("cpu16-q4-only-")
        report = json.loads(saved.read_text(encoding="utf-8"))
        assert report["run"]["from_json"] == str(raw)
        assert report["run"]["command"] is None
        assert report["run"]["models_location"] == {"dir": None, "volume": "infra_llm_models"}
        assert [model["file"] for model in report["models"]] == [Q4]
        assert report["models"][0]["sha256"] == Q4_SHA256

    def test_without_a_models_location_the_hashes_stay_empty(
        self, bench_runner, monkeypatch, tmp_path, host_facts, capsys
    ):
        raw = tmp_path / "raw.json"
        raw.write_text(json.dumps(bench_rows(Q4)), encoding="utf-8")
        monkeypatch.setattr(bench_runner, "run_text", FakeDocker("").run_text)
        status = run_main(bench_runner, monkeypatch, "--from-json", str(raw), "--out-dir", str(tmp_path / "out"))
        assert status == 0
        report = json.loads(next((tmp_path / "out").iterdir()).read_text(encoding="utf-8"))
        assert report["models"][0]["sha256"] is None
        assert "SHA-256 is not recorded" in capsys.readouterr().out
