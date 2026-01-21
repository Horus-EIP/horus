"""
rag_pipeline.py
---------------
This module defines the RAGPipeline class, which integrates knowledge retrieval and decision-making into a single pipeline.
It is designed for use by a MAS Orchestrator to process tasks.
"""

from typing import Dict, Any, Optional
from ai_agents.knowledge_retrieval_agent import KnowledgeRetrievalAgent
from ai_agents.decision_making_agent import DecisionMakingAgent
from ai_agents.tool_registry import ToolRegistry
from ai_agents.calculator_tool import CalculatorTool
from ai_agents.file_parser_tool import FileParserTool
from ai_agents.summarizer_tool import SummarizerTool


class RAGPipeline:
    """
    Integrates knowledge retrieval and decision-making into a single pipeline.
    """

    def __init__(
        self,
        retrieval_agent: KnowledgeRetrievalAgent,
        decision_agent: DecisionMakingAgent,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        """
        Args:
            retrieval_agent: An instance of KnowledgeRetrievalAgent.
            decision_agent: An instance of DecisionMakingAgent.
        """
        self.retrieval_agent = retrieval_agent
        self.decision_agent = decision_agent
        self.tool_registry = tool_registry or self._build_default_registry()

    async def generate_response(self, query: str) -> str:
        """
        Generate a response by retrieving and processing data (async).

        Args:
            query: The user query string.

        Returns:
            A formatted response string with insights.
        """
        data = await self.retrieval_agent.fetch(query)
        context_text = data.get("data", "")
        # Decision agent is CPU-bound, run in thread pool to not block event loop
        import asyncio
        insight = await asyncio.to_thread(
            self.decision_agent.decide,
            query=query,
            context=context_text
        )
        response = insight
        # Response generated successfully
        return response

    async def process_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a task from the MAS Orchestrator (async).

        Args:
            task: A dict with at least 'task_id' and 'query'.

        Returns:
            A dict containing the task_id, response, and status.
        """
        operation = (task.get("operation") or "").lower().strip()
        if operation and self.tool_registry.has(operation):
            # Tools are CPU-bound, run in thread pool
            import asyncio
            response_text = await asyncio.to_thread(
                self.tool_registry.run,
                operation,
                task
            )
        else:
            query = task.get("query", "")
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
        return registry
