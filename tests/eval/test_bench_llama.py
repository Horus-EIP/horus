import re
from pathlib import Path

from bench_llama import (
    BENCH_IMAGE,
    FETCH_IMAGE,
    KNOWN_MODELS,
    BenchMatrix,
    bench_command,
    fetch_command,
    model_records,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
Q4 = "qwen3-4b-instruct-2507-Q4_K_M.gguf"
Q5 = "qwen3-4b-instruct-2507-Q5_K_M.gguf"
Q4_SHA256 = "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"


class TestPinnedBuildAndModels:
    def test_bench_image_is_the_full_image_of_the_pinned_server_build(self):
        compose = (REPO_ROOT / "src" / "infra" / "docker-compose.cpu.yml").read_text(
            encoding="utf-8"
        )
        server_tag = re.search(r"ghcr\.io/ggml-org/llama\.cpp:server-(b\d+)", compose).group(1)
        assert BENCH_IMAGE == f"ghcr.io/ggml-org/llama.cpp:full-{server_tag}"
        assert FETCH_IMAGE == f"ghcr.io/ggml-org/llama.cpp:server-{server_tag}"

    def test_the_q4_model_is_the_one_the_cpu_stack_downloads(self):
        sources = [
            REPO_ROOT / "src" / "infra" / "docker-compose.cpu.yml",
            REPO_ROOT / "models" / "manifest.json",
        ]
        stack = " ".join(path.read_text(encoding="utf-8") for path in sources if path.is_file())
        known = KNOWN_MODELS[Q4]
        for value in (known.file, known.sha256, str(known.size_bytes), known.url):
            assert value in stack

    def test_the_q5_model_comes_from_the_same_pinned_revision(self):
        assert KNOWN_MODELS[Q5].url.rsplit("/", 1)[0] == KNOWN_MODELS[Q4].url.rsplit("/", 1)[0]
        assert re.fullmatch(r"[0-9a-f]{64}", KNOWN_MODELS[Q5].sha256)

    def test_the_fetch_script_exists(self):
        assert (REPO_ROOT / "src" / "infra" / "llm" / "fetch-model.sh").is_file()

    def test_the_kit_fetch_script_differs_from_the_stack_one_only_in_its_messages(self):
        def text(path):
            return path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")

        stack = text(REPO_ROOT / "src" / "infra" / "llm" / "fetch-model.sh")
        kit = text(
            REPO_ROOT
            / "opensource"
            / "horus-bench-kit"
            / "src"
            / "horus_bench_kit"
            / "data"
            / "fetch-model.sh"
        )
        kit = kit.replace("# SPDX-License-Identifier: Apache-2.0\n", "", 1)
        kit = kit.replace("[fetch-model]", "[llm-model]").replace(
            "the next run ", "the next start "
        )
        assert kit == stack


class TestCommands:
    def test_bench_command_is_the_plans_llama_bench_command(self):
        command = bench_command(BENCH_IMAGE, "/srv/models", [Q4, Q5], BenchMatrix())
        assert command == [
            "docker",
            "run",
            "--rm",
            "-v",
            "/srv/models:/models:ro",
            BENCH_IMAGE,
            "--bench",
            "-m",
            f"/models/{Q4}",
            "-m",
            f"/models/{Q5}",
            "-p",
            "512,2048",
            "-n",
            "128",
            "-d",
            "0,4096",
            "-ctk",
            "f16,q8_0",
            "-ctv",
            "f16,q8_0",
            "-t",
            "4,8",
            "-r",
            "5",
            "-o",
            "json",
            "--progress",
        ]

    def test_fetch_reuses_the_stack_download_script_with_the_pinned_hash(self):
        command = fetch_command(
            FETCH_IMAGE, "/srv/models", "/repo/src/infra/llm/fetch-model.sh", KNOWN_MODELS[Q5]
        )
        assert "/srv/models:/models" in command
        assert "/repo/src/infra/llm/fetch-model.sh:/opt/horus/fetch-model.sh:ro" in command
        assert f"LLM_GGUF_SHA256={KNOWN_MODELS[Q5].sha256}" in command
        assert f"LLM_GGUF_SIZE={KNOWN_MODELS[Q5].size_bytes}" in command
        assert "HF_TOKEN" in command
        assert command[-4:] == ["--entrypoint", "/bin/sh", FETCH_IMAGE, "/opt/horus/fetch-model.sh"]


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
