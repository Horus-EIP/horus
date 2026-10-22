import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from core.logger import (
    MASLogger,
    get_logger,
    log_agent_operation,
    log_api_request,
    log_auth_operation,
    log_db_operation,
    log_error,
    log_startup,
    log_success,
    log_warning,
)


class TestMASLogger:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        # Reset singleton before each test
        MASLogger._instance = None
        MASLogger._loggers = {}
        yield
        MASLogger._instance = None
        MASLogger._loggers = {}

    def test_singleton_pattern(self):
        logger1 = MASLogger()
        logger2 = MASLogger()
        assert logger1 is logger2

    def test_initialization(self):
        with (
            patch("core.logger.Path") as mock_path,
            patch("core.logger.structlog.configure") as mock_configure,
            patch("core.logger.logging.FileHandler") as mock_file_handler,
        ):
            logger = MASLogger()
            assert logger._initialized is True
            mock_path.return_value.mkdir.assert_called_with(exist_ok=True)
            mock_configure.assert_called_once()
            # File handlers are skipped in TEST_MODE to avoid ResourceWarning in pytest.
            if os.getenv("TEST_MODE") == "1":
                assert mock_file_handler.call_count == 0
            else:
                assert mock_file_handler.call_count >= 1

    def test_get_logger_creates_new(self):
        mas_logger = MASLogger()
        with patch("core.logger.structlog.get_logger") as mock_structlog_get:
            logger = mas_logger.get_logger("test_component")
            mock_structlog_get.assert_called_with("test_component")
            assert "test_component" in mas_logger._loggers

    def test_get_logger_returns_existing(self):
        mas_logger = MASLogger()
        with patch("core.logger.structlog.get_logger") as mock_structlog_get:
            logger1 = mas_logger.get_logger("test_component")
            logger2 = mas_logger.get_logger("test_component")
            assert (
                mock_structlog_get.call_count == 2
            )  # structlog.get_logger is called every time, but internal logging.Logger is cached

    def test_get_logger_with_level(self):
        mas_logger = MASLogger()
        with patch("core.logger.structlog.get_logger") as mock_structlog_get:
            logger = mas_logger.get_logger("test_component_level", level=logging.DEBUG)
            # Verify that the internal logger had setLevel called
            internal_logger = mas_logger._loggers["test_component_level"]
            assert internal_logger.level == logging.DEBUG

    def test_log_startup(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_startup("test_comp", "starting up")
            mock_logger.info.assert_called_with(
                "startup_event", component="TEST_COMP", message="starting up", icon="🚀"
            )

    def test_log_success(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_success("test_comp", "success msg")
            mock_logger.info.assert_called_with(
                "success_event", component="test_comp", message="success msg", icon="✅"
            )

    def test_log_warning(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_warning("test_comp", "warning msg")
            mock_logger.warning.assert_called_with(
                "warning_event", component="test_comp", message="warning msg", icon="⚠️"
            )

    def test_log_error(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_error("test_comp", "error msg", exc_info=True)
            mock_logger.error.assert_called_with(
                "error_event",
                component="test_comp",
                message="error msg",
                icon="❌",
                exc_info=True,
            )

    def test_log_db_operation(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_db_operation("CREATE", "users", "details")
            mock_logger.info.assert_called_with(
                "db_operations",
                icon="➕",
                operation="CREATE",
                table="users",
                details="details",
            )

    def test_log_db_operation_default_icon(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_db_operation("UNKNOWN", "users", "details")
            mock_logger.info.assert_called_with(
                "db_operations",
                icon="💾",
                operation="UNKNOWN",
                table="users",
                details="details",
            )

    def test_log_auth_operation_success(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_auth_operation("LOGIN", "user1", success=True)
            mock_logger.info.assert_called_with(
                "authentification_event",
                icon="🔐",
                operation="LOGIN",
                details="LOGIN successful for user: user1",
            )

    def test_log_auth_operation_failure(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_auth_operation("LOGIN", "user1", success=False)
            mock_logger.warning.assert_called_with(
                "authentification_event_failure",
                icon="🚫",
                operation="LOGIN",
                details="LOGIN failed for user: user1",
            )

    def test_log_api_request_info(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_api_request("GET", "/api", 200, 100.0)
            mock_logger.info.assert_called_with(
                "api_request",
                icon="✅",
                method="GET",
                endpoint="/api",
                status_code=200,
                duration=" (100.00ms)",
            )

    def test_log_api_request_redirect(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_api_request("GET", "/api", 301, 100.0)
            mock_logger.info.assert_called_with(
                "api_request",
                icon="↩️",
                method="GET",
                endpoint="/api",
                status_code=301,
                duration=" (100.00ms)",
            )

    def test_log_api_request_warning(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_api_request("GET", "/api", 404, 100.0)
            mock_logger.warning.assert_called_with(
                "api_request",
                icon="⚠️",
                method="GET",
                endpoint="/api",
                status_code=404,
                duration=" (100.00ms)",
            )

    def test_log_api_request_error(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_api_request("GET", "/api", 500, 100.0)
            mock_logger.error.assert_called_with(
                "api_request",
                icon="❌",
                method="GET",
                endpoint="/api",
                status_code=500,
                duration=" (100.00ms)",
            )

    def test_log_agent_operation(self):
        mas_logger = MASLogger()
        mock_logger = MagicMock()
        with patch.object(mas_logger, "get_logger", return_value=mock_logger):
            mas_logger.log_agent_operation("agent1", "START", "details")
            mock_logger.info.assert_called_with(
                "agent_operation",
                icon="🤖",
                agent_name="agent1",
                operation="START",
                details="details",
            )

    def test_module_level_functions(self):
        # Test that module level functions call the singleton instance methods
        with patch("core.logger.mas_logger") as mock_instance:
            get_logger("test")
            mock_instance.get_logger.assert_called_with("test")

            log_startup("comp", "msg")
            mock_instance.log_startup.assert_called_with("comp", "msg")

            log_success("comp", "msg")
            mock_instance.log_success.assert_called_with("comp", "msg")

            log_warning("comp", "msg")
            mock_instance.log_warning.assert_called_with("comp", "msg")

            log_error("comp", "msg")
            mock_instance.log_error.assert_called_with("comp", "msg", False)

            log_db_operation("op", "table")
            mock_instance.log_db_operation.assert_called_with("op", "table", "")

            log_auth_operation("op", "user")
            mock_instance.log_auth_operation.assert_called_with("op", "user", True)

            log_api_request("GET", "/api", 200)
            mock_instance.log_api_request.assert_called_with("GET", "/api", 200, None)

            log_agent_operation("agent", "op")
            mock_instance.log_agent_operation.assert_called_with("agent", "op", "")

    def test_colored_formatter(self):
        # Even if unused, we should test it if we want 100% coverage
        from core.logger import ColoredFormatter

        formatter = ColoredFormatter()
        record = logging.LogRecord("name", logging.INFO, "pathname", 1, "msg", None, None)
        formatted = formatter.format(record)
        assert "INFO" in formatted
        assert "msg" in formatted

        # Test with exception
        try:
            raise ValueError("test error")
        except ValueError:
            record.exc_info = sys.exc_info()

        formatted_with_exc = formatter.format(record)
        assert "test error" in formatted_with_exc


import sys
