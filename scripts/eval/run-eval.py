#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import platform
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from eval_events import Observation, apply_event
from eval_report import (
    ResourcePeaks,
    build_report,
    is_sha256,
    parse_docker_stats,
    parse_meminfo_swap_used,
    question_record,
    report_path,
    resummarize,
    safe_label,
    titles_from_query_result,
)
from eval_scoring import ROUTE_AGENT, ROUTE_DIRECT, ROUTE_NONE
from eval_testset import (
    CATEGORIES,
    DEFAULT_TESTSET_PATH,
    IN_CORPUS_CATEGORIES,
    REPO_ROOT,
    corpus_problems,
    corpus_root,
    file_sha256,
    load_testset,
    select_items,
    validate_testset,
)

PERF_DIR = Path(__file__).resolve().parent.parent / "perf"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmarks"
TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled", "canceled"})
CANCELED_TASK_STATUSES = frozenset({"cancelled", "canceled"})
WARMUP_QUESTION = "In one sentence, what kinds of documents are in the knowledge store?"
LATE_EVENT_GRACE_S = 3.0
CORPUS_POLL_INTERVAL_S = 5.0
SERVER_SETTINGS = (
    "LLM_BACKEND",
    "LLM_VLLM_MODEL",
    "KNOWLEDGE_STORE_N_RESULTS",
    "AGENT_MAX_NEW_TOKENS",
    "AGENT_STREAM_TOKENS",
    "AGENT_RESPONSE_CACHE",
    "LLM_TORCH_INTRAOP_THREADS",
    "AGENT_TORCH_INTRAOP_THREADS",
)


def load_perf_script(filename: str, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, PERF_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pipeline = load_perf_script("benchmark-pipeline.py", "benchmark_pipeline")
quality = load_perf_script("quality-benchmark.py", "quality_benchmark")


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def observation_fields(observation: Observation) -> dict[str, Any]:
    return {
        "first_event_s": observation.first_event_s,
        "retrieval_s": observation.retrieval_s,
        "reasoning_start_s": observation.reasoning_start_s,
        "ttft_s": observation.ttft_s,
        "answered_by": observation.answered_by,
        "retrieval_steps": observation.retrieval_steps,
        "retrieved_sources": observation.retrieved_sources,
        "cited_sources": observation.cited_sources,
        "models": list(observation.models),
        "devices": list(observation.devices),
    }


async def _cancel(task: asyncio.Task) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


class EvalClient(pipeline.PipelineBench):
    def __init__(
        self,
        mas_url: str,
        ks_url: str,
        *,
        event_timeout: float,
        submit_timeout: float,
        poll_interval: float,
        connect: Any = None,
    ) -> None:
        super().__init__(mas_url, ks_url, lambda _text: 0, "unused", event_timeout)
        self.submit_timeout = submit_timeout
        self.poll_interval = poll_interval
        self.connect = connect or pipeline.websockets.connect

    async def ask(self, question: str, conversation_name: str) -> dict[str, Any]:
        outcome: dict[str, Any] = {"mode": "chat", "status": "error"}
        conversation_id = await self.create_conversation(conversation_name)
        if conversation_id is None:
            outcome["error"] = "could not create a conversation"
            return outcome
        outcome["conversation_id"] = conversation_id
        observation = Observation()
        url = f"{self.ws_base}/chat/{conversation_id}/?token={self.token}"
        started = time.perf_counter()
        try:
            async with self.connect(url, max_size=16 * 1024 * 1024, open_timeout=20) as socket:
                started = time.perf_counter()
                await self._exchange(socket, question, conversation_id, observation, outcome, started)
        except Exception as exc:  # noqa: BLE001
            if not outcome.get("task_id") and not outcome.get("error"):
                outcome["error"] = f"websocket failed: {type(exc).__name__}: {exc}"
        if outcome.get("task_id"):
            if observation.done:
                outcome.update(
                    status="ok",
                    answer=observation.answer,
                    total_s=observation.total_s,
                    timing_source="websocket",
                )
            else:
                await self._poll(outcome["task_id"], started, outcome)
        return {**observation_fields(observation), **outcome}

    async def _exchange(
        self,
        socket: Any,
        question: str,
        conversation_id: int,
        observation: Observation,
        outcome: dict[str, Any],
        started: float,
    ) -> None:
        listener = asyncio.create_task(self._listen(socket, observation, started))
        try:
            body = await self._submit(question, conversation_id, started, outcome)
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            await _cancel(listener)
            outcome["error"] = f"new_task failed: {type(exc).__name__}: {exc}"
            return
        if not body.get("task_id"):
            await _cancel(listener)
            outcome.update(
                status="ok",
                observed_route=ROUTE_DIRECT if body.get("result") else ROUTE_NONE,
                answer=body.get("result") or body.get("message") or "",
                total_s=outcome["submit_http_s"],
                timing_source="http",
            )
            return
        outcome.update(task_id=body["task_id"], observed_route=ROUTE_AGENT)
        remaining = self.event_timeout - (time.perf_counter() - started)
        finished, _pending = await asyncio.wait({listener}, timeout=max(remaining, 0.0))
        if not finished:
            await _cancel(listener)

    async def _submit(
        self, question: str, conversation_id: int, started: float, outcome: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {
            "demand": question,
            "conversation_id": conversation_id,
            "skills_required": [],
            "mode": "auto",
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.mas_url}/tasks/new_task/",
                json=payload,
                headers=self._headers(),
                timeout=self.submit_timeout,
            )
        outcome["submit_http_s"] = round(time.perf_counter() - started, 3)
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError(f"unexpected new_task body: {str(body)[:200]}")
        return body

    async def _listen(self, socket: Any, observation: Observation, started: float) -> None:
        finished_at: float | None = None
        while True:
            timeout = None
            if finished_at is not None:
                timeout = LATE_EVENT_GRACE_S - (time.perf_counter() - finished_at)
                if timeout <= 0:
                    return
            try:
                raw = await asyncio.wait_for(socket.recv(), timeout=timeout)
            except asyncio.TimeoutError:
                return
            except Exception:  # noqa: BLE001
                return
            try:
                event = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(event, dict):
                continue
            apply_event(observation, event, round(time.perf_counter() - started, 3))
            if observation.done and finished_at is None:
                finished_at = time.perf_counter()

    async def _poll(self, task_id: str, started: float, outcome: dict[str, Any]) -> None:
        deadline = started + self.event_timeout
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    response = await client.get(
                        f"{self.mas_url}/tasks/{task_id}", headers=self._headers(), timeout=30.0
                    )
                    detail = response.json() if response.status_code == 200 else {}
                except (httpx.HTTPError, ValueError):
                    detail = {}
                status = str(detail.get("status") or "").lower()
                if status in TERMINAL_TASK_STATUSES:
                    outcome.update(
                        status=polled_status(status),
                        error=None if status == "completed" else f"task {status}",
                        answer=detail.get("result") or "",
                        total_s=round(time.perf_counter() - started, 3),
                        timing_source="poll",
                    )
                    return
                if time.perf_counter() >= deadline:
                    outcome.update(
                        status="timeout",
                        error=f"no final answer within {self.event_timeout:.0f}s",
                    )
                    return
                await asyncio.sleep(self.poll_interval)


def polled_status(task_status: str) -> str:
    if task_status == "completed":
        return "ok"
    return "timeout" if task_status in CANCELED_TASK_STATUSES else "error"


async def stored_titles(ks_url: str) -> list[str]:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{ks_url}/file", timeout=30.0)
    response.raise_for_status()
    return [str(doc.get("title")) for doc in response.json().get("documents", [])]


async def scan_corpus(ks_url: str, corpus_token: str, timeout: float = 900.0) -> str:
    headers = {"X-Corpus-Token": corpus_token}
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{ks_url}/corpus/scan", headers=headers, timeout=30.0)
        if response.status_code not in (202, 409):
            return f"HTTP {response.status_code}: {response.text[:200]}"
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            status = await client.get(f"{ks_url}/corpus/status", headers=headers, timeout=30.0)
            state = status.json().get("state") if status.status_code == 200 else None
            if state in ("completed", "failed", "idle"):
                return state
            await asyncio.sleep(CORPUS_POLL_INTERVAL_S)
    return "timeout"


async def ensure_corpus(ks_url: str, testset: dict[str, Any], corpus_token: str | None) -> bool:
    expected = list(testset["corpus"])
    try:
        problems = corpus_problems(expected, await stored_titles(ks_url))
        if problems and corpus_token:
            print(f"[info] corpus scan: {await scan_corpus(ks_url, corpus_token)}")
            problems = corpus_problems(expected, await stored_titles(ks_url))
    except (httpx.HTTPError, ValueError) as exc:
        problems = [f"knowledge store unreachable at {ks_url}: {exc}"]
    for problem in problems:
        print(f"[error] {problem}")
    if problems:
        print("[error] load demo_assets/ first (or pass --corpus-token, or --skip-corpus-check)")
    return not problems


def retrieve(ks_url: str, question: str, top_k: int) -> dict[str, Any]:
    outcome: dict[str, Any] = {"mode": "retrieval", "status": "error", "timing_source": "http"}
    started = time.perf_counter()
    with httpx.Client() as client:
        try:
            result = quality.call_knowledge_store(client, ks_url, question, top_k)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                outcome["error"] = f"HTTP {exc.response.status_code}"
                return outcome
            result = {"raw": {}, "elapsed_ms": (time.perf_counter() - started) * 1000.0}
        except httpx.HTTPError as exc:
            outcome["error"] = f"{type(exc).__name__}: {exc}"
            return outcome
    outcome.update(
        status="ok",
        total_s=round(result["elapsed_ms"] / 1000.0, 3),
        retrieved_sources=[titles_from_query_result(result["raw"])],
    )
    return outcome


def docker_memory_usage() -> dict[str, int]:
    try:
        completed = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_docker_stats(completed.stdout)


def swap_used_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.swap_memory().used)
    except Exception:  # noqa: BLE001
        pass
    try:
        return parse_meminfo_swap_used(Path("/proc/meminfo").read_text(encoding="utf-8"))
    except OSError:
        return None


class ResourceSampler(threading.Thread):
    def __init__(self, interval: float) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self.peaks = ResourcePeaks()
        self._stopping = threading.Event()

    def run(self) -> None:
        while not self._stopping.is_set():
            self.peaks.add(docker_memory_usage(), swap_used_bytes())
            self._stopping.wait(self.interval)

    def finish(self) -> dict[str, Any]:
        self._stopping.set()
        self.join(timeout=90)
        return self.peaks.as_dict()


def machine_info(args: argparse.Namespace) -> dict[str, Any]:
    gpu = pipeline.gpu_info()
    return {
        "reference": args.reference,
        "cpu_model": args.cpu_model or platform.processor() or None,
        "ram": args.ram,
        "ram_speed": args.ram_speed,
        "disk_type": args.disk_type,
        "os": platform.platform(),
        "logical_cpus": os.cpu_count(),
        "gpu": None if "error" in gpu else gpu,
    }


def testset_info(args: argparse.Namespace, testset: dict[str, Any], items: list[dict]) -> dict:
    path = Path(args.testset).resolve()
    try:
        shown = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        shown = str(path)
    return {
        "path": shown,
        "version": str(testset["version"]),
        "sha256": file_sha256(path),
        "corpus": testset["corpus"],
        "items_total": len(testset["items"]),
        "items_run": len(items),
        "filters": {"ids": args.ids, "categories": args.category, "limit": args.limit},
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def progress_line(index: int, total: int, record: dict[str, Any]) -> str:
    def flag(value: bool | None) -> str:
        return "-" if value is None else ("yes" if value else "no")

    seconds = record.get("total_s")
    shown = f"{seconds:8.2f}s" if isinstance(seconds, (int, float)) else "       ?s"
    return (
        f"[{index:3}/{total}] {record['id']:10} {record['status']:7} {shown}  "
        f"answer={flag(record.get('answer_correct_auto'))} "
        f"source={flag(record.get('source_correct_auto'))} "
        f"route={flag(record.get('route_correct'))}"
        + (f"  ({record['error']})" if record.get("error") else "")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Horus evaluation test set against a live stack."
    )
    parser.add_argument("--label", help="Run label, used in benchmarks/<label>-<date>.json")
    parser.add_argument("--mode", choices=["chat", "retrieval"], default="chat")
    parser.add_argument("--testset", default=str(DEFAULT_TESTSET_PATH))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--ids", type=lambda raw: [p.strip() for p in raw.split(",") if p.strip()])
    parser.add_argument(
        "--category", type=lambda raw: [p.strip() for p in raw.split(",") if p.strip()]
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--mas-url", default=os.environ.get("MAS_URL", "http://localhost:8000"))
    parser.add_argument("--ks-url", default=os.environ.get("KS_URL", "http://localhost:8080"))
    parser.add_argument("--username", default=os.environ.get("SUPER_USER_USERNAME", "admin"))
    parser.add_argument("--password", default=os.environ.get("SUPER_USER_PASSWORD", "secret"))
    parser.add_argument("--token", default=os.environ.get("MAS_TOKEN"))
    parser.add_argument("--event-timeout", type=float, default=1800.0)
    parser.add_argument("--submit-timeout", type=float, default=900.0)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--agent-wait", type=float, default=300.0)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--skip-corpus-check", action="store_true")
    parser.add_argument("--corpus-token", default=os.environ.get("CORPUS_SCAN_TOKEN"))
    parser.add_argument("--sample-resources", action="store_true")
    parser.add_argument("--sample-interval", type=float, default=10.0)
    parser.add_argument("--llama-cpp-build")
    parser.add_argument("--model-name")
    parser.add_argument("--model-file")
    parser.add_argument("--model-sha256")
    parser.add_argument("--reference")
    parser.add_argument("--cpu-model")
    parser.add_argument("--ram")
    parser.add_argument("--ram-speed")
    parser.add_argument("--disk-type")
    parser.add_argument("--resummarize", metavar="REPORT_JSON")
    return parser


def argument_errors(args: argparse.Namespace) -> list[str]:
    if args.resummarize:
        return []
    errors = []
    if not args.label:
        errors.append("--label is required")
    else:
        try:
            safe_label(args.label)
        except ValueError as exc:
            errors.append(f"--label: {exc}")
    if args.model_sha256 and not is_sha256(args.model_sha256):
        errors.append("--model-sha256 must be 64 hexadecimal characters")
    if args.category and set(args.category) - set(CATEGORIES):
        errors.append(f"--category must be among {', '.join(CATEGORIES)}")
    if args.limit is not None and args.limit < 1:
        errors.append("--limit must be at least 1")
    return errors


def chosen_items(args: argparse.Namespace, testset: dict[str, Any]) -> list[dict[str, Any]]:
    items = testset["items"]
    if args.mode == "retrieval" and not args.category:
        items = [item for item in items if item["category"] in IN_CORPUS_CATEGORIES]
    return select_items(items, args.ids, args.category, args.limit)


async def prepare_chat(args: argparse.Namespace, client: EvalClient) -> bool:
    if args.token:
        client.token = args.token
    elif not await client.authenticate(args.username, args.password):
        return False
    return await client.wait_for_agent(timeout=args.agent_wait) is not None


async def run_questions(
    args: argparse.Namespace,
    testset: dict[str, Any],
    items: list[dict[str, Any]],
    on_record: Any,
) -> list[dict[str, Any]] | None:
    if not args.skip_corpus_check and not await ensure_corpus(
        args.ks_url, testset, args.corpus_token
    ):
        return None
    client = None
    if args.mode == "chat":
        client = EvalClient(
            args.mas_url,
            args.ks_url,
            event_timeout=args.event_timeout,
            submit_timeout=args.submit_timeout,
            poll_interval=args.poll_interval,
        )
        if not await prepare_chat(args, client):
            return None
        if not args.no_warmup:
            print(f"[info] warmup (not scored): {WARMUP_QUESTION}")
            await client.ask(WARMUP_QUESTION, f"eval-warmup-{safe_label(args.label)}")
    records: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        if client is not None:
            name = f"eval-{safe_label(args.label)}-{item['id']}"
            outcome = await client.ask(item["question"], name)
        else:
            outcome = await asyncio.to_thread(retrieve, args.ks_url, item["question"], args.top_k)
        record = question_record(item, outcome)
        records.append(record)
        print(progress_line(index, len(items), record))
        on_record(records)
    return records


def observed_values(records: list[dict[str, Any]], field: str) -> list[str]:
    values: list[str] = []
    for record in records:
        for value in record.get(field) or []:
            if value not in values:
                values.append(value)
    return values


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
    if args.resummarize:
        path = Path(args.resummarize)
        report = resummarize(json.loads(path.read_text(encoding="utf-8")))
        write_json(path, report)
        print(json.dumps(report["summary"]["manual_review"], indent=2))
        return 0
    if args.mode == "chat" and pipeline.websockets is None:
        print("[error] chat mode needs the 'websockets' package: pip install websockets")
        return 2

    testset = load_testset(args.testset)
    problems = validate_testset(testset, corpus_root(testset, args.testset))
    if problems:
        for problem in problems:
            print(f"[error] testset: {problem}")
        return 2
    items = chosen_items(args, testset)
    if not items:
        print("[error] no test items match the filters")
        return 2

    started_at = datetime.now(UTC)
    out_path = report_path(args.out_dir, args.label, started_at.date())
    sampler = ResourceSampler(args.sample_interval) if args.sample_resources else None
    run = {
        "mode": args.mode,
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_at": None,
        "completed": False,
        "git_commit": pipeline.git_commit(),
        "mas_url": args.mas_url,
        "ks_url": args.ks_url,
        "event_timeout_s": args.event_timeout,
        "submit_timeout_s": args.submit_timeout,
        "top_k": args.top_k if args.mode == "retrieval" else None,
        "warmup": WARMUP_QUESTION if args.mode == "chat" and not args.no_warmup else None,
        "server_settings": {key: pipeline._server_param(key, "unset") for key in SERVER_SETTINGS},
        "observed_models": [],
        "observed_devices": [],
    }
    static = {
        "label": args.label,
        "testset": testset_info(args, testset, items),
        "llama_cpp_build": args.llama_cpp_build,
        "model": {
            "name": args.model_name,
            "file": args.model_file,
            "sha256": args.model_sha256.lower() if args.model_sha256 else None,
        },
        "machine": machine_info(args),
    }

    def save(records: list[dict[str, Any]], resources: dict[str, Any] | None = None) -> None:
        run["observed_models"] = observed_values(records, "models")
        run["observed_devices"] = observed_values(records, "devices")
        write_json(out_path, build_report(run=run, records=records, resources=resources, **static))

    print(f"[info] {len(items)} question(s), writing {out_path}")
    if sampler:
        sampler.start()
    records = asyncio.run(run_questions(args, testset, items, save))
    resources = sampler.finish() if sampler else None
    if records is None:
        return 1
    run.update(finished_at=now_utc(), completed=True)
    save(records, resources)
    summary = build_report(run=run, records=records, **static)["summary"]
    headline = (
        "answer_correct_auto",
        "source_correct_auto",
        "source_rank",
        "source_basis",
        "route_correct",
        "total_s",
        "ttft_s",
    )
    print(json.dumps({key: summary[key] for key in headline}, indent=2))
    print(f"[done] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
