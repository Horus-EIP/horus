# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from horus_bench_kit import __version__
from horus_bench_kit.cli.eval import (
    TIMEOUT_HELP,
    base_url_errors,
    comma_list,
    endpoint_origin,
    print_errors,
    utf8_output,
)
from horus_bench_kit.files import TIMESTAMP_FORMAT, now_utc, report_path, safe_label, write_json
from horus_bench_kit.openai_target import DEFAULT_API_KEY_ENV
from horus_bench_kit.probe import (
    DEFAULT_PROFILE,
    PROTOCOL_VERSION,
    ContractProfile,
    answered,
    api_headers,
    build_contract_report,
    chat_url,
    context_problems,
    item_context,
    item_problems,
    load_items,
    load_template,
    prepared_items,
    probe_job,
    probe_records,
    read_reply_lines,
    run_prepared_probe,
    run_template_probe,
    select_probe_items,
    split_command,
)
from horus_bench_kit.shell import Shell
from horus_bench_kit.testset import file_sha256

DESCRIPTION = (
    "Ask a model for JSON answers and check each reply against the JSON schema it was asked for: "
    "from a prompt template, from prepared requests, or through a probe command that speaks probe v1."
)
TEMPLATE_OPTIONS = ("system", "user_template")
HEADLINE_EXTRA = ("failures", "thought_first", "truncated", "wall_s")


def build_parser(prog: str | None = "hbk-contract-probe") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=DESCRIPTION)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--label", help="run label, used in <out-dir>/<label>-<date>.json")
    parser.add_argument("--out-dir", default=".")
    parser.add_argument("--items", help="probe items, .json, .jsonl or .yaml (template and command modes)")
    parser.add_argument("--ids", type=comma_list, help="comma-separated item ids")
    parser.add_argument("--category", type=comma_list, help="comma-separated item categories")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--base-url", help="OpenAI-compatible API root, for example http://127.0.0.1:8080/v1")
    parser.add_argument("--model", help="model name sent in each request")
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV, help="variable that holds the API key")
    parser.add_argument("--timeout", type=float, default=600.0, help=TIMEOUT_HELP)
    parser.add_argument("--warmup", metavar="QUESTION", help="ask this first and do not score it")
    template = parser.add_argument_group("template mode")
    template.add_argument("--system", help="system prompt file")
    template.add_argument("--user-template", help="user message file with {question} and {context}")
    template.add_argument("--schema", help="JSON schema of the reply")
    template.add_argument("--response-format", help="whole response_format object instead of --schema")
    template.add_argument("--context-dir", help="folder of <item id>.txt context files")
    template.add_argument("--max-tokens", type=int, default=512)
    template.add_argument("--temperature", type=float, default=0.0)
    prepared = parser.add_argument_group("prepared mode")
    prepared.add_argument("--prepared", help="JSON Lines file of prepared chat completion requests")
    command = parser.add_argument_group("command mode")
    command.add_argument("--probe-command", help="command that reads a probe v1 job and writes reply lines")
    command.add_argument("--probe-setup", help="command run once before --probe-command")
    return parser


def probe_mode(args: argparse.Namespace) -> str:
    if args.probe_command:
        return "command"
    return "prepared" if args.prepared else "template"


def argument_errors(args: argparse.Namespace, mode: str) -> list[str]:
    errors = []
    if not args.label:
        errors.append("--label is required")
    else:
        try:
            safe_label(args.label)
        except ValueError as exc:
            errors.append(f"--label: {exc}")
    if mode == "prepared":
        if args.items:
            errors.append("give --items or --prepared, not both")
    elif not args.items:
        errors.append("--items is required")
    if mode != "command" and not args.base_url:
        errors.append("--base-url is required")
    errors.extend(base_url_errors(args.base_url))
    if mode == "template":
        if not args.model:
            errors.append("--model is required")
        for name in TEMPLATE_OPTIONS:
            if not getattr(args, name):
                errors.append(f"--{name.replace('_', '-')} is required")
        if bool(args.schema) == bool(args.response_format):
            errors.append("give --schema or --response-format")
    if mode == "prepared" and args.warmup:
        errors.append("--warmup works with --items, not with --prepared")
    if args.prepared and args.probe_command:
        errors.append("give --prepared or --probe-command, not both")
    if args.limit is not None and args.limit < 1:
        errors.append("--limit must be at least 1")
    if args.max_tokens < 1:
        errors.append("--max-tokens must be at least 1")
    if args.timeout <= 0:
        errors.append("--timeout must be more than 0")
    if args.context_dir and not Path(args.context_dir).is_dir():
        errors.append(f"--context-dir {Path(args.context_dir).name!r} is not a folder")
    return errors


def checked_items(path: str, mode: str) -> tuple[list[dict[str, Any]], list[str]]:
    name = Path(path).name
    try:
        items = load_items(path)
    except (OSError, ValueError, RuntimeError) as exc:
        return [], [f"cannot read {name}: {exc}"]
    problems = item_problems(items, prepared=mode == "prepared")
    if problems:
        return [], problems
    return items, context_problems(items, Path(path).resolve().parent)


def optional_sha256(path: str | None) -> str | None:
    return file_sha256(path) if path else None


def settings_section(args: argparse.Namespace, mode: str) -> dict[str, Any]:
    if mode == "template":
        return {
            "max_tokens": args.max_tokens,
            "temperature": args.temperature,
            "timeout_s": args.timeout,
            "system_sha256": optional_sha256(args.system),
            "user_template_sha256": optional_sha256(args.user_template),
            "response_format_sha256": optional_sha256(args.schema or args.response_format),
        }
    if mode == "prepared":
        return {"timeout_s": args.timeout, "prepared_sha256": optional_sha256(args.prepared)}
    return {"protocol": PROTOCOL_VERSION}


def run_command_mode(
    args: argparse.Namespace, items: list[dict[str, Any]], shell: Shell
) -> tuple[int, dict[str, dict[str, Any]] | None]:
    if args.probe_setup:
        code, _lines = shell.run_and_echo(split_command(args.probe_setup))
        if code != 0:
            print(f"[error] the probe setup exited with {code}; nothing was probed")
            return code, None
    base = Path(args.items).resolve().parent
    resolved = []
    for item in items:
        context = item_context(item, base, args.context_dir)
        resolved.append({**item, "context": context} if context else item)
    job = probe_job(resolved, args.warmup)
    if args.base_url:
        job["endpoint"] = args.base_url
    code, lines = shell.run_and_echo(split_command(args.probe_command), json.dumps(job))
    return code, read_reply_lines(lines)


def headline(summary: dict[str, Any], profile: ContractProfile) -> dict[str, Any]:
    return {key: summary.get(key) for key in ("replies", *profile.rate_fields, *HEADLINE_EXTRA)}


def main(
    argv: Sequence[str] | None = None,
    *,
    profile: ContractProfile = DEFAULT_PROFILE,
    shell: Shell | None = None,
    prog: str | None = "hbk-contract-probe",
) -> int:
    utf8_output()
    args = build_parser(prog).parse_args(argv)
    mode = probe_mode(args)
    errors = argument_errors(args, mode)
    if errors:
        print_errors("", errors)
        return 2
    try:
        if mode == "command":
            split_command(args.probe_command)
            if args.probe_setup:
                split_command(args.probe_setup)
        template = None
        if mode == "template":
            template = load_template(
                args.system,
                args.user_template,
                schema_path=args.schema,
                response_format_path=args.response_format,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
            )
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}")
        return 2
    source = args.prepared if mode == "prepared" else args.items
    loaded, problems = checked_items(source, mode)
    if problems:
        print_errors(f"{Path(source).name}: ", problems)
        return 2
    items = select_probe_items(prepared_items(loaded) if mode == "prepared" else loaded, args.ids, args.category, args.limit)
    if not items:
        print("[error] no probe item matches the filters")
        return 2
    started = datetime.now(timezone.utc)
    out_path = report_path(args.out_dir, args.label, started.date())
    print(f"[info] {len(items)} item(s), {mode} mode, writing {out_path}")
    returncode = 0
    headers = api_headers(args.api_key_env)
    if mode == "command":
        returncode, replies = run_command_mode(args, items, shell or Shell())
        if replies is None:
            return 1
    elif mode == "template":
        replies = run_template_probe(
            items,
            template,
            model=args.model,
            url=chat_url(args.base_url),
            timeout=args.timeout,
            base=Path(args.items).resolve().parent,
            context_dir=args.context_dir,
            warmup=args.warmup,
            headers=headers,
        )
    else:
        replies = run_prepared_probe(
            items, url=chat_url(args.base_url), timeout=args.timeout, model=args.model, headers=headers
        )
    records = probe_records(items, replies, profile)
    run = {
        "mode": mode,
        "started_at": started.strftime(TIMESTAMP_FORMAT),
        "finished_at": now_utc(),
        "completed": returncode == 0 and len(records) == len(items),
        "endpoint": endpoint_origin(args.base_url) if args.base_url else None,
        "kit_version": __version__,
        "warmup": args.warmup,
        "items": len(items),
        "settings": settings_section(args, mode),
    }
    report = build_contract_report(
        label=args.label,
        run=run,
        model={"name": args.model},
        llama_server=None,
        records=records,
        profile=profile,
    )
    write_json(out_path, report)
    print(json.dumps(headline(report["summary"], profile), indent=2))
    if len(records) < len(items):
        print(f"[warn] {len(items) - len(records)} of {len(items)} items got no reply line (exit {returncode})")
    if not answered(records):
        print(f"[error] no item got a reply; the errors are in {out_path}")
        return 1
    print(f"[done] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
