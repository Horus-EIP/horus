import pytest
import uuid
from fastapi.testclient import TestClient
from unittest.mock import patch, ANY
from agent_server.server import app

client = TestClient(app)

class TestCorrelationMiddleware:
    
    def test_x_request_id_header(self):
        """Test that providing X-Request-ID sets the correlation ID correctly"""
        correlation_id = "test-req-id-123"
        response = client.get("/metrics", headers={"X-Request-ID": correlation_id})
        
        assert response.status_code == 200
        # Verify the response header matches
        assert response.headers.get("X-Request-ID") == correlation_id

    def test_x_correlation_id_header(self):
        """Test that providing X-Correlation-ID works as a fallback"""
        correlation_id = "test-corr-id-456"
        # Only sending X-Correlation-ID
        response = client.get("/metrics", headers={"X-Correlation-ID": correlation_id})
        
        assert response.status_code == 200
        # The middleware unifies on X-Request-ID for the response
        assert response.headers.get("X-Request-ID") == correlation_id

    def test_missing_header_generates_id(self):
        """Test that missing headers result in a generated UUID"""
        response = client.get("/metrics")
        
        assert response.status_code == 200
        generated_id = response.headers.get("X-Request-ID")
        assert generated_id is not None
        # Should look like a valid UUID (basic check)
        assert len(generated_id) > 10 

    def test_explicit_mock_verification(self):
        """
        Verify explicit set_correlation_id call using mocking 
        to ensure the specific code path line 71 is hit.
        """
        cid = "explicit-verification-id"
        
        # We also mock get_correlation_id to ensure specific interaction doesn't cause TypeErrors in headers
        # return_value=cid avoids returning a Mock which httpx.Headers chokes on
        with patch("agent_server.server.set_correlation_id") as mock_set, \
             patch("agent_server.server.get_correlation_id", return_value=cid):
            
            client.get("/metrics", headers={"X-Request-ID": cid})
            
            # Assert data passed to set
            mock_set.assert_called_with(cid)

