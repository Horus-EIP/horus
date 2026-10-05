import json
import re
from pathlib import Path

import pytest
from bench_llama import (
    BENCH_IMAGE,
    FETCH_IMAGE,
    KNOWN_MODELS,
    REPORT_KIND,
    BenchMatrix,
    bench_command,
    bench_test_name,
    build_report,
    checksum_command,
    fetch_command,
    image_build,
    listing_command,
    llama_cpp_section,
    model_files_in,
    model_records,
    parse_bench_output,
    parse_checksums,
    parse_listing,
    summary_lines,
    summary_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
Q4 = "qwen3-4b-instruct-2507-Q4_K_M.gguf"
Q5 = "qwen3-4b-instruct-2507-Q5_K_M.gguf"
Q4_SHA256 = "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"


def bench_row(**overrides):
    row = {
        "build_commit": "11fe0215",
        "build_number": 11382,
        "cpu_info": "AMD Ryzen 5 5600U with Radeon Graphics",
        "gpu_info": "",
        "backends": "CPU",
        "model_filename": f"/models/{Q4}",
        "model_type": "qwen3 4B Q4_K - Medium",
        "model_size": 2497281120,
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


class TestPinnedBuildAndModels:
    def test_bench_image_is_the_full_image_of_the_pinned_server_build(self):
        compose = (REPO_ROOT / "src" / "infra" / "docker-compose.cpu.yml").read_text(encoding="utf-8")
        server_tag = re.search(r"ghcr\.io/ggml-org/llama\.cpp:server-(b\d+)", compose).group(1)
        assert BENCH_IMAGE == f"ghcr.io/ggml-org/llama.cpp:full-{server_tag}"
        assert FETCH_IMAGE == f"ghcr.io/ggml-org/llama.cpp:server-{server_tag}"

    def test_the_q4_model_is_the_one_the_cpu_stack_downloads(self):
        sources = [REPO_ROOT / "src" / "infra" / "docker-compose.cpu.yml", REPO_ROOT / "models" / "manifest.json"]
        stack = " ".join(path.read_text(encoding="utf-8") for path in sources if path.is_file())
        known = KNOWN_MODELS[Q4]
        for value in (known.file, known.sha256, str(known.size_bytes), known.url):
            assert value in stack

    def test_the_q5_model_comes_from_the_same_pinned_revision(self):
        assert KNOWN_MODELS[Q5].url.rsplit("/", 1)[0] == KNOWN_MODELS[Q4].url.rsplit("/", 1)[0]
        assert re.fullmatch(r"[0-9a-f]{64}", KNOWN_MODELS[Q5].sha256)

    def test_the_fetch_script_exists(self):
        assert (REPO_ROOT / "src" / "infra" / "llm" / "fetch-model.sh").is_file()


class TestCommands:
    def test_bench_command_is_the_plans_llama_bench_command(self):
        command = bench_command(BENCH_IMAGE, "/srv/models", [Q4, Q5], BenchMatrix())
        assert command == [
            "docker", "run", "--rm", "-v", "/srv/models:/models:ro", BENCH_IMAGE, "--bench",
            "-m", f"/models/{Q4}", "-m", f"/models/{Q5}",
            "-p", "512,2048", "-n", "128", "-d", "0,4096",
            "-ctk", "f16,q8_0", "-ctv", "f16,q8_0", "-t", "4,8", "-r", "5",
            "-o", "json", "--progress",
        ]

    def test_the_plan_matrix_is_96_tests_for_two_models(self):
        assert BenchMatrix().test_count(2) == 96
        assert BenchMatrix(threads="6", cache_types_k="f16", cache_types_v="f16").test_count(1) == 6

    def test_a_volume_is_mounted_by_name(self):
        command = checksum_command(BENCH_IMAGE, "infra_llm_models", [Q4])
        assert command == [
            "docker", "run", "--rm", "-v", "infra_llm_models:/models:ro",
            "--entrypoint", "sha256sum", BENCH_IMAGE, f"/models/{Q4}",
        ]

    def test_listing_prints_size_and_name_of_each_gguf(self):
        command = listing_command(BENCH_IMAGE, "/srv/models")
        assert command[-2:] == ["-printf", "%s %f\\n"]
        assert "--entrypoint" in command and "find" in command

    def test_fetch_reuses_the_stack_download_script_with_the_pinned_hash(self):
        command = fetch_command(FETCH_IMAGE, "/srv/models", "/repo/src/infra/llm/fetch-model.sh", KNOWN_MODELS[Q5])
        assert "/srv/models:/models" in command
        assert "/repo/src/infra/llm/fetch-model.sh:/opt/horus/fetch-model.sh:ro" in command
        assert f"LLM_GGUF_SHA256={KNOWN_MODELS[Q5].sha256}" in command
        assert f"LLM_GGUF_SIZE={KNOWN_MODELS[Q5].size_bytes}" in command
        assert "HF_TOKEN" in command
        assert command[-4:] == ["--entrypoint", "/bin/sh", FETCH_IMAGE, "/opt/horus/fetch-model.sh"]


class TestParsing:
    def test_listing(self):
        assert parse_listing(f"2497281120 {Q4}\n2889514080 {Q5}\ngarbage\n") == {Q4: 2497281120, Q5: 2889514080}

    def test_checksums_keep_the_file_name(self):
        text = f"{Q4_SHA256.upper()}  /models/{Q4}\nsha256sum: /models/missing.gguf: No such file\n"
        assert parse_checksums(text) == {Q4: Q4_SHA256}

    def test_bench_output_with_noise_around_the_array(self):
        text = "warming up\n" + json.dumps([bench_row()]) + "\n"
        assert parse_bench_output(text)[0]["avg_ts"] == 61.2345

    @pytest.mark.parametrize("text", ["", "[]", '{"a": 1}', '[{"no_avg": 1}]'])
    def test_bench_output_without_results_is_rejected(self, text):
        with pytest.raises(ValueError):
            parse_bench_output(text)

    def test_model_files_follow_the_result_order(self):
        rows = [bench_row(), bench_row(model_filename=f"/models/{Q5}"), bench_row()]
        assert model_files_in(rows) == [Q4, Q5]


class TestEnrichment:
    def test_models_are_checked_against_the_known_hashes(self):
        records = model_records([Q4, Q5], {Q4: 2497281120}, {Q4: Q4_SHA256, Q5: "0" * 64})
        assert records[0] == {
            "file": Q4,
            "size_bytes": 2497281120,
            "sha256": Q4_SHA256,
            "known_source": KNOWN_MODELS[Q4].url,
            "matches_known_sha256": True,
        }
        assert records[1]["matches_known_sha256"] is False
        assert records[1]["size_bytes"] is None

    def test_own_model_has_no_known_source(self):
        record = model_records(["own-Q4_K_M.gguf"], {}, {})[0]
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
            "build_commit": "11fe0215",
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
                "model": Q4,
                "model_type": "qwen3 4B Q4_K - Medium",
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
        assert summary_lines(rows) == [f"{Q4}  pp512 @ d4096  KV q8_0/q8_0  t=8  61.23 ± 0.87 t/s"]

    def test_report_keeps_the_raw_results_unchanged(self):
        rows = [bench_row(), bench_row(n_prompt=0, n_gen=128, avg_ts=9.5)]
        machine = {"reference": "cpu16", "cpu_model": "AMD Ryzen 5 5600U"}
        report = build_report(
            label="cpu16",
            run={"started_at": "2026-10-06T08:00:00Z"},
            image=BENCH_IMAGE,
            image_digest=None,
            rows=rows,
            models=model_records([Q4], {Q4: 2497281120}, {Q4: Q4_SHA256}),
            machine=machine,
        )
        assert report["kind"] == REPORT_KIND
        assert report["schema_version"] == 1
        assert report["results"] == rows
        assert report["llama_cpp"]["build"] == "b11382"
        assert report["models"][0]["sha256"] == Q4_SHA256
        assert report["machine"] == machine
        assert [row["test"] for row in report["summary"]] == ["pp512", "tg128"]
        json.dumps(report)
