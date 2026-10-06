#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench_host import (
    collect_host,
    docker_data_path,
    docker_facts,
    machine_section,
    missing_fields,
    run_text,
)
from bench_llama import (
    BENCH_IMAGE,
    DEFAULT_MODEL_FILES,
    DEFAULT_REPETITIONS,
    FETCH_IMAGE,
    KNOWN_MODELS,
    MODELS_DIR_PLACEHOLDER,
    PLAN_CACHE_TYPES,
    PLAN_DEPTHS,
    PLAN_GENERATIONS,
    PLAN_PROMPTS,
    PLAN_THREADS,
    BenchMatrix,
    bench_command,
    build_report,
    checksum_command,
    fetch_command,
    file_name,
    listing_command,
    model_files_in,
    model_records,
    parse_bench_output,
    parse_checksums,
    parse_listing,
    recorded_command,
    summary_lines,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO_ROOT / "scripts" / "eval"
FETCH_SCRIPT = REPO_ROOT / "src" / "infra" / "llm" / "fetch-model.sh"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmarks"
DEFAULT_REFERENCE = "cpu16"
STACK_CONTAINERS = ("llm", "mas", "agent", "knowledge_store", "vllm")
CHECKSUM_TIMEOUT_S = 1800.0


def load_module(path: Path, name: str) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


files = load_module(EVAL_DIR / "eval_files.py", "eval_files")


def now_utc(moment: datetime | None = None) -> str:
    return (moment or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run llama-bench in the pinned llama.cpp image and save the enriched result."
    )
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--models-dir", help="Host folder that holds the GGUF files.")
    location.add_argument(
        "--models-volume", help="Docker volume that holds the GGUF files."
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="GGUF file name inside the models folder or volume; repeat for several.",
    )
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--reference", default=DEFAULT_REFERENCE)
    parser.add_argument("--label")
    parser.add_argument("--image", default=BENCH_IMAGE)
    parser.add_argument("--fetch-image", default=FETCH_IMAGE)
    parser.add_argument("--prompts", default=PLAN_PROMPTS)
    parser.add_argument("--generations", default=PLAN_GENERATIONS)
    parser.add_argument("--depths", default=PLAN_DEPTHS)
    parser.add_argument("--cache-types-k", default=PLAN_CACHE_TYPES)
    parser.add_argument("--cache-types-v", default=PLAN_CACHE_TYPES)
    parser.add_argument("--threads", default=PLAN_THREADS)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--from-json", metavar="RAW_JSON")
    parser.add_argument("--cpu-model")
    parser.add_argument("--ram")
    parser.add_argument("--ram-speed")
    parser.add_argument("--disk-type")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--dry-run", action="store_true")
    return parser


def argument_errors(args: argparse.Namespace) -> list[str]:
    errors = []
    if not args.from_json and not (args.models_dir or args.models_volume):
        errors.append("give --models-dir or --models-volume (or --from-json to enrich a saved run)")
    if args.fetch and not (args.models_dir or args.models_volume):
        errors.append("--fetch needs --models-dir or --models-volume")
    if args.repetitions < 1:
        errors.append("--repetitions must be at least 1")
    try:
        files.safe_label(args.label or args.reference)
    except ValueError as exc:
        errors.append(f"--label: {exc}")
    return errors


def models_source(args: argparse.Namespace) -> str | None:
    if args.models_volume:
        return args.models_volume
    if args.models_dir:
        return str(Path(args.models_dir).expanduser().resolve())
    return None


def matrix_from(args: argparse.Namespace) -> BenchMatrix:
    return BenchMatrix(
        prompts=args.prompts,
        generations=args.generations,
        depths=args.depths,
        cache_types_k=args.cache_types_k,
        cache_types_v=args.cache_types_v,
        threads=args.threads,
        repetitions=args.repetitions,
    )


def git_commit() -> str | None:
    return (run_text(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"]) or "").strip() or None


def image_digest(image: str) -> str | None:
    digest = run_text(["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image])
    return (digest or "").strip() or None


def running_stack_containers() -> list[str]:
    names = (run_text(["docker", "ps", "--format", "{{.Names}}"]) or "").split()
    return [name for name in STACK_CONTAINERS if name in names]


def fetch_missing(args: argparse.Namespace, source: str, missing: list[str]) -> dict[str, str]:
    failures = {}
    if args.models_dir:
        Path(source).mkdir(parents=True, exist_ok=True)
    for file in missing:
        known = KNOWN_MODELS.get(file)
        if known is None:
            failures[file] = "not a known model, copy it into the models folder yourself"
            continue
        print(f"[info] downloading {file} ({known.size_bytes:,} bytes) and checking its SHA-256")
        command = fetch_command(args.fetch_image, source, str(FETCH_SCRIPT), known)
        if subprocess.run(command).returncode != 0:
            failures[file] = "the download or its SHA-256 check failed"
    return failures


def model_inventory(
    args: argparse.Namespace, source: str | None, model_files: list[str]
) -> tuple[dict[str, int], dict[str, str], list[str]]:
    if source is None:
        return {}, {}, []
    sizes = parse_listing(run_text(listing_command(args.image, source), timeout=600))
    missing = [file for file in model_files if file not in sizes]
    failures: dict[str, str] = {}
    if missing and args.fetch:
        failures = fetch_missing(args, source, missing)
        sizes = parse_listing(run_text(listing_command(args.image, source), timeout=600))
        missing = [file for file in model_files if file not in sizes]
    problems = [f"{file}: {failures.get(file, f'not found in {source}')}" for file in missing]
    present = [file for file in model_files if file in sizes]
    checksums = {}
    if present:
        output = run_text(checksum_command(args.image, source, present), timeout=CHECKSUM_TIMEOUT_S)
        checksums = parse_checksums(output)
    return sizes, checksums, problems


def run_bench(command: list[str], label: str) -> list[dict[str, Any]] | None:
    completed = subprocess.run(
        command, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace"
    )
    try:
        if completed.returncode != 0:
            raise ValueError(f"llama-bench exited with {completed.returncode}")
        return parse_bench_output(completed.stdout)
    except ValueError as exc:
        raw = Path(tempfile.gettempdir()) / f"llama-bench-{label}-{int(time.time())}.txt"
        raw.write_text(completed.stdout or "", encoding="utf-8")
        print(f"[error] {exc}; its standard output is in {raw}")
        return None


def print_dry_run(args: argparse.Namespace, source: str | None, model_files: list[str]) -> None:
    if source is not None:
        if args.fetch:
            for file in model_files:
                if file in KNOWN_MODELS:
                    command = fetch_command(args.fetch_image, source, str(FETCH_SCRIPT), KNOWN_MODELS[file])
                    print(shlex.join(command))
        print(shlex.join(listing_command(args.image, source)))
        print(shlex.join(checksum_command(args.image, source, model_files)))
        if not args.from_json:
            print(shlex.join(bench_command(args.image, source, model_files, matrix_from(args))))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args()
    errors = argument_errors(args)
    if errors:
        for error in errors:
            print(f"[error] {error}")
        return 2
    label = files.safe_label(args.label or args.reference)
    source = models_source(args)
    matrix = matrix_from(args)
    rows = None
    if args.from_json:
        rows = parse_bench_output(Path(args.from_json).read_text(encoding="utf-8"))
    model_files = args.models or (model_files_in(rows) if rows else list(DEFAULT_MODEL_FILES))
    if args.dry_run:
        print_dry_run(args, source, model_files)
        return 0

    sizes, checksums, problems = model_inventory(args, source, model_files)
    for problem in problems:
        print(f"[error] {problem}")
    if problems and rows is None:
        print("[error] pass --fetch to download the known models, see benchmarks/README.md")
        return 1
    if source is None:
        print("[warn] no --models-dir or --models-volume: the models' SHA-256 is not recorded")
    busy = running_stack_containers()
    if busy and rows is None:
        print(f"[warn] Horus containers are running ({', '.join(busy)}) and compete for CPU and RAM")

    started = datetime.now(UTC)
    command = None
    if rows is None:
        command = bench_command(args.image, source, model_files, matrix)
        print(f"[info] {matrix.test_count(len(model_files))} tests, {matrix.repetitions} repetitions each")
        print("[info] " + shlex.join(command))
        rows = run_bench(command, label)
        if rows is None:
            return 1
    finished = datetime.now(UTC)

    docker = docker_facts()
    disk_path = Path(source) if args.models_dir else docker_data_path(docker)
    overrides = {
        "cpu_model": args.cpu_model,
        "ram": args.ram,
        "ram_speed": args.ram_speed,
        "disk_type": args.disk_type,
    }
    machine = machine_section(args.reference, collect_host(disk_path), overrides, docker)
    for item in missing_fields(machine):
        print(f"[warn] machine {item}")
    run = {
        "started_at": now_utc(started),
        "finished_at": now_utc(finished),
        "duration_s": round((finished - started).total_seconds(), 1),
        "git_commit": git_commit(),
        "from_json": file_name(args.from_json) if args.from_json else None,
        "models_location": {"dir": MODELS_DIR_PLACEHOLDER if args.models_dir else None, "volume": args.models_volume},
        "command": recorded_command(command, source if args.models_dir else None),
        "matrix": asdict(matrix),
    }
    report = build_report(
        label=label,
        run=run,
        image=args.image,
        image_digest=image_digest(args.image),
        rows=rows,
        models=model_records(model_files_in(rows) or model_files, sizes, checksums),
        machine=machine,
    )
    out_path = files.report_path(args.out_dir, label, started.date())
    files.write_json(out_path, report)
    print("\n".join(summary_lines(report["summary"])))
    for model in report["models"]:
        if model["matches_known_sha256"] is False:
            print(f"[warn] {model['file']} is not the unsloth file; record its SHA-256 with the result")
    print(f"[done] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
