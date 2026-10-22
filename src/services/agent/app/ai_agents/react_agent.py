"""ReAct (Reasoning + Acting) agent with a THOUGHT → ACTION → OBSERVATION loop.

Calls registered tools (``search_knowledge``, ``extract_data``,
``analyze_payments``, ``calc``, ``delegate``) and cites sources in every answer.
See ``docs/architecture.md`` for the walkthrough.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ai_agents.agent_tools import (
    ANALYZE_PAYMENTS,
    CALC,
    DELEGATE,
    EXTRACT_DATA,
    SEARCH_KNOWLEDGE,
    tool_definitions_block,
)

logger = logging.getLogger(__name__)

REACT_STEP_CALL = "react_step"

# --- Constants ---
MAX_REACT_STEPS = 5
# Configurable via REACT_TIMEOUT_SECONDS env var — default raised to 120s so
# GPU inference of up to 1024 tokens has time to complete within one ReAct step.
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("REACT_TIMEOUT_SECONDS", "120"))

# --- ReAct prompt templates  (L5-T1) ---

SYSTEM_PROMPT = (
    "You are an advanced reasoning agent. You solve problems step-by-step "
    "using the THOUGHT / ACTION / OBSERVATION pattern.\n\n"
    "Available tools:\n"
    "{tool_descriptions}\n\n"
    "Response format – follow EXACTLY:\n"
    "THOUGHT: <your reasoning about what to do next>\n"
    "ACTION: <tool_name>(param1, param2, ...)\n"
    "... wait for OBSERVATION ...\n\n"
    "When you have enough information to answer, respond with:\n"
    "THOUGHT: I now have enough information to answer.\n"
    "FINAL_ANSWER: <your answer here>\n\n"
    "Rules:\n"
    "- Always start with a THOUGHT.\n"
    "- Only call ONE action per step.\n"
    "- You MUST cite sources in your FINAL_ANSWER using [Source: <origin>] notation.\n"
    "- Write FINAL_ANSWER in Markdown for readability: use a short ## title, "
    "**bold** for key terms, bullet lists for multiple points, and short paragraphs. "
    "Avoid a single dense wall of text.\n"
    "- Maximum {max_steps} reasoning steps.\n"
)

STEP_PROMPT = "{history}\nOBSERVATION: {observation}\nContinue reasoning.\n"


def react_system_prompt(tool_names: Sequence[str], max_steps: int) -> str:
    return SYSTEM_PROMPT.format(
        tool_descriptions=tool_definitions_block(tool_names),
        max_steps=max_steps,
    )


def react_step_prompt(query: str, reasoning_trace: Sequence[str], step_number: int) -> str:
    sections = [f"User query: {query}"]
    if reasoning_trace:
        sections.append("Reasoning so far:\n" + "\n".join(reasoning_trace))
    sections.append(f"Step {step_number}: Provide your next THOUGHT and ACTION (or FINAL_ANSWER).")
    return "\n\n".join(sections)


# --- Data structures  (L5-T6 – execution history tracking) ---


class StepType(str, Enum):
    THOUGHT = "THOUGHT"
    ACTION = "ACTION"
    OBSERVATION = "OBSERVATION"
    FINAL_ANSWER = "FINAL_ANSWER"
    DELEGATION = "DELEGATION"


@dataclass
class ReActStep:
    """One step in the ReAct reasoning trace."""

    step_number: int
    step_type: StepType
    content: str
    tool_name: str | None = None
    tool_args: list[str] | None = None
    duration_ms: float | None = None
    source: str | None = None


@dataclass
class ExecutionHistory:
    """Complete execution history for a single query."""

    query: str
    steps: list[ReActStep] = field(default_factory=list)
    final_answer: str | None = None
    total_duration_ms: float = 0.0
    sources: list[str] = field(default_factory=list)

    def add_step(self, step: ReActStep) -> None:
        self.steps.append(step)
        if step.source and step.source not in self.sources:
            self.sources.append(step.source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "steps": [
                {
                    "step_number": s.step_number,
                    "type": s.step_type.value,
                    "content": s.content,
                    "tool_name": s.tool_name,
                    "tool_args": s.tool_args,
                    "duration_ms": s.duration_ms,
                    "source": s.source,
                }
                for s in self.steps
            ],
            "final_answer": self.final_answer,
            "total_duration_ms": self.total_duration_ms,
            "sources": self.sources,
        }


# --- ReactAgent  (L5-T2) ---


class ReactAgent:
    """
    Multi-step ReAct reasoning agent.

    Orchestrates a THOUGHT → ACTION → OBSERVATION loop using a decision model
    for thought generation and a tool registry for action execution.
    """

    def __init__(
        self,
        decision_agent,
        retrieval_agent,
        tool_registry,
        *,
        max_steps: int = MAX_REACT_STEPS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        delegation_handler=None,
    ):
        """
        Args:
            decision_agent: DecisionMakingAgent used for thought generation.
            retrieval_agent: KnowledgeRetrievalAgent for knowledge search.
            tool_registry: ToolRegistry with registered tools.
            max_steps: Maximum number of ReAct reasoning steps (default 5).
            timeout_seconds: Hard timeout for the entire reasoning loop.
            delegation_handler: Optional DelegationHandler for delegating to other agents.
        """
        self.decision_agent = decision_agent
        self.retrieval_agent = retrieval_agent
        self.tool_registry = tool_registry
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.delegation_handler = delegation_handler

        # Accumulated delegation context from upstream agents (set by caller)
        self._incoming_delegation_context: list[dict[str, Any]] | None = None

        # Map of tool names → callables used inside the ReAct loop
        self._tool_handlers = self._build_tool_handlers()

    # --- Public API ---

    async def run(self, query: str) -> dict[str, Any]:
        """
        Execute the full ReAct loop for a user query.

        Returns:
            Dict with keys: ``answer``, ``sources``, ``history``.
        """
        history = ExecutionHistory(query=query)
        start = time.perf_counter()

        try:
            answer = await asyncio.wait_for(
                self._react_loop(query, history),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            logger.warning(
                f"ReAct loop timed out after {self.timeout_seconds}s for query: {query!r}"
            )
            answer = self._build_timeout_answer(history)
        except Exception as exc:
            logger.error(f"ReAct loop error: {exc}", exc_info=True)
            answer = self._build_error_answer(history, exc)

        elapsed_ms = (time.perf_counter() - start) * 1000
        history.total_duration_ms = elapsed_ms
        history.final_answer = answer

        logger.info(
            f"ReAct completed: steps={len(history.steps)}, "
            f"duration={elapsed_ms:.1f}ms, sources={history.sources}"
        )

        return {
            "answer": answer,
            "sources": history.sources,
            "history": history.to_dict(),
        }

    # --- Core ReAct loop ---

    async def _react_loop(self, query: str, history: ExecutionHistory) -> str:
        """
        Execute the iterative THOUGHT → ACTION → OBSERVATION loop.
        """
        context_parts: list[str] = []
        reasoning_trace: list[str] = []

        for step_num in range(1, self.max_steps + 1):
            # ---------- THOUGHT generation  (L5-T3) ----------
            thought, is_final, final_text = await self._generate_thought(
                query, reasoning_trace, step_num
            )

            history.add_step(
                ReActStep(
                    step_number=step_num,
                    step_type=StepType.THOUGHT,
                    content=thought,
                )
            )
            reasoning_trace.append(f"THOUGHT: {thought}")

            if is_final:
                answer = self._attach_citations(final_text, history.sources)
                return answer

            # ---------- ACTION selection & parsing  (L5-T4) ----------
            tool_name, tool_args = self._parse_action(thought)
            if tool_name is None:
                # Model didn't produce a valid action; nudge it
                reasoning_trace.append(
                    "OBSERVATION: [System] No valid action detected. "
                    "Please specify an ACTION using the format: ACTION: tool_name(args)"
                )
                continue

            history.add_step(
                ReActStep(
                    step_number=step_num,
                    step_type=StepType.ACTION,
                    content=f"{tool_name}({', '.join(tool_args)})",
                    tool_name=tool_name,
                    tool_args=tool_args,
                )
            )
            reasoning_trace.append(f"ACTION: {tool_name}({', '.join(tool_args)})")

            # ---------- OBSERVATION processing  (L5-T5) ----------
            observation, source = await self._execute_action(tool_name, tool_args)

            obs_step = ReActStep(
                step_number=step_num,
                step_type=StepType.OBSERVATION,
                content=observation,
                tool_name=tool_name,
                source=source,
            )
            history.add_step(obs_step)

            reasoning_trace.append(f"OBSERVATION: {observation}")
            context_parts.append(observation)

        # Exhausted max steps – synthesize the best answer we can
        return self._build_exhausted_answer(query, context_parts, history)

    # --- L5-T3 – Thought generation ---

    async def _generate_thought(
        self,
        query: str,
        reasoning_trace: list[str],
        step_number: int,
    ) -> tuple[str, bool, str]:
        """
        Generate the next THOUGHT using the decision model.

        Returns:
            (thought_text, is_final_answer, final_answer_text)
        """
        raw = await asyncio.to_thread(
            self.decision_agent.reason,
            query,
            react_step_prompt(query, reasoning_trace, step_number),
            react_system_prompt(self.tool_names(), self.max_steps),
            call=REACT_STEP_CALL,
        )

        # Parse for FINAL_ANSWER
        final_match = re.search(r"FINAL_ANSWER:\s*(.+)", raw, re.DOTALL | re.IGNORECASE)
        if final_match:
            return raw.strip(), True, final_match.group(1).strip()

        return raw.strip(), False, ""

    # --- L5-T4 – Action selection & response parsing ---

    def _parse_action(self, thought_text: str) -> tuple[str | None, list[str]]:
        """
        Parse an ACTION line from the model output.

        Expected format:
            ACTION: tool_name(arg1, arg2, ...)

        Returns:
            (tool_name, [arg1, arg2, ...])  or  (None, []) if no valid action.
        """
        # Try structured format first
        match = re.search(r"ACTION:\s*(\w+)\(([^)]*)\)", thought_text, re.IGNORECASE)
        if match:
            tool_name = match.group(1).strip().lower()
            raw_args = match.group(2).strip()
            args = self._parse_args(raw_args)
            return tool_name, args

        # Fallback: ACTION: tool_name arg1
        match2 = re.search(r"ACTION:\s*(\w+)\s+(.*)", thought_text, re.IGNORECASE)
        if match2:
            tool_name = match2.group(1).strip().lower()
            args = [match2.group(2).strip()] if match2.group(2).strip() else []
            return tool_name, args

        return None, []

    @staticmethod
    def _parse_args(raw: str) -> list[str]:
        """Split comma-separated args, stripping quotes and whitespace."""
        if not raw:
            return []
        parts = []
        for part in raw.split(","):
            cleaned = part.strip().strip("'\"")
            if cleaned:
                parts.append(cleaned)
        return parts

    # --- L5-T5 – Observation processing (action execution) ---

    async def _execute_action(self, tool_name: str, tool_args: list[str]) -> tuple[str, str | None]:
        """
        Execute the selected tool and return (observation_text, source_label).
        """
        start = time.perf_counter()
        tool_names = self.tool_names()
        handler = self._tool_handlers.get(tool_name) if tool_name in tool_names else None

        if handler is None:
            return (
                f"[Error] Unknown tool '{tool_name}'. Available: {', '.join(tool_names)}",
                None,
            )

        try:
            observation, source = await handler(tool_args)
            elapsed = (time.perf_counter() - start) * 1000
            logger.debug(f"Tool '{tool_name}' executed in {elapsed:.1f}ms")
            return observation, source
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                f"Tool '{tool_name}' failed after {elapsed:.1f}ms: {exc}",
                exc_info=True,
            )
            return f"[Error] Tool '{tool_name}' failed: {exc}", None

    # --- Tool handler wrappers ---

    def _build_tool_handlers(self) -> dict[str, Any]:
        """Build a mapping of tool-name → async handler callable."""
        handlers = {
            SEARCH_KNOWLEDGE: self._handle_search_knowledge,
            EXTRACT_DATA: self._handle_extract_data,
            ANALYZE_PAYMENTS: self._handle_analyze_payments,
            CALC: self._handle_calc,
            DELEGATE: self._handle_delegate,
        }
        return handlers

    def tool_names(self) -> tuple[str, ...]:
        try:
            from agent_server.profiles import current_tools

            identity_tools = current_tools.get()
        except Exception:
            identity_tools = None
        if identity_tools is None:
            return tuple(self._tool_handlers)
        return tuple(name for name in identity_tools if name in self._tool_handlers)

    async def _handle_search_knowledge(self, args: list[str]) -> tuple[str, str | None]:
        """Search the knowledge store."""
        query = args[0] if args else ""
        if not query:
            return "[Error] search_knowledge requires a query argument.", None

        data = await self.retrieval_agent.fetch(query)
        text = data.get("data", "")
        if not text:
            return "No relevant information found in the knowledge store.", None
        source = f"knowledge_store:{query}"
        return text, source

    async def _handle_extract_data(self, args: list[str]) -> tuple[str, str | None]:
        """Extract data from a file via the file parser tool."""
        file_ref = args[0] if args else ""
        file_type = args[1] if len(args) > 1 else "txt"
        if not file_ref:
            return "[Error] extract_data requires a file URL or content.", None

        payload = {
            "file_url": file_ref,
            "file_type": file_type,
            "query": file_ref,
        }
        result = await asyncio.to_thread(self.tool_registry.run, "parse", payload)
        source = f"file:{file_ref}"
        return result, source

    async def _handle_analyze_payments(self, args: list[str]) -> tuple[str, str | None]:
        """Analyze payments by searching the knowledge store with a payments focus."""
        query = args[0] if args else "payment analysis"
        payment_query = f"payment analysis: {query}"

        data = await self.retrieval_agent.fetch(payment_query)
        text = data.get("data", "")
        if not text:
            return "No payment data found in the knowledge store.", None
        source = f"payment_analysis:{query}"
        return text, source

    async def _handle_calc(self, args: list[str]) -> tuple[str, str | None]:
        """Evaluate a mathematical expression."""
        expression = args[0] if args else ""
        if not expression:
            return "[Error] calc requires a mathematical expression.", None

        payload = {"expression": expression}
        result = await asyncio.to_thread(self.tool_registry.run, "calc", payload)
        source = f"calculation:{expression}"
        return f"Result: {result}", source

    async def _handle_delegate(self, args: list[str]) -> tuple[str, str | None]:
        """Delegate a sub-task to another agent type."""
        if not args:
            return "[Error] delegate requires at least (to_agent_type, request).", None

        to_agent_type = args[0] if args else ""
        request_text = args[1] if len(args) > 1 else ""

        if not to_agent_type:
            return "[Error] delegate requires a target agent type.", None
        if not request_text:
            return "[Error] delegate requires a request description.", None

        if self.delegation_handler is None:
            return (
                "[Error] Delegation is not available — no delegation handler configured.",
                None,
            )

        result = await asyncio.to_thread(
            self.delegation_handler.delegate,
            to_agent_type,
            request_text,
            None,
            "",
            self._incoming_delegation_context,
        )

        source = f"delegation:{to_agent_type}"

        if result.get("status") == "completed":
            return result.get("result", "No result returned"), source

        error = result.get("error", "Delegation failed")
        return f"[Delegation failed] {error}", source

    # --- L5-T8 – Source citations ---

    def _attach_citations(self, answer: str, sources: list[str]) -> str:
        """Append source citations to the final answer if not already present."""
        if not sources:
            return answer

        # Don't duplicate if the model already cited sources
        if "[Source:" in answer or "[source:" in answer.lower():
            return answer

        citations = "\n\nSources:\n" + "\n".join(
            f"  [{i + 1}] {src}" for i, src in enumerate(sources)
        )
        return answer.rstrip() + citations

    # --- L5-T10 – Fallback / error answers ---

    def _build_timeout_answer(self, history: ExecutionHistory) -> str:
        """Build an answer when the reasoning loop times out."""
        gathered = [
            s.content for s in history.steps if s.step_type == StepType.OBSERVATION and s.content
        ]
        if gathered:
            summary = " ".join(gathered)[:500]
            answer = (
                f"I was unable to complete my full analysis within the time limit, "
                f"but here is what I found so far:\n\n{summary}"
            )
        else:
            answer = (
                "I was unable to complete the analysis within the time limit. "
                "Please try a simpler query or break your question into smaller parts."
            )
        return self._attach_citations(answer, history.sources)

    def _build_error_answer(self, history: ExecutionHistory, exc: Exception) -> str:
        """Build an answer when an unexpected error occurs."""
        answer = (
            "I encountered an error during my analysis. "
            f"Error details: {exc}. "
            "Please try rephrasing your question."
        )
        return self._attach_citations(answer, history.sources)

    def _build_exhausted_answer(
        self,
        query: str,
        context_parts: list[str],
        history: ExecutionHistory,
    ) -> str:
        """
        Build the best possible answer when max steps are exhausted
        by synthesizing gathered context through the decision model.
        """
        if not context_parts:
            return self._attach_citations(
                "I was unable to find enough information to answer your question. "
                "Please try providing more details.",
                history.sources,
            )

        combined_context = "\n\n".join(context_parts)
        try:
            answer = self.decision_agent.decide(
                query=query,
                context=combined_context,
            )
        except Exception:
            answer = "Based on my research, here is what I found:\n\n" + combined_context[:500]

        return self._attach_citations(answer, history.sources)
