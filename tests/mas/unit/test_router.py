from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from prometheus_client import REGISTRY
from sqlalchemy.exc import OperationalError

from tasks import router
from tasks.router import (
    ExampleGroup,
    ExampleIndex,
    RosterAgent,
    Route,
    RouteDecision,
    RouteMethod,
    RouterExamples,
    RouterSettings,
    TaskRouter,
    assign_example_groups,
    embedding_decision,
    llm_decision,
    llm_route_messages,
    llm_route_schema,
    rule_decision,
    split_sub_questions,
)

VOCABULARY = (
    "revenue",
    "quarter",
    "budget",
    "password",
    "policy",
    "length",
    "vacation",
    "days",
    "carry",
)


class KeywordEmbedder:
    def __init__(self, vocabulary=VOCABULARY):
        self.vocabulary = vocabulary
        self.calls: list[list[str]] = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        rows = []
        for text in texts:
            words = re.findall(r"[a-z]+", text.lower())
            rows.append([float(words.count(word)) for word in self.vocabulary])
        return np.asarray(rows, dtype=np.float32)

    def embedded_texts(self):
        return [text for call in self.calls for text in call]


class VectorEmbedder:
    def __init__(self, vectors):
        self.vectors = vectors

    def __call__(self, texts):
        return np.asarray([self.vectors[text] for text in texts], dtype=np.float32)


FINANCE = RosterAgent("agent-finance", "Finance-Analyst", "Finance.", "analyst", ("financial_analysis",))
COMPLIANCE = RosterAgent(
    "agent-compliance", "Compliance-Officer", "Policy.", "analyst", ("it_security_policy",)
)
HR = RosterAgent("agent-hr", "HR-Assistant", "HR.", "general", ("leave_policy",))
ROSTER = (FINANCE, COMPLIANCE, HR)

EXAMPLES = RouterExamples(
    version="test",
    groups=(
        ExampleGroup("Finance-Analyst", ("financial_analysis",), ("revenue quarter", "revenue budget")),
        ExampleGroup(
            "Compliance-Officer", ("it_security_policy",), ("password policy", "password length")
        ),
        ExampleGroup("HR-Assistant", ("leave_policy",), ("vacation days", "vacation carry")),
    ),
)
SETTINGS = RouterSettings(min_score=0.40, min_margin=0.10)


@pytest.fixture
def embedder():
    return KeywordEmbedder()


@pytest.fixture
def index(embedder):
    return ExampleIndex(EXAMPLES, embedder)


def counter(method, route):
    return REGISTRY.get_sample_value(
        "mas_routing_decisions_total", {"method": method, "route": route}
    ) or 0.0


def latency_count(method):
    return REGISTRY.get_sample_value(
        "mas_routing_decision_seconds_count", {"method": method}
    ) or 0.0


class TestRules:
    def test_a_greeting_is_answered_directly_from_a_template(self):
        decision = rule_decision("Hello!", ROSTER)

        assert decision.route is Route.DIRECT_ANSWER
        assert decision.method is RouteMethod.RULES
        assert decision.cue == "greeting"
        assert decision.direct_answer == "Hello! What can I help you with?"

    def test_arithmetic_is_answered_with_the_computed_result(self):
        decision = rule_decision("What is 12 multiplied by 7?", ROSTER)

        assert decision.route is Route.DIRECT_ANSWER
        assert decision.cue == "arithmetic"
        assert decision.direct_answer == "12 multiplied by 7 = 84"

    def test_small_talk_about_the_assistant_lists_the_live_agents(self):
        decision = rule_decision("who are you?", ROSTER)

        assert "(Finance-Analyst, Compliance-Officer, HR-Assistant)" in decision.direct_answer

    @pytest.mark.parametrize(
        "question",
        ["What is the capital of Peru?", "What was Q4 revenue?", "what is 555-1234"],
    )
    def test_f20_a_factual_question_or_a_phone_number_is_never_a_direct_answer(self, question):
        assert rule_decision(question, ROSTER) is None

    @pytest.mark.parametrize(
        "question", ["what is 50% + 10", "what is 9^100*9^100*9^100*9^100"]
    )
    def test_arithmetic_that_cannot_be_computed_is_left_to_the_next_stage(self, question):
        assert rule_decision(question, ROSTER) is None

    @pytest.mark.parametrize(
        ("question", "cue"),
        [
            ("Compare Q3 and Q4 revenue", "comparison"),
            ("Give me the revenue and also the password policy", "and_also"),
            ("What is the hotel cap? Who approves overages?", "several_questions"),
        ],
    )
    def test_cues_for_several_questions_mean_a_complex_task(self, question, cue):
        decision = rule_decision(question, ROSTER)

        assert decision.route is Route.COMPLEX_TASK
        assert decision.method is RouteMethod.RULES
        assert decision.cue == cue

    def test_a_greeting_is_answered_even_without_agents_online(self):
        assert rule_decision("hi", ()).route is Route.DIRECT_ANSWER


class TestEmbeddings:
    def test_a_confident_match_routes_to_that_live_agent(self, index):
        decision, scores = embedding_decision("What was revenue last quarter?", ROSTER, index, SETTINGS)

        assert decision.route is Route.SINGLE_AGENT
        assert decision.method is RouteMethod.EMBEDDING
        assert decision.agent == FINANCE
        assert scores[0].agent == FINANCE
        assert scores[0].score == pytest.approx((1.0 + 0.5) / 2)

    def test_the_agent_score_is_the_mean_of_its_two_closest_examples(self, index):
        _decision, scores = embedding_decision("password", ROSTER, index, SETTINGS)

        assert scores[0].agent == COMPLIANCE
        assert scores[0].score == pytest.approx((2**-0.5 + 2**-0.5) / 2)

    def test_a_question_close_to_no_example_is_left_to_the_llm(self, index):
        decision, scores = embedding_decision("Who painted the Mona Lisa?", ROSTER, index, SETTINGS)

        assert decision is None
        assert all(entry.score == 0.0 for entry in scores)

    def test_a_score_under_the_minimum_is_left_to_the_llm(self):
        vectors = {
            "a1": [1, 0, 0],
            "a2": [1, 0, 0],
            "b1": [0, 1, 0],
            "b2": [0, 1, 0],
            "question": [0.39, 0.0, (1 - 0.39**2) ** 0.5],
        }
        examples = RouterExamples("v", (ExampleGroup("A", (), ("a1", "a2")), ExampleGroup("B", (), ("b1", "b2"))))
        roster = (RosterAgent("a", "A"), RosterAgent("b", "B"))
        index = ExampleIndex(examples, VectorEmbedder(vectors))

        decision, scores = embedding_decision("question", roster, index, SETTINGS)
        assert decision is None
        assert scores[0].score == pytest.approx(0.39)

        decision, _ = embedding_decision(
            "question", roster, index, RouterSettings(min_score=0.38, min_margin=0.10)
        )
        assert decision.agent.name == "A"

    def test_a_margin_under_the_minimum_is_left_to_the_llm(self):
        vectors = {
            "a1": [1, 0],
            "a2": [1, 0],
            "b1": [0, 1],
            "b2": [0, 1],
            "question": [0.75, 0.66],
        }
        examples = RouterExamples("v", (ExampleGroup("A", (), ("a1", "a2")), ExampleGroup("B", (), ("b1", "b2"))))
        roster = (RosterAgent("a", "A"), RosterAgent("b", "B"))
        index = ExampleIndex(examples, VectorEmbedder(vectors))

        decision, scores = embedding_decision("question", roster, index, SETTINGS)
        assert decision is None
        assert scores[0].score - scores[1].score < 0.10

        decision, _ = embedding_decision(
            "question", roster, index, RouterSettings(min_score=0.40, min_margin=0.05)
        )
        assert decision.agent.name == "A"

    def test_two_sub_questions_for_different_agents_are_a_complex_task(self, index):
        decision, _ = embedding_decision(
            "What was revenue last quarter, and what is the password length?",
            ROSTER,
            index,
            SETTINGS,
        )

        assert decision.route is Route.COMPLEX_TASK
        assert decision.method is RouteMethod.EMBEDDING
        assert decision.cue == "sub_questions"

    def test_two_sub_questions_for_the_same_agent_stay_with_that_agent(self, index):
        decision, _ = embedding_decision(
            "How many vacation days do I get, and how many vacation days carry over?",
            ROSTER,
            index,
            SETTINGS,
        )

        assert decision.route is Route.SINGLE_AGENT
        assert decision.agent == HR

    def test_a_sub_question_no_agent_owns_leaves_the_whole_request_to_the_llm(self, index):
        decision, _ = embedding_decision(
            "What was revenue last quarter, and who painted the Mona Lisa?",
            ROSTER,
            index,
            SETTINGS,
        )

        assert decision is None

    def test_examples_are_embedded_once_and_only_when_first_needed(self, embedder, index):
        assert embedder.calls == []

        embedding_decision("revenue", ROSTER, index, SETTINGS)
        embedding_decision("password", ROSTER, index, SETTINGS)

        assert embedder.embedded_texts().count("revenue quarter") == 1
        assert embedder.calls[-1] == ["password"]

    def test_concurrent_first_decisions_embed_the_examples_once(self, embedder, index):
        threads = [threading.Thread(target=index.warm) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert embedder.embedded_texts().count("revenue quarter") == 1

    def test_examples_of_an_agent_that_is_offline_are_not_scored(self, index):
        decision, scores = embedding_decision("password policy", (FINANCE, HR), index, SETTINGS)

        assert decision is None
        assert {entry.agent.name for entry in scores} == {"Finance-Analyst", "HR-Assistant"}

    def test_no_live_agent_means_no_embedding_work(self, embedder, index):
        assert embedding_decision("revenue", (), index, SETTINGS) == (None, ())
        assert embedder.calls == []


class TestExampleGroupsFollowTheLiveRoster:
    def test_a_group_belongs_to_the_live_agent_with_its_name(self):
        owners = assign_example_groups(EXAMPLES.groups, ROSTER)

        assert owners == {0: FINANCE, 1: COMPLIANCE, 2: HR}

    def test_a_renamed_agent_inherits_the_group_whose_skills_it_shares_most(self):
        renamed = RosterAgent("agent-x", "Money-Bot", skills=("financial_analysis", "audit"))

        owners = assign_example_groups(EXAMPLES.groups, (renamed, HR))

        assert owners == {0: renamed, 2: HR}

    def test_a_group_nobody_can_own_is_skipped(self):
        assert assign_example_groups(EXAMPLES.groups, (RosterAgent("z", "Other"),)) == {}


class TestSubQuestions:
    @pytest.mark.parametrize(
        ("question", "parts"),
        [
            (
                "What was revenue in Q4, and who is the Data Protection Officer?",
                ["What was revenue in Q4", "who is the Data Protection Officer"],
            ),
            (
                "Which clients joined in Q4; how long are audit logs kept?",
                ["Which clients joined in Q4", "how long are audit logs kept"],
            ),
        ],
    )
    def test_sub_questions_are_split_on_and_plus_a_question_word_or_a_semicolon(
        self, question, parts
    ):
        assert split_sub_questions(question) == parts

    @pytest.mark.parametrize(
        "question",
        [
            "Who approved the overage, and on what date?",
            "What changed and why?",
            "Summarise the travel and expense policy",
            "a; b; c; d; e; f; g",
        ],
    )
    def test_a_single_question_is_not_split(self, question):
        assert split_sub_questions(question) == []


class TestConstrainedLlm:
    def test_the_schema_lets_the_model_choose_only_a_route_type_and_a_live_agent(self):
        schema = llm_route_schema(ROSTER)

        assert schema["properties"]["route"]["enum"] == ["SINGLE_AGENT", "COMPLEX_TASK"]
        assert schema["properties"]["agent"]["enum"] == [
            "Compliance-Officer",
            "Finance-Analyst",
            "HR-Assistant",
        ]
        assert schema["required"] == ["route", "agent"]
        assert schema["additionalProperties"] is False

    def test_the_prompt_lists_each_agent_with_its_description(self):
        system, user = llm_route_messages("Who approves a $4,000 purchase?", ROSTER)

        assert "- Finance-Analyst: Finance." in system["content"]
        assert user == {"role": "user", "content": "Who approves a $4,000 purchase?"}

    def test_the_prompt_makes_one_agent_the_default_and_keeps_complex_for_separate_asks(self):
        system, _user = llm_route_messages("Is alcohol reimbursable?", ROSTER)

        assert "SINGLE_AGENT for almost every request" in system["content"]
        assert "two or more separate things" in system["content"]

    def test_the_system_message_is_the_same_whatever_the_question_and_roster_order(self):
        reordered = (HR, FINANCE, COMPLIANCE)

        first, _ = llm_route_messages("Who approves a $4,000 purchase?", ROSTER)
        second, _ = llm_route_messages("How many vacation days carry over?", reordered)

        assert first == second
        assert all(agent.agent_id not in first["content"] for agent in ROSTER)

    def test_the_schema_is_the_same_whatever_the_roster_order(self):
        assert llm_route_schema((HR, FINANCE, COMPLIANCE)) == llm_route_schema(ROSTER)

    def test_a_very_long_question_is_cut_before_it_reaches_the_llm(self):
        _system, user = llm_route_messages("x" * 50_000, ROSTER)

        assert len(user["content"]) == router.LLM_QUESTION_MAX_CHARS

    def test_the_call_asks_for_about_32_tokens_of_schema_constrained_json(self):
        ask = MagicMock(return_value='{"route": "SINGLE_AGENT", "agent": "HR-Assistant"}')

        decision = llm_decision("How do I take leave?", ROSTER, SETTINGS, ask)

        messages, schema_name, schema, max_tokens = ask.call_args.args
        assert schema_name == router.ROUTE_SCHEMA_NAME
        assert schema == llm_route_schema(ROSTER)
        assert max_tokens == 32
        assert decision == RouteDecision(Route.SINGLE_AGENT, RouteMethod.LLM, HR)

    def test_a_complex_task_needs_no_known_agent(self):
        ask = MagicMock(return_value='{"route": "COMPLEX_TASK", "agent": "Finance-Analyst"}')

        decision = llm_decision("Revenue and passwords", ROSTER, SETTINGS, ask)

        assert decision.route is Route.COMPLEX_TASK
        assert decision.method is RouteMethod.LLM

    @pytest.mark.parametrize(
        "reply",
        [
            "not json",
            '{"route": "DIRECT_ANSWER", "agent": "HR-Assistant"}',
            '{"route": "SINGLE_AGENT", "agent": "Manager"}',
            '{"route": "SINGLE_AGENT"}',
            "[]",
        ],
    )
    def test_a_reply_outside_the_schema_fails_the_llm_stage(self, reply):
        router_under_test = TaskRouter(ExampleIndex(EXAMPLES, KeywordEmbedder()))

        decision = router_under_test.decide_with_llm(
            "anything", ROSTER, SETTINGS, ask=MagicMock(return_value=reply)
        )

        assert decision.route is Route.UNROUTED
        assert decision.method is RouteMethod.LLM

    def test_a_server_error_fails_the_llm_stage_and_keeps_the_embedding_scores(self):
        router_under_test = TaskRouter(ExampleIndex(EXAMPLES, KeywordEmbedder()))
        scores = (router.AgentScore(FINANCE, 0.3),)

        decision = router_under_test.decide_with_llm(
            "anything", ROSTER, SETTINGS, scores, ask=MagicMock(side_effect=OSError("down"))
        )

        assert decision.route is Route.UNROUTED
        assert decision.scores == scores


class TestSettings:
    def test_defaults_are_the_thresholds_tuned_on_the_router_test_set(self, monkeypatch):
        for name in ("ROUTER_MIN_SCORE", "ROUTER_MIN_MARGIN", "ROUTER_LLM_MAX_TOKENS"):
            monkeypatch.delenv(name, raising=False)

        assert RouterSettings.from_env() == RouterSettings(0.40, 0.10, 32)

    def test_thresholds_and_the_token_budget_come_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("ROUTER_MIN_SCORE", "0.6")
        monkeypatch.setenv("ROUTER_MIN_MARGIN", "0.05")
        monkeypatch.setenv("ROUTER_LLM_MAX_TOKENS", "48")

        assert RouterSettings.from_env() == RouterSettings(0.6, 0.05, 48)

    def test_a_value_that_is_not_a_number_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv("ROUTER_MIN_SCORE", "high")
        monkeypatch.delenv("ROUTER_MIN_MARGIN", raising=False)
        monkeypatch.delenv("ROUTER_LLM_MAX_TOKENS", raising=False)

        assert RouterSettings.from_env().min_score == 0.40


class TestDecideWithoutLlm:
    def test_rules_run_before_any_embedding(self, embedder, index):
        decision, scores = TaskRouter(index).decide_without_llm("hello", ROSTER, SETTINGS)

        assert decision.method is RouteMethod.RULES
        assert scores == ()
        assert embedder.calls == []

    def test_an_embedder_failure_hands_the_question_to_the_llm(self):
        failing = ExampleIndex(EXAMPLES, MagicMock(side_effect=RuntimeError("not loaded")))

        assert TaskRouter(failing).decide_without_llm("revenue", ROSTER, SETTINGS) == (None, ())

    def test_a_rules_failure_hands_the_question_to_the_embeddings(self, index, monkeypatch):
        monkeypatch.setattr(router, "rule_decision", MagicMock(side_effect=OverflowError("big")))

        decision, _scores = TaskRouter(index).decide_without_llm(
            "revenue this quarter", ROSTER, SETTINGS
        )

        assert decision.method is RouteMethod.EMBEDDING
        assert decision.agent is FINANCE


def agent_row(agent_id, name, *, skills=None, agent_type="analyst", alive=True, description=""):
    heartbeat = datetime.now(UTC) - (timedelta(seconds=5) if alive else timedelta(days=1))
    return SimpleNamespace(
        id=agent_id,
        name=name,
        skills=skills,
        type=SimpleNamespace(value=agent_type),
        description=description,
        last_heartbeat=heartbeat,
    )


class TestAvailableRoster:
    def test_live_workers_are_in_the_roster_and_the_manager_and_stale_rows_are_not(self):
        db = MagicMock()
        db.query.return_value.all.return_value = [
            agent_row("m", "Manager", skills=["planning"], agent_type="manager"),
            agent_row("f", "Finance-Analyst", skills=["financial_analysis"], description="Finance."),
            agent_row("w", "Document-Writer", skills=["summarization"], alive=False),
            agent_row("g", "General-Assistant", skills=None, agent_type="general"),
        ]

        assert router.available_roster(db) == [
            RosterAgent("f", "Finance-Analyst", "Finance.", "analyst", ("financial_analysis",)),
            RosterAgent("g", "General-Assistant", "", "general", ()),
        ]

    def test_a_database_error_gives_an_empty_roster(self):
        db = MagicMock()
        db.query.return_value.all.side_effect = OperationalError("select", {}, Exception("down"))

        assert router.available_roster(db) == []
        db.rollback.assert_called_once()


@pytest.fixture
def routed(monkeypatch, index):
    monkeypatch.setattr(router, "task_router", lambda: TaskRouter(index))
    monkeypatch.setattr(router, "available_roster", lambda _db: list(ROSTER))
    monkeypatch.setattr(router, "llm_server_backend", lambda: False)
    for name in ("ROUTER_MIN_SCORE", "ROUTER_MIN_MARGIN", "ROUTER_LLM_MAX_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    with (
        patch.object(router, "choose_route_with_llm") as full_router,
        patch.object(router, "decompose_task") as planner,
        patch.object(router, "ask_llm_with_json_schema") as constrained,
    ):
        yield SimpleNamespace(full_router=full_router, planner=planner, constrained=constrained)


class TestRouteTask:
    def test_a_greeting_is_answered_without_any_llm_call(self, routed):
        before = counter("rules", "DIRECT_ANSWER")

        outcome = router.route_task("hi there", MagicMock(), task_id="t-1")

        assert outcome == (None, None, "Hello! What can I help you with?", [])
        routed.full_router.assert_not_called()
        routed.constrained.assert_not_called()
        assert counter("rules", "DIRECT_ANSWER") == before + 1

    def test_a_confident_embedding_match_dispatches_the_original_question(self, routed):
        before = latency_count("embedding")

        outcome = router.route_task("What was revenue last quarter?", MagicMock())

        assert outcome == ("agent-finance", "What was revenue last quarter?", None, [])
        routed.full_router.assert_not_called()
        assert latency_count("embedding") == before + 1

    def test_a_complex_task_runs_the_planner(self, routed):
        routed.planner.return_value = (("agent-finance", "step 1"), [("agent-hr", "step 2")])
        db = MagicMock()

        outcome = router.route_task("Compare Q3 and Q4 revenue", db)

        routed.planner.assert_called_once_with("Compare Q3 and Q4 revenue", db)
        assert outcome == ("agent-finance", "step 1", None, [("agent-hr", "step 2")])

    @pytest.mark.parametrize("planner_result", [(None, []), RuntimeError("planner down")])
    def test_a_complex_task_without_a_plan_is_left_to_the_fallback_agents(
        self, routed, planner_result
    ):
        if isinstance(planner_result, Exception):
            routed.planner.side_effect = planner_result
        else:
            routed.planner.return_value = planner_result

        assert router.route_task("Compare Q3 and Q4 revenue", MagicMock()) == (None, None, None, [])

    def test_on_the_server_backend_an_undecided_question_gets_a_constrained_llm_call(
        self, routed, monkeypatch
    ):
        monkeypatch.setattr(router, "llm_server_backend", lambda: True)
        routed.constrained.return_value = '{"route": "SINGLE_AGENT", "agent": "HR-Assistant"}'
        before = counter("llm", "SINGLE_AGENT")

        outcome = router.route_task("Who painted the Mona Lisa?", MagicMock())

        assert outcome == ("agent-hr", "Who painted the Mona Lisa?", None, [])
        routed.full_router.assert_not_called()
        assert routed.constrained.call_args.args[3] == 32
        assert counter("llm", "SINGLE_AGENT") == before + 1

    def test_on_the_server_backend_a_failed_llm_call_leaves_the_task_unrouted(
        self, routed, monkeypatch
    ):
        monkeypatch.setattr(router, "llm_server_backend", lambda: True)
        routed.constrained.side_effect = OSError("llm down")
        before = counter("llm", "UNROUTED")

        assert router.route_task("Who painted the Mona Lisa?", MagicMock()) == (None, None, None, [])
        assert counter("llm", "UNROUTED") == before + 1

    def test_on_the_transformers_backend_an_undecided_question_keeps_the_current_router(
        self, routed
    ):
        routed.full_router.return_value = ("SINGLE_AGENT", ("agent-hr", "rewritten", None, []))
        db = MagicMock()

        outcome = router.route_task("Who painted the Mona Lisa?", db)

        routed.full_router.assert_called_once_with("Who painted the Mona Lisa?", db)
        routed.constrained.assert_not_called()
        assert outcome == ("agent-hr", "rewritten", None, [])

    def test_on_the_transformers_backend_a_direct_answer_is_passed_on(self, routed):
        routed.full_router.return_value = (
            "DIRECT_ANSWER",
            (None, None, "Response for user : 4", []),
        )
        before = counter("llm", "DIRECT_ANSWER")

        outcome = router.route_task("Who painted the Mona Lisa?", MagicMock())

        assert outcome == (None, None, "Response for user : 4", [])
        assert counter("llm", "DIRECT_ANSWER") == before + 1

    def test_on_the_transformers_backend_a_complex_task_is_timed_before_the_planner_runs(
        self, routed
    ):
        routed.full_router.return_value = ("COMPLEX_TASK", (None, None, None, []))
        before = latency_count("llm")
        timed_before_planning = []
        routed.planner.side_effect = lambda _text, _db: (
            timed_before_planning.append(latency_count("llm") == before + 1)
            or (("agent-finance", "step 1"), [("agent-hr", "step 2")])
        )
        db = MagicMock()

        outcome = router.route_task("Who painted the Mona Lisa?", db)

        routed.planner.assert_called_once_with("Who painted the Mona Lisa?", db)
        assert timed_before_planning == [True]
        assert outcome == ("agent-finance", "step 1", None, [("agent-hr", "step 2")])

    def test_rules_and_embeddings_time_a_complex_task_before_the_planner_runs(self, routed):
        before = latency_count("rules")
        timed_before_planning = []
        routed.planner.side_effect = lambda _text, _db: (
            timed_before_planning.append(latency_count("rules") == before + 1) or (None, [])
        )

        router.route_task("Compare Q3 and Q4 revenue", MagicMock())

        assert timed_before_planning == [True]

    def test_arithmetic_too_large_to_show_goes_on_to_the_next_stages(self, routed):
        routed.full_router.return_value = ("SINGLE_AGENT", ("agent-hr", "big", None, []))

        outcome = router.route_task("what is 9^100*9^100*9^100*9^100", MagicMock())

        assert outcome == ("agent-hr", "big", None, [])
        routed.full_router.assert_called_once()

    def test_on_the_transformers_backend_a_router_crash_leaves_the_task_unrouted(self, routed):
        routed.full_router.side_effect = RuntimeError("LLM is not loaded")

        assert router.route_task("Who painted the Mona Lisa?", MagicMock()) == (None, None, None, [])

    def test_with_no_agent_online_a_question_is_unrouted_without_an_llm_call(
        self, routed, monkeypatch
    ):
        monkeypatch.setattr(router, "available_roster", lambda _db: [])
        before = counter("none", "UNROUTED")

        assert router.route_task("What was revenue?", MagicMock()) == (None, None, None, [])
        routed.full_router.assert_not_called()
        assert counter("none", "UNROUTED") == before + 1

    def test_every_decision_is_logged_with_method_scores_agent_and_latency(self, routed, caplog):
        caplog.set_level("INFO", logger="task_router")

        router.route_task("What was revenue last quarter?", MagicMock(), task_id="t-42")

        (record,) = [
            json.loads(entry.getMessage())
            for entry in caplog.records
            if entry.name == "task_router" and "Routing decision" in entry.getMessage()
        ]
        assert record["task_id"] == "t-42"
        assert record["method"] == "embedding"
        assert record["route"] == "SINGLE_AGENT"
        assert record["agent"] == "Finance-Analyst"
        assert record["scores"]["Finance-Analyst"] == pytest.approx(0.75)
        assert record["latency_ms"] >= 0


class TestRoutingMetrics:
    def test_buckets_resolve_milliseconds_and_reach_the_thirty_minute_timeout(self):
        assert router.observe_routing_decision is not None
        from core.metrics import ROUTING_BUCKETS

        assert ROUTING_BUCKETS[0] == 0.001
        assert 0.2 in ROUTING_BUCKETS
        assert ROUTING_BUCKETS[-1] == 1800.0
