# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from horus_bench_kit.candidates import catalog_problems, is_bare_gguf_name, known_models_of
from horus_bench_kit.files import SHA256_PATTERN, load_data
from horus_bench_kit.llama_bench import KnownModel, models_mount

FETCH_IMAGE = "ghcr.io/ggml-org/llama.cpp:server-b11382"
FETCH_SCRIPT_NAME = "fetch-model.sh"
CONTAINER_FETCH_SCRIPT = "/opt/hbk/fetch-model.sh"
KNOWN_MODEL_FIELDS = ("file", "url", "size_bytes", "sha256")


def packaged_fetch_script() -> Path:
    return Path(str(resources.files("horus_bench_kit") / "data" / FETCH_SCRIPT_NAME))


def fetch_command(
    image: str,
    source: str,
    script: str,
    model: KnownModel,
    *,
    container_script: str = CONTAINER_FETCH_SCRIPT,
) -> list[str]:
    return [
        "docker", "run", "--rm", *models_mount(source, writable=True),
        "-v", f"{script}:{container_script}:ro",
        "-e", f"LLM_GGUF_FILE={model.file}",
        "-e", f"LLM_GGUF_URL={model.url}",
        "-e", f"LLM_GGUF_SHA256={model.sha256}",
        "-e", f"LLM_GGUF_SIZE={model.size_bytes}",
        "-e", "HF_TOKEN",
        "--entrypoint", "/bin/sh", image, container_script,
    ]


def known_model_problems(entry: Any, index: int) -> list[str]:
    if not isinstance(entry, dict):
        return [f"models[{index}] must be an object"]
    label = f"models[{index}] ({entry.get('file') or '?'})"
    problems = [f"{label}: missing {name}" for name in KNOWN_MODEL_FIELDS if name not in entry]
    if problems:
        return problems
    if not is_bare_gguf_name(entry["file"]):
        problems.append(f"{label}: file must be a plain .gguf file name")
    if not str(entry["url"]).startswith(("https://", "http://")):
        problems.append(f"{label}: url must start with https:// or http://")
    size = entry["size_bytes"]
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        problems.append(f"{label}: size_bytes must be a positive whole number")
    if not SHA256_PATTERN.match(str(entry["sha256"])):
        problems.append(f"{label}: sha256 must be 64 lower-case hexadecimal characters")
    return problems


def known_models_from(data: Any) -> dict[str, KnownModel]:
    if isinstance(data, dict) and "candidates" in data:
        problems = catalog_problems(data)
        if problems:
            raise ValueError("; ".join(problems))
        return known_models_of(data)
    entries = data.get("models") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError("a known-models file holds a models list, or is a model catalog")
    problems = [problem for index, entry in enumerate(entries) for problem in known_model_problems(entry, index)]
    files = [entry["file"] for entry in entries if isinstance(entry, dict) and "file" in entry]
    repeated = sorted({file for file in files if files.count(file) > 1})
    if repeated:
        problems.append(f"files must be unique: {', '.join(repeated)}")
    if problems:
        raise ValueError("; ".join(problems))
    return {
        entry["file"]: KnownModel(entry["file"], entry["url"], entry["size_bytes"], entry["sha256"])
        for entry in entries
    }


def load_known_models(path: Path | str) -> dict[str, KnownModel]:
    return known_models_from(load_data(path, "known-models file"))
