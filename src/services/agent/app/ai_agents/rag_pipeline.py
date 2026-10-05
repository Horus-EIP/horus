"""
rag_pipeline.py
---------------
This module defines the RAGPipeline class, which integrates knowledge retrieval and decision-making into a single pipeline.
It is designed for use by a MAS Orchestrator to process tasks.

The pipeline now supports an optional ReAct reasoning mode that enables
multi-step THOUGHT → ACTION → OBSERVATION loops for complex queries.
"""

import logging
import os
from typing import Any

from ai_agents.calculator_tool import CalculatorTool
from ai_agents.decision_making_agent import DecisionMakingAgent
from ai_agents.file_parser_tool import FileParserTool
from ai_agents.knowledge_retrieval_agent import KnowledgeRetrievalAgent
from ai_agents.step_emitter import emit_step
from ai_agents.summarizer_tool import SummarizerTool
from ai_agents.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

from ai_agents.data_extractor_tool import DataExtractorTool  # noqa: E402
from ai_agents.payment_analyzer_tool import PaymentAnalyzerTool  # noqa: E402

# Cap the embedding/retrieval query. BGE-base truncates at 512 tokens (~2k
# chars), so anything longer is silently dropped by the embedder anyway — and a
# long chain transcript embeds mostly front-matter, not the actual task.
_RETRIEVAL_QUERY_CHAR_CAP = 2000

# Wall-clock budget for a single decide() call. This, not TASK_TIMEOUT, is what
# actually bounds a chat answer, and on expiry the pipeline returns a canned
# string as a *successful* task -- so too low a value reads as a bad answer
# rather than as a timeout. The old flat 120s default was a GPU number: a
# CPU-only worker cannot finish a 4B generation anywhere near it.
# REACT_TIMEOUT_SECONDS still overrides both.
_REACT_TIMEOUT_GPU_DEFAULT = 120.0
_REACT_TIMEOUT_CPU_DEFAULT = 900.0


def _react_timeout(device: object) -> float:
    """Seconds to allow one decide() call, defaulting by device."""
    raw = os.getenv("REACT_TIMEOUT_SECONDS", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            logger.warning("Ignoring non-numeric REACT_TIMEOUT_SECONDS=%r", raw)
    on_cpu = str(device or "").lower().startswith("cpu")
    return _REACT_TIMEOUT_CPU_DEFAULT if on_cpu else _REACT_TIMEOUT_GPU_DEFAULT


class RAGPipeline:
    """
    Integrates knowledge retrieval and decision-making into a single pipeline.

    When ``use_react=True`` (or when the incoming task includes
    ``"mode": "react"``), the pipeline delegates to the ``ReactAgent``
    for multi-step reasoning.  Otherwise the original single-shot
    retrieve-then-decide flow is used.
    """

    def __init__(
        self,
        retrieval_agent: KnowledgeRetrievalAgent,
        decision_agent: DecisionMakingAgent,
        tool_registry: ToolRegistry | None = None,
        *,
        use_react: bool = False,
    ):
        """
        Args:
            retrieval_agent: An instance of KnowledgeRetrievalAgent.
            decision_agent: An instance of DecisionMakingAgent.
            tool_registry: Optional pre-configured ToolRegistry.
            use_react: If True, default to ReAct mode for all queries.
        """
        self.retrieval_agent = retrieval_agent
        self.decision_agent = decision_agent
        self.tool_registry = tool_registry or self._build_default_registry()
        self.use_react = use_react

        # Lazy-initialised ReactAgent (avoids circular imports at module level)
        self._react_agent = None

    # ------------------------------------------------------------------
    # ReactAgent accessor (lazy init)
    # ------------------------------------------------------------------

    @property
    def react_agent(self):
        """Return (and lazily create) the ReactAgent instance."""
        if self._react_agent is None:
            from ai_agents.react_agent import ReactAgent

            self._react_agent = ReactAgent(
                decision_agent=self.decision_agent,
                retrieval_agent=self.retrieval_agent,
                tool_registry=self.tool_registry,
            )
        return self._react_agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_response(
        self,
        query: str,
        retrieval_query: str | None = None,
        attached_context: str | None = None,
    ) -> str:
        """
        Generate a response by retrieving and processing data (async).

        Args:
            query: The user query string (fed to the LLM in full).
            retrieval_query: Optional focused query used ONLY for knowledge
                retrieval. Defaults to ``query``. Lets a multi-agent chain pass
                the bare assigned task for embedding while the LLM still sees the
                full transcript for grounding.

        Returns:
            A formatted response string with insights.
        """
        import asyncio

        timeout = _react_timeout(getattr(self.decision_agent, "device", None))

        from ai_agents.response_cache import current_corpus_version, get_cached, set_cached

        corpus_version = await current_corpus_version()
        if attached_context:
            emit_step(
                "retrieval.results",
                "Using the attached files",
                "Answering from the files attached to this task; the knowledge "
                "store was not searched again.",
                source="attached_files",
            )
            context_text = attached_context
        else:
            rquery = retrieval_query or query
            if len(rquery) > _RETRIEVAL_QUERY_CHAR_CAP:
                rquery = rquery[:_RETRIEVAL_QUERY_CHAR_CAP]
            data = await self.retrieval_agent.fetch(rquery)
            context_text = data.get("data", "")

        # Phase 3: exact-match response cache. Keyed on (query + retrieved
        # context + generation params), so a hit is safe across users and
        # document versions — different retrieval yields a different key — and
        # skips the costly model generation. No-op unless AGENT_RESPONSE_CACHE.
        cached = await get_cached(query, context_text, corpus_version)
        if cached is not None:
            emit_step(
                "cache.hit",
                "Answer served from cache",
                "An identical query over identical retrieved content was already "
                "answered; skipped model generation.",
                source="response_cache",
            )
            return cached

        try:
            insight = await asyncio.wait_for(
                asyncio.to_thread(
                    self.decision_agent.decide,
                    query=query,
                    context=context_text,
                ),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning(
                "Single-shot LLM inference timed out after %.0fs for query: %r",
                timeout,
                query[:120],
            )
            # Do not cache the timeout fallback — it is not a real answer.
            return (
                "The model took too long to respond (no answer within "
                f"{timeout:.0f}s). Try a shorter question, or ask an "
                "administrator to raise REACT_TIMEOUT_SECONDS. On a CPU-only "
                "deployment this is expected for long questions: generation is "
                "many times slower than on a GPU."
            )

        await set_cached(query, context_text, corpus_version, insight)
        return insight

    async def generate_response_react(self, query: str) -> dict[str, Any]:
        """
        Generate a response using the ReAct multi-step reasoning loop.

        Args:
            query: The user query string.

        Returns:
            Dict with keys ``answer``, ``sources``, ``history``.
        """
        return await self.react_agent.run(query)

    async def process_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """
        Process a task from the MAS Orchestrator (async).

        Args:
            task: A dict with at least 'task_id' and 'query'.

        Returns:
            A dict containing the task_id, response, and status.
        """
        operation = (task.get("operation") or "").lower().strip()

        # Check if tool-based operation is requested
        if operation and self.tool_registry.has(operation):
            # Tools are CPU-bound, run in thread pool
            import asyncio
            emit_step(
                "tool.invoke",
                f"Running tool: {operation}",
                f"Dispatching to the '{operation}' tool in the registry.",
                tool=operation,
            )
            response_text = await asyncio.to_thread(
                self.tool_registry.run,
                operation,
                task
            )
            return {
                "task_id": task.get("task_id"),
                "response": response_text,
                "status": "completed",
            }

        query = task.get("query", "")
        # Focused retrieval query (bare assigned task in a chain); falls back to
        # the full query for single-agent / first-step tasks.
        retrieval_query = task.get("retrieval_query") or query

        # Determine whether to use ReAct mode
        task_mode = (task.get("mode") or "").lower().strip()
        should_react = self.use_react or task_mode == "react"

        if should_react:
            logger.info(f"Using ReAct reasoning for query: {query!r}")
            emit_step(
                "reasoning.start",
                "Starting ReAct multi-step reasoning",
                "Switching to the THOUGHT → ACTION → OBSERVATION loop.",
                mode="react",
            )
            result = await self.generate_response_react(query)
            return {
                "task_id": task.get("task_id"),
                "response": result["answer"],
                "sources": result.get("sources", []),
                "reasoning_history": result.get("history"),
                "status": "completed",
            }

        # Default single-shot mode
        attached_context = task.get("attached_context")
        if attached_context:
            response_text = await self.generate_response(
                task.get("demand") or query, attached_context=attached_context
            )
        else:
            response_text = await self.generate_response(
                query, retrieval_query=retrieval_query
            )
        return {
            "task_id": task.get("task_id"),
            "response": response_text,
            "status": "completed",
        }

    def _build_default_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(CalculatorTool(), aliases=["calc", "calculator"])
        registry.register(FileParserTool(), aliases=["parse", "file_parse", "file"],)
        registry.register(SummarizerTool(), aliases=["summary", "summarize_text"])
        registry.register(DataExtractorTool(), aliases=["data_extractor", "extract_data", "data", "extract"])
        registry.register(PaymentAnalyzerTool(), aliases=["payment_analysis", "analyze_payments", "payment_analyzer", "payment", "analyze"])
        return registry
