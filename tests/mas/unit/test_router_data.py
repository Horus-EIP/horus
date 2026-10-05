from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

import pytest

from tasks.router import (
    ROUTER_EXAMPLES_PATH,
    Route,
    RouteMethod,
    load_router_examples,
    rule_decision,
)
from tasks.router_eval import DEFAULT_TESTSET, load_router_testset

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_PROFILES = REPO_ROOT / "src" / "services" / "agent" / "app" / "agent_server" / "profiles.py"
DEMO_ASSETS = REPO_ROOT / "demo_assets"
COPIED_PHRASE_WORDS = 6
MIN_QUESTIONS = 100
MIN_QUESTIONS_PER_DOCUMENT = 10
EXAMPLES_PER_AGENT = range(10, 31)

TESTSET = load_router_testset(DEFAULT_TESTSET)
EXAMPLES = load_router_examples(ROUTER_EXAMPLES_PATH)


def default_profiles() -> dict[str, dict]:
    tree = ast.parse(AGENT_PROFILES.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "DEFAULT_PROFILES"
        ):
            profiles = {}
            for call in node.value.elts:
                fields = {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}
                profiles[fields["name"]] = fields
            return profiles
    raise AssertionError("DEFAULT_PROFILES not found in the agent profiles")


def phrases(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {
        tuple(words[start : start + COPIED_PHRASE_WORDS])
        for start in range(len(words) - COPIED_PHRASE_WORDS + 1)
    }


class TestRouterTestset:
    def test_it_has_at_least_100_labelled_questions_with_unique_ids(self):
        ids = [item.item_id for item in TESTSET.items]

        assert len(ids) >= MIN_QUESTIONS
        assert len(set(ids)) == len(ids)
        assert len({item.question for item in TESTSET.items}) == len(ids)

    def test_it_covers_every_route_type(self):
        routes = Counter(item.route for item in TESTSET.items)

        assert set(routes) == {Route.DIRECT_ANSWER, Route.SINGLE_AGENT, Route.COMPLEX_TASK}

    def test_single_agent_questions_name_roster_agents_and_the_others_name_none(self):
        roster = {agent.name for agent in TESTSET.roster}
        for item in TESTSET.items:
            if item.route is Route.SINGLE_AGENT:
                assert item.agents and set(item.agents) <= roster, item.item_id
            else:
                assert item.agents == (), item.item_id

    def test_the_roster_is_the_agent_workers_default_identities(self):
        profiles = default_profiles()

        assert [agent.name for agent in TESTSET.roster] == list(profiles)
        for agent in TESTSET.roster:
            assert agent.agent_type == profiles[agent.name]["type"]
            assert list(agent.skills) == profiles[agent.name]["skills"]
            assert agent.description == profiles[agent.name]["description"]

    def test_document_questions_accept_every_agent_grounded_in_that_document(self):
        document_items = [item for item in TESTSET.items if item.category == "document"]

        assert set(TESTSET.document_owners) == {path.name for path in DEMO_ASSETS.glob("*.md")}
        for item in document_items:
            assert item.source in TESTSET.document_owners, item.item_id
            assert set(TESTSET.document_owners[item.source]) <= set(item.agents), item.item_id
        per_document = Counter(item.source for item in document_items)
        assert all(count >= MIN_QUESTIONS_PER_DOCUMENT for count in per_document.values())
        assert set(per_document) == set(TESTSET.document_owners)


class TestRouterExamples:
    def test_each_group_is_a_default_identity_with_skills_it_really_has(self):
        profiles = default_profiles()

        assert [group.agent_name for group in EXAMPLES.groups] == list(profiles)
        for group in EXAMPLES.groups:
            assert group.skills, group.agent_name
            assert set(group.skills) <= set(profiles[group.agent_name]["skills"])
            assert "knowledge_retrieval" not in group.skills

    def test_each_identity_has_10_to_30_distinct_examples(self):
        for group in EXAMPLES.groups:
            assert len(group.examples) in EXAMPLES_PER_AGENT, group.agent_name
            assert len(set(group.examples)) == len(group.examples), group.agent_name

    def test_the_examples_file_is_versioned(self):
        assert EXAMPLES.version

    def test_no_test_question_copies_a_phrase_from_the_examples(self):
        example_phrases = set()
        for group in EXAMPLES.groups:
            for example in group.examples:
                example_phrases |= phrases(example)

        copied = {
            item.item_id: sorted(phrases(item.question) & example_phrases)
            for item in TESTSET.items
            if phrases(item.question) & example_phrases
        }
        assert copied == {}


class TestRulesOnTheTestset:
    @pytest.mark.parametrize(
        "item", [item for item in TESTSET.items], ids=lambda item: item.item_id
    )
    def test_the_rules_never_contradict_a_label(self, item):
        decision = rule_decision(item.question, TESTSET.roster)

        if item.route is Route.DIRECT_ANSWER:
            assert decision is not None and decision.route is Route.DIRECT_ANSWER
            assert decision.method is RouteMethod.RULES
            assert decision.direct_answer
        elif decision is not None:
            assert decision.route is item.route
