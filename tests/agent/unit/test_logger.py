import json
import logging
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from core.logger import AgentLogger, StructuredFormatter, correlation_id


class TestLoggerCoverage:
    @pytest.fixture(autouse=True)
    def fresh_logger_state(self, monkeypatch):
        monkeypatch.setattr(AgentLogger, "_configured", False)
        monkeypatch.setattr(AgentLogger, "_loggers", {})
        root = logging.getLogger()
        handlers, level = root.handlers[:], root.level
        quieted = {name: logging.getLogger(name).level for name in ("pika", "httpx", "httpcore")}
        yield
        for handler in root.handlers:
            if handler not in handlers:
                handler.close()
        root.handlers[:] = handlers
        root.setLevel(level)
        for name, previous in quieted.items():
            logging.getLogger(name).setLevel(previous)

    def test_structured_formatter_with_exception_and_correlation(self):
        # Set correlation ID
        token = correlation_id.set("test-corr-id-123")

        try:
            formatter = StructuredFormatter()
            record = logging.LogRecord(
                name="test_logger",
                level=logging.ERROR,
                pathname="test.py",
                lineno=10,
                msg="Test error message",
                args=(),
                exc_info=None
            )

            # Simulate exception info
            try:
                raise ValueError("Oops")
            except ValueError:
                record.exc_info = sys.exc_info()

            # Simulate extra fields
            record.extra_fields = {"user_id": "u123", "action": "login"}

            # Format
            json_output = formatter.format(record)
            data = json.loads(json_output)

            # Assertions
            assert data["correlation_id"] == "test-corr-id-123"
            assert data["message"] == "Test error message"
            assert data["level"] == "ERROR"
            assert data["user_id"] == "u123"
            assert "exception" in data
            assert "ValueError: Oops" in data["exception"]

        finally:
            correlation_id.reset(token)

    def test_configure_json_output_and_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            log_file = tmp.name

        # Close the file handle so logging can open it
        # On some OS like Windows this is critical, on Linux less so but good practice

        try:
            # Configure with JSON and file
            AgentLogger.configure(
                level="DEBUG",
                json_output=True,
                log_file=log_file
            )

            logger = AgentLogger.get_logger("test_json")
            logger.info("Test JSON log")

            # Check console handler
            root = logging.getLogger()
            console = [h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]
            assert len(console) > 0
            assert isinstance(console[0].formatter, StructuredFormatter)

            # Check file handler
            file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
            assert len(file_handlers) > 0
            assert file_handlers[0].baseFilename == os.path.abspath(log_file)

            # Verify file content
            # Need to flush first
            for h in root.handlers:
                h.flush()
                h.close() # Close to ensure write to disk

            with open(log_file) as f:
                content = f.read()
                assert "Test JSON log" in content
                assert "{" in content # it is JSON

        finally:
            if os.path.exists(log_file):
                os.remove(log_file)

    def test_configure_plain_text(self):
        AgentLogger.configure(json_output=False)
        root = logging.getLogger()
        console = [h for h in root.handlers if isinstance(h, logging.StreamHandler)][0]
        # Should be standard Formatter not StructuredFormatter
        assert not isinstance(console.formatter, StructuredFormatter)

    def test_get_logger_caching(self):
        l1 = AgentLogger.get_logger("my_logger")
        l2 = AgentLogger.get_logger("my_logger")
        assert l1 is l2

    def test_reconfigure_noop(self):
        AgentLogger.configure(level="INFO")
        handlers_before = list(logging.getLogger().handlers)

        # Subsequent call should do nothing
        AgentLogger.configure(level="DEBUG")
        handlers_after = list(logging.getLogger().handlers)
        # Handler count should stay same
        assert len(handlers_before) == len(handlers_after)
