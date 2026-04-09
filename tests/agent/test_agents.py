import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any

from ai_agents.decision_making_agent import DecisionMakingAgent, detect_device
from ai_agents.knowledge_retrieval_agent import KnowledgeRetrievalAgent
from ai_agents.rag_pipeline import RAGPipeline
from ai_agents.tool_registry import ToolRegistry

# --- DecisionMakingAgent Tests ---

class TestDecisionMakingAgent:
    def test_initialization_auto_device(self):
        # Causal stack is mocked in conftest (from_pretrained); no real download.
        agent = DecisionMakingAgent()
        assert agent.device in ["cpu", "cuda", "cuda:0"]
        assert agent.decision_model is None
        assert agent._causal_model is not None
        assert agent._causal_tokenizer is not None

    def test_raises_when_transformers_unavailable(self):
        with patch("ai_agents.decision_making_agent._TRANSFORMERS_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="transformers is required"):
                DecisionMakingAgent()

    @pytest.mark.asyncio
    async def test_decide_flow(self):
        mock_model = MagicMock()
        mock_model.return_value = [{"generated_text": "Processed Answer"}]
        
        agent = DecisionMakingAgent(decision_model=mock_model)
        result = agent.decide("query", "context")
        
        assert result == "Processed Answer"
        mock_model.assert_called_once()
        args, _ = mock_model.call_args
        assert "Context:\ncontext" in args[0]
        assert "Question: query" in args[0]

    def test_detect_device(self):
        with patch("ai_agents.decision_making_agent.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = True
            mock_torch.cuda.get_device_name.return_value = "Mock GPU"
            
            # Auto should pick cuda
            assert detect_device("auto") == "cuda"
            
            # Explicit CPU should pick CPU
            assert detect_device("cpu") == "cpu"
            
        with patch("ai_agents.decision_making_agent.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = False
            # Auto should fallback to cpu
            assert detect_device("auto") == "cpu"

            # CUDA requested but unavailable -> cpu
            assert detect_device("cuda") == "cpu"

    @pytest.mark.asyncio
    async def test_decide_metrics_logging(self):
         # Mock core.metrics import
         mock_metrics = MagicMock()
         # Setup the items to be imported
         mock_metrics.model_inference_total = MagicMock()
         mock_metrics.model_inference_duration = MagicMock()
         
         with patch.dict("sys.modules", {"core.metrics": mock_metrics}):
             mock_model = MagicMock(return_value=[{"generated_text": "A"}])
             agent = DecisionMakingAgent(decision_model=mock_model)
             
             agent.decide("Q", "C")
             
             mock_metrics.model_inference_total.labels.return_value.inc.assert_called()
             mock_metrics.model_inference_duration.labels.return_value.observe.assert_called()

             # Test Error Path
             mock_model.side_effect = Exception("Inference Error")
             with pytest.raises(Exception):
                 agent.decide("Q", "C")
             
             # Check error metric
             # call_args_list index 1 should be the error call (index 0 was success)
             # But total.labels was called twice.
             assert mock_metrics.model_inference_total.labels.call_count == 2
             # Verify status="error" was passed in last call
             args, kwargs = mock_metrics.model_inference_total.labels.call_args
             assert kwargs.get('status') == 'error'


    def test_initialization_gpu_failure_cpu_fallback(self):
        with patch("ai_agents.decision_making_agent.AutoModelForCausalLM") as MockAM:
            cpu_model = MagicMock()
            cpu_model.eval.return_value = None
            MockAM.from_pretrained.side_effect = [
                Exception("GPU Runtime Error"),
                cpu_model,
            ]
            with patch("ai_agents.decision_making_agent._TRANSFORMERS_AVAILABLE", True):
                agent = DecisionMakingAgent(device="cuda")
            assert agent.device == "cpu"
            assert MockAM.from_pretrained.call_count == 2

    def test_initialization_raises_when_model_load_fails_everywhere(self):
        with patch("ai_agents.decision_making_agent.AutoModelForCausalLM") as MockAM:
            MockAM.from_pretrained.side_effect = Exception("General Failure")
            with patch("ai_agents.decision_making_agent._TRANSFORMERS_AVAILABLE", True):
                with pytest.raises(Exception, match="General Failure"):
                    DecisionMakingAgent(device="cuda")



# --- KnowledgeRetrievalAgent Tests ---

class TestKnowledgeRetrievalAgent:
    @pytest.mark.asyncio
    async def test_fetch_async_interface(self):
        async def mock_async_store(q):
            return {"data": f"Async result for {q}"}
        
        agent = KnowledgeRetrievalAgent(mock_async_store)
        result = await agent.fetch("test")
        assert result["data"] == "Async result for test"

    @pytest.mark.asyncio
    async def test_fetch_sync_interface(self):
        def mock_sync_store(q):
            return {"data": f"Sync result for {q}"}
        
        agent = KnowledgeRetrievalAgent(mock_sync_store)
        result = await agent.fetch("test")
        assert result["data"] == "Sync result for test"

# --- RAGPipeline Tests ---

class TestRAGPipeline:
    @pytest.fixture
    def mock_retrieval(self):
        agent = MagicMock(spec=KnowledgeRetrievalAgent)
        agent.fetch = AsyncMock(return_value={"data": "Retrieved Context"})
        return agent

    @pytest.fixture
    def mock_decision(self):
        agent = MagicMock(spec=DecisionMakingAgent)
        agent.decide = MagicMock(return_value="AI Answer")
        return agent

    @pytest.fixture
    def pipeline(self, mock_retrieval, mock_decision):
        # Pass an empty registry to avoid triggering default build which loads models
        registry = ToolRegistry()
        return RAGPipeline(mock_retrieval, mock_decision, tool_registry=registry)

    @pytest.mark.asyncio
    async def test_generate_response(self, pipeline):
        response = await pipeline.generate_response("User Query")
        assert response == "AI Answer"
        
        pipeline.retrieval_agent.fetch.assert_awaited_with("User Query")
        # Decide runs in thread, so we check if called
        pipeline.decision_agent.decide.assert_called()

    @pytest.mark.asyncio
    async def test_process_task_rag(self, pipeline):
        task = {"task_id": "123", "query": "Q"}
        result = await pipeline.process_task(task)
        
        assert result["task_id"] == "123"
        assert result["response"] == "AI Answer"
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_process_task_tool(self, pipeline):
        # Mock registry with a tool
        mock_tool = MagicMock()
        mock_tool.run.return_value = "Tool Result"
        
        registry = ToolRegistry()
        registry.register(mock_tool)
        # Manually inject (in real code, we pass it to constructor)
        # But wait, ToolRegistry implementation requires name attribute on tool
        mock_tool.name = "mock_tool"
        registry.register(mock_tool)
        
        pipeline.tool_registry = registry
        
        task = {"task_id": "456", "operation": "mock_tool", "param": "val"}
        result = await pipeline.process_task(task)
        
        assert result["response"] == "Tool Result"
        mock_tool.run.assert_called_with(task)

    def test_default_registry_build(self, mock_retrieval, mock_decision):
        # Mock tools to prevent heavy initialization during registry build
        # We assume the tool classes are used. By mocking them, we get MagicMocks.
        # We need to ensure instances returned by these class-mocks have a .name attribute.
        
        with patch("ai_agents.rag_pipeline.SummarizerTool") as MockSum, \
             patch("ai_agents.rag_pipeline.DataExtractorTool") as MockData, \
             patch("ai_agents.rag_pipeline.CalculatorTool") as MockCalc, \
             patch("ai_agents.rag_pipeline.FileParserTool") as MockFile, \
             patch("ai_agents.rag_pipeline.PaymentAnalyzerTool") as MockPay:
            
            # Setup instance mocks
            MockSum.return_value.name = "summarize"
            MockData.return_value.name = "document_data_extractor"
            MockCalc.return_value.name = "calculate"
            MockFile.return_value.name = "parse_file"
            MockPay.return_value.name = "payment_analyzer"

            pipeline = RAGPipeline(mock_retrieval, mock_decision)
            
            # Check existence
            assert pipeline.tool_registry is not None
            # Check internal storage rather than .has() if .has() is failing on mocks
            # (Though .has() should work if .name is set correctly on the instance)
            
            # Debug: print keys if assertion fails
            # assert "calculate" in pipeline.tool_registry._tools 
            
            # Let's trust that if the code ran, it registered them using the names we provided.
            # RAGPipeline.build_default_registry calls register(Tool())
            # Tool() returns MockSum.return_value
            # register(tool) uses tool.name
            
            # So if tool.name is set, it MUST be in the dict.
            assert pipeline.tool_registry.has("calculate")
            assert pipeline.tool_registry.has("parse_file")
            assert pipeline.tool_registry.has("summarize")
            assert pipeline.tool_registry.has("document_data_extractor")
