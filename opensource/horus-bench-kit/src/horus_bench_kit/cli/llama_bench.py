# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import shlex
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from horus_bench_kit import __version__
from horus_bench_kit.cli.eval import utf8_output
from horus_bench_kit.fetch import (
    CONTAINER_FETCH_SCRIPT,
    FETCH_IMAGE,
    fetch_command,
    load_known_models,
    packaged_fetch_script,
)
from horus_bench_kit.files import TIMESTAMP_FORMAT, report_path, safe_label, write_json
from horus_bench_kit.host import docker_data_path, machine_section, missing_fields
from horus_bench_kit.llama_bench import (
    BENCH_IMAGE,
    DEFAULT_CACHE_TYPES,
    DEFAULT_DEPTHS,
    DEFAULT_GENERATIONS,
    DEFAULT_PROMPTS,
    DEFAULT_REPETITIONS,
    DEFAULT_THREADS,
    MODELS_DIR_PLACEHOLDER,
    REPORT_KIND,
    SCHEMA_VERSION,
    BenchMatrix,
    KnownModel,
    bench_command,
    build_report,
    checksum_command,
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
from horus_bench_kit.shell import Shell

DESCRIPTION = (
    "Run llama-bench in a llama.cpp container and save the result with the machine and model facts."
)
CHECKSUM_TIMEOUT_S = 1800.0
LISTING_TIMEOUT_S = 600.0
OPTION_HELP = {
    "--models-dir": "Host folder that holds the GGUF files.",
    "--models-volume": "Docker volume that holds the GGUF files.",
    "--model": "GGUF file name inside the models folder or volume; repeat for several.",
    "--known-models": "Models with their URL, size and SHA-256 (a known-models file or a model catalog).",
    "--fetch": "Download the known models that are missing.",
    "--reference": "Name of the machine, kept in the report.",
    "--label": "Report label (default: --reference, or llama-bench).",
    "--image": "llama.cpp image that runs llama-bench.",
    "--fetch-image": "llama.cpp image that downloads and checks the models.",
    "--prompts": "Prompt lengths, comma-separated (llama-bench -p).",
    "--generations": "Generation lengths, comma-separated (-n).",
    "--depths": "Context depths, comma-separated (-d).",
    "--cache-types-k": "KV cache types of K, comma-separated (-ctk).",
    "--cache-types-v": "KV cache types of V, comma-separated (-ctv).",
    "--threads": "Thread counts, comma-separated (-t).",
    "--repetitions": "Repetitions of each test (-r).",
    "--from-json": "Turn a saved llama-bench -o json output into a report, without running anything.",
    "--cpu-model": "CPU model, when it cannot be read.",
    "--ram": "RAM size, for example '32 GB', when it cannot be read.",
    "--ram-speed": "RAM speed in MT/s, when it cannot be read.",
    "--disk-type": "Disk type of the models folder, when it cannot be read.",
    "--out-dir": "Folder for the report.",
    "--dry-run": "Print the Docker commands without running them.",
}


@dataclass(frozen=True)
class LlamaBenchProfile:
    prog: str | None = "hbk-llama-bench"
    description: str = DESCRIPTION
    kind: str = REPORT_KIND
    schema_version: int = SCHEMA_VERSION
    out_dir: str = "."
    reference: str | None = None
    label: str = "llama-bench"
    bench_image: str = BENCH_IMAGE
    fetch_image: str = FETCH_IMAGE
    known_models: Mapping[str, KnownModel] = field(default_factory=dict)
    fetch_script: Path | None = None
    container_fetch_script: str = CONTAINER_FETCH_SCRIPT
    git_dir: Path | None = None
    busy_containers: tuple[str, ...] = ()
    busy_warning: str = "containers are running ({names}) and compete for CPU and RAM"
    fetch_hint: str = "pass --fetch with --known-models to download the missing models"
    known_mismatch: str = (
        "{file} does not match the SHA-256 of the known model; record its SHA-256 with the result"
    )
    option_help: Mapping[str, str | None] = field(default_factory=lambda: dict(OPTION_HELP))
    known_models_option: bool = True
    version_option: bool = True
    input_errors: tuple[type[Exception], ...] = (OSError, ValueError)


DEFAULT_PROFILE = LlamaBenchProfile()


def build_parser(profile: LlamaBenchProfile = DEFAULT_PROFILE) -> argparse.ArgumentParser:
    helps = profile.option_help
    parser = argparse.ArgumentParser(prog=profile.prog, description=profile.description)
    if profile.version_option:
        parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--models-dir", help=helps.get("--models-dir"))
    location.add_argument("--models-volume", help=helps.get("--models-volume"))
    parser.add_argument("--model", action="append", dest="models", help=helps.get("--model"))
    if profile.known_models_option:
        parser.add_argument("--known-models", metavar="FILE", help=helps.get("--known-models"))
    else:
        parser.set_defaults(known_models=None)
    parser.add_argument("--fetch", action="store_true", help=helps.get("--fetch"))
    parser.add_argument("--reference", default=profile.reference, help=helps.get("--reference"))
    parser.add_argument("--label", help=helps.get("--label"))
    parser.add_argument("--image", default=profile.bench_image, help=helps.get("--image"))
    parser.add_argument(
        "--fetch-image", default=profile.fetch_image, help=helps.get("--fetch-image")
    )
    parser.add_argument("--prompts", default=DEFAULT_PROMPTS, help=helps.get("--prompts"))
    parser.add_argument(
        "--generations", default=DEFAULT_GENERATIONS, help=helps.get("--generations")
    )
    parser.add_argument("--depths", default=DEFAULT_DEPTHS, help=helps.get("--depths"))
    parser.add_argument(
        "--cache-types-k", default=DEFAULT_CACHE_TYPES, help=helps.get("--cache-types-k")
    )
    parser.add_argument(
        "--cache-types-v", default=DEFAULT_CACHE_TYPES, help=helps.get("--cache-types-v")
    )
    parser.add_argument("--threads", default=DEFAULT_THREADS, help=helps.get("--threads"))
    parser.add_argument(
        "--repetitions", type=int, default=DEFAULT_REPETITIONS, help=helps.get("--repetitions")
    )
    parser.add_argument("--from-json", metavar="RAW_JSON", help=helps.get("--from-json"))
    parser.add_argument("--cpu-model", help=helps.get("--cpu-model"))
    parser.add_argument("--ram", help=helps.get("--ram"))
    parser.add_argument("--ram-speed", help=helps.get("--ram-speed"))
    parser.add_argument("--disk-type", help=helps.get("--disk-type"))
    parser.add_argument("--out-dir", default=profile.out_dir, help=helps.get("--out-dir"))
    parser.add_argument("--dry-run", action="store_true", help=helps.get("--dry-run"))
    return parser


def run_label(args: argparse.Namespace, profile: LlamaBenchProfile = DEFAULT_PROFILE) -> str:
    return args.label or args.reference or profile.label


def argument_errors(
    args: argparse.Namespace,
    profile: LlamaBenchProfile = DEFAULT_PROFILE,
    known: Mapping[str, KnownModel] | None = None,
) -> list[str]:
    errors = []
    if not args.from_json and not (args.models_dir or args.models_volume):
        errors.append("give --models-dir or --models-volume (or --from-json to enrich a saved run)")
    if args.fetch and not (args.models_dir or args.models_volume):
        errors.append("--fetch needs --models-dir or --models-volume")
    if args.repetitions < 1:
        errors.append("--repetitions must be at least 1")
    try:
        safe_label(run_label(args, profile))
    except ValueError as exc:
        errors.append(f"--label: {exc}")
    if (
        not args.models
        and not args.from_json
        and not (profile.known_models if known is None else known)
    ):
        errors.append("give --model at least once, or --known-models to run every known model")
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


def image_digest(shell: Shell, image: str) -> str | None:
    digest = shell.run_text(
        ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image]
    )
    return (digest or "").strip() or None


def running_containers(shell: Shell, names: Sequence[str]) -> list[str]:
    if not names:
        return []
    running = (shell.run_text(["docker", "ps", "--format", "{{.Names}}"]) or "").split()
    return [name for name in names if name in running]


class LlamaBenchRun:
    def __init__(
        self,
        args: argparse.Namespace,
        profile: LlamaBenchProfile,
        known: Mapping[str, KnownModel],
        shell: Shell,
    ) -> None:
        self.args = args
        self.profile = profile
        self.known = known
        self.shell = shell
        self.label = safe_label(run_label(args, profile))
        self.source = models_source(args)
        self.matrix = matrix_from(args)

    def fetch_script(self) -> str:
        return str(self.profile.fetch_script or packaged_fetch_script())

    def fetch_command(self, model: KnownModel) -> list[str]:
        return fetch_command(
            self.args.fetch_image,
            self.source,
            self.fetch_script(),
            model,
            container_script=self.profile.container_fetch_script,
        )

    def fetch_missing(self, missing: list[str]) -> dict[str, str]:
        failures = {}
        if self.args.models_dir:
            Path(self.source).mkdir(parents=True, exist_ok=True)
        for file in missing:
            known = self.known.get(file)
            if known is None:
                failures[file] = "not a known model, copy it into the models folder yourself"
                continue
            print(
                f"[info] downloading {file} ({known.size_bytes:,} bytes) and checking its SHA-256"
            )
            if self.shell.run(self.fetch_command(known)) != 0:
                failures[file] = "the download or its SHA-256 check failed"
        return failures

    def inventory(self, model_files: list[str]) -> tuple[dict[str, int], dict[str, str], list[str]]:
        if self.source is None:
            return {}, {}, []
        listing = listing_command(self.args.image, self.source)
        sizes = parse_listing(self.shell.run_text(listing, timeout=LISTING_TIMEOUT_S))
        missing = [file for file in model_files if file not in sizes]
        failures: dict[str, str] = {}
        if missing and self.args.fetch:
            failures = self.fetch_missing(missing)
            sizes = parse_listing(self.shell.run_text(listing, timeout=LISTING_TIMEOUT_S))
            missing = [file for file in model_files if file not in sizes]
        problems = [
            f"{file}: {failures.get(file, f'not found in {self.source}')}" for file in missing
        ]
        present = [file for file in model_files if file in sizes]
        checksums = {}
        if present:
            output = self.shell.run_text(
                checksum_command(self.args.image, self.source, present), timeout=CHECKSUM_TIMEOUT_S
            )
            checksums = parse_checksums(output)
        return sizes, checksums, problems

    def run_bench(self, command: list[str]) -> list[dict[str, Any]] | None:
        returncode, stdout = self.shell.run_captured(command)
        try:
            if returncode != 0:
                raise ValueError(f"llama-bench exited with {returncode}")
            return parse_bench_output(stdout)
        except ValueError as exc:
            raw = self.shell.temp_dir() / f"llama-bench-{self.label}-{int(time.time())}.txt"
            raw.write_text(stdout or "", encoding="utf-8")
            print(f"[error] {exc}; its standard output is in {raw}")
            return None

    def print_dry_run(self, model_files: list[str]) -> None:
        if self.source is None:
            return
        if self.args.fetch:
            for file in model_files:
                if file in self.known:
                    print(shlex.join(self.fetch_command(self.known[file])))
        print(shlex.join(listing_command(self.args.image, self.source)))
        print(shlex.join(checksum_command(self.args.image, self.source, model_files)))
        if not self.args.from_json:
            print(shlex.join(bench_command(self.args.image, self.source, model_files, self.matrix)))

    def execute(self) -> int:
        args, profile = self.args, self.profile
        rows = None
        if args.from_json:
            try:
                rows = parse_bench_output(Path(args.from_json).read_text(encoding="utf-8"))
            except profile.input_errors as exc:
                print(f"[error] --from-json: {exc}")
                return 2
        model_files = args.models or (model_files_in(rows) if rows else list(self.known))
        if args.dry_run:
            self.print_dry_run(model_files)
            return 0

        sizes, checksums, problems = self.inventory(model_files)
        for problem in problems:
            print(f"[error] {problem}")
        if problems and rows is None:
            print(f"[error] {profile.fetch_hint}")
            return 1
        if self.source is None:
            print("[warn] no --models-dir or --models-volume: the models' SHA-256 is not recorded")
        busy = running_containers(self.shell, profile.busy_containers)
        if busy and rows is None:
            print(f"[warn] {profile.busy_warning.format(names=', '.join(busy))}")

        started = datetime.now(timezone.utc)
        command = None
        if rows is None:
            command = bench_command(args.image, self.source, model_files, self.matrix)
            print(
                f"[info] {self.matrix.test_count(len(model_files))} tests, {self.matrix.repetitions} repetitions each"
            )
            print("[info] " + shlex.join(command))
            rows = self.run_bench(command)
            if rows is None:
                return 1
        finished = datetime.now(timezone.utc)

        docker = self.shell.docker_facts()
        disk_path = Path(self.source) if args.models_dir else docker_data_path(docker)
        overrides = {
            "cpu_model": args.cpu_model,
            "ram": args.ram,
            "ram_speed": args.ram_speed,
            "disk_type": args.disk_type,
        }
        machine = machine_section(
            args.reference, self.shell.collect_host(disk_path), overrides, docker
        )
        for item in missing_fields(machine):
            print(f"[warn] machine {item}")
        run = {
            "started_at": started.strftime(TIMESTAMP_FORMAT),
            "finished_at": finished.strftime(TIMESTAMP_FORMAT),
            "duration_s": round((finished - started).total_seconds(), 1),
            "git_commit": self.shell.git_commit(profile.git_dir),
            "from_json": file_name(args.from_json) if args.from_json else None,
            "models_location": {
                "dir": MODELS_DIR_PLACEHOLDER if args.models_dir else None,
                "volume": args.models_volume,
            },
            "command": recorded_command(command, self.source if args.models_dir else None),
            "matrix": asdict(self.matrix),
        }
        report = build_report(
            label=self.label,
            run=run,
            image=args.image,
            image_digest=image_digest(self.shell, args.image),
            rows=rows,
            models=model_records(model_files_in(rows) or model_files, sizes, checksums, self.known),
            machine=machine,
            kind=profile.kind,
            schema_version=profile.schema_version,
        )
        out_path = report_path(args.out_dir, self.label, started.date())
        write_json(out_path, report)
        print("\n".join(summary_lines(report["summary"])))
        for model in report["models"]:
            if model["matches_known_sha256"] is False:
                print(f"[warn] {profile.known_mismatch.format(file=model['file'])}")
        print(f"[done] wrote {out_path}")
        return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    profile: LlamaBenchProfile = DEFAULT_PROFILE,
    shell: Shell | None = None,
) -> int:
    utf8_output()
    args = build_parser(profile).parse_args(argv)
    known = dict(profile.known_models)
    errors = []
    if args.known_models:
        try:
            known.update(load_known_models(args.known_models))
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append(f"--known-models {Path(args.known_models).name}: {exc}")
    errors = argument_errors(args, profile, known) + errors
    if errors:
        for error in errors:
            print(f"[error] {error}")
        return 2
    return LlamaBenchRun(args, profile, known, shell or Shell()).execute()


if __name__ == "__main__":
    raise SystemExit(main())
