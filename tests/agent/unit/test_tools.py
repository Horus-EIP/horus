import pytest
import io
import json
import logging
import ast
from unittest.mock import MagicMock, patch, mock_open

from ai_agents.calculator_tool import CalculatorTool
from ai_agents.tool_registry import ToolRegistry, Tool
from ai_agents.summarizer_tool import SummarizerTool
from ai_agents.file_parser_tool import FileParserTool

# --- CalculatorTool Tests ---

class TestCalculatorTool:
    @pytest.fixture
    def tool(self):
        return CalculatorTool()

    def test_basic_arithmetic(self, tool):
        assert tool.run({"expression": "1 + 1"}) == "2.0"
        assert tool.run({"expression": "10 - 4"}) == "6.0"
        assert tool.run({"expression": "3 * 4"}) == "12.0"
        assert tool.run({"expression": "10 / 2"}) == "5.0"
        assert tool.run({"expression": "2 ** 3"}) == "8.0"

    def test_complex_math_functions(self, tool):
        # Allow small float discrepancies
        res_sin = float(tool.run({"expression": "sin(0)"}))
        assert res_sin == 0.0
        
        res_sqrt = float(tool.run({"expression": "sqrt(16)"}))
        assert res_sqrt == 4.0

    def test_constants(self, tool):
        res_pi = float(tool.run({"expression": "pi"}))
        assert res_pi > 3.14

    def test_security_restrictions(self, tool):
        with pytest.raises(ValueError):
            tool.run({"expression": "__import__('os').system('ls')"})
        
        with pytest.raises(ValueError, match="is not allowed"):
            tool.run({"expression": "open('/etc/passwd')"})

    def test_manual_ast_nodes(self, tool):
        node = ast.Constant(value=42)
        assert tool._eval_node(node) == 42.0
        
        node = ast.Constant(value="string")
        with pytest.raises(ValueError, match="Only numeric constants"):
            tool._eval_node(node)

        node = ast.Name(id='INVALID_VAR', ctx=ast.Load())
        with pytest.raises(ValueError, match="is not allowed"):
            tool._eval_node(node)

    def test_manual_ast_call_keywords(self, tool):
        # Construct a call with keywords: sin(0, k=1)
        node = ast.Call(
            func=ast.Name(id='sin', ctx=ast.Load()),
            args=[ast.Constant(value=0)],
            keywords=[ast.keyword(arg='k', value=ast.Constant(value=1))]
        )
        with pytest.raises(ValueError, match="Keyword arguments"):
            tool._eval_node(node)

    def test_invalid_syntax(self, tool):
        with pytest.raises(ValueError):
            tool.run({"expression": "1 + + "})

    def test_apply_binop_unsupported(self, tool):
        # Manually invoke _apply_binop with an unsupported op
        # ast.BitXor is not in _ALLOWED_BINARY_OPS, so we use it to test the raise
        op = ast.BitXor()
        with pytest.raises(ValueError, match="Operator not allowed"):
            tool._apply_binop(op, 1, 2)

    def test_invalid_function_reference(self, tool):
        # Manually invoke _resolve_name with unsupported node
        node = ast.Constant(value=1)
        with pytest.raises(ValueError, match="Invalid function reference"):
            tool._resolve_name(node)

# --- ToolRegistry Tests ---

class TestToolRegistry:
    @pytest.fixture
    def registry(self):
        return ToolRegistry()
    
    class DummyTool:
        name = "dummy"
        def run(self, payload):
            return f"Processed: {payload.get('data')}"

    def test_register_and_resolve(self, registry):
        tool = self.DummyTool()
        registry.register(tool)
        
        assert registry.has("dummy")
        assert registry.resolve("dummy") == tool
        assert registry.run("dummy", {"data": "test"}) == "Processed: test"

    def test_alias_resolution(self, registry):
        tool = self.DummyTool()
        registry.register(tool, aliases=["dum", "d"])
        
        assert registry.resolve("dum") == tool
        assert registry.resolve("d") == tool
        assert registry.run("dum", {"data": "alias"}) == "Processed: alias"

    def test_missing_tool(self, registry):
        assert not registry.has("ghost")
        assert registry.resolve("ghost") is None
        assert registry.get("ghost") is None
        
        with pytest.raises(KeyError):
            registry.run("ghost", {})

    def test_get_method(self, registry):
        """Test the get method explicitly since it duplicates resolve logic but with logging."""
        tool = self.DummyTool()
        registry.register(tool, aliases=["alias"])
        
        # Test direct name match
        assert registry.get("dummy") == tool
        
        # Test alias match
        assert registry.get("alias") == tool
        
        # Test missing
        assert registry.get("missing") is None

# --- SummarizerTool Tests ---

class TestSummarizerTool:
    def test_run_empty(self):
        tool = SummarizerTool()
        assert tool.run({"text": ""}) == ""
        assert tool.run({"text": "   "}) == ""

    @patch("transformers.pipeline")
    def test_transformers_usage(self, mock_pipeline):
        # Mock successful pipeline existence
        from ai_agents.summarizer_tool import SummarizerTool
        
        # Setup the pipeline mock instance
        mock_instance = MagicMock()
        mock_instance.return_value = [{"summary_text": "This is a summary"}]
        mock_pipeline.return_value = mock_instance

        tool = SummarizerTool()
        assert tool._pipe is None

        res = tool.run({"text": "Long text"})
        assert res == "This is a summary"
        assert tool._pipe is not None
        mock_instance.assert_called_once()

    def test_protected_keywords_fallback(self):
        # If protect_keywords is present, it uses extractive fallback even if pipeline exists
        with patch("transformers.pipeline") as mock_pipeline:
            tool = SummarizerTool()
            payload = {
                "text": "This is sentence one. This is sentence two with keyword. This is three.",
                "protect_keywords": "keyword"
            }
            # Should NOT use pipeline
            res = tool.run(payload)
            # The simple extractive logic splits by sentence and finds keyword
            assert "This is sentence two with keyword" in res
            
            # Ensure pipeline was not called
            if tool._pipe:
                 tool._pipe.assert_not_called()

    def test_return_indices_json(self):
        tool = SummarizerTool()
        payload = {"text": "A. B. C.", "return_indices": True}
        # Force a deterministic fallback path
        with patch.object(SummarizerTool, '_extractive_summary', return_value=("A.", [0])):
            res = tool.run(payload)
            # Should be valid JSON
            data = json.loads(res)
            assert data["summary"] == "A."
            assert data["kept_sentence_indices"] == [0]

    def test_return_indices_json_fail(self):
        tool = SummarizerTool()
        payload = {"text": "A. B. C.", "return_indices": True}
        
        with patch.object(SummarizerTool, '_extractive_summary', return_value=("A.", [0])):
             # Mock json.dumps to fail
             with patch("json.dumps", side_effect=Exception("JSON Error")):
                 res = tool.run(payload)
                 assert "JSON Error" not in res
                 assert "[kept_sentence_indices: [0]]" in res

    def test_extractive_summary_logic(self):
        tool = SummarizerTool()
        text = "This is sentence one. This is sentence two. This is sentence three."
        # Use keywords to force sentence 2 to definitely be picked
        summary, indices = tool._extractive_summary(text, max_sentences=2, protect_keywords=["two"])
        assert 1 in indices # Sentence index 1 (zero-based) has "two"
        assert "This is sentence two." in summary

        # Test short sentence skipping in word freq
        text_short = "A. B. C."
        summary, indices = tool._extractive_summary(text_short, max_sentences=3)
        assert len(indices) == 3

    def test_transformers_import_error(self):
        # Simulate import error
        # We need to ensure 'transformers' is not in sys.modules during this test or behaves like it's missing
        with patch.dict("sys.modules", {"transformers": None}):
            tool = SummarizerTool()
            assert tool._pipe is None

# --- FileParserTool Tests ---

class TestFileParserTool:
    @pytest.fixture
    def tool(self):
        return FileParserTool()

    def test_text_content_direct(self, tool):
        payload = {"file_content": "hello world", "file_type": "txt"}
        res = tool.run(payload)
        assert res == "hello world"

    def test_csv_content(self, tool):
        csv_bytes = b"col1,col2\nval1,val2"
        payload = {"file_content": csv_bytes, "file_type": "csv"}
        res = tool.run(payload)
        assert "col1, col2" in res
        assert "val1, val2" in res

    @patch("ai_agents.file_parser_tool.requests.get")
    def test_download_file(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"downloaded", b" content"]
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.__enter__.return_value = mock_resp
        mock_get.return_value = mock_resp

        payload = {"file_url": "http://example.com/file.txt"}
        res = tool.run(payload)
        
        assert "downloaded content" in res

    def test_pdf_not_installed_fallback(self, tool):
        # Mock _PDF_AVAILABLE = False
        with patch("ai_agents.file_parser_tool._PDF_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="not installed"):
                payload = {"file_content": b"%PDF-1.4...", "file_type": "pdf"}
                tool.run(payload)

    def test_parse_pdf_success_mock(self, tool):
        with patch("ai_agents.file_parser_tool.PdfReader") as mock_pdf_reader:
             # Setup mock page
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "PDF Page Content"
            
            # Setup mock reader
            instance = MagicMock()
            instance.pages = [mock_page]
            mock_pdf_reader.return_value = instance
            
            payload = {"file_content": b"%PDF-1.4...", "file_type": "pdf"}
            text = tool.run(payload)
            assert "PDF Page Content" in text

    def test_detect_binary_content(self, tool):
        # Invalid utf-8 sequence that isn't PDF or CSV
        payload = {"file_content": b"\x80\x81\x82", "filename": "unknown.bin"}
        text = tool.run(payload)
        # Should return [Binary File] or empty string depending on implementation
        # Implementation returns "bin" type, then _extract_text fallback returns ""
        assert text == ""


