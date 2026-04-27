import json
import logging
import uuid
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
import pika
import agent_server.server as server_module

# Ensure app is importable
from agent_server.server import app, _get_orchestrator_token, _consume_messages, send_result, register_agent

client = TestClient(app)

class TestAgentServerComprehensive:
    
    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset global state between tests"""
        server_module._AUTH_TOKEN = None
        server_module.AGENT_ID = None
        server_module.AGENT_API_KEY = None
        yield

    @patch("agent_server.server.requests")
    def test_get_orchestrator_token_cached(self, mock_requests):
        server_module._AUTH_TOKEN = "cached_token"
        token = _get_orchestrator_token()
        assert token == "cached_token"
        mock_requests.post.assert_not_called()

    @patch("agent_server.server.requests")
    def test_get_orchestrator_token_from_env_var(self, mock_requests):
        with patch("agent_server.server.ORCHESTRATOR_TOKEN", "env_token"):
            token = _get_orchestrator_token()
            assert token == "env_token"

    @patch("agent_server.server.requests")
    def test_get_orchestrator_token_via_login_success(self, mock_requests):
        # Setup env vars for username/password
        with patch("agent_server.server.ORCHESTRATOR_TOKEN", None), \
             patch("agent_server.server.ORCHESTRATOR_USERNAME", "user"), \
             patch("agent_server.server.ORCHESTRATOR_PASSWORD", "pass"):
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"access_token": "login_token"}
            mock_requests.post.return_value = mock_response
            
            token = _get_orchestrator_token()
            assert token == "login_token"

    @patch("agent_server.server.requests")
    def test_get_orchestrator_token_via_login_failure(self, mock_requests):
        with patch("agent_server.server.ORCHESTRATOR_TOKEN", None), \
             patch("agent_server.server.ORCHESTRATOR_USERNAME", "user"), \
             patch("agent_server.server.ORCHESTRATOR_PASSWORD", "pass"):
            
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_requests.post.return_value = mock_response
            
            token = _get_orchestrator_token()
            assert token is None

    @patch("agent_server.consumers.pika")
    @patch("agent_server.server.active_agent")
    def test_consume_messages_success_flow(self, mock_active_agent, mock_pika):
        """Test the RabbitMQ consumer loop logic with a simulated message"""
        server_module.AGENT_ID = "test-agent-id"
        
        # Mock Connection and Channel
        mock_connection = MagicMock()
        mock_channel = MagicMock()
        mock_pika.BlockingConnection.return_value = mock_connection
        mock_connection.channel.return_value = mock_channel
        
        # When basic_consume is called, we capture the on_message_callback 
        # and invoke it manually to simulate a received message.
        def capture_callback(queue, on_message_callback):
            self.callback = on_message_callback
        mock_channel.basic_consume.side_effect = capture_callback
        
        # When start_consuming is called, we pass. logic runs once in this test.
        mock_channel.start_consuming.return_value = None

        # Setup Agent Mock
        mock_active_agent.process_task = AsyncMock(return_value={"response": "mock result"})

        # Run _consume_messages
        _consume_messages()
        
        # Now invoke the captured callback
        assert hasattr(self, "callback")
        
        mock_method = MagicMock()
        mock_method.delivery_tag = 1
        mock_props = MagicMock()
        mock_props.headers = {"X-Request-ID": "test-correlation-id"}
        
        body_data = {
            "conversation_id": "conv-1",
            "demand": "Do something", 
            "task_id": "task-1"
        }
        body = json.dumps(body_data).encode("utf-8")
        
        # Mock send_result to verify it's called
        with patch("agent_server.server.send_result") as mock_send_result:
            self.callback(mock_channel, mock_method, mock_props, body)
            
            # Assertions
            mock_active_agent.process_task.assert_called_once()
            call_args = mock_active_agent.process_task.call_args[0][0]
            assert call_args["task_id"] == "task-1"
            assert call_args["query"] == "Do something"
            
            mock_send_result.assert_called_with(
                "mock result",
                "conv-1",
                "task-1",
                assigned_agent_id=None,
                skill_used=None,
            )
            mock_channel.basic_ack.assert_called_with(delivery_tag=1)

    @patch("agent_server.consumers.pika")
    def test_consume_messages_no_agent_id(self, mock_pika):
        server_module.AGENT_ID = None # Ensure unset
        _consume_messages()
        mock_pika.BlockingConnection.assert_not_called()

    @patch("agent_server.consumers.pika")
    def test_consume_messages_connection_error(self, mock_pika):
        server_module.AGENT_ID = "agent-1"
        mock_pika.BlockingConnection.side_effect = Exception("Connection Failed")

        # Should catch exception and log error, not crash
        with patch("agent_server.consumers.logger") as mock_logger:
            _consume_messages()
            mock_logger.error.assert_called()

    @patch("agent_server.consumers.pika")
    @patch("agent_server.server.active_agent")
    def test_consume_messages_bad_payload(self, mock_active_agent, mock_pika):
        server_module.AGENT_ID = "test-agent-id"
        
        mock_connection = MagicMock()
        mock_channel = MagicMock()
        mock_pika.BlockingConnection.return_value = mock_connection
        mock_connection.channel.return_value = mock_channel
        
        def capture_callback(queue, on_message_callback):
            self.callback = on_message_callback
        mock_channel.basic_consume.side_effect = capture_callback

        _consume_messages()
        
        mock_method = MagicMock()
        mock_props = MagicMock()
        
        # Malformed JSON body
        body = b"NOT JSON"
        
        mock_active_agent.process_task = AsyncMock(return_value={"response": "error"})

        self.callback(mock_channel, mock_method, mock_props, body)
        
        # Should fallback to treating body as demand
        mock_active_agent.process_task.assert_called()
        call_args = mock_active_agent.process_task.call_args[0][0]
        assert call_args["query"] == "NOT JSON"

    @patch("agent_server.server.requests")
    def test_send_result(self, mock_requests):
        server_module.AGENT_ID = "agent-1"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_requests.post.return_value = mock_resp

        with patch.object(server_module, "_AUTH_TOKEN", "mock-token"):
            send_result("final result", "conv-1", "task-1")

        mock_requests.post.assert_called_once()
        args = mock_requests.post.call_args
        assert args[1]["json"]["result"] == "final result"
        assert args[1]["json"]["task_id"] == "task-1"

    @patch("agent_server.server.requests")
    def test_register_agent_success(self, mock_requests):
        with patch("agent_server.server.ORCHESTRATOR_URL", "http://orch"):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "agent_id": "new-agent-id",
                "api_key": "new-key"
            }
            mock_requests.post.return_value = mock_resp
            
            register_agent()
            
            assert server_module.AGENT_ID == "new-agent-id"
            assert server_module.AGENT_API_KEY == "new-key"

    @patch("agent_server.server.requests")
    @patch("agent_server.server.time.sleep")
    def test_register_agent_failure(self, mock_sleep, mock_requests):
        # Test failure scenario
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_requests.post.return_value = mock_resp
        
        # Raise KeyboardInterrupt to break the infinite loop (since catch-all catches Exception)
        mock_sleep.side_effect = KeyboardInterrupt("Break loop")
        
        server_module.AGENT_ID = None
        
        with pytest.raises(KeyboardInterrupt):
            register_agent()
            
        assert server_module.AGENT_ID is None

