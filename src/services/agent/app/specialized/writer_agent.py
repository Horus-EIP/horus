import asyncio
import logging

logger = logging.getLogger(__name__)


class WriterAgent:
    def __init__(self, decision_agent):
        self.type = "writer"
        self.llm = decision_agent

    async def generate_report(self, data: str) -> str:
        prompt = f"Write a professional report based on the following data : {data}"
        return await asyncio.to_thread(self.llm.decide, prompt)

    async def format_text(self, text: str, final_format: str) -> str:
        prompt = f"Format the following text as {final_format}: {text}"
        return await asyncio.to_thread(self.llm.decide, prompt)

    async def process_request(self, task_type: str, data: str, extra_parameters: dict = None):
        """
        Process a request based on task type.

        Args:
            task_type: 'write' (generate report) or 'format' (format text).
            data: The main text content to process.
            extra_parameters: Dict containing 'format' key for formatting tasks.

        Returns:
            The generated or formatted text as a string.
        """
        if task_type == "write":
            res = await self.generate_report(data)
            return res
        elif task_type == "format":
            return await self.format_text(data, extra_parameters["format"])
        else:
            return "Task type not found"
