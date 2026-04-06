import pytest
import asyncio
import sys
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any

# Mock spacy to avoid Pydantic/Python 3.14 compatibility issues during tests
sys.modules["spacy"] = MagicMock()
sys.modules["spacy.cli"] = MagicMock()
sys.modules["spacy.language"] = MagicMock()

from specialized.researcher_agent import ResearcherAgent
from specialized.analyst_agent import AnalystAgent
from specialized.writer_agent import WriterAgent

# Async helper
async def async_return(val):
    return val

class TestResearcherAgent:
    def setup_method(self):
        self.mock_retrieval = MagicMock()
        self.mock_retrieval.fetch = AsyncMock(return_value={"data": "mocked search results"})
        self.agent = ResearcherAgent(self.mock_retrieval)
        self.agent.summarizer = MagicMock()
        self.agent.summarizer.run.return_value = "Mocked Summary"

    @pytest.mark.asyncio
    async def test_process_search(self):
        # process_request(task_type, data, extra_params)
        res = await self.agent.process_request("search", "query text", {})
        assert res == {"data": "mocked search results"}
        self.mock_retrieval.fetch.assert_called_with("query text")

    @pytest.mark.asyncio
    async def test_process_summarize(self):
        res = await self.agent.process_request("summarize", "text to summarize", {})
        assert res == "Mocked Summary"
        self.agent.summarizer.run.assert_called_with({"text": "text to summarize"})

    @pytest.mark.asyncio
    async def test_process_research(self):
        # Research does search -> summarize
        res = await self.agent.process_request("research", "query text", {})
        assert res == "Mocked Summary"
        self.mock_retrieval.fetch.assert_called_with("query text")
        # Ensure summarizer was called with the string result of search
        self.agent.summarizer.run.assert_called()


class TestAnalystAgent:
    def setup_method(self):
        self.agent = AnalystAgent()
        # Mock internal tools
        self.agent.data_extractor = MagicMock()
        self.agent.data_extractor._run.return_value = "Extracted Entities"
        self.agent.payment_analyzer = MagicMock()
        self.agent.payment_analyzer._run.return_value = "Payment Analysis"
        self.agent.calculator = MagicMock()
        self.agent.calculator.run.return_value = "42"

    @pytest.mark.asyncio
    async def test_process_extract(self):
        extra = {"extraction_type": "entities"}
        res = await self.agent.process_request("extract", "some text", extra)
        assert res == "Extracted Entities"
        self.agent.data_extractor._run.assert_called_with("some text", "entities")

    @pytest.mark.asyncio
    async def test_process_analyze(self):
        extra = {"analysis_type": "fraud"}
        res = await self.agent.process_request("analyze", "payment data", extra)
        assert res == "Payment Analysis"
        self.agent.payment_analyzer._run.assert_called_with("payment data", "fraud")

    @pytest.mark.asyncio
    async def test_process_calculate(self):
        extra = {"expression": "2+2"}
        # Data might be empty or redundant
        res = await self.agent.process_request("calculate", "any_data", extra)
        assert res == "42"
        # The agent.calculator.run expects {"expression": "..."}
        self.agent.calculator.run.assert_called_with({"expression": "2+2"})


class TestWriterAgent:
    def setup_method(self):
        self.mock_decision = MagicMock()
        self.mock_decision.decide = AsyncMock(return_value="Generated Content")
        self.agent = WriterAgent(self.mock_decision)

    @pytest.mark.asyncio
    async def test_process_write(self):
        res = await self.agent.process_request("write", "raw data", {})
        assert res == "Generated Content"
        # Check prompt construction
        args, _ = self.mock_decision.decide.call_args
        assert "Write a professional report" in args[0]
        assert "raw data" in args[0]

    @pytest.mark.asyncio
    async def test_process_format(self):
        extra = {"format": "markdown"}
        res = await self.agent.process_request("format", "text to format", extra)
        assert res == "Generated Content"
        # Check prompt construction
        args, _ = self.mock_decision.decide.call_args
        # Note: the implementation says extra_parameters["format"] is accessed directly
        assert "Format the following text as markdown" in args[0]
