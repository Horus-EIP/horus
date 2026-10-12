# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from horus_bench_kit.llama_bench import (
    BENCH_IMAGE,
    REPORT_KIND,
    BenchMatrix,
    KnownModel,
    bench_command,
    bench_test_name,
    build_report,
    checksum_command,
    container_path,
    image_build,
    listing_command,
    llama_cpp_section,
    model_files_in,
    model_records,
    parse_bench_output,
    parse_checksums,
    parse_listing,
    recorded_command,
    recorded_model_path,
    summary_lines,
    summary_rows,
)

SMALL = "alpha-1b-Q4_K_M.gguf"
LARGE = "alpha-1b-Q5_K_M.gguf"
SMALL_SHA256 = "a1" * 32
KNOWN = {
    SMALL: KnownModel(SMALL, f"https://models.example/alpha/{SMALL}", 812_000_000, SMALL_SHA256),
    LARGE: KnownModel(LARGE, f"https://models.example/alpha/{LARGE}", 951_000_000, "b2" * 32),
}


def bench_row(**overrides):
    row = {
        "build_commit": "0a1b2c3d",
        "build_number": 11382,
        "cpu_info": "Example CPU 6C",
        "gpu_info": "",
        "backends": "CPU",
        "model_filename": f"/models/{SMALL}",
        "model_type": "alpha 1B Q4_K - Medium",
        "model_size": 812_000_000,
        "n_threads": 4,
        "type_k": "f16",
        "type_v": "f16",
        "flash_attn": -1,
        "n_prompt": 512,
        "n_gen": 0,
        "n_depth": 0,
        "avg_ts": 61.2345,
        "stddev_ts": 0.871,
    }
    row.update(overrides)
    return row


class TestCommands:
    def test_bench_command_runs_the_whole_matrix_in_one_call(self):
        command = bench_command(BENCH_IMAGE, "/srv/models", [SMALL, LARGE], BenchMatrix())
        assert command == [
            "docker", "run", "--rm", "-v", "/srv/models:/models:ro", BENCH_IMAGE, "--bench",
            "-m", f"/models/{SMALL}", "-m", f"/models/{LARGE}",
            "-p", "512,2048", "-n", "128", "-d", "0,4096",
            "-ctk", "f16,q8_0", "-ctv", "f16,q8_0", "-t", "4,8", "-r", "5",
            "-o", "json", "--progress",
        ]

    def test_the_default_matrix_is_96_tests_for_two_models(self):
        assert BenchMatrix().test_count(2) == 96
        assert BenchMatrix(threads="6", cache_types_k="f16", cache_types_v="f16").test_count(1) == 6
        assert BenchMatrix(prompts="0", generations="64").test_count(1) == 16

    def test_a_volume_is_mounted_by_name(self):
        command = checksum_command(BENCH_IMAGE, "bench_models", [SMALL])
        assert command == [
            "docker", "run", "--rm", "-v", "bench_models:/models:ro",
            "--entrypoint", "sha256sum", BENCH_IMAGE, f"/models/{SMALL}",
        ]

    def test_listing_prints_size_and_name_of_each_gguf(self):
        command = listing_command(BENCH_IMAGE, "/srv/models")
        assert command[-2:] == ["-printf", "%s %f\\n"]
        assert "--entrypoint" in command and "find" in command

    def test_paths_in_the_container_and_in_reports(self):
        assert container_path(SMALL) == f"/models/{SMALL}"
        assert recorded_model_path(f"C:\\Users\\x\\models\\{SMALL}") == f"<models-dir>/{SMALL}"
        command = ["docker", "run", "-v", "/srv/models:/models:ro", "image"]
        assert recorded_command(command, "/srv/models") == ["docker", "run", "-v", "<models-dir>:/models:ro", "image"]
        assert recorded_command(command, None) == command
        assert recorded_command(None, "/srv/models") is None


class TestParsing:
    def test_listing(self):
        assert parse_listing(f"812000000 {SMALL}\n951000000 {LARGE}\ngarbage\n") == {
            SMALL: 812_000_000,
            LARGE: 951_000_000,
        }

    def test_checksums_keep_the_file_name(self):
        text = f"{SMALL_SHA256.upper()}  /models/{SMALL}\nsha256sum: /models/missing.gguf: No such file\n"
        assert parse_checksums(text) == {SMALL: SMALL_SHA256}

    def test_bench_output_with_noise_around_the_array(self):
        text = "warming up\n" + json.dumps([bench_row()]) + "\n"
        assert parse_bench_output(text)[0]["avg_ts"] == 61.2345

    @pytest.mark.parametrize("text", ["", "[]", '{"a": 1}', '[{"no_avg": 1}]'])
    def test_bench_output_without_results_is_rejected(self, text):
        with pytest.raises(ValueError):
            parse_bench_output(text)

    def test_model_files_follow_the_result_order(self):
        rows = [bench_row(), bench_row(model_filename=f"/models/{LARGE}"), bench_row()]
        assert model_files_in(rows) == [SMALL, LARGE]


class TestEnrichment:
    def test_models_are_checked_against_the_known_hashes(self):
        records = model_records([SMALL, LARGE], {SMALL: 812_000_000}, {SMALL: SMALL_SHA256, LARGE: "0" * 64}, KNOWN)
        assert records[0] == {
            "file": SMALL,
            "size_bytes": 812_000_000,
            "sha256": SMALL_SHA256,
            "known_source": KNOWN[SMALL].url,
            "matches_known_sha256": True,
        }
        assert records[1]["matches_known_sha256"] is False
        assert records[1]["size_bytes"] is None

    def test_without_known_models_nothing_is_matched(self):
        record = model_records([SMALL], {}, {SMALL: SMALL_SHA256})[0]
        assert record["known_source"] is None
        assert record["matches_known_sha256"] is None

    def test_image_build(self):
        assert image_build(BENCH_IMAGE) == "b11382"
        assert image_build("localhost:5000/llama.cpp:full-b11000") == "b11000"
        assert image_build("ghcr.io/ggml-org/llama.cpp:full") is None
        assert image_build("llama.cpp") is None

    def test_build_number_comes_from_the_results(self):
        section = llama_cpp_section(BENCH_IMAGE, "ghcr.io/ggml-org/llama.cpp@sha256:abc", [bench_row()])
        assert section == {
            "image": BENCH_IMAGE,
            "image_digest": "ghcr.io/ggml-org/llama.cpp@sha256:abc",
            "build": "b11382",
            "build_number": 11382,
            "build_commit": "0a1b2c3d",
            "image_tag_matches": True,
        }

    def test_string_build_number_and_a_different_tag(self):
        section = llama_cpp_section("llama.cpp:full-b11000", None, [bench_row(build_number="11382")])
        assert section["build"] == "b11382"
        assert section["image_tag_matches"] is False

    def test_test_names(self):
        assert bench_test_name(bench_row()) == "pp512"
        assert bench_test_name(bench_row(n_prompt=0, n_gen=128)) == "tg128"
        assert bench_test_name(bench_row(n_prompt=512, n_gen=128)) == "pp512+tg128"

    def test_summary_rows(self):
        rows = summary_rows([bench_row(n_depth=4096, type_k="q8_0", type_v="q8_0", n_threads=8)])
        assert rows == [
            {
                "model": SMALL,
                "model_type": "alpha 1B Q4_K - Medium",
                "test": "pp512",
                "n_depth": 4096,
                "type_k": "q8_0",
                "type_v": "q8_0",
                "n_threads": 8,
                "flash_attn": -1,
                "avg_ts": 61.23,
                "stddev_ts": 0.87,
            }
        ]
        assert summary_lines(rows) == [f"{SMALL}  pp512 @ d4096  KV q8_0/q8_0  t=8  61.23 ± 0.87 t/s"]


class TestReport:
    def report(self, **extra):
        rows = [bench_row(), bench_row(n_prompt=0, n_gen=128, avg_ts=9.5)]
        machine = {"reference": "bench-01", "cpu_model": "Example CPU 6C"}
        return rows, machine, build_report(
            label="bench-01",
            run={"started_at": "2026-10-08T08:00:00Z"},
            image=BENCH_IMAGE,
            image_digest=None,
            rows=rows,
            models=model_records([SMALL], {SMALL: 812_000_000}, {SMALL: SMALL_SHA256}, KNOWN),
            machine=machine,
            **extra,
        )

    def test_report_keeps_the_raw_results_unchanged(self):
        rows, machine, report = self.report()
        assert list(report) == [
            "kind", "schema_version", "label", "run", "llama_cpp", "models", "machine", "summary", "results",
        ]
        assert (report["kind"], report["schema_version"]) == (REPORT_KIND, 1)
        assert REPORT_KIND == "horus-llama-bench"
        assert report["results"] == rows
        assert report["llama_cpp"]["build"] == "b11382"
        assert report["models"][0]["sha256"] == SMALL_SHA256
        assert report["machine"] == machine
        assert isinstance(report["summary"], list)
        assert [row["test"] for row in report["summary"]] == ["pp512", "tg128"]
        json.dumps(report)

    def test_a_product_can_write_its_own_kind(self):
        _rows, _machine, report = self.report(kind="acme-llama-bench", schema_version=3)
        assert (report["kind"], report["schema_version"]) == ("acme-llama-bench", 3)
