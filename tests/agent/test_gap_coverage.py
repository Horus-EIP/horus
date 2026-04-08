import sys
import pytest
import json
import ast
import importlib
from unittest.mock import MagicMock, patch, AsyncMock

# Note: We import these for type checking or standard tests, 
# but for import-time failure tests we will reload modules.
from ai_agents.payment_analyzer_tool import PaymentAnalyzerTool
from ai_agents.data_extractor_tool import DataExtractorTool
from ai_agents.file_parser_tool import FileParserTool
from ai_agents.calculator_tool import CalculatorTool
from ai_agents.knowledge_store_client import KnowledgeStoreClient
# DecisionMakingAgent import moved to inside tests to avoid pre-caching state
# But TestDecisionMakingGap needs it, so we can mock or import cleanly.
from ai_agents.decision_making_agent import DecisionMakingAgent

import httpx

class TestImportCoverage:
    def test_decision_making_agent_no_transformers(self):
        with patch.dict(sys.modules, {"transformers": None, "torch": None}):
            # Remove from cache if exists
            if "ai_agents.decision_making_agent" in sys.modules:
                del sys.modules["ai_agents.decision_making_agent"]
            
            import ai_agents.decision_making_agent
            importlib.reload(ai_agents.decision_making_agent)
            
            agent = ai_agents.decision_making_agent.DecisionMakingAgent()
            assert agent.decision_model == agent.mock_decision_model

    def test_data_extractor_spacy_import_fail(self):
        # Now that data_extractor_tool handles optional spacy, this should pass naturally 
        # provided we set sys.modules correctly before import.
        
        with patch.dict(sys.modules, {"spacy": None}):
            if "ai_agents.data_extractor_tool" in sys.modules:
                 del sys.modules["ai_agents.data_extractor_tool"]
            
            import ai_agents.data_extractor_tool
            importlib.reload(ai_agents.data_extractor_tool)
            # Should not raise ImportError
            
            # Verify internal state if possible, or just knowing it imported is enough for this test
            # Note: _has_spacy check
            assert ai_agents.data_extractor_tool._has_spacy is False

class TestPaymentAnalyzerGap:
    def test_forecast_no_valid_amounts(self):
        tool = PaymentAnalyzerTool()
        # Data valid but filtered out (JPY not supported for projection in this check)
        data = [{"amount": 100, "currency": "JPY"}]
        result = tool._predict_next_month(data)
        assert "No valid amounts to calculate forecast" in result

class TestDataExtractorGap:
    def test_extract_table_flush_last_line_no_newline(self):
        tool = DataExtractorTool()
        # Heuristic: ensure the pending table is flushed if text ends without newline
        # Must use >= 2 columns for detector to accept it
        text = "| Header A | Header B |\n| Value A | Value B |" 
        # _extract_tables splits by lines. Last line is valid row.
        result = tool._extract_tables(text)
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["header"] == ["Header A", "Header B"]

    def test_clean_amount_eu_variants(self):
        tool = DataExtractorTool()
        # Scenario: "12,34" -> 12.34 (comma near end heuristic)
        text = "Cost: €12,34"
        doc = tool.nlp(text)
        res = tool._extract_payments(text, doc)
        data = json.loads(res)
        assert data[0]["amount"] == 12.34

    def test_clean_amount_thousands_separator(self):
        tool = DataExtractorTool()
        # Scenario: "1,000" -> 1000.0 (comma not near end)
        text = "Cost: €1,000"
        doc = tool.nlp(text)
        res = tool._extract_payments(text, doc)
        data = json.loads(res)
        assert data[0]["amount"] == 1000.0

class TestFileParserGap:
    def test_run_missing_args_exception(self):
        tool = FileParserTool()
        with pytest.raises(ValueError, match="Either file_url or file_content"):
            tool.run({})

    @patch("ai_agents.file_parser_tool.requests.get")
    def test_load_content_raise_for_status(self, mock_get):
        tool = FileParserTool()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP Error")
        mock_resp.__enter__.return_value = mock_resp
        mock_get.return_value = mock_resp
        
        with pytest.raises(Exception, match="HTTP Error"):
            tool.run({"file_url": "http://fail.com"})

    def test_infer_type_binary_fallback(self):
        tool = FileParserTool()
        # Invalid utf-8 sequence
        content = b"\x80\x81" 
        kind = tool._infer_type(None, None, None, content)
        assert kind == "bin"
        
        # Test extraction for bin returns empty string (lines 82?) 
        res = tool._extract_text(content, "bin")
        assert res == ""

    def test_infer_type_pdf_header(self):
        tool = FileParserTool()
        content = b"%PDF-1.4 header"
        kind = tool._infer_type(None, None, None, content)
        assert kind == "pdf"
        
class TestCalculatorGap:
    def test_eval_ast_constant_numeric(self):
        tool = CalculatorTool()
        node = ast.Constant(value=42)
        val = tool._eval_node(node)
        assert val == 42.0

    def test_eval_ast_constant_non_numeric(self):
        tool = CalculatorTool()
        # ast.Constant with string
        node = ast.Constant(value="hello")
        with pytest.raises(ValueError, match="Only numeric constants"):
            tool._eval_node(node)

    def test_operators_mod_pow(self):
        tool = CalculatorTool()
        assert tool.evaluate("10 % 3") == 1.0
        assert tool.evaluate("2 ** 3") == 8.0

class TestKnowledgeStoreGap:
    @pytest.mark.asyncio
    async def test_metrics_import_fail(self):
        # We need to reload to test import fail
         with patch.dict(sys.modules, {"core.metrics": None}):
             # Reload knowledge_store_client
             if "ai_agents.knowledge_store_client" in sys.modules:
                 del sys.modules["ai_agents.knowledge_store_client"]
             import ai_agents.knowledge_store_client
             importlib.reload(ai_agents.knowledge_store_client)
             
             client = ai_agents.knowledge_store_client.KnowledgeStoreClient()
             assert client is not None
             # Ensure METRICS_AVAILABLE is False
             assert not ai_agents.knowledge_store_client._METRICS_AVAILABLE

    @pytest.mark.asyncio
    async def test_404_handling(self):
        client = KnowledgeStoreClient()
        with patch("httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            # raise_for_status should raise HTTPStatusError
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=mock_resp
            )
            
            mock_bg = MagicMock()
            # The client.get call is awaited, so it must return an awaitable or be an AsyncMock
            mock_bg.get = AsyncMock(return_value=mock_resp)
            mock_client.return_value.__aenter__.return_value = mock_bg

            res = await client.query("missing")
            # KnowledgeStoreClient returns data="" for 404
            assert res["data"] == ""

    @pytest.mark.asyncio
    async def test_request_error_handling_exhaustion(self):
        # This tests the final failure block
        client = KnowledgeStoreClient(max_retries=1, retry_delay=0.01)
        with patch("httpx.AsyncClient") as mock_client:
            mock_bg = MagicMock()
            # Make .get async
            mock_bg.get = AsyncMock(side_effect=httpx.RequestError("Connection Refused"))
            mock_client.return_value.__aenter__.return_value = mock_bg
            
            res = await client.query("fail")
            # Should return an error dict, not None
            assert res is not None
            assert "Error" in res["data"]
            assert "Connection Refused" in res["data"]

class TestDecisionMakingGap:
    def test_import_failures_safe(self):
         with patch("ai_agents.decision_making_agent._TRANSFORMERS_AVAILABLE", False):
             with patch("ai_agents.decision_making_agent._TORCH_AVAILABLE", False):
                 with patch("ai_agents.decision_making_agent.detect_device", return_value="cpu"):
                    agent = DecisionMakingAgent()
                    assert agent.decision_model == agent.mock_decision_model

class TestCalculatorAdditionalGap:
    def test_unary_ops(self):
        tool = CalculatorTool()
        assert tool.evaluate("+5") == 5.0
        assert tool.evaluate("-5") == -5.0

    def test_unsupported_node_type(self):
        tool = CalculatorTool()
        # ast.List is not supported
        try:
            node = ast.List(elts=[], ctx=ast.Load())
            with pytest.raises(ValueError, match="Unsupported expression"):
                tool._eval_node(node)
        except AttributeError:
             # ast.List might differ in recent python or node construction
             pass
            
    def test_expr_node_wrapper(self):
        tool = CalculatorTool()
        inner = ast.Constant(value=10)
        node = ast.Expr(value=inner)
        assert tool._eval_node(node) == 10.0


class TestPaymentAnalyzerAdditionalGap:
    def test_run_by_payee_integration(self):
        tool = PaymentAnalyzerTool()
        data = json.dumps([{"amount": 50, "currency": "USD", "payee": "Vendor"}])
        # Calling run with dict to map to multiple arguments
        res = tool.run({"payments_data": data, "analysis_type": "by_payee"})
        assert "Vendor (USD)" in res

    def test_run_forecast_integration(self):
        tool = PaymentAnalyzerTool()
        data = [{"amount": 100, "currency": "EUR"}]
        res = tool.run({"payments_data": json.dumps(data), "analysis_type": "forecast"})
        assert "Projected" in res

    def test_calculate_average_exception_continue(self):
        tool = PaymentAnalyzerTool()
        # Invalid amount causing ValueError in float conversion
        data = [{"amount": "invalid", "currency": "USD"}, {"amount": 10, "currency": "USD"}]
        res = tool._calculate_average(data)
        assert "Average USD: 10.0" in res

    def test_payee_breakdown_fallback_context(self):
        tool = PaymentAnalyzerTool()
        # Missing payee, use context
        data = [{"amount": 10, "currency": "USD", "context": " AWS "}]
        res = tool._get_payee_breakdown(data)
        assert "AWS (USD)" in res
        
    def test_payee_breakdown_fallback_unknown(self):
        tool = PaymentAnalyzerTool()
        # Missing payee and context
        data = [{"amount": 10, "currency": "USD"}]
        res = tool._get_payee_breakdown(data)
        assert "Unknown Payee (USD)" in res

    def test_payee_breakdown_exception_continue(self):
        tool = PaymentAnalyzerTool()
        # Invalid amount
        data = [{"amount": "bad", "currency": "USD", "payee": "Me"}]
        res = tool._get_payee_breakdown(data)
        assert "{}" in res

from ai_agents.summarizer_tool import SummarizerTool
class TestSummarizerAdditionalGap:
    def test_protect_keywords_comma_string(self):
         tool = SummarizerTool()
         text = "Important sentence. Useless filler. Another key info."
         # "important,key" -> ["important", "key"]
         # Should select sentence 0 and 2
         res = tool.run({"text": text, "protect_keywords": "important,key", "max_sentences": 2, "return_indices": True})
         assert "kept_sentence_indices" in res
         # We expect indices [0, 2] to be present in json or text
         # res should be json string
         data = json.loads(res)
         assert 0 in data["kept_sentence_indices"]
         assert 2 in data["kept_sentence_indices"]

    def test_transformers_exception_fallback(self):
         tool = SummarizerTool()
         # Mock pipe to exist but fail
         tool._pipe = MagicMock(side_effect=Exception("Model failed"))
         
         text = "Simple text. Because we need content. To trigger summary."
         # Should fallback to extractive
         res = tool.run({"text": text})
         assert len(res) > 0
         # Check that mock was called
         tool._pipe.assert_called()


from ai_agents.tool_registry import ToolRegistry

class TestToolRegistryComprehensive:
    def test_run_success(self):
        registry = ToolRegistry()
        class MockTool:
            name = "mock"
            def run(self, payload): return "success"
        
        registry.register(MockTool())
        assert registry.run("mock", {}) == "success"

class TestFileParserComprehensive:
    def test_parse_txt_str(self):
        tool = FileParserTool()
        assert tool.run({"file_content": "hello", "file_type": "txt"}) == "hello"

    def test_parse_csv(self):
        tool = FileParserTool()
        csv_data = b"a,b\n1,2"
        res = tool.run({"file_content": csv_data, "file_type": "csv"})
        assert "a, b" in res

    def test_parse_pdf_mock_success(self):
         with patch("ai_agents.file_parser_tool.PdfReader") as mock_reader:
             instance = mock_reader.return_value
             page = MagicMock()
             page.extract_text.return_value = "pdf content"
             instance.pages = [page]
             
             tool = FileParserTool()
             res = tool.run({"file_content": b"%PDF-mock", "file_type": "pdf"})
             assert "pdf content" in res

    @patch("ai_agents.file_parser_tool.requests.get")
    def test_download_success(self, mock_get):
        tool = FileParserTool()
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"down", b"load"]
        mock_resp.headers = {}
        mock_resp.__enter__.return_value = mock_resp
        mock_get.return_value = mock_resp
        
        res = tool.run({"file_url": "http://ok.com"})
        assert res == "download"

class TestCalculatorComprehensive:
    def test_basic_math(self):
        tool = CalculatorTool()
        assert tool.evaluate("1 + 2") == 3.0
        assert tool.evaluate("2 * 3") == 6.0
        assert tool.evaluate("10 / 2") == 5.0

    def test_functions(self):
        tool = CalculatorTool()
        assert tool.evaluate("sqrt(4)") == 2.0
        assert tool.evaluate("pow(2, 3)") == 8.0

    def test_constants(self):
        tool = CalculatorTool()
        # pi is roughly 3.14
        assert abs(tool.evaluate("pi") - 3.14159) < 0.001

class TestDecisionMakingComprehensive:
    @pytest.mark.asyncio
    async def test_decide_mock_flow(self):
        # Full flow with mock model to cover 'decide' method lines
        mock_model = MagicMock()
        mock_model.return_value = [{"generated_text": "Answer"}]
        agent = DecisionMakingAgent(decision_model=mock_model)
        
        res = await agent.decide("Q", "C")
        assert res == "Answer"
        mock_model.assert_called()

    def test_detect_device_gpu(self):
        with patch("ai_agents.decision_making_agent._TORCH_AVAILABLE", True):
             with patch("ai_agents.decision_making_agent.torch") as mock_torch:
                 mock_torch.cuda.is_available.return_value = True
                 mock_torch.cuda.get_device_name.return_value = "GPU"
                 
                 from ai_agents.decision_making_agent import detect_device
                 assert detect_device("auto") == "cuda"

    def test_detect_device_cpu_explicit(self):
        from ai_agents.decision_making_agent import detect_device
        assert detect_device("cpu") == "cpu"

from ai_agents.knowledge_retrieval_agent import KnowledgeRetrievalAgent
from ai_agents.rag_pipeline import RAGPipeline

class TestKnowledgeRetrievalComprehensive:
    @pytest.mark.asyncio
    async def test_fetch(self):
        mock_store = AsyncMock(return_value={"data": "Retrieved Data"})
        agent = KnowledgeRetrievalAgent(store_interface=mock_store)
        res = await agent.fetch("query")
        assert res["data"] == "Retrieved Data"
        if isinstance(mock_store, AsyncMock):
            mock_store.assert_called_with("query")

class TestRAGPipelineComprehensive:
    @pytest.mark.asyncio
    async def test_process_task_tool(self):
        # Mock dependencies
        mock_retrieval = MagicMock()
        mock_decision = MagicMock()
        
        # Mock registry
        mock_registry = MagicMock()
        mock_registry.has.return_value = True
        mock_registry.run.return_value = "Tool Result"
        
        pipeline = RAGPipeline(mock_retrieval, mock_decision, tool_registry=mock_registry)
        
        task = {"task_id": 1, "query": "do something", "operation": "mytool"}
        res = await pipeline.process_task(task)
        
        # Check result format
        assert res["response"] == "Tool Result"
        assert res["status"] == "completed"
        mock_registry.run.assert_called()

    @pytest.mark.asyncio
    async def test_process_task_rag(self):
        # Mock dependencies
        mock_retrieval = MagicMock()
        # Mock fetch as async
        mock_retrieval.fetch = AsyncMock(return_value={"data": "Context"})
        
        mock_decision = MagicMock()
        mock_decision.decide.return_value = "Insight"
        
        # Registry returns false for operation
        mock_registry = MagicMock()
        mock_registry.has.return_value = False
        
        pipeline = RAGPipeline(mock_retrieval, mock_decision, tool_registry=mock_registry)
        
        task = {"task_id": 1, "query": "What is x?", "operation": "unknown"}
        res = await pipeline.process_task(task)
        
        assert res["response"] == "Insight"
        mock_retrieval.fetch.assert_called_with("What is x?")
        mock_decision.decide.assert_called()


    @pytest.mark.asyncio
    async def test_generate_response(self):
         # Mock dependencies
        mock_retrieval = MagicMock()
        mock_retrieval.fetch = AsyncMock(return_value={"data": "Context"})
        
        mock_decision = MagicMock()
        mock_decision.decide.return_value = "Insight generated"
        
        pipeline = RAGPipeline(mock_retrieval, mock_decision)
        
        res = await pipeline.generate_response("query")
        assert res == "Insight generated"

    def test_default_registry_build(self):
         # Just instantiate with None to trigger _build_default_registry
         mock_retrieval = MagicMock()
         mock_decision = MagicMock()
         pipeline = RAGPipeline(mock_retrieval, mock_decision)
         assert pipeline.tool_registry is not None
         # Check known tool
         assert pipeline.tool_registry.has("calculator")


class TestDecisionMakingMetricsGap:
    @pytest.mark.asyncio
    async def test_inference_exception_metrics(self):
        # Create a mock module for core.metrics
        mock_metrics_module = MagicMock()
        mock_total = MagicMock()
        mock_dur = MagicMock()
        mock_metrics_module.model_inference_total = mock_total
        mock_metrics_module.model_inference_duration = mock_dur
        
        # Patch sys.modules to include core.metrics
        with patch.dict("sys.modules", {"core.metrics": mock_metrics_module}):
             mock_model = MagicMock(side_effect=Exception("GPU Burn"))
             agent = DecisionMakingAgent(decision_model=mock_model)
             
             with pytest.raises(Exception) as exc:
                 await agent.decide("Q", "C")
             
             assert "GPU Burn" in str(exc.value)
             
             # Verify metrics were called
             mock_dur.labels.assert_called()
             mock_total.labels.assert_called_with(
                 model_name=agent.model_name,
                 device=agent.device,
                 status="error"
             )

class TestFileParserLimitsGap:
    @patch("ai_agents.file_parser_tool.requests.get")
    def test_download_too_large(self, mock_get):
        tool = FileParserTool(max_download_bytes=10) # Small limit
        mock_resp = MagicMock()
        # Returns chunks that exceed 10 bytes total
        mock_resp.iter_content.return_value = [b"12345", b"678901"] 
        mock_resp.headers = {}
        mock_resp.__enter__.return_value = mock_resp
        mock_get.return_value = mock_resp
        
        with pytest.raises(ValueError, match="exceeds max allowed size"):
            tool.run({"file_url": "http://bigfile.com"})

class TestKnowledgeStoreJsonFailGap:
    @pytest.mark.asyncio
    async def test_400_bad_json_response(self):
        client = KnowledgeStoreClient()
        with patch("httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "400 Bad Request", request=MagicMock(), response=mock_resp
            )
            # JSON parse fails
            mock_resp.json.side_effect = json.JSONDecodeError("Fail", "doc", 0)
            mock_resp.text = "Raw Error Text"
            
            mock_bg = MagicMock()
            mock_bg.get = AsyncMock(return_value=mock_resp)
            mock_client.return_value.__aenter__.return_value = mock_bg
            
            res = await client.query("bad_request")
            # Should fall back to text
            assert "Raw Error Text" in res["data"]
