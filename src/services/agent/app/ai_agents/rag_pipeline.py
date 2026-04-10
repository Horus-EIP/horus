"""
rag_pipeline.py
---------------
This module defines the RAGPipeline class, which integrates knowledge retrieval and decision-making into a single pipeline.
It is designed for use by a MAS Orchestrator to process tasks.

The pipeline now supports an optional ReAct reasoning mode that enables
multi-step THOUGHT → ACTION → OBSERVATION loops for complex queries.
"""

import logging
from typing import Dict, Any, Optional

from ai_agents.knowledge_retrieval_agent import KnowledgeRetrievalAgent
from ai_agents.decision_making_agent import DecisionMakingAgent
from ai_agents.tool_registry import ToolRegistry
from ai_agents.calculator_tool import CalculatorTool
from ai_agents.file_parser_tool import FileParserTool
from ai_agents.summarizer_tool import SummarizerTool

logger = logging.getLogger(__name__)

from ai_agents.data_extractor_tool import DataExtractorTool
from ai_agents.payment_analyzer_tool import PaymentAnalyzerTool

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
        tool_registry: Optional[ToolRegistry] = None,
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

    async def generate_response(self, query: str) -> str:
        """
        Generate a response by retrieving and processing data (async).

        Args:
            query: The user query string.

        Returns:
            A formatted response string with insights.
        """
        import asyncio
        import os

        timeout = float(os.getenv("REACT_TIMEOUT_SECONDS", "120"))

        data = await self.retrieval_agent.fetch(query)
        context_text = data.get("data", "")

        try:
            insight = await asyncio.wait_for(
                asyncio.to_thread(
                    self.decision_agent.decide,
                    query=query,
                    context=context_text,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Single-shot LLM inference timed out after %.0fs for query: %r",
                timeout,
                query[:120],
            )
            insight = (
                "The model took too long to respond. "
                "Try a shorter question or ask an administrator to increase REACT_TIMEOUT_SECONDS."
            )

        return insight

    async def generate_response_react(self, query: str) -> Dict[str, Any]:
        """
        Generate a response using the ReAct multi-step reasoning loop.

        Args:
            query: The user query string.

        Returns:
            Dict with keys ``answer``, ``sources``, ``history``.
        """
        return await self.react_agent.run(query)

    async def process_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
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

        # Determine whether to use ReAct mode
        task_mode = (task.get("mode") or "").lower().strip()
        should_react = self.use_react or task_mode == "react"

        if should_react:
            logger.info(f"Using ReAct reasoning for query: {query!r}")
            result = await self.generate_response_react(query)
            return {
                "task_id": task.get("task_id"),
                "response": result["answer"],
                "sources": result.get("sources", []),
                "reasoning_history": result.get("history"),
                "status": "completed",
            }

        # Default single-shot mode
        response_text = await self.generate_response(query)
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
