from __future__ import annotations

import json
import sys
from pathlib import Path

MARKER = "smoke steps: "
STEP_COUNT = 9


def steps_in(log: Path) -> list[dict]:
    lines = [
        line
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
        if MARKER in line
    ]
    if not lines:
        raise ValueError(f"{log} has no '{MARKER}' line: smoke.py did not finish")
    return json.loads(lines[-1].split(MARKER, 1)[1])


def problems(steps: list[dict]) -> list[str]:
    found = [f"{step['name']}: {step.get('detail', '')}" for step in steps if not step.get("ok")]
    found += [f"{step['name']}: warned, {step['warning']}" for step in steps if step.get("warning")]
    if len(steps) != STEP_COUNT:
        found.append(f"{len(steps)} steps ran, not {STEP_COUNT}")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: smoke-steps.py SMOKE_LOG", file=sys.stderr)
        return 2
    try:
        steps = steps_in(Path(argv[0]))
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    for step in steps:
        print(
            f"{'ok    ' if step.get('ok') else 'NOT OK'} {step['name']} - {step.get('detail', '')}"
        )
    failed = problems(steps)
    for problem in failed:
        print(f"::error::{problem}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
