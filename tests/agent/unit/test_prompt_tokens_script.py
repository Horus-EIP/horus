from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "perf" / "prompt-tokens.py"
spec = importlib.util.spec_from_file_location("prompt_tokens_script", SCRIPT)
prompt_tokens_script = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = prompt_tokens_script
spec.loader.exec_module(prompt_tokens_script)


def exposition(prefix: str, calls: dict[str, list[int]], budget: int = 4096) -> str:
    registry = CollectorRegistry()
    histogram = Histogram(
        f"{prefix}_llm_prompt_tokens",
        "prompt tokens",
        ["call", "source"],
        buckets=(512, 4096, 32768),
        registry=registry,
    )
    over = Counter(f"{prefix}_llm_prompts_over_budget_total", "over", ["call"], registry=registry)
    for call, prompts in calls.items():
        for index, tokens in enumerate(prompts):
            source = "usage" if index % 2 == 0 else "estimate"
            histogram.labels(call=call, source=source).observe(tokens)
            if tokens > budget:
                over.labels(call=call).inc()
    return generate_latest(registry).decode("utf-8")


def write_metrics(directory: Path, agent: str, mas: str) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    agent_file, mas_file = directory / "agent.prom", directory / "mas.prom"
    agent_file.write_text(agent, encoding="utf-8")
    mas_file.write_text(mas, encoding="utf-8")
    return agent_file, mas_file


def test_the_average_per_call_adds_every_source_of_a_call():
    totals = prompt_tokens_script.call_totals("agent", exposition("agent", {"answer": [1000, 2000, 3000]}))

    assert totals["answer"].calls == 3
    assert totals["answer"].tokens == 6000


def test_the_report_passes_when_every_average_is_within_its_budget(tmp_path, capsys):
    agent_file, mas_file = write_metrics(
        tmp_path / "now",
        exposition("agent", {"answer": [1200, 1800], "react_step": [600]}),
        exposition("mas", {"task_route": [300, 340], "aggregate": [2500]}),
    )

    status = prompt_tokens_script.main(
        ["--agent", str(agent_file), "--mas", str(mas_file), "--json", str(tmp_path / "out.json")]
    )

    assert status == prompt_tokens_script.EXIT_WITHIN_BUDGET
    rows = {(row["service"], row["call"]): row for row in json.loads((tmp_path / "out.json").read_text())}
    assert rows[("agent", "answer")]["average_prompt_tokens"] == 1500.0
    assert rows[("mas", "task_route")]["calls"] == 2
    assert "OVER BUDGET" not in capsys.readouterr().out


def test_an_average_over_its_budget_fails_the_check(tmp_path, capsys):
    agent_file, mas_file = write_metrics(
        tmp_path / "now",
        exposition("agent", {"answer": [5000, 4000]}, budget=4096),
        exposition("mas", {"aggregate": [900]}),
    )

    status = prompt_tokens_script.main(["--agent", str(agent_file), "--mas", str(mas_file)])

    assert status == prompt_tokens_script.EXIT_OVER_BUDGET
    report = capsys.readouterr().out
    assert "answer" in report and "4500.0" in report and "OVER BUDGET" in report


def test_a_smaller_budget_can_be_given_per_service(tmp_path):
    agent_file, mas_file = write_metrics(
        tmp_path / "now",
        exposition("agent", {"answer": [1500]}),
        exposition("mas", {"task_route": [400]}),
    )

    status = prompt_tokens_script.main(
        ["--agent", str(agent_file), "--mas", str(mas_file), "--mas-budget", "300"]
    )

    assert status == prompt_tokens_script.EXIT_OVER_BUDGET


def test_only_the_calls_made_after_a_saved_snapshot_are_counted(tmp_path):
    before_agent, before_mas = write_metrics(
        tmp_path / "source-before",
        exposition("agent", {"answer": [9000]}),
        exposition("mas", {}),
    )
    assert prompt_tokens_script.main(
        ["--agent", str(before_agent), "--mas", str(before_mas), "--save", str(tmp_path / "before")]
    ) == prompt_tokens_script.EXIT_WITHIN_BUDGET
    agent_file, mas_file = write_metrics(
        tmp_path / "now",
        exposition("agent", {"answer": [9000, 1000, 2000]}),
        exposition("mas", {"plan": [700]}),
    )

    status = prompt_tokens_script.main(
        [
            "--agent", str(agent_file),
            "--mas", str(mas_file),
            "--since", str(tmp_path / "before"),
            "--json", str(tmp_path / "out.json"),
        ]
    )

    assert status == prompt_tokens_script.EXIT_WITHIN_BUDGET
    rows = {(row["service"], row["call"]): row for row in json.loads((tmp_path / "out.json").read_text())}
    assert rows[("agent", "answer")]["calls"] == 2
    assert rows[("agent", "answer")]["average_prompt_tokens"] == 1500.0
    assert rows[("agent", "answer")]["calls_over_budget"] == 0


def test_no_recorded_call_is_reported_as_such(tmp_path, capsys):
    agent_file, mas_file = write_metrics(tmp_path / "now", exposition("agent", {}), "")

    status = prompt_tokens_script.main(["--agent", str(agent_file), "--mas", str(mas_file)])

    assert status == prompt_tokens_script.EXIT_NO_CALLS
    assert "No LLM call" in capsys.readouterr().out
