import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from core.llm_setup import ask_llm_with_json_schema, llm_server_backend
from tasks.router import (ROUTER_EXAMPLES_PATH, ExampleIndex, RosterAgent,
                          Route, RouteDecision, RouteMethod, RouterSettings,
                          TaskRouter, load_router_examples)

TESTSET_IN_REPOSITORY = Path("tests", "mas", "data", "router_testset.yaml")
METHODS = (RouteMethod.RULES, RouteMethod.EMBEDDING, RouteMethod.LLM)
WARM_UP_QUESTION = "How many vacation days do new employees get?"
NOT_RUN = "not run"


@dataclass(frozen=True)
class LabelledQuestion:
    item_id: str
    question: str
    route: Route
    agents: tuple[str, ...] = ()
    category: str = ""
    source: str | None = None


@dataclass(frozen=True)
class RouterTestset:
    version: str
    roster: tuple[RosterAgent, ...]
    items: tuple[LabelledQuestion, ...]
    document_owners: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class RoutedQuestion:
    item: LabelledQuestion
    decision: RouteDecision | None
    seconds: float

    @property
    def method(self) -> RouteMethod:
        return self.decision.method if self.decision is not None else RouteMethod.LLM

    @property
    def reached_the_llm(self) -> bool:
        return self.method is RouteMethod.LLM

    @property
    def correct(self) -> bool | None:
        if self.decision is None:
            return None
        if self.decision.route is not self.item.route:
            return False
        if self.item.route is Route.SINGLE_AGENT:
            return (
                self.decision.agent is not None
                and self.decision.agent.name in self.item.agents
            )
        return True


def default_testset(module_path: Path = Path(__file__)) -> Path | None:
    for directory in module_path.resolve().parents:
        candidate = directory / TESTSET_IN_REPOSITORY
        if candidate.is_file():
            return candidate
    return None


def load_router_testset(path: Path) -> RouterTestset:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    roster = tuple(
        RosterAgent(
            agent_id=entry["name"],
            name=entry["name"],
            description=entry.get("description", ""),
            agent_type=entry.get("type", "general"),
            skills=tuple(entry.get("skills") or ()),
        )
        for entry in document["roster"]
    )
    items = tuple(
        LabelledQuestion(
            item_id=entry["id"],
            question=entry["question"],
            route=Route(entry["route"]),
            agents=tuple(entry.get("agents") or ()),
            category=entry.get("category", ""),
            source=entry.get("source"),
        )
        for entry in document["items"]
    )
    owners = {
        source: tuple(agents)
        for source, agents in (document.get("document_owners") or {}).items()
    }
    return RouterTestset(str(document["version"]), roster, items, owners)


def route_testset(
    testset: RouterTestset,
    router: TaskRouter,
    settings: RouterSettings,
    ask: Callable[[list, str, dict, int], str] | None = None,
) -> list[RoutedQuestion]:
    router.index.warm()
    router.index.embed([WARM_UP_QUESTION])
    routed = []
    for item in testset.items:
        started = time.perf_counter()
        decision, scores = router.decide_without_llm(
            item.question, testset.roster, settings
        )
        if decision is None and ask is not None:
            decision = router.decide_with_llm(
                item.question, testset.roster, settings, scores, ask
            )
        routed.append(RoutedQuestion(item, decision, time.perf_counter() - started))
    return routed


def _milliseconds(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    return round(float(np.percentile(np.asarray(values) * 1000.0, percentile)), 2)


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def summarise(
    routed: Sequence[RoutedQuestion],
    *,
    testset_version: str,
    examples_version: str,
    settings: RouterSettings,
    llm_ran: bool,
) -> dict:
    total = len(routed)
    methods = {}
    for method in METHODS:
        chosen = [entry for entry in routed if entry.method is method]
        judged = [entry for entry in chosen if entry.correct is not None]
        methods[method.value] = {
            "count": len(chosen),
            "rate": _ratio(len(chosen), total),
            "correct": sum(1 for entry in judged if entry.correct),
            "accuracy": _ratio(
                sum(1 for entry in judged if entry.correct), len(judged)
            ),
            "p50_ms": _milliseconds([entry.seconds for entry in chosen], 50),
            "p95_ms": _milliseconds([entry.seconds for entry in chosen], 95),
        }
    without_llm = [entry for entry in routed if not entry.reached_the_llm]
    routes = {}
    for route in (Route.DIRECT_ANSWER, Route.SINGLE_AGENT, Route.COMPLEX_TASK):
        expected = [entry for entry in routed if entry.item.route is route]
        routes[route.value] = {
            "count": len(expected),
            "decided_without_llm": sum(
                1 for entry in expected if not entry.reached_the_llm
            ),
            "correct": sum(1 for entry in expected if entry.correct),
        }
    return {
        "testset_version": testset_version,
        "examples_version": examples_version,
        "questions": total,
        "min_score": settings.min_score,
        "min_margin": settings.min_margin,
        "llm_ran": llm_ran,
        "fallback_rate": _ratio(
            sum(1 for entry in routed if entry.reached_the_llm), total
        ),
        "accuracy_without_llm": _ratio(
            sum(1 for entry in without_llm if entry.correct), len(without_llm)
        ),
        "accuracy": (
            _ratio(sum(1 for entry in routed if entry.correct), total)
            if llm_ran
            else None
        ),
        "latency_without_llm_ms": {
            "p50": _milliseconds([entry.seconds for entry in without_llm], 50),
            "p95": _milliseconds([entry.seconds for entry in without_llm], 95),
        },
        "methods": methods,
        "routes": routes,
        "misrouted": [_miss(entry) for entry in routed if entry.correct is False],
        "sent_to_llm": [
            entry.item.item_id for entry in routed if entry.reached_the_llm
        ],
    }


def _miss(entry: RoutedQuestion) -> dict:
    decision = entry.decision
    return {
        "id": entry.item.item_id,
        "question": entry.item.question,
        "expected": [entry.item.route.value, *entry.item.agents],
        "got": [
            decision.route.value,
            *([decision.agent.name] if decision.agent else []),
        ],
        "method": decision.method.value,
        "scores": decision.logged_scores(),
    }


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} ms"


def format_report(summary: dict) -> str:
    lines = [
        f"Router report: {summary['questions']} questions "
        f"(test set {summary['testset_version']}, examples {summary['examples_version']}), "
        f"min score {summary['min_score']:.2f}, min margin {summary['min_margin']:.2f}",
        "",
        f"{'method':<10} {'count':>5} {'share':>7} {'accuracy':>9} {'p50':>10} {'p95':>10}",
    ]
    for method, row in summary["methods"].items():
        accuracy, p50, p95 = (
            _percent(row["accuracy"]),
            _ms(row["p50_ms"]),
            _ms(row["p95_ms"]),
        )
        if method == RouteMethod.LLM.value and not summary["llm_ran"]:
            accuracy = p50 = p95 = NOT_RUN
        lines.append(
            f"{method:<10} {row['count']:>5} {_percent(row['rate']):>7} {accuracy:>9} "
            f"{p50:>10} {p95:>10}"
        )
    latency = summary["latency_without_llm_ms"]
    lines += [
        "",
        f"Fallback rate (questions sent to the LLM): {_percent(summary['fallback_rate'])}",
        f"Accuracy without the LLM fallback: {_percent(summary['accuracy_without_llm'])}",
        "Accuracy with the LLM fallback: "
        + (
            _percent(summary["accuracy"])
            if summary["llm_ran"]
            else "not run (pass --llm)"
        ),
        f"Latency when no fallback is needed: p50 {_ms(latency['p50'])}, p95 {_ms(latency['p95'])}",
        "",
        "By expected route:",
    ]
    for route, row in summary["routes"].items():
        lines.append(
            f"  {route:<14} {row['count']:>4} questions, {row['decided_without_llm']:>4} "
            f"decided without the LLM, {row['correct']:>4} correct"
        )
    if summary["misrouted"]:
        lines += ["", "Misrouted:"]
        for miss in summary["misrouted"]:
            lines.append(
                f"  {miss['id']}: {miss['question']!r} expected {' '.join(miss['expected'])}, "
                f"got {' '.join(miss['got'])} by {miss['method']} {miss['scores']}"
            )
    if summary["sent_to_llm"]:
        lines += ["", "Sent to the LLM: " + ", ".join(summary["sent_to_llm"])]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tasks.router_eval",
        description=(
            "Route the labelled router test set with the rules and embedding stages "
            "and report accuracy, the share of each method, the fallback rate and latency."
        ),
    )
    parser.add_argument(
        "--testset",
        type=Path,
        help=f"Labelled questions (default: {TESTSET_IN_REPOSITORY.as_posix()} in the repository).",
    )
    parser.add_argument("--examples", type=Path, default=ROUTER_EXAMPLES_PATH)
    parser.add_argument("--min-score", type=float)
    parser.add_argument("--min-margin", type=float)
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Send undecided questions to the constrained LLM router (needs LLM_BACKEND=vllm).",
    )
    parser.add_argument(
        "--json", type=Path, help="Also write the report as JSON to this file."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.llm and not llm_server_backend():
        print(
            "--llm needs LLM_BACKEND=vllm and LLM_VLLM_URL pointing at llama-server or vLLM."
        )
        return 2
    defaults = RouterSettings.from_env()
    settings = RouterSettings(
        min_score=defaults.min_score if args.min_score is None else args.min_score,
        min_margin=defaults.min_margin if args.min_margin is None else args.min_margin,
        llm_max_tokens=defaults.llm_max_tokens,
    )
    testset_path = args.testset or default_testset()
    if testset_path is None:
        print(
            f"No test set found: {TESTSET_IN_REPOSITORY.as_posix()} is not above this module "
            "(for example inside the MAS image); pass --testset."
        )
        return 2
    testset = load_router_testset(testset_path)
    examples = load_router_examples(args.examples)
    router = TaskRouter(ExampleIndex(examples))
    routed = route_testset(
        testset, router, settings, ask_llm_with_json_schema if args.llm else None
    )
    summary = summarise(
        routed,
        testset_version=testset.version,
        examples_version=examples.version,
        settings=settings,
        llm_ran=args.llm,
    )
    print(format_report(summary))
    if args.json is not None:
        args.json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
