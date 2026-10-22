# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from conftest import GIB, RecordingShell, run_module
from horus_bench_kit import __version__
from horus_bench_kit.cli.llama_bench import LlamaBenchProfile, argument_errors, build_parser, main
from horus_bench_kit.llama_bench import KnownModel

SMALL = "alpha-1b-Q4_K_M.gguf"
LARGE = "alpha-1b-Q5_K_M.gguf"
SUMS = {SMALL: "a1" * 32, LARGE: "a2" * 32}
KNOWN = {
    SMALL: KnownModel(SMALL, f"https://models.example/{SMALL}", 812_000_000, SUMS[SMALL]),
    LARGE: KnownModel(LARGE, f"https://models.example/{LARGE}", 951_000_000, SUMS[LARGE]),
}


def bench_rows(model=SMALL):
    return [
        {
            "build_commit": "0a1b2c3d",
            "build_number": 11382,
            "model_filename": f"/models/{model}",
            "model_type": "alpha 1B",
            "n_threads": 4,
            "type_k": "f16",
            "type_v": "f16",
            "n_prompt": prompt,
            "n_gen": generated,
            "n_depth": 0,
            "avg_ts": 55.0 if prompt else 9.0,
            "stddev_ts": 0.5,
        }
        for prompt, generated in ((512, 0), (0, 128))
    ]


class FakeDocker(RecordingShell):
    def __init__(
        self, listing, temp=None, bench_output=None, bench_code=0, running="db\nmodel-server\n"
    ):
        super().__init__(temp)
        self.listings = listing if isinstance(listing, list) else [listing]
        self.bench_output = bench_output
        self.bench_code = bench_code
        self.running = running

    def text(self, argv):
        if "find" in argv:
            return self.listings.pop(0) if len(self.listings) > 1 else self.listings[0]
        if "sha256sum" in argv:
            return "".join(
                f"{SUMS[path.rsplit('/', 1)[-1]]}  {path}\n"
                for path in argv
                if path.startswith("/models/")
            )
        if argv[:2] == ["docker", "image"]:
            return "ghcr.io/ggml-org/llama.cpp@sha256:" + "b" * 64 + "\n"
        if argv[:2] == ["docker", "ps"]:
            return self.running
        return super().text(argv)

    def run_captured(self, argv):
        self.calls.append(list(argv))
        return self.bench_code, self.bench_output if self.bench_output is not None else json.dumps(
            bench_rows(SMALL) + bench_rows(LARGE)
        )


def known_file(tmp_path):
    path = tmp_path / "known.json"
    models = [
        {"file": m.file, "url": m.url, "size_bytes": m.size_bytes, "sha256": m.sha256}
        for m in KNOWN.values()
    ]
    path.write_text(json.dumps({"models": models}), encoding="utf-8")
    return str(path)


def only_report(folder):
    [saved] = list(folder.iterdir())
    return saved, json.loads(saved.read_text(encoding="utf-8"))


class TestArguments:
    def test_defaults(self):
        args = build_parser().parse_args(["--models-dir", "models", "--model", SMALL])
        assert args.reference is None
        assert args.image == "ghcr.io/ggml-org/llama.cpp:full-b11382"
        assert args.fetch_image == "ghcr.io/ggml-org/llama.cpp:server-b11382"
        assert (args.prompts, args.generations, args.depths) == ("512,2048", "128", "0,4096")
        assert (args.cache_types_k, args.cache_types_v, args.threads, args.repetitions) == (
            "f16,q8_0",
            "f16,q8_0",
            "4,8",
            5,
        )
        assert args.out_dir == "."
        assert argument_errors(args) == []

    def test_a_models_location_and_models_are_required_unless_enriching_a_saved_run(self):
        parse = build_parser().parse_args
        assert argument_errors(parse([])) == [
            "give --models-dir or --models-volume (or --from-json to enrich a saved run)",
            "give --model at least once, or --known-models to run every known model",
        ]
        assert argument_errors(parse(["--from-json", "raw.json"])) == []
        assert argument_errors(parse(["--models-dir", "m"]), known=KNOWN) == []

    def test_fetch_needs_a_location_and_repetitions_must_be_positive(self):
        args = build_parser().parse_args(
            ["--from-json", "raw.json", "--fetch", "--repetitions", "0", "--label", "!!"]
        )
        assert argument_errors(args) == [
            "--fetch needs --models-dir or --models-volume",
            "--repetitions must be at least 1",
            "--label: label must contain at least one letter or digit",
        ]

    def test_dir_and_volume_are_exclusive(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--models-dir", "m", "--models-volume", "v"])

    def test_every_option_has_help_and_a_product_can_change_or_drop_it(self):
        helps = {action.option_strings[-1]: action.help for action in build_parser()._actions}
        assert all(helps.values())
        assert "--version" in helps
        profile = LlamaBenchProfile(
            option_help={"--fetch": "Fetch."}, known_models_option=False, version_option=False
        )
        parser = build_parser(profile)
        actions = {action.option_strings[-1]: action for action in parser._actions}
        assert actions["--fetch"].help == "Fetch."
        assert actions["--models-dir"].help is None
        assert "--known-models" not in actions and "--version" not in actions
        assert parser.parse_args(["--models-dir", "m"]).known_models is None

    def test_a_broken_known_models_file_stops_before_docker(self, tmp_path, capsys):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"models": [{"file": "x.gguf"}]}), encoding="utf-8")
        shell = RecordingShell()
        assert main(["--models-dir", str(tmp_path), "--known-models", str(bad)], shell=shell) == 2
        assert (
            "[error] --known-models bad.json: models[0] (x.gguf): missing url"
            in capsys.readouterr().out
        )
        assert shell.calls == []


class TestDryRun:
    def test_prints_the_commands_without_running_docker(self, tmp_path, capsys):
        shell = RecordingShell()
        status = main(
            [
                "--models-dir",
                str(tmp_path),
                "--known-models",
                known_file(tmp_path),
                "--fetch",
                "--dry-run",
            ],
            shell=shell,
        )
        assert status == 0
        assert shell.calls == []
        lines = capsys.readouterr().out.splitlines()
        assert len(lines) == 5
        assert "/opt/hbk/fetch-model.sh" in lines[0] and f"LLM_GGUF_FILE={SMALL}" in lines[0]
        assert f"LLM_GGUF_FILE={LARGE}" in lines[1]
        assert lines[-1].endswith(
            f"--bench -m /models/{SMALL} -m /models/{LARGE} -p 512,2048 -n 128 -d 0,4096 "
            "-ctk f16,q8_0 -ctv f16,q8_0 -t 4,8 -r 5 -o json --progress"
        )


class TestRun:
    def test_benchmark_is_run_and_saved_with_build_hashes_and_machine(self, tmp_path, capsys):
        shell = FakeDocker(f"812000000 {SMALL}\n951000000 {LARGE}\n")
        out_dir = tmp_path / "results"
        models = tmp_path / "models"
        status = main(
            [
                "--models-dir",
                str(models),
                "--known-models",
                known_file(tmp_path),
                "--out-dir",
                str(out_dir),
                "--reference",
                "bench-01",
                "--ram-speed",
                "3200 MT/s",
            ],
            shell=shell,
        )
        assert status == 0
        saved, report = only_report(out_dir)
        assert saved.name.startswith("bench-01-") and saved.suffix == ".json"
        assert (report["kind"], report["schema_version"], report["label"]) == (
            "horus-llama-bench",
            1,
            "bench-01",
        )
        assert report["llama_cpp"]["build"] == "b11382"
        assert report["llama_cpp"]["image_digest"].endswith("b" * 64)
        assert [model["sha256"] for model in report["models"]] == [SUMS[SMALL], SUMS[LARGE]]
        assert all(model["matches_known_sha256"] for model in report["models"])
        assert report["models"][1]["size_bytes"] == 951_000_000
        assert report["machine"]["reference"] == "bench-01"
        assert report["machine"]["cpu_model"] == "Example CPU 8C"
        assert report["machine"]["ram_speed"] == "3200 MT/s"
        assert report["machine"]["docker"]["mem_total_bytes"] == 16 * GIB
        assert report["run"]["git_commit"] == "abc1234"
        launched = next(call for call in shell.calls if "--bench" in call)
        assert launched[3:5] == ["-v", f"{models.resolve()}:/models:ro"]
        assert report["run"]["command"] == [*launched[:4], "<models-dir>:/models:ro", *launched[5:]]
        assert report["run"]["matrix"]["repetitions"] == 5
        assert len(report["results"]) == 4
        assert shell.host_paths == [models.resolve()]
        output = capsys.readouterr().out
        assert "containers are running" not in output
        assert "[info] 96 tests, 5 repetitions each" in output
        assert f"[done] wrote {saved}" in output

    def test_a_product_names_the_containers_that_compete_for_the_machine(self, tmp_path, capsys):
        profile = LlamaBenchProfile(
            busy_containers=("model-server", "web"),
            busy_warning="stack containers are running ({names})",
            known_models=KNOWN,
            reference="lab-01",
        )
        shell = FakeDocker(f"812000000 {SMALL}\n951000000 {LARGE}\n")
        assert (
            main(
                ["--models-dir", str(tmp_path), "--out-dir", str(tmp_path / "out")],
                profile=profile,
                shell=shell,
            )
            == 0
        )
        assert "[warn] stack containers are running (model-server)" in capsys.readouterr().out
        _saved, report = only_report(tmp_path / "out")
        assert report["label"] == "lab-01"
        assert [model["file"] for model in report["models"]] == [SMALL, LARGE]

    def test_missing_model_stops_before_the_benchmark(self, tmp_path, capsys):
        shell = FakeDocker(f"812000000 {SMALL}\n")
        status = main(
            [
                "--models-dir",
                str(tmp_path),
                "--model",
                SMALL,
                "--model",
                LARGE,
                "--out-dir",
                str(tmp_path / "out"),
            ],
            shell=shell,
        )
        assert status == 1
        output = capsys.readouterr().out
        assert f"{LARGE}: not found in" in output
        assert "[error] pass --fetch with --known-models to download the missing models" in output
        assert not any("--bench" in call for call in shell.calls)
        assert not (tmp_path / "out").exists()

    def test_fetch_downloads_a_missing_known_model(self, tmp_path):
        shell = FakeDocker([f"812000000 {SMALL}\n", f"812000000 {SMALL}\n951000000 {LARGE}\n"])
        models = tmp_path / "new-models"
        status = main(
            [
                "--models-dir",
                str(models),
                "--known-models",
                known_file(tmp_path),
                "--fetch",
                "--out-dir",
                str(tmp_path / "out"),
            ],
            shell=shell,
        )
        assert status == 0
        assert models.is_dir()
        fetches = [call for call in shell.calls if "LLM_GGUF_FILE=" + LARGE in call]
        assert len(fetches) == 1
        assert any(
            part.endswith("fetch-model.sh:/opt/hbk/fetch-model.sh:ro") for part in fetches[0]
        )
        assert shell.calls.index(fetches[0]) < next(
            i for i, call in enumerate(shell.calls) if "--bench" in call
        )

    def test_an_unknown_missing_model_cannot_be_fetched(self, tmp_path, capsys):
        shell = FakeDocker("")
        status = main(
            [
                "--models-dir",
                str(tmp_path),
                "--model",
                "own.gguf",
                "--fetch",
                "--out-dir",
                str(tmp_path / "out"),
            ],
            shell=shell,
        )
        assert status == 1
        assert (
            "own.gguf: not a known model, copy it into the models folder yourself"
            in capsys.readouterr().out
        )

    def test_unreadable_output_is_kept_for_diagnosis(self, tmp_path, capsys):
        shell = FakeDocker(f"1 {SMALL}\n", temp=tmp_path, bench_output="oops", bench_code=1)
        status = main(
            [
                "--models-dir",
                str(tmp_path),
                "--model",
                SMALL,
                "--out-dir",
                str(tmp_path / "out"),
                "--label",
                "lab",
            ],
            shell=shell,
        )
        assert status == 1
        assert "llama-bench exited with 1" in capsys.readouterr().out
        assert [path.read_text() for path in tmp_path.glob("llama-bench-lab-*.txt")] == ["oops"]

    def test_a_different_file_than_the_known_one_is_flagged(self, tmp_path, capsys):
        known = {SMALL: KnownModel(SMALL, "https://models.example/x", 1, "f" * 64)}
        shell = FakeDocker(f"812000000 {SMALL}\n", bench_output=json.dumps(bench_rows(SMALL)))
        status = main(
            ["--models-dir", str(tmp_path), "--out-dir", str(tmp_path / "out")],
            profile=LlamaBenchProfile(known_models=known),
            shell=shell,
        )
        assert status == 0
        output = capsys.readouterr().out
        assert (
            f"[warn] {SMALL} does not match the SHA-256 of the known model; record its SHA-256 with the result"
            in output
        )


class TestFromJson:
    def test_a_saved_raw_run_is_enriched_without_running_llama_bench(self, tmp_path):
        raw = tmp_path / "raw.json"
        raw.write_text(json.dumps(bench_rows(SMALL)), encoding="utf-8")
        shell = FakeDocker(f"812000000 {SMALL}\n")
        status = main(
            [
                "--from-json",
                str(raw),
                "--models-volume",
                "bench_models",
                "--label",
                "lab q4 only",
                "--out-dir",
                str(tmp_path / "out"),
            ],
            shell=shell,
        )
        assert status == 0
        assert not any("--bench" in call for call in shell.calls)
        saved, report = only_report(tmp_path / "out")
        assert saved.name.startswith("lab-q4-only-")
        assert report["run"]["from_json"] == "raw.json"
        assert report["run"]["command"] is None
        assert report["run"]["models_location"] == {"dir": None, "volume": "bench_models"}
        assert [model["file"] for model in report["models"]] == [SMALL]
        assert report["models"][0]["sha256"] == SUMS[SMALL]

    def test_without_a_models_location_the_hashes_stay_empty(self, tmp_path, capsys):
        raw = tmp_path / "raw.json"
        raw.write_text(json.dumps(bench_rows(SMALL)), encoding="utf-8")
        assert (
            main(
                ["--from-json", str(raw), "--out-dir", str(tmp_path / "out")], shell=FakeDocker("")
            )
            == 0
        )
        _saved, report = only_report(tmp_path / "out")
        assert report["label"] == "llama-bench"
        assert report["models"][0]["sha256"] is None
        assert "SHA-256 is not recorded" in capsys.readouterr().out

    def test_an_unreadable_saved_run_is_an_input_error(self, tmp_path, capsys):
        raw = tmp_path / "raw.json"
        raw.write_text("no results here", encoding="utf-8")
        assert (
            main(
                ["--from-json", str(raw), "--out-dir", str(tmp_path / "out")], shell=FakeDocker("")
            )
            == 2
        )
        assert (
            "[error] --from-json: the llama-bench output holds no JSON array"
            in capsys.readouterr().out
        )

    def test_a_product_can_let_input_errors_raise(self, tmp_path):
        argv = ["--from-json", str(tmp_path / "missing.json"), "--dry-run"]
        with pytest.raises(FileNotFoundError):
            main(argv, profile=LlamaBenchProfile(input_errors=()), shell=RecordingShell())


class TestRecordedPaths:
    def test_the_report_keeps_no_part_of_the_host_models_folder(
        self, tmp_path, host_folder, host_folder_leaks
    ):
        shell = FakeDocker(f"812000000 {SMALL}\n", bench_output=json.dumps(bench_rows(SMALL)))
        status = main(
            ["--models-dir", host_folder, "--model", SMALL, "--out-dir", str(tmp_path / "out")],
            shell=shell,
        )
        assert status == 0
        launched = next(call for call in shell.calls if "--bench" in call)
        assert host_folder_leaks(" ".join(launched)) != []
        saved, report = only_report(tmp_path / "out")
        assert report["run"]["models_location"] == {"dir": "<models-dir>", "volume": None}
        assert "<models-dir>:/models:ro" in report["run"]["command"]
        assert host_folder_leaks(saved.read_text(encoding="utf-8")) == []

    def test_a_saved_raw_run_is_recorded_by_its_file_name(self, tmp_path):
        raw = tmp_path / "raw.json"
        raw.write_text(json.dumps(bench_rows(SMALL)), encoding="utf-8")
        assert (
            main(
                ["--from-json", str(raw), "--out-dir", str(tmp_path / "out")], shell=FakeDocker("")
            )
            == 0
        )
        saved, report = only_report(tmp_path / "out")
        assert report["run"]["from_json"] == "raw.json"
        assert tmp_path.name not in saved.read_text(encoding="utf-8")


def test_the_tool_also_runs_as_a_module():
    completed = run_module("horus_bench_kit.cli.llama_bench", "--help")
    assert completed.returncode == 0
    assert "--known-models" in completed.stdout
    version = run_module("horus_bench_kit.cli.llama_bench", "--version")
    assert (version.returncode, version.stdout.strip()) == (0, f"hbk-llama-bench {__version__}")
