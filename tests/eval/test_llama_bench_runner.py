import importlib.util
import json
import sys
from pathlib import Path

import pytest
from horus_bench_kit.cli import llama_bench as kit_cli
from horus_bench_kit.shell import Shell

BENCH_DIR = Path(__file__).resolve().parents[2] / "scripts" / "benchmarks"
Q4 = "qwen3-4b-instruct-2507-Q4_K_M.gguf"
Q5 = "qwen3-4b-instruct-2507-Q5_K_M.gguf"
Q4_SHA256 = "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
Q5_SHA256 = "5bde5e9d883622acb02bf77fe7dcbc56a8b9a9ad4be78a72ca23a532658b4ecb"
HOST_FACTS = {
    "cpu_model": ("AMD Ryzen 5 5600U", "/proc/cpuinfo"),
    "physical_cores": (6, "/proc/cpuinfo"),
    "avx2": (True, "/proc/cpuinfo"),
    "ram_total_bytes": (16 * 2**30, "/proc/meminfo"),
    "disk_type": ("NVMe SSD", "lsblk"),
}


@pytest.fixture(scope="module")
def bench_runner():
    spec = importlib.util.spec_from_file_location(
        "run_llama_bench", BENCH_DIR / "run-llama-bench.py"
    )
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


class FakeDocker(Shell):
    def __init__(self, *listings, rows=None):
        self.listings = list(listings)
        self.rows = rows if rows is not None else bench_rows(Q4) + bench_rows(Q5)
        self.launched = []
        self.host_paths = []

    def run_text(self, argv, timeout=60.0):
        argv = list(argv)
        if "find" in argv:
            return self.listings.pop(0) if len(self.listings) > 1 else self.listings[0]
        if "sha256sum" in argv:
            sums = {Q4: Q4_SHA256, Q5: Q5_SHA256}
            return "".join(
                f"{sums[path.rsplit('/', 1)[-1]]}  {path}\n"
                for path in argv
                if path.startswith("/models/")
            )
        if argv[:2] == ["docker", "image"]:
            return "ghcr.io/ggml-org/llama.cpp@sha256:" + "a" * 64 + "\n"
        if argv[:2] == ["docker", "ps"]:
            return "postgres\nllm\n"
        if argv[0] == "git":
            return "abc1234\n"
        return None

    def run(self, argv):
        self.launched.append(list(argv))
        return 0

    def run_captured(self, argv):
        self.launched.append(list(argv))
        return 0, json.dumps(self.rows)

    def collect_host(self, disk_path=None):
        self.host_paths.append(disk_path)
        return dict(HOST_FACTS)

    def docker_facts(self):
        return {"mem_total_bytes": 16 * 2**30, "root_dir": "/var/lib/docker"}


class NoDocker(Shell):
    def run_text(self, argv, timeout=60.0):
        pytest.fail("docker was called")

    def run(self, argv):
        pytest.fail("a process was started")

    def run_captured(self, argv):
        pytest.fail("a process was started")


class TestArguments:
    def test_defaults_are_the_plans_matrix_and_reference(self, bench_runner):
        args = kit_cli.build_parser(bench_runner.LLAMA_BENCH).parse_args(["--models-dir", "models"])
        assert args.reference == "cpu16"
        assert args.image == "ghcr.io/ggml-org/llama.cpp:full-b11382"
        assert args.fetch_image == "ghcr.io/ggml-org/llama.cpp:server-b11382"
        assert (args.prompts, args.generations, args.depths) == ("512,2048", "128", "0,4096")
        assert (args.cache_types_k, args.cache_types_v, args.threads) == (
            "f16,q8_0",
            "f16,q8_0",
            "4,8",
        )
        assert Path(args.out_dir) == BENCH_DIR.parents[1] / "benchmarks"
        assert kit_cli.argument_errors(args, bench_runner.LLAMA_BENCH) == []


class TestErrorsStayUncaught:
    def test_a_missing_saved_run_raises(self, bench_runner, tmp_path):
        with pytest.raises(FileNotFoundError):
            bench_runner.main(
                ["--from-json", str(tmp_path / "missing.json"), "--dry-run"], shell=NoDocker()
            )

    def test_a_broken_saved_run_raises(self, bench_runner, tmp_path):
        raw = tmp_path / "raw.json"
        raw.write_text("[1, 2", encoding="utf-8")
        with pytest.raises(ValueError):
            bench_runner.main(["--from-json", str(raw), "--dry-run"], shell=NoDocker())

    def test_a_program_that_cannot_start_raises(self, bench_runner):
        shell = bench_runner.HorusShell()
        with pytest.raises(FileNotFoundError):
            shell.run(["hbk-test-no-such-program"])
        with pytest.raises(FileNotFoundError):
            shell.run_captured(["hbk-test-no-such-program"])


class TestDryRun:
    def test_prints_the_commands_for_the_two_known_models_without_running_docker(
        self, bench_runner, capsys, tmp_path
    ):
        assert (
            bench_runner.main(
                ["--models-dir", str(tmp_path), "--fetch", "--dry-run"], shell=NoDocker()
            )
            == 0
        )
        lines = capsys.readouterr().out.splitlines()
        assert [f"LLM_GGUF_FILE={Q4}" in lines[0], f"LLM_GGUF_FILE={Q5}" in lines[1]] == [
            True,
            True,
        ]
        assert lines[0].endswith(
            "ghcr.io/ggml-org/llama.cpp:server-b11382 /opt/horus/fetch-model.sh"
        )
        assert "src/infra/llm/fetch-model.sh:/opt/horus/fetch-model.sh:ro" in lines[0].replace(
            "\\", "/"
        )
        assert lines[-1].endswith(
            f"--bench -m /models/{Q4} -m /models/{Q5} -p 512,2048 -n 128 -d 0,4096 "
            "-ctk f16,q8_0 -ctv f16,q8_0 -t 4,8 -r 5 -o json --progress"
        )


class TestRun:
    def test_benchmark_is_run_and_saved_with_build_hashes_and_machine(
        self, bench_runner, tmp_path, capsys
    ):
        docker = FakeDocker(f"2497281120 {Q4}\n2889514080 {Q5}\n")
        out_dir = tmp_path / "benchmarks"
        models = tmp_path / "models"
        argv = ["--models-dir", str(models), "--out-dir", str(out_dir), "--ram-speed", "3200 MT/s"]
        assert bench_runner.main(argv, shell=docker) == 0
        [saved] = list(out_dir.iterdir())
        assert saved.name.startswith("cpu16-") and saved.suffix == ".json"
        report = json.loads(saved.read_text(encoding="utf-8"))
        assert report["kind"] == "horus-llama-bench"
        assert report["llama_cpp"]["build"] == "b11382"
        assert report["llama_cpp"]["image_digest"].endswith("a" * 64)
        assert [model["sha256"] for model in report["models"]] == [Q4_SHA256, Q5_SHA256]
        assert all(model["matches_known_sha256"] for model in report["models"])
        assert report["models"][1]["known_source"].endswith("/Qwen3-4B-Instruct-2507-Q5_K_M.gguf")
        assert report["machine"]["reference"] == "cpu16"
        assert report["machine"]["ram_speed"] == "3200 MT/s"
        assert report["run"]["git_commit"] == "abc1234"
        assert report["run"]["command"] == [
            *docker.launched[0][:4],
            "<models-dir>:/models:ro",
            *docker.launched[0][5:],
        ]
        assert docker.host_paths == [models.resolve()]
        output = capsys.readouterr().out
        assert "[warn] Horus containers are running (llm) and compete for CPU and RAM" in output
        assert "[done] wrote" in output

    def test_a_missing_default_model_stops_before_the_benchmark(
        self, bench_runner, tmp_path, capsys
    ):
        docker = FakeDocker(f"2497281120 {Q4}\n")
        argv = ["--models-dir", str(tmp_path), "--out-dir", str(tmp_path / "out")]
        assert bench_runner.main(argv, shell=docker) == 1
        output = capsys.readouterr().out
        assert f"{Q5}: not found in" in output
        assert (
            "[error] pass --fetch to download the known models, see benchmarks/README.md" in output
        )
        assert docker.launched == []
        assert not (tmp_path / "out").exists()

    def test_fetch_downloads_a_missing_known_model_with_the_stack_script(
        self, bench_runner, tmp_path
    ):
        docker = FakeDocker(
            f"2497281120 {Q4}\n", f"2497281120 {Q4}\n2889514080 {Q5}\n", rows=bench_rows()
        )
        models = tmp_path / "new-models"
        argv = ["--models-dir", str(models), "--fetch", "--out-dir", str(tmp_path / "out")]
        assert bench_runner.main(argv, shell=docker) == 0
        assert models.is_dir()
        fetch, bench = docker.launched
        assert f"LLM_GGUF_FILE={Q5}" in fetch
        assert fetch[-1] == "/opt/horus/fetch-model.sh"
        assert "--bench" in bench
