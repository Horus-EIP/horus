# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from horus_bench_kit.files import check_report, read_json
from horus_bench_kit.markdown import (
    EMPTY,
    UNITLESS,
    Metric,
    MetricRow,
    format_metric,
    row_change,
    short_hash,
    table,
)
from horus_bench_kit.report import REPORT_KIND, SCHEMA_VERSION, Profile, build_summary
from horus_bench_kit.target import STATUS_OK, observed_values

CORE_PROFILE = Profile(summary_sections=())
REQUIRED_QUESTION_KEYS = ("id", "category")
METRIC_ROWS = (
    MetricRow("answer_auto", "Answers correct, automatic", "every answer pattern matches", "%"),
    MetricRow(
        "answer_reviewed", "Answers correct, reviewed", "both reviewers marked it correct", "%"
    ),
    MetricRow("source", "Sources correct", "expected documents cited, or ranked at the top", "%"),
    MetricRow("route", "Route correct", "direct answer or retrieval, as expected", "%"),
    MetricRow("answered", "Questions answered", "status ok", "count", is_total=True),
    MetricRow("failed", "Errors and timeouts", "any other status", "count", is_total=True),
    MetricRow(
        "fallbacks",
        "Fallback answers",
        "the answer holds a fallback marker",
        "count",
        is_total=True,
    ),
    MetricRow("total_median", "Total time, median", "question sent to full answer", "s"),
    MetricRow("total_p90", "Total time, p90", "question sent to full answer", "s"),
    MetricRow("total_sum", "Total time, sum", "every question", "s", is_total=True),
    MetricRow("ttft_median", "Time to first token, median", "streamed answers", "s"),
    MetricRow("ttft_p90", "Time to first token, p90", "streamed answers", "s"),
)


@dataclass
class Side:
    name: str
    report: dict[str, Any]
    summary: dict[str, Any]

    @property
    def questions(self) -> list[dict[str, Any]]:
        return self.report["questions"]

    @property
    def run(self) -> dict[str, Any]:
        return self.report.get("run") or {}

    @property
    def testset(self) -> dict[str, Any]:
        return self.report.get("testset") or {}


def load_eval_report(path: Path | str) -> dict[str, Any]:
    document = read_json(path)
    name = Path(path).name
    questions = document.get("questions") if isinstance(document, dict) else None
    if not isinstance(questions, list):
        raise ValueError(f"{name} is not an evaluation report: it has no questions list")
    if document.get("kind") == REPORT_KIND:
        check_report(document, REPORT_KIND, SCHEMA_VERSION)
    for question in questions:
        missing = [
            key
            for key in REQUIRED_QUESTION_KEYS
            if not isinstance(question, dict) or key not in question
        ]
        if missing:
            raise ValueError(f"{name}: a question record has no {', '.join(missing)}")
    return document


def build_side(name: str, report: dict[str, Any]) -> Side:
    return Side(name, report, build_summary(report["questions"], CORE_PROFILE))


def _rate_metric(rate: dict[str, Any]) -> Metric:
    return Metric(rate.get("pct"), n=rate.get("n"))


def _stat_metric(values: dict[str, Any], key: str) -> Metric:
    return Metric(values.get(key), n=values.get("n") or None)


def side_metrics(side: Side) -> dict[str, Metric]:
    summary = side.summary
    questions = summary["questions"]
    review = summary["manual_review"]
    answered = summary["status"].get(STATUS_OK, 0)
    return {
        "answer_auto": _rate_metric(summary["answer_correct_auto"]),
        "answer_reviewed": Metric(review["answer_correct_pct"], n=review["reviewed"] or None),
        "source": _rate_metric(summary["source_correct_auto"]),
        "route": _rate_metric(summary["route_correct"]),
        "answered": Metric(answered, n=questions),
        "failed": Metric(questions - answered, n=questions),
        "fallbacks": Metric(sum(summary["fallbacks"].values()), n=questions),
        "total_median": _stat_metric(summary["total_s"], "median"),
        "total_p90": _stat_metric(summary["total_s"], "p90"),
        "total_sum": _stat_metric(summary["total_s"], "sum"),
        "ttft_median": _stat_metric(summary["ttft_s"], "median"),
        "ttft_p90": _stat_metric(summary["ttft_s"], "p90"),
    }


def model_text(side: Side) -> str | None:
    model = side.report.get("model")
    named = side.run.get("model") or (model.get("name") if isinstance(model, dict) else None)
    if named:
        return str(named)
    observed = side.run.get("observed_models") or observed_values(side.questions, "models")
    return ", ".join(observed) or None


def testset_text(side: Side) -> str | None:
    testset = side.testset
    if not testset:
        return None
    text = str(testset.get("version") or EMPTY)
    if testset.get("sha256"):
        text += f" (sha256 {short_hash(testset['sha256'])})"
    if testset.get("items_run") is not None and testset.get("items_total") is not None:
        text += f", {testset['items_run']} of {testset['items_total']} questions"
    return text


def finished_text(side: Side) -> str:
    if side.run.get("completed") is False:
        return "not finished"
    return side.run.get("finished_at") or EMPTY


def header_rows(sides: Sequence[Side]) -> list[list[Any]]:
    def kind(side: Side) -> str | None:
        found = side.report.get("kind")
        version = side.report.get("schema_version")
        return f"{found} v{version}" if found and version is not None else found

    return [
        ["Label", *[side.report.get("label") for side in sides]],
        ["Report", *[kind(side) for side in sides]],
        ["Started", *[side.run.get("started_at") for side in sides]],
        ["Finished", *[finished_text(side) for side in sides]],
        ["Target", *[side.run.get("target") for side in sides]],
        ["Model", *[model_text(side) for side in sides]],
        ["Test set", *[testset_text(side) for side in sides]],
    ]


def comparison_warnings(sides: Sequence[Side]) -> list[str]:
    warnings = []
    for side in sides:
        planned = side.testset.get("items_run")
        if side.run.get("completed") is False:
            shown = f" of {planned}" if planned is not None else ""
            warnings.append(
                f"{side.name} did not finish: {len(side.questions)}{shown} questions recorded."
            )
        review = side.summary["manual_review"]
        if review["pending"]:
            warnings.append(
                f"{side.name}: {review['pending']} of {review['pending'] + review['reviewed']} answers "
                "are not reviewed yet, so the reviewed rate leaves them out."
            )
    if len(sides) == 2:
        before, after = (side.testset.get("sha256") for side in sides)
        if before and after and before != after:
            warnings.append(
                f"The runs used different test sets (sha256 {short_hash(before)} and {short_hash(after)}): "
                "the same id may not be the same question."
            )
        ids = [{question["id"] for question in side.questions} for side in sides]
        if ids[0] != ids[1]:
            warnings.append(
                f"The runs did not ask the same questions: {len(ids[0] - ids[1])} only in "
                f"{sides[0].name}, {len(ids[1] - ids[0])} only in {sides[1].name}."
            )
    return warnings


def metric_rows(sides: Sequence[Side]) -> list[list[str]]:
    metrics = [side_metrics(side) for side in sides]
    rows = []
    for row in METRIC_ROWS:
        values = [found.get(row.key) for found in metrics]
        label = row.label if row.unit in UNITLESS else f"{row.label} ({row.unit})"
        cells = [label, row.how, *[format_metric(value, row.unit) for value in values]]
        if len(sides) == 2:
            cells.append(row_change(row, values[0], values[1]))
        rows.append(cells)
    return rows


def category_rows(sides: Sequence[Side]) -> list[list[str]]:
    categories = list(
        dict.fromkeys(category for side in sides for category in side.summary["by_category"])
    )
    rows = []
    for category in categories:
        row = MetricRow(category, category, "", "%")
        values = [
            _rate_metric(side.summary["by_category"][category]["answer_correct_auto"])
            if category in side.summary["by_category"]
            else None
            for side in sides
        ]
        cells = [category, *[format_metric(value, row.unit) for value in values]]
        if len(sides) == 2:
            cells.append(row_change(row, values[0], values[1]))
        rows.append(cells)
    return rows


def _flag(value: bool | None) -> str:
    return EMPTY if value is None else ("yes" if value else "no")


def changed_questions(sides: Sequence[Side]) -> list[list[str]]:
    after = {question["id"]: question for question in sides[1].questions}
    rows = []
    for old in sides[0].questions:
        new = after.get(old["id"])
        if new is None:
            continue
        scores = [
            question.get(key)
            for key in ("answer_correct_auto", "source_correct_auto")
            for question in (old, new)
        ]
        if scores[0] != scores[1] or scores[2] != scores[3]:
            rows.append([old["id"], old["category"], *[_flag(score) for score in scores]])
    return rows


def render(sides: Sequence[Side]) -> str:
    names = [side.name for side in sides]
    two = len(sides) == 2
    lines = [
        "# Evaluation comparison" if two else "# Evaluation",
        "",
        *table(["", *names], header_rows(sides)),
    ]
    warnings = comparison_warnings(sides)
    if warnings:
        lines += ["", *[f"- {warning}" for warning in warnings]]
    change = ["Change"] if two else []
    lines += [
        "",
        "## Metrics",
        "",
        *table(["Metric", "How it's measured", *names, *change], metric_rows(sides)),
    ]
    categories = category_rows(sides)
    if categories:
        header = ["Category", *[f"{name} (answers correct)" for name in names], *change]
        lines += ["", "## Answers by category", "", *table(header, categories)]
    if two:
        changed = changed_questions(sides)
        lines += ["", "## Questions that changed", ""]
        if changed:
            header = ["Question", "Category"] + [
                f"{score} ({name})" for score in ("Answer", "Source") for name in names
            ]
            lines += table(header, changed)
        else:
            lines.append("No question changed its automatic answer or source score.")
    return "\n".join(lines) + "\n"


def compare_reports(reports: Sequence[dict[str, Any]]) -> str:
    if len(reports) not in (1, 2):
        raise ValueError("compare one or two evaluation reports")
    names = ("run",) if len(reports) == 1 else ("before", "after")
    return render([build_side(name, report) for name, report in zip(names, reports, strict=True)])


def compare_markdown(paths: Sequence[Path | str]) -> str:
    return compare_reports([load_eval_report(path) for path in paths])
