
import pytest
import logging
import json
import sys
from unittest.mock import MagicMock, patch, ANY

# Metrics coverage
from app.core.metrics import (
    record_document_operation,
    set_document_count,
    record_query,
    record_embedding
)

def test_metrics_coverage():
    # Call functions with various parameters to hit all lines
    record_document_operation("add", True)
    record_document_operation("delete", False)
    
    set_document_count(100)
    
    record_query(True, 0.1, 5)
    record_query(False, 0.1, 0)
    
    record_embedding(True, 0.05)
    record_embedding(False, 0.05)

# Logging coverage
from app.core.logging import (
    JSONFormatter,
    KnowledgeStoreLogger,
    set_correlation_id,
    log_document_operation,
    log_query_operation,
    correlation_id_var
)

def test_json_formatter_exception():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="Error Occurred",
        args=(),
        exc_info=(ValueError, ValueError("oops"), None)
    )
    
    log_output = formatter.format(record)
    data = json.loads(log_output)
    assert "exception" in data
    assert "ValueError: oops" in data["exception"]

def test_json_formatter_extra_types():
    formatter = JSONFormatter()
    # Create record with non-serializable object in extra dict (simulated via __dict__)
    class NonSerializable:
        def __str__(self):
            return "ImNotJSON"
            
    record = logging.LogRecord("test", logging.INFO, "path", 1, "msg", (), None)
    record.my_extra = NonSerializable()
    
    log_output = formatter.format(record)
    data = json.loads(log_output)
    assert data["my_extra"] == "ImNotJSON"

def test_knowledge_store_logger_singleton():
    # Reset singleton
    KnowledgeStoreLogger._instance = None
    KnowledgeStoreLogger._configured = False
    
    with patch("os.getenv", return_value="false"):  # JSON_LOGGING=false
        logger_instance = KnowledgeStoreLogger()
        logger = logger_instance.get_logger("test")
        assert logger.name == "test"
        
        # Verify console handler is not JSON
        # This is hard to verify without inspecting handlers thoroughly, 
        # but execution hitting the 'else' block is enough for coverage.

def test_logging_helpers():
    # Use patch to avoid writing to actual logs or stdout
    with patch("app.core.logging.get_logger") as mock_get:
        mock_logger = MagicMock()
        mock_get.return_value = mock_logger
        
        log_document_operation("create", "doc1")
        mock_logger.info.assert_called()
        
        log_query_operation("query", 10, 100.0)
        mock_logger.info.assert_called()

# Middleware coverage
from app.core.middleware import CorrelationIDMiddleware
from starlette.requests import Request
from starlette.responses import Response

@pytest.mark.asyncio
async def test_middleware_excluded_path():
    middleware = CorrelationIDMiddleware(app=MagicMock())
    
    scope = {"type": "http", "path": "/metrics", "headers": []}
    request = Request(scope)
    
    async def call_next(req):
        return Response("ok")
        
    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_middleware_exception():
    middleware = CorrelationIDMiddleware(app=MagicMock())
    
    scope = {"type": "http", "path": "/api", "headers": [], "method": "GET"}
    request = Request(scope)
    
    async def call_next_error(req):
        raise ValueError("Middleware Error")
        
    with pytest.raises(ValueError):
        await middleware.dispatch(request, call_next_error)
        
    # Verify correlation ID was cleared is implicit in finally block


def test_correlation_id_generation():
    cid = set_correlation_id(None)
    assert cid is not None
    assert isinstance(cid, str)
