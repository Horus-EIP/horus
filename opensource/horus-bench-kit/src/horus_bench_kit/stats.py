# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import statistics
from typing import Any


def rate(flags: list[bool | None]) -> dict[str, Any]:
    known = [flag for flag in flags if flag is not None]
    correct = sum(1 for flag in known if flag)
    return {
        "n": len(known),
        "correct": correct,
        "pct": round(100.0 * correct / len(known), 1) if known else None,
    }


def stats(values: list[float | None]) -> dict[str, Any]:
    known = sorted(value for value in values if value is not None)
    if not known:
        return {"n": 0}
    return {
        "n": len(known),
        "mean": round(statistics.mean(known), 3),
        "median": round(statistics.median(known), 3),
        "p90": round(known[min(int(len(known) * 0.9), len(known) - 1)], 3),
        "min": round(known[0], 3),
        "max": round(known[-1], 3),
        "sum": round(sum(known), 3),
    }
