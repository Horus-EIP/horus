# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from horus_bench_kit import __version__
from horus_bench_kit.candidates import (
    DEFAULT_PROFILE,
    SERVING_STEPS,
    STEPS,
    CandidatesProfile,
    Variant,
    build_report,
    catalog_problems,
    load_catalog,
    markdown_summary,
    select_variants,
    variant_gate,
    variant_summary,
    written_report,
)
from horus_bench_kit.cli.eval import comma_list, utf8_output
from horus_bench_kit.fetch import CONTAINER_FETCH_SCRIPT, fetch_command, packaged_fetch_script
from horus_bench_kit.files import TIMESTAMP_FORMAT, report_path, safe_label, write_json
from horus_bench_kit.host import machine_section, missing_fields
from horus_bench_kit.llama_bench import (
    MODELS_DIR_PLACEHOLDER,
    recorded_command,
    recorded_model_path,
)
from horus_bench_kit.llama_server import (
    CANDIDATE_CONTAINER,
    DEFAULT_PORT,
    REASONING_MODES,
    build_tag,
    candidate_run_command,
    parse_container_inspect,
    parse_memory_events,
    parse_memory_limit,
    parse_process_memory,
    parse_props,
    parse_whole_number,
    server_args,
)
from horus_bench_kit.probe import DEFAULT_PROFILE as DEFAULT_CONTRACT
from horus_bench_kit.probe import (
    ContractProfile,
    build_contract_report,
    chat_url,
    context_problems,
    item_context,
    item_problems,
    load_items,
    load_template,
    probe_job,
    probe_records,
    read_reply_lines,
    run_template_probe,
    select_probe_items,
    split_command,
)
from horus_bench_kit.shell import Shell
from horus_bench_kit.target import shown_path
from horus_bench_kit.testset import file_sha256, load_testset

DESCRIPTION = (
    "Screen GGUF model candidates from a catalog: download and verify each file, run llama-bench, then "
    "serve each model with llama-server to probe a JSON answer contract and run an evaluation."
)
DOWNLOAD_FAILED = "download failed: "
NOT_SERVED = "not served: "
HEALTH_POLL_S = 5.0
DEFAULT_START_TIMEOUT_S = 900.0
DOCKER_STOP_TIMEOUT_S = 120.0
LOG_TAIL_LINES = 40
MACHINE_OVERRIDES = ("cpu_model", "ram", "ram_speed", "disk_type")
DEFAULT_PUBLISHED_PORT = 18080
DEFAULT_CTX_SIZE = 8192
DEFAULT_PROBE_MAX_TOKENS = 512
DEFAULT_PROBE_TIMEOUT_S = 600.0
LLAMA_BENCH_TOOL = "horus_bench_kit.cli.llama_bench"
EVAL_TOOL = "horus_bench_kit.cli.eval"
TEMPLATE_OPTIONS = ("probe_system", "probe_user_template")
OPTION_HELP = {
    "--catalog": "Model catalog, .json or .yaml.",
    "--only": "Candidate or GGUF ids, comma-separated.",
    "--all-quants": "Also the GGUFs that are not defaults.",
    "--steps": f"Among {','.join(STEPS)}.",
    "--models-dir": "Folder of the GGUF files; the fetch step creates it.",
    "--out-dir": "Folder for the summary and for the reports of each step.",
    "--reference": "Name of the machine, kept in the reports.",
    "--reasoning": "Reasoning mode of llama-server while it serves a candidate.",
    "--llm-mem-limit": "Memory limit of the candidate llama-server, e.g. 6g.",
    "--server-image": "Default: the catalog's pinned server image.",
    "--start-timeout": "Seconds to wait for llama-server to load a model.",
    "--testset": "Test set of the eval step.",
    "--ids": "Item ids, comma-separated, kept in the probe items and in the test set.",
    "--category": "Categories, comma-separated, kept in the probe items and in the test set.",
    "--limit": "Run at most this many probe items and test-set questions.",
    "--bench-arg": "Extra llama-bench tool argument.",
    "--eval-arg": "Extra evaluation tool argument.",
    "--cpu-model": "CPU model, when it cannot be read.",
    "--ram": "RAM size, for example '32 GB', when it cannot be read.",
    "--ram-speed": "RAM speed in MT/s, when it cannot be read.",
    "--disk-type": "Disk type of the models folder, when it cannot be read.",
    "--dry-run": "Print the plan without running anything.",
    "--resume": "Run more steps into an earlier summary.",
    "--resummarize": "Rebuild an earlier summary and its Markdown from the reports of its steps.",
}


def timestamp(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).strftime(TIMESTAMP_FORMAT)


@dataclass(frozen=True)
class RunnerProfile:
    prog: str | None = "hbk-model-candidates"
    description: str = DESCRIPTION
    summary: CandidatesProfile = DEFAULT_PROFILE
    contract: ContractProfile = DEFAULT_CONTRACT
    catalog: str | None = None
    models_dir: str = "models"
    out_dir: str = "."
    reference: str | None = None
    testset: str | None = None
    steps: tuple[str, ...] = ("fetch", "bench")
    categories: tuple[str, ...] | None = None
    base_dir: Path | None = None
    git_dir: Path | None = None
    candidate_container: str = CANDIDATE_CONTAINER
    fetch_script: Path | None = None
    container_fetch_script: str = CONTAINER_FETCH_SCRIPT
    option_help: Mapping[str, str | None] = field(default_factory=lambda: dict(OPTION_HELP))
    version_option: bool = True
    input_errors: tuple[type[Exception], ...] = (OSError, ValueError, RuntimeError)


DEFAULT_RUNNER = RunnerProfile()


def build_parser(
    profile: RunnerProfile = DEFAULT_RUNNER, run_class: type[CandidateRun] | None = None
) -> argparse.ArgumentParser:
    helps = profile.option_help
    parser = argparse.ArgumentParser(prog=profile.prog, description=profile.description)
    if profile.version_option:
        parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--catalog", default=profile.catalog, help=helps.get("--catalog"))
    parser.add_argument("--only", type=comma_list, help=helps.get("--only"))
    parser.add_argument("--all-quants", action="store_true", help=helps.get("--all-quants"))
    parser.add_argument("--steps", type=comma_list, default=list(profile.steps), help=helps.get("--steps"))
    parser.add_argument("--models-dir", default=profile.models_dir, help=helps.get("--models-dir"))
    parser.add_argument("--out-dir", default=profile.out_dir, help=helps.get("--out-dir"))
    parser.add_argument("--reference", default=profile.reference, help=helps.get("--reference"))
    parser.add_argument("--reasoning", choices=REASONING_MODES, default="off", help=helps.get("--reasoning"))
    parser.add_argument("--llm-mem-limit", help=helps.get("--llm-mem-limit"))
    parser.add_argument("--server-image", help=helps.get("--server-image"))
    if run_class is not None:
        run_class.add_serving_arguments(parser)
    parser.add_argument(
        "--start-timeout", type=float, default=DEFAULT_START_TIMEOUT_S, help=helps.get("--start-timeout")
    )
    parser.add_argument("--testset", default=profile.testset, help=helps.get("--testset"))
    parser.add_argument("--ids", type=comma_list, help=helps.get("--ids"))
    parser.add_argument("--category", type=comma_list, help=helps.get("--category"))
    parser.add_argument("--limit", type=int, help=helps.get("--limit"))
    parser.add_argument("--bench-arg", action="append", default=[], help=helps.get("--bench-arg"))
    parser.add_argument("--eval-arg", action="append", default=[], help=helps.get("--eval-arg"))
    parser.add_argument("--cpu-model", help=helps.get("--cpu-model"))
    parser.add_argument("--ram", help=helps.get("--ram"))
    parser.add_argument("--ram-speed", help=helps.get("--ram-speed"))
    parser.add_argument("--disk-type", help=helps.get("--disk-type"))
    parser.add_argument("--dry-run", action="store_true", help=helps.get("--dry-run"))
    previous = parser.add_mutually_exclusive_group()
    previous.add_argument("--resume", metavar="SUMMARY_JSON", help=helps.get("--resume"))
    previous.add_argument("--resummarize", metavar="SUMMARY_JSON", help=helps.get("--resummarize"))
    if run_class is not None:
        run_class.add_arguments(parser)
    return parser


def argument_errors(args: argparse.Namespace, profile: RunnerProfile = DEFAULT_RUNNER) -> list[str]:
    errors = []
    unknown = [step for step in args.steps if step not in STEPS]
    if unknown:
        errors.append(f"--steps: unknown {', '.join(unknown)}; choose among {', '.join(STEPS)}")
    if profile.categories and args.category and set(args.category) - set(profile.categories):
        errors.append(f"--category must be among {', '.join(profile.categories)}")
    if args.limit is not None and args.limit < 1:
        errors.append("--limit must be at least 1")
    if args.llm_mem_limit and parse_memory_limit(args.llm_mem_limit) is None:
        errors.append("--llm-mem-limit must look like 6g, 6144m or a number of bytes")
    if args.start_timeout <= 0:
        errors.append("--start-timeout must be positive")
    if not args.catalog:
        errors.append("--catalog is required")
    return errors


def machine_overrides(args: argparse.Namespace) -> list[str]:
    flags: list[str] = []
    for name in MACHINE_OVERRIDES:
        value = getattr(args, name)
        if value:
            flags += [f"--{name.replace('_', '-')}", value]
    return flags


def item_filters(args: argparse.Namespace) -> list[str]:
    flags: list[str] = []
    if args.ids:
        flags += ["--ids", ",".join(args.ids)]
    if args.category:
        flags += ["--category", ",".join(args.category)]
    if args.limit:
        flags += ["--limit", str(args.limit)]
    return flags


def relative_to(path: Path | str | None, base: Path | None) -> str | None:
    if not path:
        return None
    return shown_path(path, base)


def read_report(base: Path, relative: str | None) -> dict[str, Any] | None:
    if not relative:
        return None
    path = Path(relative) if Path(relative).is_absolute() else base / relative
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def catalog_info(path: Path, catalog: dict[str, Any], base: Path | None) -> dict[str, Any]:
    return {
        "path": relative_to(path, base),
        "version": str(catalog["version"]),
        "sha256": file_sha256(path),
        "looked_up": str(catalog.get("looked_up")),
        "pinned_build": catalog["llama_cpp"]["pinned_build"],
    }


class CandidateRun:
    def __init__(
        self,
        args: argparse.Namespace,
        catalog: dict[str, Any],
        variants: list[Variant],
        testset: dict[str, Any] | None,
        summary_path: Path,
        started: datetime,
        previous: dict[str, Any] | None = None,
        *,
        profile: RunnerProfile = DEFAULT_RUNNER,
        shell: Shell | None = None,
    ) -> None:
        self.args = args
        self.catalog = catalog
        self.variants = variants
        self.testset = testset
        self.summary_path = summary_path
        self.base_dir = summary_path.parent
        self.run_dir = summary_path.with_suffix("")
        self.started = started
        self.profile = profile
        self.shell = shell or Shell()
        self.container = profile.candidate_container
        self.previous_run = (previous or {}).get("run") or {}
        self.models_dir = Path(args.models_dir).expanduser().resolve()
        self.server_image = args.server_image or catalog["llama_cpp"]["server_image"]
        self.cache_type = str(catalog["llama_bench"]["cache_types_k"]).split(",")[0]
        earlier = {entry.get("id"): entry for entry in (previous or {}).get("variants") or []}
        self.state: dict[str, dict[str, Any]] = {}
        for variant in variants:
            entry = earlier.get(variant.id) or {}
            problems = list(entry.get("problems") or [])
            gate = [f"skipped: {text}" for text in variant_gate(variant, catalog, profile.summary.gate_build)]
            self.state[variant.id] = {
                "skipped": bool(gate),
                "fetch": entry.get("fetch"),
                "reports": dict(entry.get("reports") or {}),
                "server": entry.get("server"),
                "memory": dict(entry.get("memory") or {}),
                "problems": problems + [text for text in gate if text not in problems],
            }
        self.machine: dict[str, Any] | None = (previous or {}).get("machine") or None
        self.stack: dict[str, Any] | None = self.previous_run.get("stack_llm")
        self.completed = False
        self.setup()

    @classmethod
    def add_serving_arguments(cls, parser: argparse.ArgumentParser) -> None:
        return None

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        return None

    @classmethod
    def argument_errors(cls, args: argparse.Namespace) -> list[str]:
        return []

    @classmethod
    def load_testset(cls, path: str) -> dict[str, Any]:
        return load_testset(path)

    def setup(self) -> None:
        return None

    def runnable(self, variant: Variant) -> bool:
        state = self.state[variant.id]
        fetched = state["fetch"] is None or state["fetch"].get("status") == "verified"
        return not state["skipped"] and fetched

    def probe_items(self) -> list[dict[str, Any]]:
        return []

    def testset_section(self) -> dict[str, Any] | None:
        if self.testset is None:
            return None
        testset_path = Path(self.args.testset).resolve()
        return {
            "path": relative_to(self.args.testset, self.profile.base_dir),
            "version": str(self.testset.get("version")),
            "sha256": file_sha256(testset_path),
            "filters": {"ids": self.args.ids, "categories": self.args.category, "limit": self.args.limit},
            "probe_items": len(self.probe_items()),
        }

    def session(self) -> dict[str, Any]:
        return {
            "started_at": timestamp(self.started),
            "finished_at": timestamp() if self.completed else None,
            "completed": self.completed,
            "git_commit": self.shell.git_commit(self.profile.git_dir),
            "steps": list(self.args.steps),
            "reasoning": self.args.reasoning,
            "only": self.args.only,
            "all_quants": self.args.all_quants,
            "models_dir": MODELS_DIR_PLACEHOLDER,
            "server_image": self.server_image,
            "llm_mem_limit_bytes": self.memory_limit(),
            "testset": self.testset_section(),
        }

    def run_info(self) -> dict[str, Any]:
        sessions = [*(self.previous_run.get("sessions") or []), self.session()]
        serving = [s for s in sessions if SERVING_STEPS & set(s.get("steps") or [])]
        current = sessions[-1]
        return {
            "started_at": sessions[0]["started_at"],
            "finished_at": current["finished_at"],
            "completed": current["completed"],
            "git_commit": current["git_commit"],
            "steps": [step for step in STEPS if any(step in (s.get("steps") or []) for s in sessions)],
            "reasoning": (serving[-1] if serving else current)["reasoning"],
            "stack_llm": self.stack,
            "testset": current["testset"],
            "sessions": sessions,
        }

    def memory_limit(self) -> int | None:
        if self.args.llm_mem_limit:
            return parse_memory_limit(self.args.llm_mem_limit)
        return (self.stack or {}).get("memory_bytes")

    def summaries(self) -> list[dict[str, Any]]:
        result = []
        for variant in self.variants:
            state = self.state[variant.id]
            reports = state["reports"]
            result.append(
                variant_summary(
                    variant,
                    profile=self.profile.summary,
                    cache_type=self.cache_type,
                    fetch=state["fetch"],
                    reports=reports,
                    bench_report=read_report(self.base_dir, reports.get("llama_bench")),
                    contract_report=read_report(self.base_dir, reports.get("contract")),
                    eval_report=read_report(self.base_dir, reports.get("eval")),
                    server=state["server"],
                    memory=state["memory"] or None,
                    problems=state["problems"],
                )
            )
        return result

    def save(self) -> None:
        report = build_report(
            run=self.run_info(),
            catalog=catalog_info(Path(self.args.catalog), self.catalog, self.profile.base_dir),
            machine=self.machine,
            variants=self.summaries(),
            profile=self.profile.summary,
        )
        write_json(self.summary_path, report)
        self.summary_path.with_suffix(".md").write_text(
            markdown_summary(report, self.profile.summary.markdown), encoding="utf-8"
        )

    def problem(self, variant: Variant, text: str) -> None:
        print(f"[error] {variant.id}: {text}")
        self.state[variant.id]["problems"].append(text)

    def execute(self) -> int:
        docker = self.shell.docker_facts()
        overrides = {name: getattr(self.args, name) for name in MACHINE_OVERRIDES}
        self.machine = machine_section(self.args.reference, self.shell.collect_host(self.models_dir), overrides, docker)
        for item in missing_fields(self.machine):
            print(f"[warn] machine {item}")
        for variant in self.variants:
            for text in self.state[variant.id]["problems"]:
                print(f"[warn] {variant.id} {text}")
        self.save()
        if "fetch" in self.args.steps:
            self.fetch_all()
        if "bench" in self.args.steps:
            self.bench_all()
        if SERVING_STEPS & set(self.args.steps):
            self.serve_all()
        self.completed = True
        self.save()
        print(f"[done] wrote {self.summary_path} and {self.summary_path.with_suffix('.md')}")
        return 0

    def prepare_fetch(self) -> None:
        return None

    def fetch_script(self) -> Path:
        return self.profile.fetch_script or packaged_fetch_script()

    def fetch_variant(self, variant: Variant) -> dict[str, Any]:
        command = fetch_command(
            self.server_image,
            str(self.models_dir),
            str(self.fetch_script()),
            variant.known_model(),
            container_script=self.profile.container_fetch_script,
        )
        returncode, _lines = self.shell.run_and_echo(command)
        if returncode != 0:
            return {"status": "failed", "method": "docker", "error": f"fetch-model.sh exited with {returncode}"}
        return {"status": "verified", "method": "docker", "path": recorded_model_path(variant.file)}

    def fetch_all(self) -> None:
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.prepare_fetch()
        for variant in self.variants:
            state = self.state[variant.id]
            if state["skipped"]:
                continue
            state["problems"] = [text for text in state["problems"] if not text.startswith(DOWNLOAD_FAILED)]
            print(f"[info] {variant.id}: {variant.file} ({variant.gguf['size_bytes']:,} bytes) from {variant.url}")
            outcome = self.fetch_variant(variant)
            state["fetch"] = outcome
            if outcome["status"] != "verified":
                self.problem(variant, f"{DOWNLOAD_FAILED}{outcome.get('error')}")
            self.save()

    def bench_tool(self) -> list[str]:
        return [sys.executable, "-m", LLAMA_BENCH_TOOL, "--known-models", str(Path(self.args.catalog).resolve())]

    def bench_command(self, variant: Variant) -> list[str]:
        matrix = self.catalog["llama_bench"]
        reference = ["--reference", self.args.reference] if self.args.reference else []
        return [
            *self.bench_tool(),
            "--models-dir", str(self.models_dir),
            "--model", variant.file,
            "--label", f"{variant.id}-llama-bench",
            "--out-dir", str(self.run_dir),
            *reference,
            "--image", self.catalog["llama_cpp"]["bench_image"],
            "--fetch-image", self.server_image,
            "--prompts", str(matrix["prompts"]),
            "--generations", str(matrix["generations"]),
            "--depths", str(matrix["depths"]),
            "--cache-types-k", str(matrix["cache_types_k"]),
            "--cache-types-v", str(matrix["cache_types_v"]),
            "--threads", str(matrix["threads"]),
            "--repetitions", str(matrix["repetitions"]),
            *machine_overrides(self.args),
            *self.args.bench_arg,
        ]

    def bench_all(self) -> None:
        for variant in self.variants:
            if not self.runnable(variant) or self.model_missing(variant):
                continue
            returncode, lines = self.shell.run_and_echo(self.bench_command(variant))
            written = written_report(lines)
            if returncode != 0 or not written:
                self.problem(variant, f"llama-bench failed (exit {returncode})")
            if written:
                self.state[variant.id]["reports"]["llama_bench"] = relative_to(written, self.base_dir)
            self.save()

    def serving_trouble(self, serving: list[Variant]) -> str | None:
        return None

    def announce_serving(self) -> None:
        return None

    def take_over(self) -> str | None:
        return None

    def give_back(self) -> None:
        return None

    def serve_all(self) -> None:
        serving = [variant for variant in self.variants if self.runnable(variant)]
        if not serving:
            return
        trouble = self.serving_trouble(serving)
        if trouble:
            self.refuse(serving, trouble)
            return
        self.announce_serving()
        try:
            trouble = self.take_over()
            if trouble:
                self.refuse(serving, trouble)
                return
            for variant in serving:
                self.forget_refusals(variant)
                self.serve(variant)
                self.save()
        finally:
            self.remove_candidate()
            self.give_back()

    def refuse(self, variants: list[Variant], text: str) -> None:
        for variant in variants:
            self.problem(variant, f"{NOT_SERVED}{text}")
        self.save()

    def forget_refusals(self, variant: Variant) -> None:
        state = self.state[variant.id]
        state["problems"] = [text for text in state["problems"] if not text.startswith(NOT_SERVED)]

    def remove_candidate(self) -> None:
        self.shell.docker_text(["rm", "-f", self.container], timeout=DOCKER_STOP_TIMEOUT_S)

    def server_command(self, variant: Variant) -> list[str]:
        raise NotImplementedError

    def server_port(self) -> int:
        return DEFAULT_PORT

    def wait_healthy(self) -> str | None:
        deadline = time.monotonic() + self.args.start_timeout
        url = f"http://localhost:{self.server_port()}/health"
        while time.monotonic() < deadline:
            state = parse_container_inspect(self.shell.docker_text(["inspect", self.container]))
            if not state or not state["running"]:
                return "llama-server stopped while loading the model:\n" + self.log_tail()
            if self.shell.docker_text(["exec", self.container, "curl", "-fsS", "-m", "10", url]) is not None:
                return None
            self.shell.sleep(HEALTH_POLL_S)
        return f"llama-server was not healthy after {self.args.start_timeout:.0f}s:\n" + self.log_tail()

    def log_tail(self) -> str:
        return self.shell.docker_output(["logs", "--tail", str(LOG_TAIL_LINES), self.container]).strip()

    def server_facts(self, command: list[str]) -> dict[str, Any]:
        url = f"http://localhost:{self.server_port()}/props"
        props = parse_props(self.shell.docker_text(["exec", self.container, "curl", "-fsS", "-m", "10", url]))
        return {
            "container": self.container,
            "image": self.server_image,
            "command": recorded_command(command, str(self.models_dir)),
            "memory_limit_bytes": self.memory_limit(),
            "reasoning": self.args.reasoning,
            "build_info": props.get("build_info"),
            "build": build_tag(props.get("build_info")) or build_tag(self.server_image.rsplit(":", 1)[-1]),
            "n_ctx": props.get("n_ctx"),
            "model_path": props.get("model_path"),
        }

    def memory_snapshot(self) -> dict[str, Any]:
        def read(path: str) -> str | None:
            return self.shell.docker_text(["exec", self.container, "cat", path])

        state = parse_container_inspect(self.shell.docker_text(["inspect", self.container])) or {}
        return {
            "taken_at": timestamp(),
            "process": parse_process_memory(read("/proc/1/status")),
            "cgroup_peak_bytes": parse_whole_number(read("/sys/fs/cgroup/memory.peak")),
            "oom_kills": parse_memory_events(read("/sys/fs/cgroup/memory.events")).get("oom_kill"),
            "oom_killed": state.get("oom_killed"),
            "restart_count": state.get("restart_count"),
        }

    def model_missing(self, variant: Variant) -> bool:
        if (self.models_dir / variant.file).is_file():
            return False
        self.problem(variant, f"{variant.file} is not in {self.models_dir}: run the fetch step first")
        return True

    def serve(self, variant: Variant) -> None:
        state = self.state[variant.id]
        if self.model_missing(variant):
            return
        self.remove_candidate()
        command = self.server_command(variant)
        returncode, _lines = self.shell.run_and_echo(command)
        if returncode != 0:
            self.problem(variant, f"docker run failed (exit {returncode})")
            return
        trouble = self.wait_healthy()
        if trouble:
            self.problem(variant, trouble)
            self.remove_candidate()
            return
        state["server"] = self.server_facts(command)
        if "probe" in self.args.steps:
            self.probe(variant)
            state["memory"]["after_probe"] = self.memory_snapshot()
            self.save()
        if "eval" in self.args.steps:
            self.evaluate(variant)
            state["memory"]["after_eval"] = self.memory_snapshot()
        self.remove_candidate()

    def probe(self, variant: Variant) -> None:
        raise NotImplementedError

    def eval_command(self, variant: Variant) -> list[str]:
        raise NotImplementedError

    def evaluate(self, variant: Variant) -> None:
        returncode, lines = self.shell.run_and_echo(self.eval_command(variant))
        written = written_report(lines)
        if returncode != 0 or not written:
            self.problem(variant, f"the evaluation failed (exit {returncode})")
        if written:
            self.state[variant.id]["reports"]["eval"] = relative_to(written, self.base_dir)

    def plan_serve(self, variant: Variant) -> str:
        return "  serve: " + shlex.join(self.server_command(variant))

    def plan_probe(self) -> str:
        return f"  probe: {len(self.probe_items())} questions"

    def print_plan(self) -> None:
        print(
            f"[plan] summary {self.summary_path} and {self.summary_path.with_suffix('.md')}, reports in {self.run_dir}"
        )
        for variant in self.variants:
            state = self.state[variant.id]
            print(f"\n[plan] {variant.id}: {variant.name} {variant.gguf['quant']} ({variant.candidate['licence']})")
            for text in state["problems"]:
                print(f"  {text}")
            if state["skipped"]:
                continue
            if "fetch" in self.args.steps:
                print(f"  fetch {variant.url} -> {self.models_dir / variant.file}")
                print(f"        {variant.gguf['size_bytes']:,} bytes, SHA-256 {variant.gguf['sha256']}")
            if "bench" in self.args.steps:
                print("  " + shlex.join(self.bench_command(variant)))
            if SERVING_STEPS & set(self.args.steps):
                print(self.plan_serve(variant))
            if "probe" in self.args.steps:
                print(self.plan_probe())
            if "eval" in self.args.steps:
                print("  " + shlex.join(self.eval_command(variant)))


class PublishedCandidateRun(CandidateRun):
    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        serving = parser.add_argument_group("serving (each candidate in its own llama-server container)")
        serving.add_argument("--port", type=int, default=DEFAULT_PUBLISHED_PORT, help="Host port on 127.0.0.1.")
        serving.add_argument("--ctx-size", type=int, default=DEFAULT_CTX_SIZE, help="Context size of llama-server.")
        serving.add_argument("--server-arg", action="append", default=[], help="Extra llama-server argument.")
        probe = parser.add_argument_group("probe step")
        probe.add_argument("--probe-items", help="Probe items, .json, .jsonl or .yaml.")
        probe.add_argument("--probe-system", help="System prompt file (template mode).")
        probe.add_argument("--probe-user-template", help="User message template with {question} and {context}.")
        probe.add_argument("--probe-schema", help="JSON schema of the reply (template mode).")
        probe.add_argument("--probe-response-format", help="Whole response_format object instead of --probe-schema.")
        probe.add_argument("--probe-context-dir", help="Folder of <item id>.txt context files.")
        probe.add_argument(
            "--probe-max-tokens", type=int, default=DEFAULT_PROBE_MAX_TOKENS, help="max_tokens of each template request."
        )
        probe.add_argument(
            "--probe-timeout",
            type=float,
            default=DEFAULT_PROBE_TIMEOUT_S,
            help="Seconds to wait for the server to connect or to send more data.",
        )
        probe.add_argument("--probe-command", help="Command that runs a probe v1 job instead of the template.")
        probe.add_argument("--probe-setup", help="Command run once per candidate before --probe-command.")
        probe.add_argument("--warmup", metavar="QUESTION", help="Ask this first in the probe and do not score it.")

    @classmethod
    def argument_errors(cls, args: argparse.Namespace) -> list[str]:
        errors = []
        if not 0 < args.port < 65536:
            errors.append("--port must be between 1 and 65535")
        if args.ctx_size < 1:
            errors.append("--ctx-size must be at least 1")
        if "eval" in args.steps and not args.testset:
            errors.append("--steps eval needs --testset")
        if "probe" in args.steps:
            if not args.probe_items:
                errors.append("--steps probe needs --probe-items")
            template = [getattr(args, name) for name in TEMPLATE_OPTIONS]
            if not args.probe_command and not (all(template) and (args.probe_schema or args.probe_response_format)):
                errors.append(
                    "--steps probe needs --probe-command, or --probe-system, --probe-user-template and "
                    "--probe-schema (or --probe-response-format)"
                )
        if args.probe_schema and args.probe_response_format:
            errors.append("give --probe-schema or --probe-response-format, not both")
        if args.probe_max_tokens < 1:
            errors.append("--probe-max-tokens must be at least 1")
        if args.probe_timeout <= 0:
            errors.append("--probe-timeout must be more than 0")
        return errors

    def setup(self) -> None:
        self.probe_source: list[dict[str, Any]] = []
        self.probe_base = Path.cwd()
        self.template = None
        if "probe" not in self.args.steps or not self.args.probe_items:
            return
        items = load_items(self.args.probe_items)
        self.probe_base = Path(self.args.probe_items).resolve().parent
        problems = item_problems(items) or context_problems(items, self.probe_base)
        if problems:
            raise ValueError("; ".join(problems))
        self.probe_source = items
        if not self.args.probe_command:
            self.template = load_template(
                self.args.probe_system,
                self.args.probe_user_template,
                schema_path=self.args.probe_schema,
                response_format_path=self.args.probe_response_format,
                max_tokens=self.args.probe_max_tokens,
            )

    def probe_items(self) -> list[dict[str, Any]]:
        return select_probe_items(self.probe_source, self.args.ids, self.args.category, self.args.limit)

    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.args.port}/v1"

    def base_server_args(self) -> list[str]:
        return [
            "--host", "0.0.0.0",
            "--port", str(DEFAULT_PORT),
            "--ctx-size", str(self.args.ctx_size),
            *self.args.server_arg,
        ]

    def server_command(self, variant: Variant) -> list[str]:
        return candidate_run_command(
            image=self.server_image,
            models_dir=str(self.models_dir),
            args=server_args(self.base_server_args(), variant.file, self.args.reasoning),
            memory_bytes=self.memory_limit(),
            name=self.container,
            publish=f"127.0.0.1:{self.args.port}:{DEFAULT_PORT}",
        )

    def announce_serving(self) -> None:
        print(f"[info] each candidate is served by the {self.container!r} container on {self.base_url()}")

    def probe_mode(self) -> str:
        return "command" if self.args.probe_command else "template"

    def command_replies(self, items: list[dict[str, Any]]) -> tuple[int, dict[str, dict[str, Any]], str | None]:
        if self.args.probe_setup:
            code, _lines = self.shell.run_and_echo(split_command(self.args.probe_setup))
            if code != 0:
                return code, {}, f"the probe setup exited with {code}"
        resolved = []
        for item in items:
            context = item_context(item, self.probe_base, self.args.probe_context_dir)
            resolved.append({**item, "context": context} if context else item)
        job = {**probe_job(resolved, self.args.warmup), "endpoint": self.base_url()}
        code, lines = self.shell.run_and_echo(split_command(self.args.probe_command), json.dumps(job))
        return code, read_reply_lines(lines), None

    def probe(self, variant: Variant) -> None:
        items = self.probe_items()
        started = datetime.now(timezone.utc)
        if self.args.probe_command:
            returncode, replies, trouble = self.command_replies(items)
            if trouble:
                self.problem(variant, trouble)
                return
        else:
            returncode = 0
            replies = run_template_probe(
                items,
                self.template,
                model=variant.id,
                url=chat_url(self.base_url()),
                timeout=self.args.probe_timeout,
                base=self.probe_base,
                context_dir=self.args.probe_context_dir,
                warmup=self.args.warmup,
            )
        records = probe_records(items, replies, self.profile.contract)
        if returncode != 0 or len(records) < len(items):
            self.problem(
                variant,
                f"the contract probe answered {len(records)} of {len(items)} questions (exit {returncode})",
            )
        label = f"{variant.id}-contract"
        path = report_path(self.run_dir, label, started.date())
        report = build_contract_report(
            label=label,
            run={
                "mode": self.probe_mode(),
                "started_at": timestamp(started),
                "finished_at": timestamp(),
                "completed": returncode == 0 and len(records) == len(items),
                "warmup": self.args.warmup,
                "items": len(items),
            },
            model={"id": variant.id, "file": variant.file, "sha256": variant.gguf["sha256"]},
            llama_server=self.state[variant.id]["server"],
            records=records,
            profile=self.profile.contract,
        )
        write_json(path, report)
        self.state[variant.id]["reports"]["contract"] = relative_to(path, self.base_dir)

    def eval_command(self, variant: Variant) -> list[str]:
        return [
            sys.executable,
            "-m",
            EVAL_TOOL,
            "run",
            "--base-url", self.base_url(),
            "--model", variant.id,
            "--testset", str(self.args.testset),
            "--label", f"{variant.id}-eval",
            "--out-dir", str(self.run_dir),
            *item_filters(self.args),
            *self.args.eval_arg,
        ]

    def plan_probe(self) -> str:
        return f"  probe: {len(self.probe_items())} items, {self.probe_mode()} mode, on {self.base_url()}"


def earlier_summary(path: Path, profile: CandidatesProfile = DEFAULT_PROFILE) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(report, dict) or report.get("kind") != profile.kind:
        raise ValueError(f"{path} is not a {profile.kind} summary")
    version = report.get("schema_version")
    if isinstance(version, int) and not isinstance(version, bool) and version > profile.schema_version:
        raise ValueError(f"{path} has schema_version {version}, newer than the {profile.schema_version} read here")
    return report


def resummarize(path: Path, catalog: dict[str, Any], profile: CandidatesProfile = DEFAULT_PROFILE) -> int:
    try:
        report = earlier_summary(path, profile)
    except ValueError as exc:
        print(f"[error] --resummarize: {exc}")
        return 2
    by_id = {variant.id: variant for variant in select_variants(catalog, all_quants=True, name_key=profile.name_key)}
    cache_type = str(catalog["llama_bench"]["cache_types_k"]).split(",")[0]
    refreshed = []
    for entry in report.get("variants") or []:
        variant = by_id.get(entry.get("id"))
        if variant is None:
            refreshed.append(entry)
            continue
        reports = entry.get("reports") or {}
        refreshed.append(
            variant_summary(
                variant,
                profile=profile,
                cache_type=cache_type,
                fetch=entry.get("fetch"),
                reports=reports,
                bench_report=read_report(path.parent, reports.get("llama_bench")),
                contract_report=read_report(path.parent, reports.get("contract")),
                eval_report=read_report(path.parent, reports.get("eval")),
                server=entry.get("server"),
                memory=entry.get("memory"),
                problems=entry.get("problems"),
            )
        )
    report["variants"] = refreshed
    write_json(path, report)
    path.with_suffix(".md").write_text(markdown_summary(report, profile.markdown), encoding="utf-8")
    print(f"[done] wrote {path} and {path.with_suffix('.md')}")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    profile: RunnerProfile = DEFAULT_RUNNER,
    run_class: type[CandidateRun] = PublishedCandidateRun,
    shell: Shell | None = None,
) -> int:
    utf8_output()
    args = build_parser(profile, run_class).parse_args(argv)
    errors = argument_errors(args, profile) + run_class.argument_errors(args)
    name_key = profile.summary.name_key
    catalog: dict[str, Any] = {}
    if args.catalog:
        try:
            catalog = load_catalog(args.catalog)
        except profile.input_errors as exc:
            errors.append(f"catalog: cannot read {Path(args.catalog).name}: {exc}")
        else:
            errors += [f"catalog: {problem}" for problem in catalog_problems(catalog, name_key)]
    if errors:
        for error in errors:
            print(f"[error] {error}")
        return 2
    if args.resummarize:
        return resummarize(Path(args.resummarize), catalog, profile.summary)
    started = datetime.now(timezone.utc)
    previous = None
    if args.resume:
        summary_path = Path(args.resume)
        try:
            previous = earlier_summary(summary_path, profile.summary)
        except ValueError as exc:
            print(f"[error] --resume: {exc}")
            return 2
        args.only = args.only or [entry["id"] for entry in previous.get("variants") or []]
        if args.reference is None:
            args.reference = (previous.get("machine") or {}).get("reference")
    else:
        summary_path = report_path(args.out_dir, safe_label(profile.summary.label), started.date())
    try:
        variants = select_variants(catalog, args.only, args.all_quants, name_key)
    except ValueError as exc:
        print(f"[error] --only: {exc}")
        return 2
    if not variants:
        print("[error] no model matches --only")
        return 2
    try:
        testset = run_class.load_testset(args.testset) if args.testset else None
        run = run_class(
            args, catalog, variants, testset, summary_path, started, previous, profile=profile, shell=shell
        )
    except profile.input_errors as exc:
        print(f"[error] {exc}")
        return 2
    if args.dry_run:
        run.print_plan()
        return 0
    return run.execute()


if __name__ == "__main__":
    raise SystemExit(main())
