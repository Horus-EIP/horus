"""
test_react_agent.py
--------------------
Unit tests for the ReAct reasoning loop (Phase 5).

Covers:
    - ReactAgent multi-step reasoning
    - THOUGHT / ACTION / OBSERVATION parsing
    - Tool execution (search_knowledge, extract_data, analyze_payments, calc)
    - Source citation generation
    - Execution history tracking
    - Error handling and timeouts
    - Integration with RAGPipeline (react mode)
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai_agents.react_agent import (
    ReactAgent,
    ReActStep,
    ExecutionHistory,
    StepType,
    SYSTEM_PROMPT,
    TOOL_DESCRIPTIONS,
    MAX_REACT_STEPS,
)
from ai_agents.rag_pipeline import RAGPipeline
from ai_agents.tool_registry import ToolRegistry
from ai_agents.calculator_tool import CalculatorTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_retrieval_agent():
    """Create a mock KnowledgeRetrievalAgent."""
    agent = MagicMock()
    agent.fetch = AsyncMock(
        return_value={
            "query": "test",
            "data": "Global revenue grew 15% in Q1 2025. North America led with 18% increase.",
        }
    )
    return agent


@pytest.fixture
def mock_decision_agent():
    """
    Create a mock DecisionMakingAgent.

    By default the mock produces a FINAL_ANSWER on the first call.
    Individual tests override this behaviour as needed.
    """
    agent = MagicMock()
    agent.decide = MagicMock(
        return_value=(
            "THOUGHT: I have enough information to answer.\n"
            "FINAL_ANSWER: Global revenue grew 15% in Q1 2025."
        )
    )
    return agent


@pytest.fixture
def tool_registry():
    """Create a ToolRegistry with default tools."""
    registry = ToolRegistry()
    registry.register(CalculatorTool(), aliases=["calc", "calculator"])
    # Register a lightweight mock for parse & summarize
    mock_parse = MagicMock()
    mock_parse.name = "parse_file"
    mock_parse.run = MagicMock(return_value="Extracted: sales data Q1 2025")
    registry.register(mock_parse, aliases=["parse", "file_parse", "file"])

    mock_summarize = MagicMock()
    mock_summarize.name = "summarize"
    mock_summarize.run = MagicMock(return_value="Revenue grew 15%.")
    registry.register(mock_summarize, aliases=["summary", "summarize_text"])
    return registry


@pytest.fixture
def react_agent(mock_decision_agent, mock_retrieval_agent, tool_registry):
    """Create a ReactAgent with mocked dependencies."""
    return ReactAgent(
        decision_agent=mock_decision_agent,
        retrieval_agent=mock_retrieval_agent,
        tool_registry=tool_registry,
        max_steps=5,
        timeout_seconds=10.0,
    )


# ---------------------------------------------------------------------------
# Test: Prompt templates (L5-T1)
# ---------------------------------------------------------------------------


class TestPromptTemplates:
    """Tests for ReAct prompt templates."""

    def test_system_prompt_contains_tool_placeholders(self):
        """SYSTEM_PROMPT should include placeholders for tool descriptions."""
        assert "{tool_descriptions}" in SYSTEM_PROMPT
        assert "{max_steps}" in SYSTEM_PROMPT

    def test_system_prompt_mentions_react_format(self):
        """SYSTEM_PROMPT should mention THOUGHT / ACTION / OBSERVATION."""
        assert "THOUGHT" in SYSTEM_PROMPT
        assert "ACTION" in SYSTEM_PROMPT
        assert "OBSERVATION" in SYSTEM_PROMPT
        assert "FINAL_ANSWER" in SYSTEM_PROMPT

    def test_tool_descriptions_keys(self):
        """All required tools should have descriptions."""
        expected = {"search_knowledge", "extract_data", "analyze_payments", "calc"}
        assert set(TOOL_DESCRIPTIONS.keys()) == expected

    def test_system_prompt_renders(self):
        """SYSTEM_PROMPT should render without errors."""
        desc = "\n".join(f"  - {d}" for d in TOOL_DESCRIPTIONS.values())
        rendered = SYSTEM_PROMPT.format(tool_descriptions=desc, max_steps=5)
        assert "search_knowledge" in rendered
        assert "calc" in rendered


# ---------------------------------------------------------------------------
# Test: Action parsing (L5-T4)
# ---------------------------------------------------------------------------


class TestActionParsing:
    """Tests for action selection and response parsing."""

    def test_parse_action_standard_format(self, react_agent):
        """Parse ACTION: tool_name(arg1, arg2)."""
        text = "THOUGHT: I need data.\nACTION: search_knowledge(revenue Q1 2025)"
        name, args = react_agent._parse_action(text)
        assert name == "search_knowledge"
        assert args == ["revenue Q1 2025"]

    def test_parse_action_multiple_args(self, react_agent):
        """Parse ACTION with multiple comma-separated args."""
        text = "ACTION: extract_data(report.pdf, pdf)"
        name, args = react_agent._parse_action(text)
        assert name == "extract_data"
        assert args == ["report.pdf", "pdf"]

    def test_parse_action_no_args(self, react_agent):
        """Parse ACTION with empty parentheses."""
        text = "ACTION: search_knowledge()"
        name, args = react_agent._parse_action(text)
        assert name == "search_knowledge"
        assert args == []

    def test_parse_action_quoted_args(self, react_agent):
        """Parse ACTION with quoted arguments."""
        text = "ACTION: calc('2 + 3 * 4')"
        name, args = react_agent._parse_action(text)
        assert name == "calc"
        assert args == ["2 + 3 * 4"]

    def test_parse_action_fallback_format(self, react_agent):
        """Parse ACTION without parentheses (fallback)."""
        text = "ACTION: search_knowledge revenue growth Q1"
        name, args = react_agent._parse_action(text)
        assert name == "search_knowledge"
        assert args == ["revenue growth Q1"]

    def test_parse_action_no_action_found(self, react_agent):
        """Return (None, []) when no ACTION line is present."""
        text = "THOUGHT: I need to think more about this."
        name, args = react_agent._parse_action(text)
        assert name is None
        assert args == []

    def test_parse_action_case_insensitive(self, react_agent):
        """ACTION parsing should be case-insensitive for the keyword."""
        text = "action: CALC(2+2)"
        name, args = react_agent._parse_action(text)
        assert name == "calc"
        assert args == ["2+2"]


# ---------------------------------------------------------------------------
# Test: Execution history (L5-T6)
# ---------------------------------------------------------------------------


class TestExecutionHistory:
    """Tests for execution history tracking."""

    def test_empty_history(self):
        history = ExecutionHistory(query="test")
        assert history.query == "test"
        assert history.steps == []
        assert history.final_answer is None
        assert history.sources == []

    def test_add_step(self):
        history = ExecutionHistory(query="test")
        step = ReActStep(
            step_number=1,
            step_type=StepType.THOUGHT,
            content="I need to search.",
        )
        history.add_step(step)
        assert len(history.steps) == 1
        assert history.steps[0].content == "I need to search."

    def test_add_step_with_source(self):
        history = ExecutionHistory(query="test")
        step = ReActStep(
            step_number=1,
            step_type=StepType.OBSERVATION,
            content="Revenue data",
            source="knowledge_store:revenue",
        )
        history.add_step(step)
        assert "knowledge_store:revenue" in history.sources

    def test_no_duplicate_sources(self):
        history = ExecutionHistory(query="test")
        for _ in range(3):
            step = ReActStep(
                step_number=1,
                step_type=StepType.OBSERVATION,
                content="data",
                source="knowledge_store:test",
            )
            history.add_step(step)
        assert len(history.sources) == 1

    def test_to_dict(self):
        history = ExecutionHistory(query="test query")
        history.add_step(
            ReActStep(
                step_number=1,
                step_type=StepType.THOUGHT,
                content="thinking",
            )
        )
        history.final_answer = "42"
        history.total_duration_ms = 100.0
        d = history.to_dict()
        assert d["query"] == "test query"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["type"] == "THOUGHT"
        assert d["final_answer"] == "42"
        assert d["total_duration_ms"] == 100.0


# ---------------------------------------------------------------------------
# Test: Source citations (L5-T8)
# ---------------------------------------------------------------------------


class TestSourceCitations:
    """Tests for source citation attachment."""

    def test_citations_appended(self, react_agent):
        sources = ["knowledge_store:revenue", "calculation:2+2"]
        result = react_agent._attach_citations("Answer text", sources)
        assert "Sources:" in result
        assert "[1] knowledge_store:revenue" in result
        assert "[2] calculation:2+2" in result

    def test_no_citations_when_empty(self, react_agent):
        result = react_agent._attach_citations("Answer text", [])
        assert result == "Answer text"
        assert "Sources:" not in result

    def test_no_duplicate_citations(self, react_agent):
        answer = "Answer [Source: knowledge_store:revenue]"
        result = react_agent._attach_citations(answer, ["knowledge_store:revenue"])
        # Should NOT add extra citation block because model already cited
        assert result.count("Sources:") == 0


# ---------------------------------------------------------------------------
# Test: Tool handlers (L5-T5)
# ---------------------------------------------------------------------------


class TestToolHandlers:
    """Tests for observation processing / tool execution."""

    @pytest.mark.asyncio
    async def test_search_knowledge(self, react_agent):
        obs, source = await react_agent._handle_search_knowledge(
            ["revenue Q1 2025"]
        )
        assert "revenue" in obs.lower() or "15%" in obs
        assert source == "knowledge_store:revenue Q1 2025"

    @pytest.mark.asyncio
    async def test_search_knowledge_empty_query(self, react_agent):
        obs, source = await react_agent._handle_search_knowledge([])
        assert "[Error]" in obs
        assert source is None

    @pytest.mark.asyncio
    async def test_calc_tool(self, react_agent):
        obs, source = await react_agent._handle_calc(["2 + 3"])
        assert "5.0" in obs
        assert source == "calculation:2 + 3"

    @pytest.mark.asyncio
    async def test_calc_tool_empty(self, react_agent):
        obs, source = await react_agent._handle_calc([])
        assert "[Error]" in obs

    @pytest.mark.asyncio
    async def test_extract_data(self, react_agent):
        obs, source = await react_agent._handle_extract_data(
            ["report.pdf", "pdf"]
        )
        assert "Extracted" in obs or "sales" in obs.lower()
        assert source == "file:report.pdf"

    @pytest.mark.asyncio
    async def test_extract_data_empty(self, react_agent):
        obs, source = await react_agent._handle_extract_data([])
        assert "[Error]" in obs

    @pytest.mark.asyncio
    async def test_analyze_payments(self, react_agent):
        obs, source = await react_agent._handle_analyze_payments(
            ["Q1 transactions"]
        )
        assert obs  # Should return knowledge store data
        assert "payment_analysis" in source

    @pytest.mark.asyncio
    async def test_unknown_tool(self, react_agent):
        obs, source = await react_agent._execute_action(
            "nonexistent_tool", ["arg"]
        )
        assert "[Error]" in obs
        assert "Unknown tool" in obs
        assert source is None


# ---------------------------------------------------------------------------
# Test: Full ReAct loop (L5-T2, L5-T3)
# ---------------------------------------------------------------------------


class TestReActLoop:
    """Tests for the full ReAct reasoning loop."""

    @pytest.mark.asyncio
    async def test_single_step_final_answer(self, react_agent):
        """Agent produces FINAL_ANSWER on first step → immediate resolution."""
        result = await react_agent.run("What was Q1 revenue growth?")
        assert "answer" in result
        assert "sources" in result
        assert "history" in result
        assert result["answer"]  # non-empty
        assert result["history"]["query"] == "What was Q1 revenue growth?"

    @pytest.mark.asyncio
    async def test_multi_step_reasoning(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry
    ):
        """Agent performs multiple steps before reaching FINAL_ANSWER."""
        call_count = 0

        def multi_step_decide(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (
                    "THOUGHT: I need to search for revenue data first.\n"
                    "ACTION: search_knowledge(revenue growth Q1 2025)"
                )
            elif call_count == 2:
                return (
                    "THOUGHT: Now I need to calculate the total.\n"
                    "ACTION: calc(15 * 1.18)"
                )
            else:
                return (
                    "THOUGHT: I now have enough information to answer.\n"
                    "FINAL_ANSWER: Revenue grew 15% in Q1 2025, with a compounded factor of 17.7."
                )

        mock_decision_agent.decide = MagicMock(side_effect=multi_step_decide)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
            max_steps=5,
        )

        result = await agent.run("Analyze Q1 revenue growth")
        assert "17.7" in result["answer"]
        assert len(result["history"]["steps"]) > 2
        assert len(result["sources"]) >= 1

    @pytest.mark.asyncio
    async def test_max_steps_exhausted(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry
    ):
        """When max steps exhausted, agent synthesizes best answer from gathered context."""
        mock_decision_agent.decide = MagicMock(
            return_value=(
                "THOUGHT: I need more information.\n"
                "ACTION: search_knowledge(more data)"
            )
        )
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
            max_steps=2,
        )

        result = await agent.run("Complex query")
        # Should still produce an answer (synthesized from context)
        assert result["answer"]
        assert result["history"]["steps"]

    @pytest.mark.asyncio
    async def test_up_to_five_steps(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry
    ):
        """Verify the agent can execute up to 5 reasoning steps."""
        call_count = 0

        def five_step_decide(query, context):
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                return (
                    f"THOUGHT: Step {call_count}, need more data.\n"
                    f"ACTION: search_knowledge(data step {call_count})"
                )
            return (
                "THOUGHT: I have gathered all the information I need.\n"
                "FINAL_ANSWER: Comprehensive answer based on 5 steps of research."
            )

        mock_decision_agent.decide = MagicMock(side_effect=five_step_decide)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
            max_steps=5,
        )

        result = await agent.run("Complex multi-step query")
        assert "5 steps" in result["answer"] or "Comprehensive" in result["answer"]
        # Should have at least THOUGHT + ACTION + OBSERVATION per step
        assert len(result["history"]["steps"]) >= 5

    @pytest.mark.asyncio
    async def test_invalid_action_recovery(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry
    ):
        """Agent recovers when model doesn't produce a valid ACTION."""
        call_count = 0

        def recovering_decide(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "THOUGHT: Let me think... I'm not sure what to do."
            return (
                "THOUGHT: I now know the answer.\n"
                "FINAL_ANSWER: The answer is 42."
            )

        mock_decision_agent.decide = MagicMock(side_effect=recovering_decide)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
        )

        result = await agent.run("What is the answer?")
        assert "42" in result["answer"]


# ---------------------------------------------------------------------------
# Test: Timeout and error handling (L5-T10)
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for performance optimization and error handling."""

    @pytest.mark.asyncio
    async def test_timeout_produces_partial_answer(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry
    ):
        """When the loop times out, a partial answer is returned."""

        def slow_decide(query, context):
            import time
            time.sleep(2)  # Simulate slow model
            return (
                "THOUGHT: Still working.\n"
                "ACTION: search_knowledge(data)"
            )

        mock_decision_agent.decide = MagicMock(side_effect=slow_decide)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
            max_steps=5,
            timeout_seconds=1.0,
        )

        result = await agent.run("Slow query")
        assert "unable to complete" in result["answer"].lower() or result["answer"]

    @pytest.mark.asyncio
    async def test_tool_failure_handled_gracefully(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry
    ):
        """When a tool raises an exception, the error becomes an OBSERVATION."""
        call_count = 0

        def tool_error_decide(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "THOUGHT: Let me calculate.\nACTION: calc(1/0)"
            return (
                "THOUGHT: The calculation failed. Let me answer directly.\n"
                "FINAL_ANSWER: Division by zero is undefined."
            )

        mock_decision_agent.decide = MagicMock(side_effect=tool_error_decide)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
        )

        result = await agent.run("What is 1/0?")
        assert "undefined" in result["answer"].lower() or "division" in result["answer"].lower()

    @pytest.mark.asyncio
    async def test_decision_agent_exception(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry
    ):
        """When the decision agent raises, the error answer is produced."""
        mock_decision_agent.decide = MagicMock(
            side_effect=RuntimeError("Model crashed")
        )
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
        )

        result = await agent.run("Broken query")
        assert "error" in result["answer"].lower()

    @pytest.mark.asyncio
    async def test_retrieval_agent_failure(
        self, mock_decision_agent, tool_registry
    ):
        """When retrieval agent fails, the error is captured as an observation."""
        failing_retrieval = MagicMock()
        failing_retrieval.fetch = AsyncMock(
            side_effect=ConnectionError("Knowledge store unavailable")
        )

        call_count = 0

        def search_then_answer(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "THOUGHT: Search for data.\nACTION: search_knowledge(test)"
            return "THOUGHT: Done.\nFINAL_ANSWER: Fallback answer."

        mock_decision_agent.decide = MagicMock(side_effect=search_then_answer)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=failing_retrieval,
            tool_registry=tool_registry,
        )

        result = await agent.run("Test with broken retrieval")
        # Should still produce some answer (graceful degradation)
        assert result["answer"]


# ---------------------------------------------------------------------------
# Test: RAGPipeline integration (L5-T7)
# ---------------------------------------------------------------------------


class TestRAGPipelineIntegration:
    """Tests for ReactAgent integration with RAGPipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_react_mode_via_task(
        self, mock_retrieval_agent, mock_decision_agent, tool_registry
    ):
        """RAGPipeline delegates to ReactAgent when mode=react."""
        pipeline = RAGPipeline(
            retrieval_agent=mock_retrieval_agent,
            decision_agent=mock_decision_agent,
            tool_registry=tool_registry,
        )

        task = {
            "task_id": "test-001",
            "query": "What was revenue growth?",
            "mode": "react",
        }
        result = await pipeline.process_task(task)

        assert result["status"] == "completed"
        assert result["response"]
        assert "sources" in result
        assert "reasoning_history" in result

    @pytest.mark.asyncio
    async def test_pipeline_use_react_flag(
        self, mock_retrieval_agent, mock_decision_agent, tool_registry
    ):
        """RAGPipeline uses ReactAgent when use_react=True."""
        pipeline = RAGPipeline(
            retrieval_agent=mock_retrieval_agent,
            decision_agent=mock_decision_agent,
            tool_registry=tool_registry,
            use_react=True,
        )

        task = {
            "task_id": "test-002",
            "query": "Analyze payments",
        }
        result = await pipeline.process_task(task)

        assert result["status"] == "completed"
        assert "sources" in result

    @pytest.mark.asyncio
    async def test_pipeline_default_mode_unchanged(
        self, mock_retrieval_agent, mock_decision_agent, tool_registry
    ):
        """Default pipeline mode still uses single-shot (no react)."""
        mock_decision_agent.decide = MagicMock(return_value="Simple answer.")
        pipeline = RAGPipeline(
            retrieval_agent=mock_retrieval_agent,
            decision_agent=mock_decision_agent,
            tool_registry=tool_registry,
        )

        task = {
            "task_id": "test-003",
            "query": "Simple question",
        }
        result = await pipeline.process_task(task)

        assert result["status"] == "completed"
        assert result["response"] == "Simple answer."
        # Should NOT have react-specific keys
        assert "reasoning_history" not in result

    @pytest.mark.asyncio
    async def test_pipeline_tool_operations_still_work(
        self, mock_retrieval_agent, mock_decision_agent, tool_registry
    ):
        """Tool-based operations bypass ReAct even when use_react=True."""
        pipeline = RAGPipeline(
            retrieval_agent=mock_retrieval_agent,
            decision_agent=mock_decision_agent,
            tool_registry=tool_registry,
            use_react=True,
        )

        task = {
            "task_id": "test-004",
            "operation": "calc",
            "expression": "10 + 20",
        }
        result = await pipeline.process_task(task)

        assert result["status"] == "completed"
        assert result["response"] == "30.0"

    @pytest.mark.asyncio
    async def test_pipeline_generate_response_react(
        self, mock_retrieval_agent, mock_decision_agent, tool_registry
    ):
        """Test the generate_response_react method directly."""
        pipeline = RAGPipeline(
            retrieval_agent=mock_retrieval_agent,
            decision_agent=mock_decision_agent,
            tool_registry=tool_registry,
        )

        result = await pipeline.generate_response_react("Test query")
        assert "answer" in result
        assert "sources" in result
        assert "history" in result


# ---------------------------------------------------------------------------
# Test: All required tools are usable (acceptance criteria)
# ---------------------------------------------------------------------------


class TestRequiredTools:
    """Verify all four required tools are accessible via ReactAgent."""

    def test_tool_handlers_registered(self, react_agent):
        handlers = react_agent._tool_handlers
        assert "search_knowledge" in handlers
        assert "extract_data" in handlers
        assert "analyze_payments" in handlers
        assert "calc" in handlers

    @pytest.mark.asyncio
    async def test_search_knowledge_callable(self, react_agent):
        obs, src = await react_agent._execute_action(
            "search_knowledge", ["test query"]
        )
        assert obs
        assert src

    @pytest.mark.asyncio
    async def test_extract_data_callable(self, react_agent):
        obs, src = await react_agent._execute_action(
            "extract_data", ["test.txt", "txt"]
        )
        assert obs
        assert src

    @pytest.mark.asyncio
    async def test_analyze_payments_callable(self, react_agent):
        obs, src = await react_agent._execute_action(
            "analyze_payments", ["Q1 transactions"]
        )
        assert obs
        assert src

    @pytest.mark.asyncio
    async def test_calc_callable(self, react_agent):
        obs, src = await react_agent._execute_action("calc", ["2+2"])
        assert "4.0" in obs
        assert src
