"""Behavioral coverage tests for the ReAct reasoning agent.

Hermetic: langchain/transformers/torch are mocked in ``tests/agent/conftest.py``.
The collaborators (decision agent, retrieval agent, tool registry, delegation
handler) are stubbed so the THOUGHT -> ACTION -> OBSERVATION loop is fully
deterministic.

Collaborator call conventions (mirrored by the stubs below):
  * decision_agent.reason(query, user_content, system_content, call=) -> str
                                            (sync; run via to_thread; one per step)
  * decision_agent.decide(query=, context=) -> str   (sync; the final synthesis)
  * retrieval_agent.fetch(query)            -> dict   (async; awaited directly)
  * tool_registry.run(name, payload)        -> str    (sync; run via to_thread)
  * delegation_handler.delegate(...)        -> dict   (sync; run via to_thread)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agents.react_agent import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_REACT_STEPS,
    REACT_STEP_CALL,
    ExecutionHistory,
    ReactAgent,
    ReActStep,
    StepType,
)


# --------------------------------------------------------------------------- #
# Stubs / fixtures
# --------------------------------------------------------------------------- #
class FakeDecisionAgent:
    """Returns queued scripted responses for successive ``reason`` and ``decide`` calls.

    Once the queue is exhausted the last response repeats, so a runaway loop
    never crashes the test for an unrelated reason.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []  # list of (query, user content or context) tuples
        self.system_prompts = []
        self.call_labels = []

    def _next(self):
        if self._responses:
            resp = self._responses.pop(0)
            self._last = resp
            return resp
        return getattr(self, "_last", "")

    def reason(self, query, user_content, system_content, *, call):
        self.calls.append((query, user_content))
        self.system_prompts.append(system_content)
        self.call_labels.append(call)
        return self._next()

    def decide(self, query, context):
        self.calls.append((query, context))
        return self._next()


def make_retrieval(data_text="some retrieved knowledge"):
    """Async retrieval agent whose ``fetch`` returns ``{"data": ...}``."""
    agent = MagicMock()
    agent.fetch = AsyncMock(return_value={"data": data_text})
    return agent


def make_agent(
    decision_responses,
    *,
    retrieval=None,
    tool_registry=None,
    delegation_handler=None,
    max_steps=MAX_REACT_STEPS,
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
):
    decision = FakeDecisionAgent(decision_responses)
    retrieval = retrieval if retrieval is not None else make_retrieval()
    tool_registry = tool_registry if tool_registry is not None else MagicMock()
    return ReactAgent(
        decision,
        retrieval,
        tool_registry,
        max_steps=max_steps,
        timeout_seconds=timeout_seconds,
        delegation_handler=delegation_handler,
    )


# --------------------------------------------------------------------------- #
# Data structures (ExecutionHistory / ReActStep / to_dict)
# --------------------------------------------------------------------------- #
class TestExecutionHistory:
    def test_add_step_dedupes_sources(self):
        hist = ExecutionHistory(query="q")
        hist.add_step(ReActStep(1, StepType.OBSERVATION, "obs1", source="src-a"))
        hist.add_step(ReActStep(2, StepType.OBSERVATION, "obs2", source="src-a"))
        hist.add_step(ReActStep(3, StepType.OBSERVATION, "obs3", source="src-b"))
        # src-a appears twice but is recorded only once; order preserved.
        assert hist.sources == ["src-a", "src-b"]
        assert len(hist.steps) == 3

    def test_add_step_without_source_leaves_sources_empty(self):
        hist = ExecutionHistory(query="q")
        hist.add_step(ReActStep(1, StepType.THOUGHT, "thinking"))
        assert hist.sources == []

    def test_to_dict_serializes_full_trace(self):
        hist = ExecutionHistory(query="why?")
        hist.add_step(
            ReActStep(
                1,
                StepType.ACTION,
                "calc(1+1)",
                tool_name="calc",
                tool_args=["1+1"],
                duration_ms=12.5,
                source="calculation:1+1",
            )
        )
        hist.final_answer = "2"
        hist.total_duration_ms = 99.0
        d = hist.to_dict()

        assert d["query"] == "why?"
        assert d["final_answer"] == "2"
        assert d["total_duration_ms"] == 99.0
        assert d["sources"] == ["calculation:1+1"]
        assert len(d["steps"]) == 1
        step = d["steps"][0]
        assert step["type"] == "ACTION"  # enum serialized to its value
        assert step["tool_name"] == "calc"
        assert step["tool_args"] == ["1+1"]
        assert step["duration_ms"] == 12.5


# --------------------------------------------------------------------------- #
# Action parsing (_parse_action / _parse_args)
# --------------------------------------------------------------------------- #
class TestParseAction:
    def test_structured_action_with_multiple_args(self):
        agent = make_agent(["x"])
        name, args = agent._parse_action("THOUGHT: go\nACTION: extract_data('report.pdf', pdf)")
        assert name == "extract_data"  # lower-cased
        assert args == ["report.pdf", "pdf"]  # quotes stripped

    def test_structured_action_with_no_args(self):
        agent = make_agent(["x"])
        name, args = agent._parse_action("ACTION: search_knowledge()")
        assert name == "search_knowledge"
        assert args == []

    def test_fallback_space_separated_action(self):
        agent = make_agent(["x"])
        name, args = agent._parse_action("ACTION: calc 2 + 2")
        assert name == "calc"
        assert args == ["2 + 2"]

    def test_fallback_action_keyword_without_args(self):
        # Matches the bare-tool fallback; the trailing-args group is empty.
        agent = make_agent(["x"])
        name, args = agent._parse_action("ACTION: search_knowledge ")
        assert name == "search_knowledge"
        assert args == []

    def test_no_action_returns_none(self):
        agent = make_agent(["x"])
        name, args = agent._parse_action("THOUGHT: I am just thinking out loud.")
        assert name is None
        assert args == []

    def test_parse_args_strips_quotes_and_skips_empties(self):
        # Empty fragments (trailing comma / blank) are dropped.
        assert ReactAgent._parse_args("'a', \"b\" , , c,") == ["a", "b", "c"]

    def test_parse_args_empty_string(self):
        assert ReactAgent._parse_args("") == []


# --------------------------------------------------------------------------- #
# Citations (_attach_citations)
# --------------------------------------------------------------------------- #
class TestAttachCitations:
    def test_no_sources_returns_answer_unchanged(self):
        agent = make_agent(["x"])
        assert agent._attach_citations("answer", []) == "answer"

    def test_appends_numbered_citation_block(self):
        agent = make_agent(["x"])
        out = agent._attach_citations("answer\n", ["src-a", "src-b"])
        assert "Sources:" in out
        assert "[1] src-a" in out
        assert "[2] src-b" in out

    def test_does_not_duplicate_when_already_cited(self):
        agent = make_agent(["x"])
        answer = "Per the docs [Source: docs]."
        out = agent._attach_citations(answer, ["docs"])
        assert out == answer
        assert "Sources:" not in out

    def test_does_not_duplicate_when_lowercase_source_present(self):
        agent = make_agent(["x"])
        answer = "see [source: x]"
        out = agent._attach_citations(answer, ["x"])
        assert out == answer


# --------------------------------------------------------------------------- #
# Thought generation (_generate_thought)
# --------------------------------------------------------------------------- #
class TestGenerateThought:
    async def test_detects_final_answer_with_multiline_body(self):
        raw = "THOUGHT: done.\nFINAL_ANSWER: The answer is 42.\nWith extra detail."
        agent = make_agent([raw])
        thought, is_final, final_text = await agent._generate_thought("q", [], 1)
        assert is_final is True
        assert thought == raw.strip()
        # DOTALL: the final-answer body spans newlines.
        assert final_text == "The answer is 42.\nWith extra detail."

    async def test_non_final_thought(self):
        agent = make_agent(["THOUGHT: keep going\nACTION: calc(1)"])
        thought, is_final, final_text = await agent._generate_thought("q", [], 1)
        assert is_final is False
        assert final_text == ""
        assert thought.startswith("THOUGHT: keep going")

    async def test_prompt_includes_the_query_the_trace_and_the_step(self):
        agent = make_agent(["THOUGHT: ok"])
        await agent._generate_thought(
            "my-query",
            ["THOUGHT: earlier", "OBSERVATION: stuff"],
            2,
        )
        _, user_content = agent.decision_agent.calls[0]
        assert user_content == (
            "User query: my-query\n\n"
            "Reasoning so far:\nTHOUGHT: earlier\nOBSERVATION: stuff\n\n"
            "Step 2: Provide your next THOUGHT and ACTION (or FINAL_ANSWER)."
        )
        assert agent.decision_agent.call_labels == [REACT_STEP_CALL]


# --------------------------------------------------------------------------- #
# Tool handlers (_execute_action + individual handlers)
# --------------------------------------------------------------------------- #
class TestToolHandlers:
    async def test_unknown_tool_reports_error_and_no_source(self):
        agent = make_agent(["x"])
        obs, source = await agent._execute_action("does_not_exist", [])
        assert obs.startswith("[Error] Unknown tool 'does_not_exist'")
        assert "search_knowledge" in obs  # lists available tools
        assert source is None

    async def test_handler_exception_is_caught(self):
        agent = make_agent(["x"])
        agent.retrieval_agent.fetch = AsyncMock(side_effect=RuntimeError("boom"))
        obs, source = await agent._execute_action("search_knowledge", ["q"])
        assert obs.startswith("[Error] Tool 'search_knowledge' failed:")
        assert "boom" in obs
        assert source is None

    # -- search_knowledge -------------------------------------------------- #
    async def test_search_knowledge_success(self):
        agent = make_agent(["x"], retrieval=make_retrieval("found docs"))
        obs, source = await agent._execute_action("search_knowledge", ["fraud"])
        assert obs == "found docs"
        assert source == "knowledge_store:fraud"
        agent.retrieval_agent.fetch.assert_awaited_once_with("fraud")

    async def test_search_knowledge_empty_query(self):
        agent = make_agent(["x"])
        obs, source = await agent._execute_action("search_knowledge", [])
        assert obs == "[Error] search_knowledge requires a query argument."
        assert source is None

    async def test_search_knowledge_no_data(self):
        agent = make_agent(["x"], retrieval=make_retrieval(""))
        obs, source = await agent._execute_action("search_knowledge", ["nope"])
        assert obs == "No relevant information found in the knowledge store."
        assert source is None

    # -- extract_data ------------------------------------------------------ #
    async def test_extract_data_success_with_explicit_type(self):
        registry = MagicMock()
        registry.run = MagicMock(return_value="extracted text")
        agent = make_agent(["x"], tool_registry=registry)
        obs, source = await agent._execute_action("extract_data", ["report.pdf", "pdf"])
        assert obs == "extracted text"
        assert source == "file:report.pdf"
        name, payload = registry.run.call_args.args
        assert name == "parse"
        assert payload == {
            "file_url": "report.pdf",
            "file_type": "pdf",
            "query": "report.pdf",
        }

    async def test_extract_data_defaults_filetype_to_txt(self):
        registry = MagicMock()
        registry.run = MagicMock(return_value="text")
        agent = make_agent(["x"], tool_registry=registry)
        await agent._execute_action("extract_data", ["notes"])
        _, payload = registry.run.call_args.args
        assert payload["file_type"] == "txt"

    async def test_extract_data_missing_file_ref(self):
        agent = make_agent(["x"])
        obs, source = await agent._execute_action("extract_data", [])
        assert obs == "[Error] extract_data requires a file URL or content."
        assert source is None

    # -- analyze_payments -------------------------------------------------- #
    async def test_analyze_payments_success(self):
        retrieval = make_retrieval("payment insights")
        agent = make_agent(["x"], retrieval=retrieval)
        obs, source = await agent._execute_action("analyze_payments", ["Q1"])
        assert obs == "payment insights"
        assert source == "payment_analysis:Q1"
        retrieval.fetch.assert_awaited_once_with("payment analysis: Q1")

    async def test_analyze_payments_default_query(self):
        retrieval = make_retrieval("insights")
        agent = make_agent(["x"], retrieval=retrieval)
        await agent._execute_action("analyze_payments", [])
        retrieval.fetch.assert_awaited_once_with("payment analysis: payment analysis")

    async def test_analyze_payments_no_data(self):
        agent = make_agent(["x"], retrieval=make_retrieval(""))
        obs, source = await agent._execute_action("analyze_payments", ["Q1"])
        assert obs == "No payment data found in the knowledge store."
        assert source is None

    # -- calc -------------------------------------------------------------- #
    async def test_calc_success(self):
        registry = MagicMock()
        registry.run = MagicMock(return_value="4")
        agent = make_agent(["x"], tool_registry=registry)
        obs, source = await agent._execute_action("calc", ["2+2"])
        assert obs == "Result: 4"
        assert source == "calculation:2+2"
        name, payload = registry.run.call_args.args
        assert name == "calc"
        assert payload == {"expression": "2+2"}

    async def test_calc_missing_expression(self):
        agent = make_agent(["x"])
        obs, source = await agent._execute_action("calc", [])
        assert obs == "[Error] calc requires a mathematical expression."
        assert source is None

    # -- delegate ---------------------------------------------------------- #
    async def test_delegate_completed(self):
        handler = MagicMock()
        handler.delegate = MagicMock(
            return_value={"status": "completed", "result": "analyst says hi"}
        )
        agent = make_agent(["x"], delegation_handler=handler)
        obs, source = await agent._execute_action("delegate", ["analyst", "do the thing"])
        assert obs == "analyst says hi"
        assert source == "delegation:analyst"
        args = handler.delegate.call_args.args
        assert args[0] == "analyst"
        assert args[1] == "do the thing"

    async def test_delegate_completed_missing_result_field(self):
        handler = MagicMock()
        handler.delegate = MagicMock(return_value={"status": "completed"})
        agent = make_agent(["x"], delegation_handler=handler)
        obs, _ = await agent._execute_action("delegate", ["analyst", "task"])
        assert obs == "No result returned"

    async def test_delegate_failed_status(self):
        handler = MagicMock()
        handler.delegate = MagicMock(return_value={"status": "error", "error": "agent offline"})
        agent = make_agent(["x"], delegation_handler=handler)
        obs, source = await agent._execute_action("delegate", ["analyst", "task"])
        assert obs == "[Delegation failed] agent offline"
        assert source == "delegation:analyst"

    async def test_delegate_failed_default_error_message(self):
        handler = MagicMock()
        handler.delegate = MagicMock(return_value={"status": "error"})
        agent = make_agent(["x"], delegation_handler=handler)
        obs, _ = await agent._execute_action("delegate", ["analyst", "task"])
        assert obs == "[Delegation failed] Delegation failed"

    async def test_delegate_no_handler_configured(self):
        agent = make_agent(["x"], delegation_handler=None)
        obs, source = await agent._execute_action("delegate", ["analyst", "task"])
        assert "no delegation handler configured" in obs
        assert source is None

    async def test_delegate_no_args(self):
        agent = make_agent(["x"], delegation_handler=MagicMock())
        obs, source = await agent._execute_action("delegate", [])
        assert obs.startswith("[Error] delegate requires at least")
        assert source is None

    async def test_delegate_missing_request(self):
        agent = make_agent(["x"], delegation_handler=MagicMock())
        obs, source = await agent._execute_action("delegate", ["analyst"])
        assert obs == "[Error] delegate requires a request description."
        assert source is None

    async def test_delegate_empty_agent_type(self):
        # First positional arg present but empty -> target-agent guard fires.
        agent = make_agent(["x"], delegation_handler=MagicMock())
        obs, source = await agent._execute_action("delegate", ["", "task"])
        assert obs == "[Error] delegate requires a target agent type."
        assert source is None


# --------------------------------------------------------------------------- #
# Full run() loop behavior
# --------------------------------------------------------------------------- #
class TestRunLoop:
    async def test_immediate_final_answer(self):
        agent = make_agent(["THOUGHT: easy.\nFINAL_ANSWER: The sky is blue."])
        result = await agent.run("why is the sky blue?")
        assert result["answer"] == "The sky is blue."
        # No tools used -> no sources -> no appended citation block.
        assert result["sources"] == []
        assert "Sources:" not in result["answer"]
        hist = result["history"]
        assert hist["query"] == "why is the sky blue?"
        # Exactly one THOUGHT step recorded before terminating.
        assert len(hist["steps"]) == 1
        assert hist["steps"][0]["type"] == "THOUGHT"

    async def test_full_reason_act_observe_then_final(self):
        # Step 1: act via calc. Step 2: produce final answer using observation.
        registry = MagicMock()
        registry.run = MagicMock(return_value="42")
        agent = make_agent(
            [
                "THOUGHT: I should compute.\nACTION: calc(40 + 2)",
                "THOUGHT: got it.\nFINAL_ANSWER: The result is 42.",
            ],
            tool_registry=registry,
        )
        result = await agent.run("compute 40+2")

        assert result["answer"].startswith("The result is 42.")
        # Citation block appended because the calc produced a source.
        assert "calculation:40 + 2" in result["answer"]
        assert result["sources"] == ["calculation:40 + 2"]

        types = [s["type"] for s in result["history"]["steps"]]
        # THOUGHT, ACTION, OBSERVATION (step 1) then THOUGHT (step 2).
        assert types == ["THOUGHT", "ACTION", "OBSERVATION", "THOUGHT"]
        action_step = result["history"]["steps"][1]
        assert action_step["tool_name"] == "calc"
        assert action_step["tool_args"] == ["40 + 2"]
        obs_step = result["history"]["steps"][2]
        assert obs_step["content"] == "Result: 42"

    async def test_no_valid_action_nudges_then_recovers(self):
        # Step 1 has no ACTION -> nudge + continue (no ACTION/OBSERVATION steps).
        # Step 2 yields the final answer.
        agent = make_agent(
            [
                "THOUGHT: hmm, just musing with no action.",
                "THOUGHT: now I'm ready.\nFINAL_ANSWER: Done.",
            ]
        )
        result = await agent.run("q")
        assert result["answer"] == "Done."
        types = [s["type"] for s in result["history"]["steps"]]
        # Two THOUGHTs only; the nudged step added neither ACTION nor OBSERVATION.
        assert types == ["THOUGHT", "THOUGHT"]

    async def test_unknown_tool_then_final(self):
        # Exercises the unknown-tool observation path inside the live loop.
        agent = make_agent(
            [
                "THOUGHT: try a bogus tool.\nACTION: teleport(home)",
                "THOUGHT: ok.\nFINAL_ANSWER: Could not teleport.",
            ]
        )
        result = await agent.run("q")
        assert result["answer"] == "Could not teleport."
        obs_steps = [s for s in result["history"]["steps"] if s["type"] == "OBSERVATION"]
        assert len(obs_steps) == 1
        assert obs_steps[0]["content"].startswith("[Error] Unknown tool 'teleport'")
        # Unknown tool yields no source.
        assert result["sources"] == []

    async def test_max_steps_exhausted_synthesizes_answer(self):
        # Every step acts (never final) -> loop exhausts and synthesizes.
        registry = MagicMock()
        registry.run = MagicMock(return_value="num")
        # The synthesis call (last decide) returns the summary answer.
        responses = ["THOUGHT: keep going.\nACTION: calc(1)"] * 2 + ["Synthesized final summary."]
        agent = make_agent(responses, tool_registry=registry, max_steps=2)
        result = await agent.run("never-ending")

        assert result["answer"].startswith("Synthesized final summary.")
        # 2 steps x (THOUGHT, ACTION, OBSERVATION) = 6 trace steps.
        assert len(result["history"]["steps"]) == 6
        assert result["sources"] == ["calculation:1"]

    async def test_max_steps_exhausted_no_context(self):
        # Every step fails to produce a valid action -> no context gathered.
        agent = make_agent(
            ["THOUGHT: no action here."],  # repeats for both steps
            max_steps=2,
        )
        result = await agent.run("q")
        assert "unable to find enough information" in result["answer"]
        # Only THOUGHT steps; never any OBSERVATION.
        assert all(s["type"] == "THOUGHT" for s in result["history"]["steps"])

    async def test_exhausted_synthesis_decide_raises_uses_context_fallback(self):
        # The final synthesis decide() raises -> falls back to raw context.
        registry = MagicMock()
        registry.run = MagicMock(return_value="OBSDATA")

        class FlakyDecision(FakeDecisionAgent):
            def reason(self, query, user_content, system_content, *, call):
                return "THOUGHT: go.\nACTION: calc(1)"

            def decide(self, query, context):
                raise RuntimeError("synthesis model down")

        decision = FlakyDecision([])
        agent = ReactAgent(
            decision,
            make_retrieval(),
            registry,
            max_steps=2,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        )
        result = await agent.run("q")
        assert "here is what I found" in result["answer"]
        assert "Result: OBSDATA" in result["answer"]

    async def test_timeout_with_partial_observations(self):
        # A retrieval that hangs forces the asyncio.wait_for timeout; the agent
        # then summarizes whatever observations it managed to gather.
        import asyncio

        async def slow_fetch(_query):
            await asyncio.sleep(10)
            return {"data": "late"}

        retrieval = MagicMock()
        retrieval.fetch = AsyncMock(side_effect=slow_fetch)
        agent = make_agent(
            ["THOUGHT: search.\nACTION: search_knowledge(topic)"],
            retrieval=retrieval,
            timeout_seconds=0.05,
        )
        result = await agent.run("q")
        # No observation completed -> generic timeout message.
        assert "within the time limit" in result["answer"]

    async def test_run_handles_unexpected_exception(self):
        # decision_agent.decide raising a non-timeout error hits the generic
        # exception branch of run().
        class ExplodingDecision:
            def reason(self, query, user_content, system_content, *, call):
                raise ValueError("kaboom")

        agent = ReactAgent(
            ExplodingDecision(),
            make_retrieval(),
            MagicMock(),
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        )
        result = await agent.run("q")
        assert "encountered an error" in result["answer"]
        assert "kaboom" in result["answer"]


# --------------------------------------------------------------------------- #
# Fallback answer builders (direct unit coverage)
# --------------------------------------------------------------------------- #
class TestFallbackBuilders:
    def test_timeout_answer_summarizes_observations(self):
        agent = make_agent(["x"])
        hist = ExecutionHistory(query="q")
        hist.add_step(
            ReActStep(
                1,
                StepType.OBSERVATION,
                "partial finding",
                source="knowledge_store:q",
            )
        )
        out = agent._build_timeout_answer(hist)
        assert "here is what I found so far" in out
        assert "partial finding" in out
        # Source from the observation is cited.
        assert "knowledge_store:q" in out

    def test_timeout_answer_without_observations(self):
        agent = make_agent(["x"])
        out = agent._build_timeout_answer(ExecutionHistory(query="q"))
        assert "unable to complete the analysis within the time limit" in out

    def test_error_answer_includes_exception_text(self):
        agent = make_agent(["x"])
        out = agent._build_error_answer(ExecutionHistory(query="q"), ValueError("specific failure"))
        assert "encountered an error" in out
        assert "specific failure" in out

    def test_exhausted_answer_with_context_uses_decision_agent(self):
        agent = make_agent(["synthesized answer"])
        hist = ExecutionHistory(query="q")
        out = agent._build_exhausted_answer("q", ["ctx-a", "ctx-b"], hist)
        assert out.startswith("synthesized answer")

    def test_exhausted_answer_no_context(self):
        agent = make_agent(["x"])
        out = agent._build_exhausted_answer("q", [], ExecutionHistory(query="q"))
        assert "unable to find enough information" in out


# --------------------------------------------------------------------------- #
# Constructor / wiring
# --------------------------------------------------------------------------- #
class TestConstruction:
    def test_tool_handlers_registered(self):
        agent = make_agent(["x"])
        assert set(agent._tool_handlers) == {
            "search_knowledge",
            "extract_data",
            "analyze_payments",
            "calc",
            "delegate",
        }

    def test_defaults_applied(self):
        agent = make_agent(["x"])
        assert agent.max_steps == MAX_REACT_STEPS
        assert agent.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
        assert agent._incoming_delegation_context is None
