#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from typing import Any

import httpx

TOKEN_HEADER = "X-Corpus-Token"
FINISHED_STATES = frozenset({"completed", "failed", "idle"})


class ReindexRefused(RuntimeError):
    pass


def _headers(token: str) -> dict[str, str]:
    return {TOKEN_HEADER: token}


def reindex_status(client: httpx.Client, ks_url: str, token: str) -> dict[str, Any]:
    response = client.get(f"{ks_url}/corpus/reindex", headers=_headers(token), timeout=30.0)
    response.raise_for_status()
    return response.json()


def start_reindex(client: httpx.Client, ks_url: str, token: str) -> dict[str, Any]:
    response = client.post(f"{ks_url}/corpus/reindex", headers=_headers(token), timeout=30.0)
    if response.status_code == 409:
        status = reindex_status(client, ks_url, token)
        if status.get("state") == "running":
            return status
    if response.status_code != 202:
        raise ReindexRefused(f"HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


def wait_for_reindex(
    client: httpx.Client,
    ks_url: str,
    token: str,
    *,
    timeout: float,
    interval: float,
    report: Callable[[dict[str, Any]], None],
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        status = reindex_status(client, ks_url, token)
        report(status)
        if status.get("state") in FINISHED_STATES:
            return status
        if time.monotonic() >= deadline:
            raise TimeoutError(f"the re-index was still running after {timeout:.0f}s")
        sleep(interval)


def progress_line(status: dict[str, Any]) -> str:
    totals = status.get("totals") or {}
    done = sum(totals.get(key, 0) for key in ("migrated", "reembedded", "unchanged", "failed"))
    return (
        f"[{status.get('state')}] {done}/{totals.get('pending', 0)} documents "
        f"(migrated {totals.get('migrated', 0)}, re-embedded {totals.get('reembedded', 0)}, "
        f"unchanged {totals.get('unchanged', 0)}, failed {totals.get('failed', 0)}) "
        f"embed_model={status.get('embed_model')}"
    )


def exit_code(status: dict[str, Any]) -> int:
    if status.get("state") != "completed":
        return 1
    return 1 if (status.get("totals") or {}).get("failed") else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Re-index the knowledge store: split documents stored as one whole-file entry "
            "into passages and embed again every passage whose embed_model is not the "
            "running one. Safe to run again; an interrupted run continues where it stopped."
        )
    )
    parser.add_argument("--ks-url", default=os.environ.get("KS_URL", "http://localhost:8080"))
    parser.add_argument("--token", default=os.environ.get("CORPUS_SCAN_TOKEN"))
    parser.add_argument("--timeout", type=float, default=6 * 3600.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.token:
        print("[error] pass --token or set CORPUS_SCAN_TOKEN (src/infra/.env)", file=sys.stderr)
        return 2
    ks_url = args.ks_url.rstrip("/")
    with httpx.Client() as client:
        try:
            job = start_reindex(client, ks_url, args.token)
            print(f"[info] re-index {job.get('job_id')} running with {job.get('embed_model')}")
            final = wait_for_reindex(
                client, ks_url, args.token,
                timeout=args.timeout,
                interval=args.poll_interval,
                report=lambda status: print(progress_line(status), flush=True),
            )
        except ReindexRefused as exc:
            print(f"[error] the knowledge store refused the re-index: {exc}", file=sys.stderr)
            return 2
        except (httpx.HTTPError, TimeoutError) as exc:
            print(f"[error] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    for failure in final.get("failures") or []:
        print(f"[failed] {failure.get('doc_id')}: {failure.get('reason')}", file=sys.stderr)
    if final.get("error"):
        print(f"[error] {final['error']}", file=sys.stderr)
    return exit_code(final)


if __name__ == "__main__":
    sys.exit(main())
