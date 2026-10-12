# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

EMPTY = "—"
DECIMALS = {"t/s": 1, "s": 1, "ms": 0, "GiB": 2, "%": 1, "min": 1, "GB": 1}
SMALL_VALUE_UNITS = frozenset({"t/s", "s"})
UNITLESS = frozenset({"count", "text"})


@dataclass(frozen=True)
class Metric:
    value: Any
    n: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class MetricRow:
    key: str
    label: str
    how: str
    unit: str
    is_total: bool = False


def format_number(value: float, unit: str) -> str:
    if unit == "count":
        return f"{int(value)}"
    digits = DECIMALS.get(unit, 2)
    if unit in SMALL_VALUE_UNITS and abs(value) < 10:
        digits = 2
    text = f"{value:,.{digits}f}"
    return f"{text}%" if unit == "%" else f"{text} {unit}"


def format_metric(metric: Metric | None, unit: str) -> str:
    if metric is None or metric.value is None:
        return EMPTY
    text = str(metric.value) if unit == "text" else format_number(metric.value, unit)
    extras = [f"n={metric.n}"] if metric.n is not None else []
    if metric.note:
        extras.append(metric.note)
    return f"{text} ({', '.join(extras)})" if extras else text


def format_change(before: Metric | None, after: Metric | None, unit: str) -> str:
    if before is None or after is None or before.value is None or after.value is None:
        return ""
    if unit == "text":
        return "same" if before.value == after.value else "changed"
    delta = after.value - before.value
    if unit == "%":
        return f"{delta:+.1f} pts"
    if unit == "count":
        return f"{int(delta):+d}"
    digits = DECIMALS.get(unit, 2)
    if unit in SMALL_VALUE_UNITS and abs(delta) < 10:
        digits = 2
    relative = f" ({delta / before.value * 100:+.0f}%)" if before.value else ""
    return f"{delta:+,.{digits}f} {unit}{relative}"


def row_change(row: MetricRow, before: Metric | None, after: Metric | None) -> str:
    if row.is_total and before and after and before.n != after.n:
        return "not comparable: different question counts"
    return format_change(before, after, row.unit)


def cell(text: Any) -> str:
    return str(text if text not in (None, "") else EMPTY).replace("|", "\\|")


def table(header: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]
    return lines


def short_hash(value: Any) -> str | None:
    return f"{value[:12]}…" if isinstance(value, str) and len(value) > 12 else value
