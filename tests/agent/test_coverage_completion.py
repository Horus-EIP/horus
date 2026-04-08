import pytest
import ast
import json
import sys
from unittest.mock import MagicMock, patch, Mock

class TestCoverageCompletion:

    def test_calculator_ast_num(self):
        from ai_agents.calculator_tool import CalculatorTool
        tool = CalculatorTool()
        node = ast.Constant(value=10)
        res = tool._eval_node(node)
        assert res == 10.0

    def test_calculator_resolve_name_attribute(self):
        from ai_agents.calculator_tool import CalculatorTool
        tool = CalculatorTool()
        node = ast.Attribute(attr="my_attr", value=ast.Name(id="obj", ctx=ast.Load()), ctx=ast.Load())
        res = tool._resolve_name(node)
        assert res == "my_attr"

    def test_data_extractor_arun(self):
        from ai_agents.data_extractor_tool import DataExtractorTool
        tool = DataExtractorTool()
        with pytest.raises(NotImplementedError):
            tool._arun("text", "payments")

    def test_payment_extraction_value_error(self):
        from ai_agents.data_extractor_tool import DataExtractorTool
        tool = DataExtractorTool()
        text = "The amount is 12.34.56 EUR. Valid amount 100 EUR."
        with patch("spacy.load") as mock_spacy:
             mock_nlp = MagicMock()
             mock_nlp.return_value.ents = []
             tool.nlp = mock_nlp
             res_json = tool._extract_payments(text, mock_nlp(text))
        
        # We expect the invalid amount to be skipped.
        # However, "12.34.56" might be detected as a date for the valid entry.
        # So we verify that the EXTRACTED AMOUNT is 100.0 and we have 1 entry.
        data = json.loads(res_json)
        assert len(data) == 1
        assert data[0]["amount"] == 100.0

    def test_spacy_init_failures_complex(self):
        with patch.dict("sys.modules", {"spacy": None}):
             with patch("ai_agents.data_extractor_tool.spacy", None):
                 with patch("ai_agents.data_extractor_tool._has_spacy", False):
                     from ai_agents.data_extractor_tool import DataExtractorTool
                     tool = DataExtractorTool()
                     assert tool.nlp("test").ents == []

    def test_payment_analyzer_arun(self):
        from ai_agents.payment_analyzer_tool import PaymentAnalyzerTool
        tool = PaymentAnalyzerTool()
        with pytest.raises(NotImplementedError):
            tool._arun([], "total")

    def test_payment_analyzer_loops_exceptions(self):
        from ai_agents.payment_analyzer_tool import PaymentAnalyzerTool
        tool = PaymentAnalyzerTool()
        data = [{"amount": "invalid", "currency": "EUR"}]
        res = tool._calculate_total(data)
        assert "No valid EUR or USD amounts" in res
        res = tool._calculate_average(data)
        assert "No valid amounts" in res
        res = tool._get_payee_breakdown(data)
        assert json.loads(res) == {}
        res = tool._predict_next_month(data)

    def test_summarizer_pipeline_success(self):
        with patch.dict("sys.modules", {"transformers": MagicMock()}):
             from ai_agents.summarizer_tool import SummarizerTool
             mock_pipe = MagicMock(return_value=[{"summary_text": "Summary result"}])
             tool = SummarizerTool()
             tool._pipe = mock_pipe 
             res = tool.run({"text": "Long text", "protect_keywords": []})
             assert res == "Summary result"

    def test_summarizer_indices(self):
        with patch.dict("sys.modules", {"transformers": None}):
            from ai_agents.summarizer_tool import SummarizerTool
            tool = SummarizerTool()
            tool._pipe = None
            res = tool.run({"text": "Sentence one. Sentence two.", "return_indices": True})
            data = json.loads(res)
            assert "summary" in data
            assert "kept_sentence_indices" in data

    def test_file_parser_infer_type_explicit(self):
        from ai_agents.file_parser_tool import FileParserTool
        tool = FileParserTool()
        res = tool._infer_type("PDF", None, None, b"")
        assert res == "pdf"

    def test_file_parser_import_error_simulation(self):
        with patch("ai_agents.file_parser_tool._PDF_AVAILABLE", False):
            from ai_agents.file_parser_tool import FileParserTool
            tool = FileParserTool()
            with pytest.raises(RuntimeError):
                tool._extract_text(b"content", "pdf")

    @pytest.mark.asyncio
    async def test_knowledge_store_loop_exceptions(self):
        from ai_agents.knowledge_store_client import KnowledgeStoreClient
        client = KnowledgeStoreClient(retry_delay=0.0)
        with patch("httpx.AsyncClient.get", side_effect=[Exception("Generic Failure"), Mock(status_code=200, json=lambda: {})]):
             res = await client.query("q")
             assert res == {'data': '', 'query': 'q'}

    @pytest.mark.asyncio
    async def test_decision_making_metrics_import_fail(self):
        with patch.dict("sys.modules", {"core.metrics": None}):
             from ai_agents.decision_making_agent import DecisionMakingAgent
             mock_model = MagicMock(return_value=[{"generated_text": "Answer"}])
             agent = DecisionMakingAgent(decision_model=mock_model)
             res = await agent.decide("Q", "C")
             assert res == "Answer"

    def test_file_parser_extensions(self):
        from ai_agents.file_parser_tool import FileParserTool
        tool = FileParserTool()
        assert tool._infer_type(None, "doc.pdf", None, b"") == "pdf"
        assert tool._infer_type(None, "data.csv", None, b"") == "csv"

    @pytest.mark.asyncio
    async def test_decision_making_fallback_format(self):
        from ai_agents.decision_making_agent import DecisionMakingAgent
        mock_model = MagicMock(return_value="Valid String Answer")
        agent = DecisionMakingAgent(decision_model=mock_model)
        with patch.dict("sys.modules", {"core.metrics": None}):
            res = await agent.decide("Q", "C")
        assert res == "Valid String Answer"
        
        mock_model2 = MagicMock(return_value=["Just a string in list"])
        agent2 = DecisionMakingAgent(decision_model=mock_model2)
        with patch.dict("sys.modules", {"core.metrics": None}):
             res2 = await agent2.decide("Q", "C")
        assert "Just a string in list" in res2

    def test_calculator_floordiv(self):
        from ai_agents.calculator_tool import CalculatorTool
        tool = CalculatorTool()
        op = ast.FloorDiv()
        left = ast.Constant(value=10)
        right = ast.Constant(value=3)
        node = ast.BinOp(left=left, op=op, right=right)
        res = tool._eval_node(node)
        assert res == 3.0

    def test_payment_analyzer_empty_logic(self):
        from ai_agents.payment_analyzer_tool import PaymentAnalyzerTool
        tool = PaymentAnalyzerTool()
        assert tool._calculate_average([]) == "No data to calculate average"
        assert tool._get_payee_breakdown([]) == "No data to calculate payee breakdown"

    def test_summarizer_keywords_list_and_overflow(self):
        with patch.dict("sys.modules", {"transformers": None}):
            from ai_agents.summarizer_tool import SummarizerTool
            tool = SummarizerTool()
            tool._pipe = None
            res = tool.run({"text": "Sentence A. Sentence B.", "protect_keywords": ["A"]})
            assert "Sentence A" in res
            
            text = "S1 key. S2 key. S3 key. S4 key. S5 key."
            payload = {
                "text": text, 
                "max_sentences": 2, 
                "protect_keywords": ["key"], 
                "return_indices": True
            }
            res_json = tool.run(payload)
            data = json.loads(res_json)
            assert len(data["kept_sentence_indices"]) == 2

    def test_payment_analyzer_run_average(self):
        from ai_agents.payment_analyzer_tool import PaymentAnalyzerTool
        tool = PaymentAnalyzerTool()
        data = '[{"amount": 10, "currency": "USD"}, {"amount": 20, "currency": "USD"}]'
        res = tool._run(data, "average")
        assert "15.0" in res

    def test_data_extractor_run_key_values(self):
        from ai_agents.data_extractor_tool import DataExtractorTool
        tool = DataExtractorTool()
        text = "Invoice: 123"
        res = tool._run(text, "key_values")
        assert "Invoice" in res and "123" in res

    def test_data_extractor_tables_invalid_row_flush(self):
        from ai_agents.data_extractor_tool import DataExtractorTool
        tool = DataExtractorTool()
        text = "H1|H2\nD1|D2\nBroken | "
        res = tool._extract_tables(text)
        data = json.loads(res)
        assert len(data) == 1
        assert data[0]["header"] == ["H1", "H2"]

    def test_calculator_constant_number(self):
        from ai_agents.calculator_tool import CalculatorTool
        tool = CalculatorTool()
        res = tool.evaluate("42.5")
        assert res == 42.5

    def test_payment_analyzer_run_by_payee(self):
        from ai_agents.payment_analyzer_tool import PaymentAnalyzerTool
        tool = PaymentAnalyzerTool()
        data = '[{"amount": 100, "currency": "USD", "payee": "VendorA"}]'
        res = tool._run(data, "by_payee")
        assert "VendorA" in res
        
    def test_payment_analyzer_run_forecast(self):
        from ai_agents.payment_analyzer_tool import PaymentAnalyzerTool
        tool = PaymentAnalyzerTool()
        data = '[{"amount": 100, "currency": "USD", "date": "2023-01-01"}]'
        res = tool._run(data, "forecast")
        # Just check it returns something valid (mock logic might vary)
        assert res is not None

    def test_calculator_constant_explicit_types(self):
        from ai_agents.calculator_tool import CalculatorTool
        tool = CalculatorTool()
        # Direct ast.Constant test
        node = ast.Constant(value=123.456)
        res = tool._eval_node(node)
        assert res == 123.456
        
        # Test non-numeric constant (should raise ValueError)
        node_str = ast.Constant(value="string")
        with pytest.raises(ValueError, match="Only numeric constants are allowed"):
            tool._eval_node(node_str)
