#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parents[1]
EVAL_DIR = REPO_ROOT / "scripts" / "eval"
INSTALLER_DIR = REPO_ROOT / "installer"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(1, str(EVAL_DIR))

from bench_host import (  # noqa: E402
    collect_host,
    docker_facts,
    machine_section,
    missing_fields,
    run_text,
)
from bench_llama import (  # noqa: E402
    MODELS_DIR_PLACEHOLDER,
    KnownModel,
    fetch_command,
    recorded_command,
    recorded_model_path,
)
from eval_contract import (  # noqa: E402
    WARMUP_QUESTION,
    build_contract_report,
    probe_items,
    reply_record,
)
from eval_files import report_path, safe_label, write_json  # noqa: E402
from eval_stack import (  # noqa: E402
    LLM_PORT,
    build_tag,
    parse_memory_events,
    parse_props,
    parse_server_args,
    parse_whole_number,
)
from eval_testset import (  # noqa: E402
    CATEGORIES,
    DEFAULT_TESTSET_PATH,
    file_sha256,
    load_testset,
    select_items,
)
from model_candidates import (  # noqa: E402
    AGENT_CONTAINER,
    CANDIDATE_CONTAINER,
    DEFAULT_CATALOG,
    REASONING_MODES,
    REPORT_KIND,
    RESPONSE_CACHE_SETTING,
    SERVING_STEPS,
    STACK_LLM_CONTAINER,
    STEPS,
    SUMMARY_LABEL,
    Variant,
    build_report,
    candidate_network,
    candidate_run_command,
    catalog_problems,
    load_catalog,
    markdown_summary,
    parse_container_env,
    parse_container_inspect,
    parse_memory_limit,
    parse_process_memory,
    response_cache_finding,
    select_variants,
    server_args,
    variant_gate,
    variant_summary,
    written_report,
)

RUN_LLAMA_BENCH = BENCH_DIR / "run-llama-bench.py"
RUN_EVAL = EVAL_DIR / "run-eval.py"
PROBE_SCRIPT = EVAL_DIR / "agent-contract-probe.py"
PROBE_TARGET = "/tmp/horus-agent-contract-probe.py"
AGENT_WORKDIR = "/app"
FETCH_SCRIPT = REPO_ROOT / "src" / "infra" / "llm" / "fetch-model.sh"
DEFAULT_MODELS_DIR = REPO_ROOT / "models"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmarks"
DEFAULT_REFERENCE = "cpu16"
DOWNLOAD_LOG = "model-candidates-download.log"
DOWNLOAD_FAILED = "download failed: "
NOT_SERVED = "not served: "
HEALTH_POLL_S = 5.0
DEFAULT_START_TIMEOUT_S = 900.0
DOCKER_STOP_TIMEOUT_S = 120.0
LOG_TAIL_LINES = 40
MACHINE_OVERRIDES = ("cpu_model", "ram", "ram_speed", "disk_type")


def now_utc(moment: datetime | None = None) -> str:
    return (moment or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def comma_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark the B-102 model candidates against the Qwen3-4B baseline: "
        "download and verify each GGUF, run llama-bench, probe the B-98 answer contract and run "
        "the 100-question evaluation with that model behind the CPU stack's llama-server."
    )
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--only", type=comma_list, help="Candidate or GGUF ids, comma-separated.")
    parser.add_argument("--all-quants", action="store_true", help="Also the GGUFs that are not defaults.")
    parser.add_argument("--steps", type=comma_list, default=list(STEPS), help="Among fetch,bench,probe,eval.")
    parser.add_argument("--models-dir", default=str(DEFAULT_MODELS_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--reference", default=DEFAULT_REFERENCE)
    parser.add_argument("--reasoning", choices=REASONING_MODES, default="off")
    parser.add_argument("--llm-mem-limit", help="Memory limit of the candidate llama-server, e.g. 6g.")
    parser.add_argument("--server-image", help="Default: the catalog's pinned server image.")
    parser.add_argument("--stack-llm-container", default=STACK_LLM_CONTAINER)
    parser.add_argument("--agent-container", default=AGENT_CONTAINER)
    parser.add_argument(
        "--allow-response-cache",
        action="store_true",
        help="Run the eval step although the agent's response cache is on or cannot be checked.",
    )
    parser.add_argument("--start-timeout", type=float, default=DEFAULT_START_TIMEOUT_S)
    parser.add_argument("--testset", default=str(DEFAULT_TESTSET_PATH))
    parser.add_argument("--ids", type=comma_list)
    parser.add_argument("--category", type=comma_list)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--bench-arg", action="append", default=[], help="Extra run-llama-bench.py argument.")
    parser.add_argument("--eval-arg", action="append", default=[], help="Extra run-eval.py argument.")
    parser.add_argument("--cpu-model")
    parser.add_argument("--ram")
    parser.add_argument("--ram-speed")
    parser.add_argument("--disk-type")
    parser.add_argument("--dry-run", action="store_true")
    previous = parser.add_mutually_exclusive_group()
    previous.add_argument("--resume", metavar="SUMMARY_JSON", help="Run more steps into an earlier summary.")
    previous.add_argument("--resummarize", metavar="SUMMARY_JSON")
    return parser


def argument_errors(args: argparse.Namespace) -> list[str]:
    errors = []
    unknown = [step for step in args.steps if step not in STEPS]
    if unknown:
        errors.append(f"--steps: unknown {', '.join(unknown)}; choose among {', '.join(STEPS)}")
    if args.category and set(args.category) - set(CATEGORIES):
        errors.append(f"--category must be among {', '.join(CATEGORIES)}")
    if args.limit is not None and args.limit < 1:
        errors.append("--limit must be at least 1")
    if args.llm_mem_limit and parse_memory_limit(args.llm_mem_limit) is None:
        errors.append("--llm-mem-limit must look like 6g, 6144m or a number of bytes")
    if args.start_timeout <= 0:
        errors.append("--start-timeout must be positive")
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


def docker_text(argv: list[str], timeout: float = 60.0) -> str | None:
    return run_text(["docker", *argv], timeout=timeout)


def docker_output(argv: list[str], timeout: float = 60.0) -> str:
    try:
        completed = subprocess.run(
            ["docker", *argv],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (completed.stdout or "") + (completed.stderr or "")


def run_and_echo(command: list[str], stdin_text: str | None = None) -> tuple[int, list[str]]:
    print("[info] " + shlex.join(command), flush=True)
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE if stdin_text is not None else None,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        print(f"[error] could not start {command[0]}: {exc}")
        return 127, []
    if stdin_text is not None:
        process.stdin.write(stdin_text)
        process.stdin.close()
    lines = []
    for line in process.stdout:
        lines.append(line.rstrip("\n"))
        if stdin_text is None:
            print(line, end="", flush=True)
    return process.wait(), lines


def installer_modules() -> SimpleNamespace | None:
    if str(INSTALLER_DIR) not in sys.path:
        sys.path.insert(0, str(INSTALLER_DIR))
    try:
        common = importlib.import_module("common")
        manager = importlib.import_module("model_manager")
    except ImportError:
        return None
    if not hasattr(manager, "ModelDownload") or not hasattr(common, "InstallError"):
        return None
    return SimpleNamespace(common=common, manager=manager)


def fetch_with_installer(
    modules: SimpleNamespace, variant: Variant, models_dir: Path, log_path: Path, version: str
) -> dict[str, Any]:
    gguf = variant.gguf
    entry = modules.manager.ModelEntry(
        id=variant.id,
        version=version,
        file=variant.file,
        size_bytes=gguf["size_bytes"],
        sha256=gguf["sha256"],
        min_ram_gb=0,
        profiles=(),
        mirrors=(variant.url,),
        licence=variant.candidate["licence"],
        source=f"{gguf['repo']}@{gguf['revision']}:{gguf['upstream_file']}",
    )
    log = modules.common.Log(log_path)
    code = 0
    try:
        path = modules.manager.ModelDownload(
            log, entry, models_dir, entry.mirrors, token=os.environ.get("HF_TOKEN")
        ).run()
    except modules.common.InstallError as exc:
        code = exc.code
        detail = " ".join(part.strip() for part in (exc.headline, exc.detail) if part)
        return {"status": "failed", "method": "installer", "error": detail}
    finally:
        log.close(code)
    return {"status": "verified", "method": "installer", "path": recorded_model_path(path)}


def fetch_with_docker(variant: Variant, models_dir: Path, image: str) -> dict[str, Any]:
    gguf = variant.gguf
    known = KnownModel(variant.file, variant.url, gguf["size_bytes"], gguf["sha256"])
    command = fetch_command(image, str(models_dir), str(FETCH_SCRIPT), known)
    returncode, _lines = run_and_echo(command)
    if returncode != 0:
        return {"status": "failed", "method": "docker", "error": f"fetch-model.sh exited with {returncode}"}
    return {"status": "verified", "method": "docker", "path": recorded_model_path(variant.file)}


def relative_to(path: Path | str | None, base: Path) -> str | None:
    if not path:
        return None
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(base.resolve()).as_posix()
    except ValueError:
        return resolved.name


def read_report(base: Path, relative: str | None) -> dict[str, Any] | None:
    if not relative:
        return None
    path = Path(relative) if Path(relative).is_absolute() else base / relative
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def git_commit() -> str | None:
    return (run_text(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"]) or "").strip() or None


def stack_trouble(stack: dict[str, Any] | None, name: str) -> str | None:
    if not stack or not stack["running"]:
        return (
            f"no running llama-server container {name!r}: start the CPU stack first "
            f"(after an interrupted run: docker rm -f {CANDIDATE_CONTAINER} && docker start {name})"
        )
    if not candidate_network(stack["networks"]):
        return f"the {name!r} container is on no Docker network"
    if not parse_server_args(stack["args"]).get("model"):
        return f"the {name!r} container was not started with --model, so its arguments cannot be reused"
    return None


def catalog_info(path: Path, catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": relative_to(path, REPO_ROOT),
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
        testset: dict[str, Any],
        summary_path: Path,
        started: datetime,
        previous: dict[str, Any] | None = None,
    ) -> None:
        self.args = args
        self.catalog = catalog
        self.variants = variants
        self.testset = testset
        self.summary_path = summary_path
        self.base_dir = summary_path.parent
        self.run_dir = summary_path.with_suffix("")
        self.started = started
        self.previous_run = (previous or {}).get("run") or {}
        self.models_dir = Path(args.models_dir).expanduser().resolve()
        self.server_image = args.server_image or catalog["llama_cpp"]["server_image"]
        self.cache_type = str(catalog["llama_bench"]["cache_types_k"]).split(",")[0]
        earlier = {entry.get("id"): entry for entry in (previous or {}).get("variants") or []}
        self.state: dict[str, dict[str, Any]] = {}
        for variant in variants:
            entry = earlier.get(variant.id) or {}
            problems = list(entry.get("problems") or [])
            gate = [f"skipped: {text}" for text in variant_gate(variant, catalog)]
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

    def runnable(self, variant: Variant) -> bool:
        state = self.state[variant.id]
        fetched = state["fetch"] is None or state["fetch"].get("status") == "verified"
        return not state["skipped"] and fetched

    def probe_items(self) -> list[dict[str, Any]]:
        return select_items(probe_items(self.testset["items"]), self.args.ids, self.args.category, self.args.limit)

    def session(self) -> dict[str, Any]:
        testset_path = Path(self.args.testset).resolve()
        return {
            "started_at": now_utc(self.started),
            "finished_at": now_utc() if self.completed else None,
            "completed": self.completed,
            "git_commit": git_commit(),
            "steps": list(self.args.steps),
            "reasoning": self.args.reasoning,
            "only": self.args.only,
            "all_quants": self.args.all_quants,
            "models_dir": MODELS_DIR_PLACEHOLDER,
            "server_image": self.server_image,
            "llm_mem_limit_bytes": self.memory_limit(),
            "testset": {
                "path": relative_to(testset_path, REPO_ROOT),
                "version": str(self.testset.get("version")),
                "sha256": file_sha256(testset_path),
                "filters": {"ids": self.args.ids, "categories": self.args.category, "limit": self.args.limit},
                "probe_items": len(self.probe_items()),
            },
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
            catalog=catalog_info(Path(self.args.catalog), self.catalog),
            machine=self.machine,
            variants=self.summaries(),
        )
        write_json(self.summary_path, report)
        self.summary_path.with_suffix(".md").write_text(markdown_summary(report), encoding="utf-8")

    def problem(self, variant: Variant, text: str) -> None:
        print(f"[error] {variant.id}: {text}")
        self.state[variant.id]["problems"].append(text)

    def execute(self) -> int:
        docker = docker_facts()
        overrides = {name: getattr(self.args, name) for name in MACHINE_OVERRIDES}
        self.machine = machine_section(self.args.reference, collect_host(self.models_dir), overrides, docker)
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

    def fetch_all(self) -> None:
        self.models_dir.mkdir(parents=True, exist_ok=True)
        modules = installer_modules()
        if modules is None:
            print("[warn] the installer's model downloader is not importable: fetching with fetch-model.sh in Docker")
        for variant in self.variants:
            state = self.state[variant.id]
            if state["skipped"]:
                continue
            state["problems"] = [text for text in state["problems"] if not text.startswith(DOWNLOAD_FAILED)]
            print(f"[info] {variant.id}: {variant.file} ({variant.gguf['size_bytes']:,} bytes) from {variant.url}")
            if modules is not None:
                outcome = fetch_with_installer(
                    modules, variant, self.models_dir, self.models_dir / DOWNLOAD_LOG, str(self.catalog["version"])
                )
            else:
                outcome = fetch_with_docker(variant, self.models_dir, self.server_image)
            state["fetch"] = outcome
            if outcome["status"] != "verified":
                self.problem(variant, f"{DOWNLOAD_FAILED}{outcome.get('error')}")
            self.save()

    def bench_command(self, variant: Variant) -> list[str]:
        matrix = self.catalog["llama_bench"]
        return [
            sys.executable,
            str(RUN_LLAMA_BENCH),
            "--models-dir", str(self.models_dir),
            "--model", variant.file,
            "--label", f"{variant.id}-llama-bench",
            "--out-dir", str(self.run_dir),
            "--reference", self.args.reference,
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
            returncode, lines = run_and_echo(self.bench_command(variant))
            written = written_report(lines)
            if returncode != 0 or not written:
                self.problem(variant, f"llama-bench failed (exit {returncode})")
            if written:
                self.state[variant.id]["reports"]["llama_bench"] = relative_to(written, self.base_dir)
            self.save()

    def serve_all(self) -> None:
        serving = [variant for variant in self.variants if self.runnable(variant)]
        if not serving:
            return
        stack_name = self.args.stack_llm_container
        self.stack = parse_container_inspect(docker_text(["inspect", stack_name]))
        trouble = stack_trouble(self.stack, stack_name) or self.response_cache_trouble(serving)
        if trouble:
            self.refuse(serving, trouble)
            return
        network = candidate_network(self.stack["networks"])
        print(f"[info] stopping {stack_name}; each candidate answers as 'llm' on {network}")
        try:
            trouble = self.stop_stack_llm(stack_name)
            if trouble:
                self.refuse(serving, trouble)
                return
            for variant in serving:
                self.forget_refusals(variant)
                self.serve(variant)
                self.save()
        finally:
            self.remove_candidate()
            self.start_stack_llm(stack_name)

    def refuse(self, variants: list[Variant], text: str) -> None:
        for variant in variants:
            self.problem(variant, f"{NOT_SERVED}{text}")
        self.save()

    def forget_refusals(self, variant: Variant) -> None:
        state = self.state[variant.id]
        state["problems"] = [text for text in state["problems"] if not text.startswith(NOT_SERVED)]

    def response_cache_trouble(self, serving: list[Variant]) -> str | None:
        if "eval" not in self.args.steps:
            return None
        agent = self.args.agent_container
        finding = response_cache_finding(parse_container_env(docker_text(["inspect", agent])), agent)
        if finding is None:
            return None
        if self.args.allow_response_cache:
            caveat = f"{finding} (--allow-response-cache)"
            for variant in serving:
                if caveat not in self.state[variant.id]["problems"]:
                    self.problem(variant, caveat)
            return None
        return (
            f"{finding}. Set {RESPONSE_CACHE_SETTING}=0 in src/infra/.env, recreate the agent "
            "(cd src/infra && docker compose up -d agent) and run again, or pass --allow-response-cache"
        )

    def stop_stack_llm(self, name: str) -> str | None:
        docker_text(["stop", name], timeout=DOCKER_STOP_TIMEOUT_S)
        state = parse_container_inspect(docker_text(["inspect", name]))
        if state and not state["running"]:
            return None
        return (
            f"could not stop {name!r}: a candidate started next to it under the alias 'llm' "
            "would split the requests between two models"
        )

    def start_stack_llm(self, name: str) -> None:
        print(f"[info] starting {name} again")
        if docker_text(["start", name], timeout=DOCKER_STOP_TIMEOUT_S) is None:
            print(f"[error] could not start {name!r} again: the stack has no llama-server until `docker start {name}`")

    def remove_candidate(self) -> None:
        docker_text(["rm", "-f", CANDIDATE_CONTAINER], timeout=DOCKER_STOP_TIMEOUT_S)

    def server_command(self, variant: Variant) -> list[str]:
        return candidate_run_command(
            image=self.server_image,
            network=candidate_network(self.stack["networks"]),
            models_dir=str(self.models_dir),
            args=server_args(self.stack["args"], variant.file, self.args.reasoning),
            memory_bytes=self.memory_limit(),
        )

    def server_port(self) -> int:
        port = parse_server_args(self.stack["args"]).get("port")
        return port if isinstance(port, int) else LLM_PORT

    def wait_healthy(self) -> str | None:
        deadline = time.monotonic() + self.args.start_timeout
        url = f"http://localhost:{self.server_port()}/health"
        while time.monotonic() < deadline:
            state = parse_container_inspect(docker_text(["inspect", CANDIDATE_CONTAINER]))
            if not state or not state["running"]:
                return "llama-server stopped while loading the model:\n" + self.log_tail()
            if docker_text(["exec", CANDIDATE_CONTAINER, "curl", "-fsS", "-m", "10", url]) is not None:
                return None
            time.sleep(HEALTH_POLL_S)
        return f"llama-server was not healthy after {self.args.start_timeout:.0f}s:\n" + self.log_tail()

    def log_tail(self) -> str:
        return docker_output(["logs", "--tail", str(LOG_TAIL_LINES), CANDIDATE_CONTAINER]).strip()

    def server_facts(self, command: list[str]) -> dict[str, Any]:
        url = f"http://localhost:{self.server_port()}/props"
        props = parse_props(docker_text(["exec", CANDIDATE_CONTAINER, "curl", "-fsS", "-m", "10", url]))
        return {
            "container": CANDIDATE_CONTAINER,
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
            return docker_text(["exec", CANDIDATE_CONTAINER, "cat", path])

        state = parse_container_inspect(docker_text(["inspect", CANDIDATE_CONTAINER])) or {}
        return {
            "taken_at": now_utc(),
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
        returncode, _lines = run_and_echo(command)
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
        items = self.probe_items()
        agent = self.args.agent_container
        if docker_text(["cp", str(PROBE_SCRIPT), f"{agent}:{PROBE_TARGET}"]) is None:
            self.problem(variant, f"could not copy the contract probe into the {agent!r} container")
            return
        job = {"items": [{"id": item["id"], "question": item["question"]} for item in items], "warmup": WARMUP_QUESTION}
        command = ["docker", "exec", "-i", "-w", AGENT_WORKDIR, agent, "python", PROBE_TARGET]
        started = datetime.now(UTC)
        returncode, lines = run_and_echo(command, json.dumps(job))
        replies = {}
        for line in lines:
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if isinstance(reply, dict) and reply.get("id"):
                replies[reply["id"]] = reply
        records = [reply_record(item, replies[item["id"]]) for item in items if item["id"] in replies]
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
                "started_at": now_utc(started),
                "finished_at": now_utc(),
                "completed": returncode == 0 and len(records) == len(items),
                "agent_container": agent,
                "warmup": WARMUP_QUESTION,
                "items": len(items),
            },
            model={"id": variant.id, "file": variant.file, "sha256": variant.gguf["sha256"]},
            llama_server=self.state[variant.id]["server"],
            records=records,
        )
        write_json(path, report)
        self.state[variant.id]["reports"]["contract"] = relative_to(path, self.base_dir)

    def eval_command(self, variant: Variant) -> list[str]:
        return [
            sys.executable,
            str(RUN_EVAL),
            "--label", f"{variant.id}-eval",
            "--out-dir", str(self.run_dir),
            "--testset", str(self.args.testset),
            "--llm-container", CANDIDATE_CONTAINER,
            "--model-name", variant.id,
            "--model-file", variant.file,
            "--sample-resources",
            "--reference", self.args.reference,
            *item_filters(self.args),
            *machine_overrides(self.args),
            *self.args.eval_arg,
        ]

    def evaluate(self, variant: Variant) -> None:
        returncode, lines = run_and_echo(self.eval_command(variant))
        written = written_report(lines)
        if returncode != 0 or not written:
            self.problem(variant, f"the evaluation failed (exit {returncode})")
        if written:
            self.state[variant.id]["reports"]["eval"] = relative_to(written, self.base_dir)


def print_plan(run: CandidateRun) -> None:
    print(f"[plan] summary {run.summary_path} and {run.summary_path.with_suffix('.md')}, reports in {run.run_dir}")
    for variant in run.variants:
        state = run.state[variant.id]
        print(f"\n[plan] {variant.id}: {variant.name} {variant.gguf['quant']} ({variant.candidate['licence']})")
        for text in state["problems"]:
            print(f"  {text}")
        if state["skipped"]:
            continue
        if "fetch" in run.args.steps:
            print(f"  fetch {variant.url} -> {run.models_dir / variant.file}")
            print(f"        {variant.gguf['size_bytes']:,} bytes, SHA-256 {variant.gguf['sha256']}")
        if "bench" in run.args.steps:
            print("  " + shlex.join(run.bench_command(variant)))
        if SERVING_STEPS & set(run.args.steps):
            args = server_args(["--model", "<stack model>"], variant.file, run.args.reasoning)
            changes = shlex.join(args[:2] + args[-2:])
            print(f"  serve: the arguments of {run.args.stack_llm_container!r} with {changes}")
        if "probe" in run.args.steps:
            print(f"  probe: {len(run.probe_items())} questions through {run.args.agent_container!r}")
        if "eval" in run.args.steps:
            print("  " + shlex.join(run.eval_command(variant)))


def earlier_summary(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(report, dict) or report.get("kind") != REPORT_KIND:
        raise ValueError(f"{path} is not a {REPORT_KIND} summary")
    return report


def resummarize(path: Path, catalog: dict[str, Any]) -> int:
    try:
        report = earlier_summary(path)
    except ValueError as exc:
        print(f"[error] --resummarize: {exc}")
        return 2
    by_id = {variant.id: variant for variant in select_variants(catalog, all_quants=True)}
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
    path.with_suffix(".md").write_text(markdown_summary(report), encoding="utf-8")
    print(f"[done] wrote {path} and {path.with_suffix('.md')}")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args()
    errors = argument_errors(args)
    catalog = load_catalog(args.catalog)
    errors += [f"catalog: {problem}" for problem in catalog_problems(catalog)]
    if errors:
        for error in errors:
            print(f"[error] {error}")
        return 2
    if args.resummarize:
        return resummarize(Path(args.resummarize), catalog)
    started = datetime.now(UTC)
    previous = None
    if args.resume:
        summary_path = Path(args.resume)
        try:
            previous = earlier_summary(summary_path)
        except ValueError as exc:
            print(f"[error] --resume: {exc}")
            return 2
        args.only = args.only or [entry["id"] for entry in previous.get("variants") or []]
    else:
        summary_path = report_path(args.out_dir, safe_label(SUMMARY_LABEL), started.date())
    try:
        variants = select_variants(catalog, args.only, args.all_quants)
    except ValueError as exc:
        print(f"[error] --only: {exc}")
        return 2
    if not variants:
        print("[error] no model matches --only")
        return 2
    run = CandidateRun(args, catalog, variants, load_testset(args.testset), summary_path, started, previous)
    if args.dry_run:
        print_plan(run)
        return 0
    return run.execute()


if __name__ == "__main__":
    raise SystemExit(main())
