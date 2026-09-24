"""
test_delegation_integration.py
------------------------------
Integration tests for the agent delegation system.

Covers:
    - ReAct agent delegation flow (end-to-end with mocks)
    - Delegation results returning to original agent
    - Delegation loop prevention
    - Timeout handling for delegations
    - DelegationHandler integration with ReAct agent
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from ai_agents.calculator_tool import CalculatorTool
from ai_agents.delegation_handler import DelegationHandler
from ai_agents.rag_pipeline import RAGPipeline
from ai_agents.react_agent import (
    TOOL_DESCRIPTIONS,
    ReactAgent,
    StepType,
)
from ai_agents.tool_registry import ToolRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_retrieval_agent():
    agent = MagicMock()
    agent.fetch = AsyncMock(
        return_value={
            "query": "test",
            "data": "Revenue data: Q1 grew 15%, Q2 grew 12%.",
        }
    )
    return agent


@pytest.fixture
def mock_decision_agent():
    agent = MagicMock()
    agent.decide = MagicMock(
        return_value=(
            "THOUGHT: I have enough information.\n"
            "FINAL_ANSWER: Revenue grew 15% in Q1."
        )
    )
    return agent


@pytest.fixture
def tool_registry():
    registry = ToolRegistry()
    registry.register(CalculatorTool(), aliases=["calc", "calculator"])
    mock_parse = MagicMock()
    mock_parse.name = "parse_file"
    mock_parse.run = MagicMock(return_value="Extracted data")
    registry.register(mock_parse, aliases=["parse", "file_parse", "file"])
    return registry


@pytest.fixture
def mock_delegation_handler():
    handler = MagicMock(spec=DelegationHandler)
    handler.delegate = MagicMock(return_value={
        "status": "completed",
        "result": "Calculated total: $600",
        "agent_id": "agent-analyst",
        "delegation_id": "del-test-123",
    })
    handler.get_history = MagicMock(return_value=[])
    handler.reset_chain = MagicMock()
    return handler


@pytest.fixture
def react_agent_with_delegation(
    mock_decision_agent, mock_retrieval_agent, tool_registry, mock_delegation_handler
):
    return ReactAgent(
        decision_agent=mock_decision_agent,
        retrieval_agent=mock_retrieval_agent,
        tool_registry=tool_registry,
        max_steps=5,
        timeout_seconds=10.0,
        delegation_handler=mock_delegation_handler,
    )


# ---------------------------------------------------------------------------
# Test: Delegate tool is registered
# ---------------------------------------------------------------------------

class TestDelegateToolRegistration:
    def test_delegate_in_tool_descriptions(self):
        assert "delegate" in TOOL_DESCRIPTIONS

    def test_delegate_handler_registered(self, react_agent_with_delegation):
        assert "delegate" in react_agent_with_delegation._tool_handlers

    def test_delegate_in_system_prompt(self):
        assert "delegate" in TOOL_DESCRIPTIONS
        assert "agent type" in TOOL_DESCRIPTIONS["delegate"].lower()


# ---------------------------------------------------------------------------
# Test: Agent can delegate to another agent type
# ---------------------------------------------------------------------------

class TestAgentDelegation:
    @pytest.mark.asyncio
    async def test_delegation_in_react_loop(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry,
        mock_delegation_handler
    ):
        """Full ReAct loop: agent delegates then produces final answer."""
        call_count = 0

        def decide_with_delegation(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (
                    "THOUGHT: I found financial data but need calculations.\n"
                    "ACTION: delegate(analyst, Calculate total payments from this data)"
                )
            return (
                "THOUGHT: I now have the calculation result.\n"
                "FINAL_ANSWER: The total payments amount to $600."
            )

        mock_decision_agent.decide = MagicMock(side_effect=decide_with_delegation)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
            delegation_handler=mock_delegation_handler,
        )

        result = await agent.run("What are the total payments?")

        assert "$600" in result["answer"]
        mock_delegation_handler.delegate.assert_called_once()
        assert len(result["history"]["steps"]) >= 3

    @pytest.mark.asyncio
    async def test_delegation_result_used_in_reasoning(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry,
        mock_delegation_handler
    ):
        """Delegation result is incorporated into the reasoning trace."""
        call_count = 0

        def decide_with_delegation(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (
                    "THOUGHT: I need expert analysis.\n"
                    "ACTION: delegate(analyst, Analyze payment trends)"
                )
            assert "Calculated total" in context or "600" in context
            return (
                "THOUGHT: The analyst provided the result.\n"
                "FINAL_ANSWER: Payment analysis shows a total of $600."
            )

        mock_decision_agent.decide = MagicMock(side_effect=decide_with_delegation)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
            delegation_handler=mock_delegation_handler,
        )

        result = await agent.run("Analyze payments")
        assert result["answer"]
        assert "delegation:analyst" in result["sources"]


# ---------------------------------------------------------------------------
# Test: Delegation results return to original agent
# ---------------------------------------------------------------------------

class TestDelegationResults:
    @pytest.mark.asyncio
    async def test_delegation_result_in_history(
        self, react_agent_with_delegation, mock_decision_agent, mock_delegation_handler
    ):
        call_count = 0

        def decide_fn(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "THOUGHT: Delegate.\nACTION: delegate(analyst, Calculate)"
            return "THOUGHT: Done.\nFINAL_ANSWER: Result received."

        mock_decision_agent.decide = MagicMock(side_effect=decide_fn)

        result = await react_agent_with_delegation.run("Test delegation")
        steps = result["history"]["steps"]
        observation_steps = [s for s in steps if s["type"] == "OBSERVATION"]
        assert any("Calculated total" in s["content"] for s in observation_steps)


# ---------------------------------------------------------------------------
# Test: Delegation loops prevented
# ---------------------------------------------------------------------------

class TestDelegationLoopPrevention:
    @pytest.mark.asyncio
    async def test_delegation_fails_when_handler_reports_depth_limit(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry
    ):
        handler = MagicMock(spec=DelegationHandler)
        handler.delegate = MagicMock(return_value={
            "status": "error",
            "error": "Maximum delegation depth (5) reached.",
        })

        call_count = 0

        def decide_fn(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "THOUGHT: Delegate.\nACTION: delegate(analyst, Task)"
            return "THOUGHT: Delegation failed.\nFINAL_ANSWER: Unable to delegate."

        mock_decision_agent.decide = MagicMock(side_effect=decide_fn)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
            delegation_handler=handler,
        )

        result = await agent.run("Deep delegation")
        steps = result["history"]["steps"]
        observation_steps = [s for s in steps if s["type"] == "OBSERVATION"]
        assert any("failed" in s["content"].lower() or "depth" in s["content"].lower()
                    for s in observation_steps)


# ---------------------------------------------------------------------------
# Test: Timeout handling for delegations
# ---------------------------------------------------------------------------

class TestDelegationTimeout:
    @pytest.mark.asyncio
    async def test_delegation_timeout_handled(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry
    ):
        handler = MagicMock(spec=DelegationHandler)
        handler.delegate = MagicMock(return_value={
            "status": "timeout",
            "error": "Delegation timed out after 30s",
        })

        call_count = 0

        def decide_fn(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "THOUGHT: Delegate.\nACTION: delegate(analyst, Slow task)"
            return "THOUGHT: Delegation timed out. I'll answer directly.\nFINAL_ANSWER: Fallback answer."

        mock_decision_agent.decide = MagicMock(side_effect=decide_fn)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
            delegation_handler=handler,
        )

        result = await agent.run("Task with timeout")
        assert "Fallback" in result["answer"]


# ---------------------------------------------------------------------------
# Test: Delegation without handler configured
# ---------------------------------------------------------------------------

class TestDelegationWithoutHandler:
    @pytest.mark.asyncio
    async def test_delegate_without_handler(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry
    ):
        """When no delegation handler is set, delegate action returns an error."""
        call_count = 0

        def decide_fn(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "THOUGHT: Delegate.\nACTION: delegate(analyst, Task)"
            return "THOUGHT: Can't delegate.\nFINAL_ANSWER: No delegation available."

        mock_decision_agent.decide = MagicMock(side_effect=decide_fn)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
        )

        result = await agent.run("Try to delegate")
        steps = result["history"]["steps"]
        observation_steps = [s for s in steps if s["type"] == "OBSERVATION"]
        assert any("not available" in s["content"].lower() for s in observation_steps)


# ---------------------------------------------------------------------------
# Test: Context chain propagated through delegation
# ---------------------------------------------------------------------------

class TestDelegationContextPropagation:
    @pytest.mark.asyncio
    async def test_incoming_context_forwarded_to_handler(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry,
        mock_delegation_handler
    ):
        """When _incoming_delegation_context is set, it is passed through to
        the delegation handler so the next agent receives all prior context."""
        call_count = 0

        def decide_fn(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "THOUGHT: Delegate.\nACTION: delegate(analyst, Crunch numbers)"
            return "THOUGHT: Done.\nFINAL_ANSWER: Result."

        mock_decision_agent.decide = MagicMock(side_effect=decide_fn)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
            delegation_handler=mock_delegation_handler,
        )

        prior_ctx = [
            {"agent_id": "agent-1", "request": "Search data", "data": {"q": "x"}},
            {"agent_id": "agent-2", "request": "Filter data", "data": {}},
        ]
        agent._incoming_delegation_context = prior_ctx

        await agent.run("Do analysis")

        mock_delegation_handler.delegate.assert_called_once()
        call_args = mock_delegation_handler.delegate.call_args
        forwarded_ctx = call_args[0][4] if len(call_args[0]) > 4 else call_args[1].get("delegation_context")
        assert forwarded_ctx == prior_ctx

    @pytest.mark.asyncio
    async def test_no_context_when_not_set(
        self, mock_decision_agent, mock_retrieval_agent, tool_registry,
        mock_delegation_handler
    ):
        """When _incoming_delegation_context is None, handler receives None."""
        call_count = 0

        def decide_fn(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "THOUGHT: Delegate.\nACTION: delegate(analyst, Task)"
            return "THOUGHT: Done.\nFINAL_ANSWER: Result."

        mock_decision_agent.decide = MagicMock(side_effect=decide_fn)
        agent = ReactAgent(
            decision_agent=mock_decision_agent,
            retrieval_agent=mock_retrieval_agent,
            tool_registry=tool_registry,
            delegation_handler=mock_delegation_handler,
        )

        await agent.run("Simple delegation")

        call_args = mock_delegation_handler.delegate.call_args
        forwarded_ctx = call_args[0][4] if len(call_args[0]) > 4 else call_args[1].get("delegation_context")
        assert forwarded_ctx is None


# ---------------------------------------------------------------------------
# Test: RAGPipeline integration with delegation
# ---------------------------------------------------------------------------

class TestRAGPipelineDelegation:
    @pytest.mark.asyncio
    async def test_pipeline_react_mode_with_delegation(
        self, mock_retrieval_agent, mock_decision_agent, tool_registry,
        mock_delegation_handler
    ):
        """RAGPipeline in react mode supports delegation via the ReactAgent."""
        mock_decision_agent.decide = MagicMock(
            return_value=(
                "THOUGHT: I have enough information.\n"
                "FINAL_ANSWER: Answer with delegation support."
            )
        )

        pipeline = RAGPipeline(
            retrieval_agent=mock_retrieval_agent,
            decision_agent=mock_decision_agent,
            tool_registry=tool_registry,
        )

        # Inject delegation handler into the react agent
        pipeline.react_agent.delegation_handler = mock_delegation_handler

        task = {
            "task_id": "test-del-001",
            "query": "Test delegation pipeline",
            "mode": "react",
        }
        result = await pipeline.process_task(task)
        assert result["status"] == "completed"
        assert result["response"]
