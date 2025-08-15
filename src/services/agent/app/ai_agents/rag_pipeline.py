"""
rag_pipeline.py
---------------
This module defines the RAGPipeline class, which integrates knowledge retrieval and decision-making into a single pipeline.
It is designed for use by a MAS Orchestrator to process tasks.
"""

from typing import Dict, Any
from ai_agents.knowledge_retrieval_agent import KnowledgeRetrievalAgent
from ai_agents.decision_making_agent import DecisionMakingAgent


class RAGPipeline:
    """
    Integrates knowledge retrieval and decision-making into a single pipeline.
    """

    def __init__(self, retrieval_agent: KnowledgeRetrievalAgent, decision_agent: DecisionMakingAgent):
        """
        Args:
            retrieval_agent: An instance of KnowledgeRetrievalAgent.
            decision_agent: An instance of DecisionMakingAgent.
        """
        self.retrieval_agent = retrieval_agent
        self.decision_agent = decision_agent

    def generate_response(self, query: str) -> str:
        """
        Generate a response by retrieving and processing data.

        Args:
            query: The user query string.

        Returns:
            A formatted response string with insights.
        """
        data = self.retrieval_agent.fetch(query)
        context_text = data.get("data", "")
        insight = self.decision_agent.decide(query=query, context=context_text)
        response = insight
        print("[RAGPipeline] Final response generated.")
        return response

    def process_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a task from the MAS Orchestrator.

        Args:
            task: A dict with at least 'task_id' and 'query'.

        Returns:
            A dict containing the task_id, response, and status.
        """
        query = task.get('query', '')
        response_text = self.generate_response(query)
        return {
            "task_id": task.get("task_id"),
            "response": response_text,
            "status": "completed"
        }
