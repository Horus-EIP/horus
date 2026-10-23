import logging
from typing import Any

from ai_agents.calculator_tool import CalculatorTool
from ai_agents.data_extractor_tool import DataExtractorTool
from ai_agents.payment_analyzer_tool import PaymentAnalyzerTool

logger = logging.getLogger(__name__)


class AnalystAgent:
    def __init__(self):
        self.type = "analyst"
        self.data_extractor = DataExtractorTool()
        self.payment_analyzer = PaymentAnalyzerTool()
        self.calculator = CalculatorTool()

    def extract(self, text: str, extraction_type: str):
        return self.data_extractor._run(text, extraction_type)

    def analyze(self, payments_data: str, analysis_type: str):
        return self.payment_analyzer._run(payments_data, analysis_type)

    def calculate(self, expression: str):
        expression_dict = {"expression": expression}
        return self.calculator.run(expression_dict)

    async def process_request(self, task_type: str, data: Any, extra_parameters: dict = None):
        """
        Process extraction, analysis, or calculation requests.

        Args:
            task_type: 'extract', 'analyze', or 'calculate'.
            data: The content to process (text, payments data, or calculation details).
            extra_parameters: Optional params like 'extraction_type', 'analysis_type', or 'expression'.

        Returns:
            The analysis result as a string or compatible type.
        """
        if extra_parameters is None:
            extra_parameters = {}

        if task_type == "extract":
            extraction_type = extra_parameters.get("extraction_type", "entities")
            return self.extract(data, extraction_type)
        elif task_type == "analyze":
            analysis_type = extra_parameters.get("analysis_type", "fraud")
            return self.analyze(data, analysis_type)
        elif task_type == "calculate":
            expression = extra_parameters.get("expression") or str(data)
            return self.calculate(expression)
        else:
            return "Task type not found"
