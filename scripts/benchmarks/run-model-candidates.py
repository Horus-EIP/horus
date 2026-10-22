#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import os
import shlex
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parents[1]
KIT_SRC = REPO_ROOT / "opensource" / "horus-bench-kit" / "src"
EVAL_DIR = REPO_ROOT / "scripts" / "eval"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(1, str(EVAL_DIR))

from eval_contract import WARMUP_QUESTION, build_contract_report, probe_items  # noqa: E402
from eval_stack import LLM_PORT, parse_server_args  # noqa: E402
from eval_testset import load_testset, select_items  # noqa: E402
from horus_bench_kit.cli import candidates as kit  # noqa: E402
from horus_bench_kit.cli.candidates import (  # noqa: E402, F401
    DOCKER_STOP_TIMEOUT_S,
    CandidateRun,
    item_filters,
    machine_overrides,
    relative_to,
    timestamp,
)
from horus_bench_kit.files import report_path, write_json  # noqa: E402
from horus_bench_kit.llama_bench import recorded_model_path  # noqa: E402
from horus_bench_kit.llama_server import (  # noqa: E402
    parse_container_env,
    parse_container_inspect,
    server_args,
)
from horus_bench_kit.probe import probe_job, probe_records, read_reply_lines  # noqa: E402
from horus_bench_kit.shell import Shell  # noqa: E402
from horus_profile import (  # noqa: E402
    AGENT_CONTAINER,
    AGENT_WORKDIR,
    CANDIDATE_CONTAINER,
    DOWNLOAD_LOG,
    INSTALLER_DIR,
    PROBE_SCRIPT,
    PROBE_TARGET,
    RESPONSE_CACHE_SETTING,
    RUN_EVAL,
    RUN_LLAMA_BENCH,
    RUNNER,
    STACK_LLM_CONTAINER,
    HorusShell,
)
from model_candidates import (  # noqa: E402
    Variant,
    candidate_network,
    candidate_run_command,
    response_cache_finding,
)


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


class StackCandidateRun(CandidateRun):
    @classmethod
    def add_serving_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--stack-llm-container", default=STACK_LLM_CONTAINER)
        parser.add_argument("--agent-container", default=AGENT_CONTAINER)
        parser.add_argument(
            "--allow-response-cache",
            action="store_true",
            help="Run the eval step although the agent's response cache is on or cannot be checked.",
        )

    @classmethod
    def load_testset(cls, path: str) -> dict[str, Any]:
        return load_testset(path)

    def setup(self) -> None:
        self.installer: SimpleNamespace | None = None

    def probe_items(self) -> list[dict[str, Any]]:
        return select_items(
            probe_items(self.testset["items"]), self.args.ids, self.args.category, self.args.limit
        )

    def prepare_fetch(self) -> None:
        self.installer = installer_modules()
        if self.installer is None:
            print(
                "[warn] the installer's model downloader is not importable: fetching with fetch-model.sh in Docker"
            )

    def fetch_variant(self, variant: Variant) -> dict[str, Any]:
        if self.installer is None:
            return super().fetch_variant(variant)
        log_path = self.models_dir / DOWNLOAD_LOG
        return fetch_with_installer(
            self.installer, variant, self.models_dir, log_path, str(self.catalog["version"])
        )

    def bench_tool(self) -> list[str]:
        return [sys.executable, str(RUN_LLAMA_BENCH)]

    def serving_trouble(self, serving: list[Variant]) -> str | None:
        name = self.args.stack_llm_container
        self.stack = parse_container_inspect(self.shell.docker_text(["inspect", name]))
        return stack_trouble(self.stack, name) or self.response_cache_trouble(serving)

    def response_cache_trouble(self, serving: list[Variant]) -> str | None:
        if "eval" not in self.args.steps:
            return None
        agent = self.args.agent_container
        finding = response_cache_finding(
            parse_container_env(self.shell.docker_text(["inspect", agent])), agent
        )
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

    def announce_serving(self) -> None:
        network = candidate_network(self.stack["networks"])
        print(
            f"[info] stopping {self.args.stack_llm_container}; each candidate answers as 'llm' on {network}"
        )

    def take_over(self) -> str | None:
        name = self.args.stack_llm_container
        self.shell.docker_text(["stop", name], timeout=DOCKER_STOP_TIMEOUT_S)
        state = parse_container_inspect(self.shell.docker_text(["inspect", name]))
        if state and not state["running"]:
            return None
        return (
            f"could not stop {name!r}: a candidate started next to it under the alias 'llm' "
            "would split the requests between two models"
        )

    def give_back(self) -> None:
        name = self.args.stack_llm_container
        print(f"[info] starting {name} again")
        if self.shell.docker_text(["start", name], timeout=DOCKER_STOP_TIMEOUT_S) is None:
            print(
                f"[error] could not start {name!r} again: the stack has no llama-server until `docker start {name}`"
            )

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

    def probe(self, variant: Variant) -> None:
        items = self.probe_items()
        agent = self.args.agent_container
        if self.shell.docker_text(["cp", str(PROBE_SCRIPT), f"{agent}:{PROBE_TARGET}"]) is None:
            self.problem(variant, f"could not copy the contract probe into the {agent!r} container")
            return
        command = ["docker", "exec", "-i", "-w", AGENT_WORKDIR, agent, "python", PROBE_TARGET]
        started = datetime.now(timezone.utc)
        returncode, lines = self.shell.run_and_echo(
            command, json.dumps(probe_job(items, WARMUP_QUESTION))
        )
        records = probe_records(items, read_reply_lines(lines), self.profile.contract)
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
                "started_at": timestamp(started),
                "finished_at": timestamp(),
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
            "--label",
            f"{variant.id}-eval",
            "--out-dir",
            str(self.run_dir),
            "--testset",
            str(self.args.testset),
            "--llm-container",
            CANDIDATE_CONTAINER,
            "--model-name",
            variant.id,
            "--model-file",
            variant.file,
            "--sample-resources",
            "--reference",
            self.args.reference,
            *item_filters(self.args),
            *machine_overrides(self.args),
            *self.args.eval_arg,
        ]

    def plan_serve(self, variant: Variant) -> str:
        args = server_args(["--model", "<stack model>"], variant.file, self.args.reasoning)
        changes = shlex.join(args[:2] + args[-2:])
        return f"  serve: the arguments of {self.args.stack_llm_container!r} with {changes}"

    def plan_probe(self) -> str:
        return f"  probe: {len(self.probe_items())} questions through {self.args.agent_container!r}"


def main(argv: Sequence[str] | None = None, *, shell: Shell | None = None) -> int:
    return kit.main(argv, profile=RUNNER, run_class=StackCandidateRun, shell=shell or HorusShell())


if __name__ == "__main__":
    raise SystemExit(main())
