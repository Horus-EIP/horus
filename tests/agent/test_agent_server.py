import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

# Mock spacy to avoid Pydantic/Python 3.14 import errors
sys.modules["spacy"] = MagicMock()
sys.modules["spacy.cli"] = MagicMock()
sys.modules["spacy.language"] = MagicMock()

from agent_server.server import app
import agent_server.server as server_module

client = TestClient(app)

class TestAgentServer:
    
    @pytest.fixture(autouse=True)
    def mock_threading(self):
        """ Prevent background threads from starting during tests """
        with patch("agent_server.server.threading.Thread") as mock_thread:
             yield mock_thread

    @pytest.fixture
    def mock_requests(self):
        with patch("agent_server.server.requests") as mock:
            yield mock

    @pytest.fixture
    def mock_pipeline(self):
        # The pipeline is already instantiated in server.py as active_agent
        mock_pipeline = AsyncMock()
        mock_pipeline.process_task.return_value = {"response": "Mocked Response"}
        
        with patch("agent_server.server.active_agent", mock_pipeline):
            yield mock_pipeline

    def test_startup_event_registration(self, mock_requests):
        # Mock successful registration
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"agent_id": "test-agent-1", "api_key": "secret"}
        mock_requests.post.return_value = mock_response

        # Pre-set auth token so _get_orchestrator_token won't make an extra POST
        with patch.object(server_module, "_AUTH_TOKEN", "mock-token"):
            with TestClient(app) as c:
                pass

        # Verify registration called
        args, kwargs = mock_requests.post.call_args_list[0]
        assert "/agents/register" in args[0]
        assert kwargs["json"]["name"] == server_module.AGENT_NAME

        # Check if global ID was updated
        assert server_module.AGENT_ID == "test-agent-1"

    def test_receive_task_endpoint(self, mock_pipeline, mock_requests):
        # Ensure agent_id is set
        server_module.AGENT_ID = "test-agent-1"
        
        # Mock Orchestrator result callback
        mock_callback_resp = MagicMock()
        mock_callback_resp.status_code = 200
        mock_requests.post.return_value = mock_callback_resp
        
        mock_pipeline.process_task.return_value = {"response": "Processed Result"}

        task_payload = {
            "conversation_id": "conv-123",
            "query": "Test query"
        }
        
        response = client.post("/task", json=task_payload)
        
        assert response.status_code == 200
        assert response.json() == {"agent_id": "test-agent-1", "result": "Processed Result"}
        
        # Verify pipeline request
        mock_pipeline.process_task.assert_called_once()
        call_args = mock_pipeline.process_task.call_args[0][0]
        assert call_args["query"] == "Test query"
        assert call_args["conversation_id"] == "conv-123"
        # Task ID should be auto-generated
        assert "task_id" in call_args

    def test_receive_task_missing_fields(self):
        response = client.post("/task", json={})
        # conversation_id is required
        assert response.status_code == 422 

    def test_send_heartbeat(self, mock_requests):
        server_module.AGENT_ID = "test-agent-1"
        server_module.AGENT_API_KEY = "key"
        
        # Mock successful heartbeat
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}
        mock_requests.post.return_value = mock_resp
        
        with patch.object(server_module, "_AUTH_TOKEN", "mock-token"):
            server_module.send_heartbeat()
            
        mock_requests.post.assert_called()
        
    def test_receive_specialized_task(self, mock_requests):
        # Case: AGENT_TYPE is researcher
        mock_agent = AsyncMock()
        mock_agent.process_request.return_value = "Search Results"
        
        # Patch both the type check inside the function and the active agent instance
        with patch("agent_server.server.AGENT_TYPE", "researcher"), \
             patch("agent_server.server.active_agent", mock_agent):
            
            server_module.AGENT_ID = "research-agent-1"
            
            # Mock Orchestrator result callback
            mock_callback_resp = MagicMock()
            mock_callback_resp.status_code = 200
            mock_requests.post.return_value = mock_callback_resp

            task_payload = {
                "conversation_id": "conv-special",
                "query": "Find something",
                "operation": "search"
            }
            
            response = client.post("/task", json=task_payload)
            
            assert response.status_code == 200
            assert response.json() == {"agent_id": "research-agent-1", "result": "Search Results"}
            
            mock_agent.process_request.assert_called_once()
            # Verify arguments passed to process_request
            call_kwargs = mock_agent.process_request.call_args.kwargs
            assert call_kwargs["task_type"] == "search"
            assert call_kwargs["data"] == "Find something"

    def test_build_headers(self, mock_requests):
        # Setup token
        server_module._AUTH_TOKEN = "test-token"
        
        headers = server_module._build_headers(include_api_key=False)
        assert headers["Authorization"] == "Bearer test-token"
        
        server_module.AGENT_ID = "agent-1"
        server_module.AGENT_API_KEY = "api-key"
        headers_with_key = server_module._build_headers(include_api_key=True)
        assert headers_with_key["X-API-Key"] == "agent-1:api-key"

    def test_send_result_error_handling(self, mock_requests):
        # Simulate network error
        mock_requests.post.side_effect = Exception("Network Error")
        
        # Should not raise exception (caught and logged)
        server_module.send_result("res", "conv", "task")

    def test_receive_task_with_correlation_id(self, mock_pipeline, mock_requests):
        """Test that receive_task endpoint processes correlation ID correctly (Line 438 coverage)"""
        server_module.AGENT_ID = "test-agent-1"
        mock_pipeline.process_task.return_value = {"response": "Processed Result"}
        
        task_payload = {
            "conversation_id": "conv-123",
            "query": "Test query"
        }
        
        cid = "test-corr-id-explicit"
        
        # Patch set_correlation_id specifically in server module to verify the call
        with patch("agent_server.server.set_correlation_id") as mock_set_corr:
            response = client.post("/task", json=task_payload, headers={"X-Request-ID": cid})
            
            assert response.status_code == 200
            # Verify line 438 was hit and executed logic
            mock_set_corr.assert_called_with(cid)

    def test_register_agent_no_api_key(self, mock_requests):
        server_module.AGENT_ID = None
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"agent_id": "test-agent-no-key"} # Missing api_key
        mock_requests.post.return_value = mock_response

        with patch("agent_server.server.time.sleep"):
            server_module.register_agent()

        assert server_module.AGENT_ID == "test-agent-no-key"

    def test_register_agent_conflict_retry(self, mock_requests):
        server_module.AGENT_ID = None
        
        resp_conflict = MagicMock(); resp_conflict.status_code = 409
        resp_success = MagicMock(); resp_success.status_code = 200
        resp_success.json.return_value = {"agent_id": "retry-id", "api_key": "k"}
        
        mock_requests.post.side_effect = [resp_conflict, resp_success]
        
        with patch("agent_server.server.time.sleep"): # Skip sleep
            server_module.register_agent()
            
        assert server_module.AGENT_ID == "retry-id"
        assert mock_requests.post.call_count == 2
        # Verify second call had modified name
        args, kwargs = mock_requests.post.call_args_list[1]
        assert kwargs["json"]["name"] != server_module.AGENT_NAME
        assert kwargs["json"]["name"].startswith(server_module.AGENT_NAME)

    def test_register_agent_failure_retry(self, mock_requests):
        server_module.AGENT_ID = None
        
        resp_fail = MagicMock(); resp_fail.status_code = 500
        resp_fail.text = "Internal Server Error"
        resp_success = MagicMock(); resp_success.status_code = 200
        resp_success.json.return_value = {"agent_id": "fail-retry-id", "api_key": "k"}
        
        mock_requests.post.side_effect = [resp_fail, resp_success]
        
        with patch("agent_server.server.time.sleep"):
            server_module.register_agent()
            
        assert server_module.AGENT_ID == "fail-retry-id"
        assert mock_requests.post.call_count == 2

    def test_register_agent_exception(self, mock_requests):
        server_module.AGENT_ID = None
        
        resp_success = MagicMock(); resp_success.status_code = 200
        resp_success.json.return_value = {"agent_id": "exc-retry-id", "api_key": "k"}
        
        # First call raises Ex, second succeeds
        mock_requests.post.side_effect = [Exception("Network Down"), resp_success]
        
        with patch("agent_server.server.time.sleep"):
            server_module.register_agent()

        assert server_module.AGENT_ID == "exc-retry-id"

    def test_send_heartbeat_no_agent_id(self, mock_requests):
        server_module.AGENT_ID = None
        server_module.send_heartbeat()
        mock_requests.post.assert_not_called()

    def test_send_heartbeat_exception(self, mock_requests):
        server_module.AGENT_ID = "hb-agent"
        mock_requests.post.side_effect = Exception("HB Fail")
        
        # Should not raise
        server_module.send_heartbeat()
        mock_requests.post.assert_called_once()

    def test_send_heartbeat_failure_status(self, mock_requests):
        server_module.AGENT_ID = "hb-agent"
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Error"
        mock_requests.post.return_value = mock_resp
        
        # Should not raise
        server_module.send_heartbeat()
        mock_requests.post.assert_called_once()
        
    def test_heartbeat_task(self):
        with patch("agent_server.server.send_heartbeat") as mock_send, \
             patch("agent_server.server.time.sleep") as mock_sleep:
             
            mock_sleep.side_effect = [None, StopIteration] # Run loop twice then break
            
            try:
                server_module.heartbeat_task()
            except StopIteration:
                pass
            
            assert mock_send.call_count == 2

