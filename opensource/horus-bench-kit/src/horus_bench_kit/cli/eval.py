# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from horus_bench_kit import __version__
from horus_bench_kit.eval_compare import compare_markdown
from horus_bench_kit.files import (
    TIMESTAMP_FORMAT,
    now_utc,
    read_json,
    report_path,
    safe_label,
    write_json,
)
from horus_bench_kit.openai_target import DEFAULT_API_KEY_ENV, SYSTEM_PROMPT, OpenAITarget
from horus_bench_kit.report import build_report, build_summary, question_record, resummarize
from horus_bench_kit.target import STATUS_OK, observed_values, run_items, testset_info
from horus_bench_kit.testset import (
    CATEGORIES,
    corpus_root,
    load_testset,
    schema_errors,
    select_items,
    validate_testset,
)

TARGETS = ("openai",)
CONTEXT_SUFFIX = ".txt"
HEADLINE = ("answer_correct_auto", "source_correct_auto", "status", "total_s", "ttft_s", "usage")
TESTSET_PREFIX = "testset: "
TIMEOUT_HELP = "seconds to wait for the server to connect or to send more data"

ContextFinder = Callable[[dict[str, Any]], Sequence[Path]]


def comma_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hbk-eval",
        description="Check a question-answering test set, run it against a model, then summarise "
        "or compare the reports.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    validate = commands.add_parser("validate", help="check a test set against its corpus")
    validate.add_argument("testset", help="test set file, .json or .yaml")

    run = commands.add_parser("run", help="ask every selected question and write a report")
    run.add_argument("--target", choices=TARGETS, default=TARGETS[0])
    run.add_argument(
        "--base-url", help="OpenAI-compatible API root, for example http://127.0.0.1:8080/v1"
    )
    run.add_argument("--model", help="model name sent in each request")
    run.add_argument("--testset", help="test set file, .json or .yaml")
    run.add_argument("--label", help="run label, used in <out-dir>/<label>-<date>.json")
    run.add_argument("--out-dir", default=".")
    run.add_argument("--context-dir", help=f"folder of <question id>{CONTEXT_SUFFIX} context files")
    run.add_argument("--ids", type=comma_list, help="comma-separated question ids")
    run.add_argument("--category", type=comma_list, help="comma-separated categories")
    run.add_argument("--limit", type=int)
    run.add_argument(
        "--system-prompt-file", help="plain-text system prompt instead of the default one"
    )
    run.add_argument("--max-tokens", type=int, default=512)
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--timeout", type=float, default=600.0, help=TIMEOUT_HELP)
    run.add_argument(
        "--api-key-env", default=DEFAULT_API_KEY_ENV, help="variable that holds the API key"
    )
    run.add_argument(
        "--no-stream", action="store_true", help="wait for whole replies (no time to first token)"
    )
    run.add_argument(
        "--no-stream-usage", action="store_true", help="do not send stream_options.include_usage"
    )
    run.add_argument("--warmup", metavar="QUESTION", help="ask this first and do not score it")

    summarize = commands.add_parser("resummarize", help="rebuild the summary after a manual review")
    summarize.add_argument("report")

    compare = commands.add_parser(
        "compare", help="Markdown summary of one report, or of two side by side"
    )
    compare.add_argument("reports", nargs="+", metavar="REPORT")
    compare.add_argument("--out", help="write the Markdown to this file instead of the screen")
    return parser


def run_argument_errors(args: argparse.Namespace) -> list[str]:
    errors = []
    for option, value in (
        ("--testset", args.testset),
        ("--base-url", args.base_url),
        ("--model", args.model),
    ):
        if not value:
            errors.append(f"{option} is required")
    if not args.label:
        errors.append("--label is required")
    else:
        try:
            safe_label(args.label)
        except ValueError as exc:
            errors.append(f"--label: {exc}")
    errors.extend(base_url_errors(args.base_url))
    if args.category and set(args.category) - set(CATEGORIES):
        errors.append(f"--category must be among {', '.join(CATEGORIES)}")
    if args.limit is not None and args.limit < 1:
        errors.append("--limit must be at least 1")
    if args.max_tokens < 1:
        errors.append("--max-tokens must be at least 1")
    if args.timeout <= 0:
        errors.append("--timeout must be more than 0")
    if args.context_dir and not Path(args.context_dir).is_dir():
        errors.append(f"--context-dir {Path(args.context_dir).name!r} is not a folder")
    if args.system_prompt_file and not Path(args.system_prompt_file).is_file():
        errors.append(f"--system-prompt-file {Path(args.system_prompt_file).name!r} does not exist")
    return errors


def base_url_errors(base_url: str | None) -> list[str]:
    if not base_url:
        return []
    try:
        if urlsplit(base_url).scheme not in ("http", "https"):
            return ["--base-url must start with http:// or https://"]
        endpoint_origin(base_url)
    except ValueError as exc:
        return [f"--base-url: {exc}"]
    return []


def context_finder(testset_path: Path | str, context_dir: Path | str | None) -> ContextFinder:
    base = Path(testset_path).resolve().parent

    def files_for(item: dict[str, Any]) -> Sequence[Path]:
        if item.get("context_file"):
            return [base / item["context_file"]]
        if context_dir:
            candidate = Path(context_dir) / f"{item['id']}{CONTEXT_SUFFIX}"
            if candidate.is_file():
                return [candidate]
        return []

    return files_for


def context_errors(testset: dict[str, Any], testset_path: Path | str) -> list[str]:
    base = Path(testset_path).resolve().parent
    return [
        f"{item['id']}: context_file {item['context_file']!r} does not exist"
        for item in testset["items"]
        if item.get("context_file") and not (base / item["context_file"]).is_file()
    ]


def checked_testset(path: Path | str) -> tuple[dict[str, Any] | None, list[str]]:
    name = Path(path).name
    try:
        testset = load_testset(path)
    except Exception as exc:
        return None, [f"cannot read {name}: {exc}"]
    if not isinstance(testset, dict):
        return None, [f"{name} does not hold a test set object"]
    problems = schema_errors(testset)
    if problems:
        return testset, problems
    return testset, validate_testset(testset, corpus_root(testset, path)) + context_errors(
        testset, path
    )


def endpoint_origin(base_url: str) -> str:
    parts = urlsplit(base_url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme}://{host}" + (f":{parts.port}" if parts.port else "")


def run_section(
    args: argparse.Namespace,
    target: OpenAITarget,
    started_at: datetime,
    context_files: int,
) -> dict[str, Any]:
    return {
        "target": target.name,
        "endpoint": endpoint_origin(target.base_url),
        "model": target.model,
        "started_at": started_at.strftime(TIMESTAMP_FORMAT),
        "finished_at": None,
        "completed": False,
        "kit_version": __version__,
        "warmup": args.warmup,
        "settings": {
            "max_tokens": target.max_tokens,
            "temperature": target.temperature,
            "timeout_s": target.timeout,
            "stream": target.stream,
            "stream_usage": target.stream and target.stream_usage,
            "system_prompt": "file" if args.system_prompt_file else "default",
            "system_prompt_sha256": hashlib.sha256(
                target.system_prompt.encode("utf-8")
            ).hexdigest(),
            "context_files": context_files,
        },
        "observed_models": [],
    }


def print_errors(prefix: str, errors: list[str]) -> None:
    for error in errors:
        print(f"[error] {prefix}{error}")


def print_testset_errors(problems: list[str]) -> None:
    for problem in problems:
        print(
            f"[error] {problem if problem.startswith(TESTSET_PREFIX) else TESTSET_PREFIX + problem}"
        )


def validate_command(args: argparse.Namespace) -> int:
    testset, problems = checked_testset(args.testset)
    if problems:
        print_testset_errors(problems)
        return 2
    print(
        f"[ok] {Path(args.testset).name}: version {testset['version']}, "
        f"{len(testset['items'])} questions, {len(testset['corpus'])} corpus documents"
    )
    return 0


def run_command(args: argparse.Namespace) -> int:
    errors = run_argument_errors(args)
    if errors:
        print_errors("", errors)
        return 2
    testset, problems = checked_testset(args.testset)
    if problems:
        print_testset_errors(problems)
        return 2
    items = select_items(testset["items"], args.ids, args.category, args.limit)
    if not items:
        print("[error] no test items match the filters")
        return 2
    target = OpenAITarget(
        base_url=args.base_url,
        model=args.model,
        api_key_env=args.api_key_env,
        system_prompt=Path(args.system_prompt_file).read_text(encoding="utf-8")
        if args.system_prompt_file
        else SYSTEM_PROMPT,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        timeout=args.timeout,
        stream=not args.no_stream,
        stream_usage=not args.no_stream_usage,
    )
    files_for = context_finder(args.testset, args.context_dir)
    started_at = datetime.now(timezone.utc)
    out_path = report_path(args.out_dir, args.label, started_at.date())
    run = run_section(args, target, started_at, sum(1 for item in items if files_for(item)))
    filters = {"ids": args.ids, "categories": args.category, "limit": args.limit}
    testset_section = testset_info(args.testset, testset, items, filters)

    def save(records: list[dict[str, Any]]) -> None:
        run["observed_models"] = observed_values(records, "models")
        write_json(
            out_path,
            build_report(label=args.label, run=run, testset=testset_section, records=records),
        )

    if args.warmup:
        print(f"[info] warmup (not scored): {args.warmup}")
        warmup = asyncio.run(target.ask(args.warmup, item_id="warmup"))
        if warmup.get("status") != STATUS_OK:
            print(f"[error] warmup failed: {warmup.get('error')}")
            return 1
    print(f"[info] {len(items)} question(s), writing {out_path}")
    records = asyncio.run(
        run_items(target, items, record=question_record, on_record=save, files_for=files_for)
    )
    run.update(finished_at=now_utc(), completed=True)
    save(records)
    summary = build_summary(records)
    print(json.dumps({key: summary[key] for key in HEADLINE}, indent=2))
    if not any(record["status"] == STATUS_OK for record in records):
        print(
            f"[error] no question got an answer from {run['endpoint']}; the errors are in {out_path}"
        )
        return 1
    print(f"[done] wrote {out_path}")
    return 0


def resummarize_command(args: argparse.Namespace) -> int:
    path = Path(args.report)
    try:
        report = resummarize(read_json(path))
    except (OSError, ValueError) as exc:
        print(f"[error] {path.name}: {exc}")
        return 2
    write_json(path, report)
    print(json.dumps(report["summary"]["manual_review"], indent=2))
    return 0


def compare_command(args: argparse.Namespace) -> int:
    if len(args.reports) > 2:
        print("[error] compare takes one or two reports")
        return 2
    try:
        markdown = compare_markdown(args.reports)
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}")
        return 2
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
        print(f"[done] wrote {args.out}")
    else:
        print(markdown, end="")
    return 0


COMMANDS = {
    "validate": validate_command,
    "run": run_command,
    "resummarize": resummarize_command,
    "compare": compare_command,
}


def utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: Sequence[str] | None = None) -> int:
    utf8_output()
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
