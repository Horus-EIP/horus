from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_server.profiles import (
    DEFAULT_PROFILES,
    DEFAULT_TOOLS,
    SYSTEM_PROMPT_TOKEN_BUDGET,
    AgentProfile,
)
from ai_agents import agent_tools
from ai_agents.agent_tools import MAX_TOOLS_PER_IDENTITY, TOOL_NAMES
from ai_agents.answer_contract import answer_prompt
from ai_agents.decision_making_agent import APP_DIR, LOCAL_MODEL_DIR
from ai_agents.prompt_tokens import CONSERVATIVE_CHARS_PER_TOKEN, estimate_tokens
from ai_agents.react_agent import ReactAgent, react_system_prompt

MODEL_TYPE = "qwen3"


def _is_the_agent_model(model_dir: Path) -> bool:
    try:
        config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return config.get("model_type") == MODEL_TYPE


def _offline_model_tokenizer():
    try:
        from tokenizers import Tokenizer
    except ImportError:
        return None
    candidates = [
        LOCAL_MODEL_DIR / "tokenizer.json",
        *sorted(APP_DIR.glob("models/*/tokenizer.json")),
    ]
    for path in candidates:
        if path.is_file() and _is_the_agent_model(path.parent):
            return Tokenizer.from_file(str(path))
    return None


MODEL_TOKENIZER = _offline_model_tokenizer()


def prompt_tokens(text: str) -> int:
    if MODEL_TOKENIZER is None:
        return estimate_tokens(text)
    return len(MODEL_TOKENIZER.encode(text, add_special_tokens=False).ids)


def identity_ids(profile: AgentProfile) -> str:
    return profile.name


class TestSystemPromptBudget:
    @pytest.mark.parametrize("profile", DEFAULT_PROFILES, ids=identity_ids)
    def test_every_identity_has_a_system_prompt_under_the_budget(self, profile):
        assert profile.system_prompt
        assert prompt_tokens(profile.system_prompt) < SYSTEM_PROMPT_TOKEN_BUDGET

    @pytest.mark.parametrize("profile", DEFAULT_PROFILES, ids=identity_ids)
    def test_the_estimate_alone_keeps_every_system_prompt_under_the_budget(self, profile):
        assert estimate_tokens(profile.system_prompt) < SYSTEM_PROMPT_TOKEN_BUDGET

    @pytest.mark.skipif(
        MODEL_TOKENIZER is None, reason="the model tokenizer is not on this machine"
    )
    def test_the_estimate_never_counts_fewer_tokens_than_the_model_tokenizer(self):
        fixed_prompts = [profile.system_prompt for profile in DEFAULT_PROFILES]
        fixed_prompts += [answer_prompt("q", "", labels)[0] for labels in (["S1"], [])]
        fixed_prompts += [react_system_prompt(profile.tools, 5) for profile in DEFAULT_PROFILES]

        for text in fixed_prompts:
            exact = len(MODEL_TOKENIZER.encode(text, add_special_tokens=False).ids)
            assert estimate_tokens(text) >= exact, text[:60]

    def test_the_estimate_rounds_up(self):
        assert CONSERVATIVE_CHARS_PER_TOKEN == 3
        assert estimate_tokens("") == 0
        assert estimate_tokens("abcd") == 2
        assert estimate_tokens("abcdef") == 2


class TestIdentityTools:
    @pytest.mark.parametrize("profile", DEFAULT_PROFILES, ids=identity_ids)
    def test_every_identity_has_at_most_five_known_tools(self, profile):
        assert 1 <= len(profile.tools) <= MAX_TOOLS_PER_IDENTITY == 5
        assert set(profile.tools) <= set(TOOL_NAMES)
        assert len(set(profile.tools)) == len(profile.tools)

    def test_every_identity_can_search_the_knowledge_store(self):
        assert all("search_knowledge" in profile.tools for profile in DEFAULT_PROFILES)

    def test_an_identity_defined_elsewhere_gets_the_default_tools(self):
        profile = AgentProfile(name="Solo", type="general", skills=[], description="")

        assert profile.tools == DEFAULT_TOOLS
        assert len(DEFAULT_TOOLS) <= MAX_TOOLS_PER_IDENTITY

    def test_tools_given_as_a_list_are_kept_as_a_tuple(self):
        profile = AgentProfile(
            name="Solo", type="general", skills=[], description="", tools=["calc"]
        )

        assert profile.tools == ("calc",)

    def test_more_than_five_tools_are_refused(self, monkeypatch):
        monkeypatch.setitem(agent_tools.TOOL_DEFINITIONS, "summarize", "summarize(text)")

        with pytest.raises(ValueError, match="6 tools, more than the 5"):
            AgentProfile(
                name="Greedy",
                type="general",
                skills=[],
                description="",
                tools=(*TOOL_NAMES, "summarize"),
            )

    def test_an_unknown_tool_is_refused(self):
        with pytest.raises(ValueError, match="unknown tools"):
            AgentProfile(name="Odd", type="general", skills=[], description="", tools=("teleport",))

    def test_a_tool_listed_twice_is_refused(self):
        with pytest.raises(ValueError, match=r"\['calc'\] more than once"):
            AgentProfile(
                name="Odd", type="general", skills=[], description="", tools=("calc", "calc")
            )

    def test_the_tool_names_are_the_react_agents_tools(self):
        agent = ReactAgent(object(), object(), object())

        assert set(agent._tool_handlers) == set(TOOL_NAMES)
