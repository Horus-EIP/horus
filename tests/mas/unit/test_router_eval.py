from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
import yaml

from tasks import router_eval
from tasks.router import (
    ExampleGroup,
    ExampleIndex,
    Route,
    RouteMethod,
    RouterExamples,
    RouterSettings,
    TaskRouter,
)
from tasks.router_eval import (
    format_report,
    load_router_testset,
    route_testset,
    summarise,
)

VOCABULARY = ("revenue", "quarter", "budget", "password", "policy", "length", "vacation", "days")


def keyword_embedder(texts):
    rows = []
    for text in texts:
        words = re.findall(r"[a-z]+", text.lower())
        rows.append([float(words.count(word)) for word in VOCABULARY])
    return np.asarray(rows, dtype=np.float32)


EXAMPLES = RouterExamples(
    "test",
    (
        ExampleGroup("Finance-Analyst", ("financial_analysis",), ("revenue quarter", "revenue budget")),
        ExampleGroup("Compliance-Officer", ("audit",), ("password policy", "password length")),
        ExampleGroup("HR-Assistant", ("leave_policy",), ("vacation days", "vacation policy")),
    ),
)

TESTSET_DOCUMENT = {
    "version": "9.9.9",
    "roster": [
        {"name": "Finance-Analyst", "type": "analyst", "skills": ["financial_analysis"]},
        {"name": "Compliance-Officer", "type": "analyst", "skills": ["audit"]},
        {"name": "HR-Assistant", "type": "general", "skills": ["leave_policy"]},
    ],
    "items": [
        {"id": "d1", "question": "hello", "route": "DIRECT_ANSWER"},
        {"id": "d2", "question": "what is 6 x 7", "route": "DIRECT_ANSWER"},
        {"id": "c1", "question": "compare revenue and budget", "route": "COMPLEX_TASK"},
        {
            "id": "s1",
            "question": "revenue this quarter",
            "route": "SINGLE_AGENT",
            "agents": ["Finance-Analyst"],
        },
        {
            "id": "s2",
            "question": "password length",
            "route": "SINGLE_AGENT",
            "agents": ["HR-Assistant"],
        },
        {
            "id": "s3",
            "question": "who painted the mona lisa",
            "route": "SINGLE_AGENT",
            "agents": ["HR-Assistant"],
        },
    ],
}


@pytest.fixture
def testset_path(tmp_path):
    path = tmp_path / "router_testset.yaml"
    path.write_text(yaml.safe_dump(TESTSET_DOCUMENT), encoding="utf-8")
    return path


@pytest.fixture
def testset(testset_path):
    return load_router_testset(testset_path)


def report(testset, ask=None):
    settings = RouterSettings(min_score=0.40, min_margin=0.10)
    routed = route_testset(testset, TaskRouter(ExampleIndex(EXAMPLES, keyword_embedder)), settings, ask)
    return summarise(
        routed,
        testset_version=testset.version,
        examples_version=EXAMPLES.version,
        settings=settings,
        llm_ran=ask is not None,
    )


class TestLoadTestset:
    def test_items_and_roster_are_read_from_yaml(self, testset):
        assert testset.version == "9.9.9"
        assert [agent.name for agent in testset.roster] == [
            "Finance-Analyst",
            "Compliance-Officer",
            "HR-Assistant",
        ]
        assert testset.items[3].route is Route.SINGLE_AGENT
        assert testset.items[3].agents == ("Finance-Analyst",)


class TestSummary:
    def test_without_the_llm_the_report_counts_methods_fallbacks_and_misroutes(self, testset):
        summary = report(testset)

        assert summary["questions"] == 6
        assert summary["methods"]["rules"]["count"] == 3
        assert summary["methods"]["rules"]["accuracy"] == 1.0
        assert summary["methods"]["embedding"]["count"] == 2
        assert summary["methods"]["embedding"]["accuracy"] == 0.5
        assert summary["methods"]["llm"]["count"] == 1
        assert summary["methods"]["llm"]["accuracy"] is None
        assert summary["fallback_rate"] == pytest.approx(1 / 6, abs=1e-4)
        assert summary["accuracy_without_llm"] == 0.8
        assert summary["accuracy"] is None
        assert summary["sent_to_llm"] == ["s3"]
        assert [miss["id"] for miss in summary["misrouted"]] == ["s2"]
        assert summary["misrouted"][0]["got"] == ["SINGLE_AGENT", "Compliance-Officer"]
        assert summary["routes"]["SINGLE_AGENT"] == {
            "count": 3,
            "decided_without_llm": 2,
            "correct": 1,
        }

    def test_latency_percentiles_are_reported_in_milliseconds(self, testset):
        summary = report(testset)

        latency = summary["latency_without_llm_ms"]
        assert 0 <= latency["p50"] <= latency["p95"]
        for method in ("rules", "embedding", "llm"):
            assert summary["methods"][method]["p50_ms"] <= summary["methods"][method]["p95_ms"]

    def test_with_the_llm_every_question_is_judged(self, testset):
        ask = MagicMock(return_value='{"route": "SINGLE_AGENT", "agent": "HR-Assistant"}')

        summary = report(testset, ask)

        ask.assert_called_once()
        assert summary["methods"]["llm"]["accuracy"] == 1.0
        assert summary["accuracy"] == pytest.approx(5 / 6, abs=1e-4)


class TestFormattedReport:
    def test_the_report_names_each_number_the_plan_asks_for(self, testset):
        text = format_report(report(testset))

        assert "Router report: 6 questions (test set 9.9.9, examples test)" in text
        assert "Fallback rate (questions sent to the LLM): 16.7%" in text
        assert "Accuracy without the LLM fallback: 80.0%" in text
        assert "Accuracy with the LLM fallback: not run (pass --llm)" in text
        assert "Latency when no fallback is needed: p50" in text
        assert re.search(
            r"^llm\s+1\s+16\.7%\s+not run\s+not run\s+not run$", text, re.MULTILINE
        )
        assert "s2: 'password length' expected SINGLE_AGENT HR-Assistant" in text
        assert "Sent to the LLM: s3" in text


class TestCommandLine:
    @pytest.fixture
    def fake_embedder(self, monkeypatch):
        monkeypatch.setattr(
            router_eval, "ExampleIndex", lambda examples: ExampleIndex(examples, keyword_embedder)
        )
        monkeypatch.setattr(router_eval, "load_router_examples", lambda _path: EXAMPLES)

    def test_main_prints_the_report_and_writes_json(
        self, fake_embedder, testset_path, tmp_path, capsys
    ):
        output = tmp_path / "report.json"

        exit_code = router_eval.main(
            ["--testset", str(testset_path), "--json", str(output), "--min-margin", "0.2"]
        )

        assert exit_code == 0
        assert "Router report: 6 questions" in capsys.readouterr().out
        summary = json.loads(output.read_text(encoding="utf-8"))
        assert summary["min_margin"] == 0.2
        assert summary["llm_ran"] is False

    def test_the_llm_option_needs_the_server_backend(self, fake_embedder, testset_path, monkeypatch):
        monkeypatch.setattr(router_eval, "llm_server_backend", lambda: False)

        assert router_eval.main(["--testset", str(testset_path), "--llm"]) == 2

    def test_the_default_test_set_is_the_one_in_the_repository(self):
        repository = Path(__file__).resolve().parents[3]

        assert router_eval.default_testset() == repository / router_eval.TESTSET_IN_REPOSITORY
        assert router_eval.METHODS == (RouteMethod.RULES, RouteMethod.EMBEDDING, RouteMethod.LLM)

    def test_a_shallow_install_like_the_mas_image_has_no_default_test_set(self):
        assert router_eval.default_testset(Path("/app/tasks/router_eval.py")) is None

    def test_without_a_default_test_set_main_asks_for_one(self, fake_embedder, monkeypatch, capsys):
        monkeypatch.setattr(router_eval, "default_testset", lambda: None)

        assert router_eval.main([]) == 2
        assert "pass --testset" in capsys.readouterr().out

    def test_an_explicit_test_set_needs_no_default(self, fake_embedder, testset_path, monkeypatch):
        monkeypatch.setattr(router_eval, "default_testset", MagicMock(side_effect=IndexError(4)))

        assert router_eval.main(["--testset", str(testset_path)]) == 0
