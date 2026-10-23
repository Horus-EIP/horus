# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

REPORT_KIND = "horus-llama-bench"
SCHEMA_VERSION = 1
RAW_REPORT_KIND = "llama-bench"
BENCH_IMAGE = "ghcr.io/ggml-org/llama.cpp:full-b11382"
CONTAINER_MODELS_DIR = "/models"
MODELS_DIR_PLACEHOLDER = "<models-dir>"
DEFAULT_PROMPTS = "512,2048"
DEFAULT_GENERATIONS = "128"
DEFAULT_DEPTHS = "0,4096"
DEFAULT_CACHE_TYPES = "f16,q8_0"
DEFAULT_THREADS = "4,8"
DEFAULT_REPETITIONS = 5

_IMAGE_BUILD = re.compile(r"(?:^|-)b(\d+)$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class KnownModel:
    file: str
    url: str
    size_bytes: int
    sha256: str


def split_values(text: str) -> list[str]:
    return [value.strip() for value in str(text).split(",") if value.strip()]


@dataclass(frozen=True)
class BenchMatrix:
    prompts: str = DEFAULT_PROMPTS
    generations: str = DEFAULT_GENERATIONS
    depths: str = DEFAULT_DEPTHS
    cache_types_k: str = DEFAULT_CACHE_TYPES
    cache_types_v: str = DEFAULT_CACHE_TYPES
    threads: str = DEFAULT_THREADS
    repetitions: int = DEFAULT_REPETITIONS

    def llama_bench_args(self) -> list[str]:
        return [
            "-p",
            self.prompts,
            "-n",
            self.generations,
            "-d",
            self.depths,
            "-ctk",
            self.cache_types_k,
            "-ctv",
            self.cache_types_v,
            "-t",
            self.threads,
            "-r",
            str(self.repetitions),
        ]

    def test_count(self, model_count: int) -> int:
        tests = sum(1 for value in split_values(self.prompts) if value != "0")
        tests += sum(1 for value in split_values(self.generations) if value != "0")
        return (
            model_count
            * tests
            * len(split_values(self.depths))
            * len(split_values(self.cache_types_k))
            * len(split_values(self.cache_types_v))
            * len(split_values(self.threads))
        )


def file_name(path: Any) -> str:
    return re.split(r"[\\/]", str(path or ""))[-1]


def container_path(file: str) -> str:
    return f"{CONTAINER_MODELS_DIR}/{file}"


def models_mount(source: str, *, writable: bool = False) -> list[str]:
    return ["-v", f"{source}:{CONTAINER_MODELS_DIR}" + ("" if writable else ":ro")]


def recorded_model_path(path: Any) -> str:
    return f"{MODELS_DIR_PLACEHOLDER}/{file_name(path)}"


def recorded_command(command: list[str] | None, models_dir: str | None) -> list[str] | None:
    if not command or not models_dir:
        return command
    host = f"{models_dir}:"
    return [
        MODELS_DIR_PLACEHOLDER + arg[len(models_dir) :] if arg.startswith(host) else arg
        for arg in command
    ]


def bench_command(image: str, source: str, files: list[str], matrix: BenchMatrix) -> list[str]:
    command = ["docker", "run", "--rm", *models_mount(source), image, "--bench"]
    for file in files:
        command += ["-m", container_path(file)]
    return [*command, *matrix.llama_bench_args(), "-o", "json", "--progress"]


def listing_command(image: str, source: str) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        *models_mount(source),
        "--entrypoint",
        "find",
        image,
        CONTAINER_MODELS_DIR,
        "-maxdepth",
        "1",
        "-name",
        "*.gguf",
        "-printf",
        "%s %f\\n",
    ]


def checksum_command(image: str, source: str, files: list[str]) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        *models_mount(source),
        "--entrypoint",
        "sha256sum",
        image,
        *[container_path(file) for file in files],
    ]


def parse_listing(text: str | None) -> dict[str, int]:
    sizes = {}
    for line in (text or "").splitlines():
        size, _, name = line.strip().partition(" ")
        if size.isdigit() and name:
            sizes[name] = int(size)
    return sizes


def parse_checksums(text: str | None) -> dict[str, str]:
    checksums = {}
    for line in (text or "").splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and _SHA256.match(parts[0]):
            checksums[file_name(parts[1].lstrip("*"))] = parts[0].lower()
    return checksums


def parse_bench_output(text: str) -> list[dict[str, Any]]:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("the llama-bench output holds no JSON array")
    rows = json.loads(text[start : end + 1])
    if not isinstance(rows, list) or not rows:
        raise ValueError("llama-bench returned no results")
    if not all(isinstance(row, dict) and "avg_ts" in row for row in rows):
        raise ValueError("the llama-bench output is not a list of results")
    return rows


def model_files_in(rows: list[dict[str, Any]]) -> list[str]:
    return list(
        dict.fromkeys(
            file_name(row.get("model_filename")) for row in rows if row.get("model_filename")
        )
    )


def model_records(
    files: list[str],
    sizes: dict[str, int],
    checksums: dict[str, str],
    known_models: Mapping[str, KnownModel] | None = None,
) -> list[dict[str, Any]]:
    known_models = known_models or {}
    records = []
    for file in files:
        known = known_models.get(file)
        sha256 = checksums.get(file)
        records.append(
            {
                "file": file,
                "size_bytes": sizes.get(file),
                "sha256": sha256,
                "known_source": known.url if known else None,
                "matches_known_sha256": sha256 == known.sha256 if known and sha256 else None,
            }
        )
    return records


def image_build(image: str) -> str | None:
    last = image.rsplit("/", 1)[-1]
    if ":" not in last:
        return None
    match = _IMAGE_BUILD.search(last.rsplit(":", 1)[-1])
    return f"b{match.group(1)}" if match else None


def _single(values: Any) -> Any:
    distinct = list(dict.fromkeys(value for value in values if value not in (None, "")))
    return distinct[0] if len(distinct) == 1 else None


def llama_cpp_section(
    image: str, image_digest: str | None, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    number = _single(str(row.get("build_number") or "") for row in rows)
    build_number = int(number) if number and number.isdigit() else None
    tag_build = image_build(image)
    build = f"b{build_number}" if build_number is not None else tag_build
    return {
        "image": image,
        "image_digest": image_digest,
        "build": build,
        "build_number": build_number,
        "build_commit": _single(row.get("build_commit") for row in rows),
        "image_tag_matches": tag_build == build if tag_build and build_number is not None else None,
    }


def bench_test_name(row: dict[str, Any]) -> str:
    prompt = int(row.get("n_prompt") or 0)
    generated = int(row.get("n_gen") or 0)
    if prompt and generated:
        return f"pp{prompt}+tg{generated}"
    return f"pp{prompt}" if prompt else f"tg{generated}"


def _rounded(value: Any) -> float | None:
    return round(float(value), 2) if isinstance(value, (int, float)) else None


def summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "model": file_name(row.get("model_filename")) or None,
            "model_type": row.get("model_type"),
            "test": bench_test_name(row),
            "n_depth": int(row.get("n_depth") or 0),
            "type_k": row.get("type_k"),
            "type_v": row.get("type_v"),
            "n_threads": row.get("n_threads"),
            "flash_attn": row.get("flash_attn"),
            "avg_ts": _rounded(row.get("avg_ts")),
            "stddev_ts": _rounded(row.get("stddev_ts")),
        }
        for row in rows
    ]


def summary_lines(summary: list[dict[str, Any]]) -> list[str]:
    lines = []
    for row in summary:
        depth = f" @ d{row['n_depth']}" if row["n_depth"] else ""
        lines.append(
            f"{row['model']}  {row['test']}{depth}  KV {row['type_k']}/{row['type_v']}  "
            f"t={row['n_threads']}  {row['avg_ts']} ± {row['stddev_ts']} t/s"
        )
    return lines


def build_report(
    *,
    label: str,
    run: dict[str, Any],
    image: str,
    image_digest: str | None,
    rows: list[dict[str, Any]],
    models: list[dict[str, Any]],
    machine: dict[str, Any],
    kind: str = REPORT_KIND,
    schema_version: int = SCHEMA_VERSION,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "schema_version": schema_version,
        "label": label,
        "run": run,
        "llama_cpp": llama_cpp_section(image, image_digest, rows),
        "models": models,
        "machine": machine,
        "summary": summary_rows(rows),
        "results": rows,
    }
