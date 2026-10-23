#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

HISTOGRAMS = {"agent": "agent_llm_prompt_tokens", "mas": "mas_llm_prompt_tokens"}
OVER_BUDGET_COUNTERS = {
    "agent": "agent_llm_prompts_over_budget_total",
    "mas": "mas_llm_prompts_over_budget_total",
}
DEFAULT_URLS = {"agent": "http://localhost:8001/metrics/", "mas": "http://localhost:8000/metrics"}
DEFAULT_BUDGET = 4096
FETCH_TIMEOUT_SECONDS = 10
EXIT_WITHIN_BUDGET = 0
EXIT_OVER_BUDGET = 1
EXIT_NO_CALLS = 2

_SAMPLE = re.compile(r"^(?P<name>[a-zA-Z_:][\w:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>\S+)")
_LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class CallTotals:
    tokens: float = 0.0
    calls: float = 0.0
    over_budget: float = 0.0

    def __add__(self, other: CallTotals) -> CallTotals:
        return CallTotals(
            self.tokens + other.tokens,
            self.calls + other.calls,
            self.over_budget + other.over_budget,
        )

    def __sub__(self, other: CallTotals) -> CallTotals:
        return CallTotals(
            self.tokens - other.tokens,
            self.calls - other.calls,
            self.over_budget - other.over_budget,
        )


@dataclass(frozen=True)
class CallAverage:
    service: str
    call: str
    calls: int
    average_prompt_tokens: float
    calls_over_budget: int
    budget: int
    within_budget: bool


def parse_samples(text: str) -> Iterable[tuple[str, dict[str, str], float]]:
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE.match(line)
        if match is None:
            continue
        try:
            value = float(match["value"])
        except ValueError:
            continue
        yield match["name"], dict(_LABEL.findall(match["labels"] or "")), value


def call_totals(service: str, metrics_text: str) -> dict[str, CallTotals]:
    histogram = HISTOGRAMS[service]
    totals: dict[str, CallTotals] = {}
    for name, labels, value in parse_samples(metrics_text):
        call = labels.get("call")
        if call is None:
            continue
        if name == f"{histogram}_sum":
            part = CallTotals(tokens=value)
        elif name == f"{histogram}_count":
            part = CallTotals(calls=value)
        elif name == OVER_BUDGET_COUNTERS[service]:
            part = CallTotals(over_budget=value)
        else:
            continue
        totals[call] = totals.get(call, CallTotals()) + part
    return totals


def call_averages(
    service: str, now: dict[str, CallTotals], before: dict[str, CallTotals], budget: int
) -> list[CallAverage]:
    averages = []
    for call in sorted(now):
        totals = now[call] - before.get(call, CallTotals())
        if totals.calls <= 0:
            continue
        average = totals.tokens / totals.calls
        averages.append(
            CallAverage(
                service=service,
                call=call,
                calls=round(totals.calls),
                average_prompt_tokens=round(average, 1),
                calls_over_budget=round(totals.over_budget),
                budget=budget,
                within_budget=average <= budget,
            )
        )
    return averages


def fetch_metrics(url: str) -> str:
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")


def format_report(averages: Sequence[CallAverage]) -> str:
    lines = [
        f"{'service':<8}{'call':<14}{'calls':>7}{'avg tokens':>12}{'over':>6}{'budget':>8}  verdict"
    ]
    for row in averages:
        verdict = "ok" if row.within_budget else "OVER BUDGET"
        lines.append(
            f"{row.service:<8}{row.call:<14}{row.calls:>7}{row.average_prompt_tokens:>12.1f}"
            f"{row.calls_over_budget:>6}{row.budget:>8}  {verdict}"
        )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Average prompt tokens per LLM call of the agent and MAS, read from their "
            "Prometheus metrics, checked against a token budget."
        )
    )
    for service in HISTOGRAMS:
        parser.add_argument(
            f"--{service}",
            default=DEFAULT_URLS[service],
            help=f"{service} /metrics URL or a saved metrics file (default: %(default)s)",
        )
        parser.add_argument(
            f"--{service}-budget",
            type=int,
            default=DEFAULT_BUDGET,
            help=f"average prompt tokens per {service} call allowed (default: %(default)s)",
        )
    parser.add_argument(
        "--save",
        type=Path,
        help="write the current metrics of both services to this directory and stop",
    )
    parser.add_argument(
        "--since",
        type=Path,
        help="a directory written by --save: only the calls made after it are counted",
    )
    parser.add_argument("--json", type=Path, help="also write the averages to this JSON file")
    return parser


def _read(source: str) -> str:
    if source.startswith(("http://", "https://")):
        return fetch_metrics(source)
    return Path(source).read_text(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    current = {service: _read(getattr(args, service)) for service in HISTOGRAMS}
    if args.save is not None:
        args.save.mkdir(parents=True, exist_ok=True)
        for service, text in current.items():
            (args.save / f"{service}.prom").write_text(text, encoding="utf-8")
        print(f"Saved the agent and MAS metrics to {args.save}")
        return EXIT_WITHIN_BUDGET
    averages: list[CallAverage] = []
    for service, text in current.items():
        before = {}
        if args.since is not None:
            before = call_totals(
                service, (args.since / f"{service}.prom").read_text(encoding="utf-8")
            )
        budget = getattr(args, f"{service}_budget")
        averages += call_averages(service, call_totals(service, text), before, budget)
    if not averages:
        print("No LLM call was recorded in the agent or MAS metrics.")
        return EXIT_NO_CALLS
    print(format_report(averages))
    if args.json is not None:
        args.json.write_text(
            json.dumps([asdict(row) for row in averages], indent=2), encoding="utf-8"
        )
    if all(row.within_budget for row in averages):
        return EXIT_WITHIN_BUDGET
    return EXIT_OVER_BUDGET


if __name__ == "__main__":
    sys.exit(main())
