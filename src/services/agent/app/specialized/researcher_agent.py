import logging

from ai_agents.summarizer_tool import SummarizerTool

logger = logging.getLogger(__name__)

class ResearcherAgent:
    def __init__(self, retrieval_agent):
        self.knowledge_retriever = retrieval_agent
        self.summarizer = SummarizerTool()
        self.type = "researcher"

    async def search(self, query: str):
        relevant_data = await self.knowledge_retriever.fetch(query)

        return relevant_data

    def summarize(self, text: str):
        data = {"text": text}
        summary = self.summarizer.run(data)

        return summary

    async def process_request(self, task_type: str, data: str, extra_parameters: dict = None):
        """
        Perform searches, summaries, or combined research tasks.
        
        Args:
            task_type: 'search' (fetch data), 'summarize' (text summary), or 'research' (both).
            data: The query or text to process.
            extra_parameters: Optional dict (unused but reserved for future extensions).

        Returns:
            The search results or summary text.
        """
        if task_type == "search":
            res = await self.search(data)
            return res
        elif task_type == "summarize":
            res = self.summarize(data)
            return res
        elif task_type == "research":
            res_dict = await self.search(data)
            res_str = str(res_dict)
            final_result = self.summarize(res_str)
            return final_result
        else:
            return "Task type not found"

