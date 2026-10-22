# SPDX-License-Identifier: Apache-2.0
import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

from horus_bench_kit.fetch import (
    CONTAINER_FETCH_SCRIPT,
    FETCH_IMAGE,
    fetch_command,
    known_models_from,
    load_known_models,
    packaged_fetch_script,
)
from horus_bench_kit.llama_bench import KnownModel

MODEL = KnownModel(
    "alpha-1b-Q4_K_M.gguf", "https://models.example/alpha-1b-Q4_K_M.gguf", 812_000_000, "a1" * 32
)


def entry(**overrides):
    value = {
        "file": MODEL.file,
        "url": MODEL.url,
        "size_bytes": MODEL.size_bytes,
        "sha256": MODEL.sha256,
    }
    value.update(overrides)
    return value


class TestCommand:
    def test_the_packaged_script_is_mounted_read_only_with_the_expected_hash(self):
        command = fetch_command(FETCH_IMAGE, "/srv/models", "/kit/fetch-model.sh", MODEL)
        assert CONTAINER_FETCH_SCRIPT == "/opt/hbk/fetch-model.sh"
        assert command[:6] == ["docker", "run", "--rm", "-v", "/srv/models:/models", "-v"]
        assert "/kit/fetch-model.sh:/opt/hbk/fetch-model.sh:ro" in command
        assert f"LLM_GGUF_FILE={MODEL.file}" in command
        assert f"LLM_GGUF_URL={MODEL.url}" in command
        assert f"LLM_GGUF_SHA256={MODEL.sha256}" in command
        assert f"LLM_GGUF_SIZE={MODEL.size_bytes}" in command
        assert "HF_TOKEN" in command
        assert command[-4:] == ["--entrypoint", "/bin/sh", FETCH_IMAGE, "/opt/hbk/fetch-model.sh"]

    def test_a_product_can_mount_its_own_script_elsewhere(self):
        command = fetch_command(
            FETCH_IMAGE, "models", "own.sh", MODEL, container_script="/opt/acme/get.sh"
        )
        assert "own.sh:/opt/acme/get.sh:ro" in command
        assert command[-1] == "/opt/acme/get.sh"


class TestPackagedScript:
    def test_the_script_ships_with_the_package(self):
        script = packaged_fetch_script()
        lines = script.read_text(encoding="utf-8").splitlines()
        assert lines[:2] == ["#!/bin/sh", "# SPDX-License-Identifier: Apache-2.0"]
        assert b"\r\n" not in script.read_bytes()
        text = "\n".join(lines)
        for name in (
            "LLM_GGUF_FILE",
            "LLM_GGUF_URL",
            "LLM_GGUF_SHA256",
            "LLM_GGUF_SIZE",
            "HF_TOKEN",
        ):
            assert name in text


def shell_tools():
    if sys.platform == "darwin":
        return None
    found = [shutil.which(name) for name in ("sh", "sha256sum", "stat", "cut")]
    return found[0] if all(found) else None


@pytest.mark.skipif(shell_tools() is None, reason="needs a POSIX sh with GNU coreutils")
class TestScriptRuns:
    def run_script(self, folder, model, **env):
        variables = {
            **os.environ,
            "LLM_MODELS_DIR": folder.as_posix(),
            "LLM_GGUF_FILE": model.file,
            "LLM_GGUF_URL": model.url,
            "LLM_GGUF_SHA256": model.sha256,
            "LLM_GGUF_SIZE": str(model.size_bytes),
            "LLM_GGUF_ATTEMPTS": "1",
            "LLM_GGUF_RETRY_SECONDS": "0",
            **env,
        }
        script = packaged_fetch_script().as_posix()
        return subprocess.run(
            [shell_tools(), script],
            env=variables,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_a_file_already_in_place_is_verified_and_marked(self, tmp_path):
        content = b"GGUF example bytes"
        model = KnownModel(
            "tiny.gguf",
            "http://127.0.0.1:9/tiny.gguf",
            len(content),
            hashlib.sha256(content).hexdigest(),
        )
        (tmp_path / "tiny.gguf").write_bytes(content)
        first = self.run_script(tmp_path, model)
        assert first.returncode == 0, first.stdout + first.stderr
        assert "[fetch-model] it has the expected SHA-256" in first.stdout
        assert (tmp_path / "tiny.gguf.sha256").read_text().strip() == model.sha256
        second = self.run_script(tmp_path, model)
        assert "was verified before" in second.stdout

    def test_a_wrong_file_is_replaced_and_a_failed_download_stops(self, tmp_path):
        model = KnownModel("tiny.gguf", "http://127.0.0.1:9/tiny.gguf", 4, "0" * 64)
        (tmp_path / "tiny.gguf").write_bytes(b"nope")
        if shutil.which("curl") is None:
            pytest.skip("needs curl")
        completed = self.run_script(tmp_path, model)
        assert completed.returncode == 1
        assert "it is not the expected file" in completed.stdout
        assert "the download failed 1 times" in completed.stdout
        assert not (tmp_path / "tiny.gguf").exists()


class TestKnownModels:
    def test_a_models_list(self, tmp_path):
        path = tmp_path / "known.json"
        path.write_text(json.dumps({"models": [entry()]}), encoding="utf-8")
        assert load_known_models(path) == {MODEL.file: MODEL}

    def test_a_catalog_gives_every_gguf_with_its_pinned_url(self, examples):
        known = load_known_models(examples / "catalog.json")
        assert sorted(known) == [
            "gemma-4-e4b-it-Q4_0.gguf",
            "qwen3-4b-instruct-2507-Q4_K_M.gguf",
            "qwen3-4b-instruct-2507-Q5_K_M.gguf",
        ]
        model = known["gemma-4-e4b-it-Q4_0.gguf"]
        assert model.url.startswith("https://huggingface.co/ggml-org/gemma-4-E4B-it-GGUF/resolve/")
        assert model.url.endswith("/gemma-4-E4B-it-Q4_0.gguf")

    def test_the_example_known_models_file(self, examples):
        known = load_known_models(examples / "known-models.json")
        assert list(known) == ["qwen3-4b-instruct-2507-Q4_K_M.gguf"]
        assert (
            known["qwen3-4b-instruct-2507-Q4_K_M.gguf"]
            == load_known_models(examples / "catalog.json")["qwen3-4b-instruct-2507-Q4_K_M.gguf"]
        )

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            (
                {"models": [entry(sha256="ABC")]},
                "sha256 must be 64 lower-case hexadecimal characters",
            ),
            ({"models": [entry(file="../x.gguf")]}, "file must be a plain .gguf file name"),
            ({"models": [entry(url="ftp://x")]}, "url must start with https:// or http://"),
            ({"models": [entry(size_bytes=0)]}, "size_bytes must be a positive whole number"),
            ({"models": [{"file": "x.gguf"}]}, "missing url"),
            ({"models": [entry(), entry()]}, "files must be unique: alpha-1b-Q4_K_M.gguf"),
            ({"files": []}, "holds a models list, or is a model catalog"),
            ({"candidates": []}, "missing top-level version"),
        ],
    )
    def test_problems_are_named(self, data, message):
        with pytest.raises(ValueError) as raised:
            known_models_from(data)
        assert message in str(raised.value)
