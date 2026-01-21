"""
Tests for hybrid logging functionality
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from core.hybrid_logging import (HybridLogger, LogCategory, LogLevel,
                                 hybrid_logger, log_business_operation,
                                 log_security_event, log_system_performance,
                                 log_user_action)


class TestLogEnums:
    """Test the logging enums"""

    def test_log_level_values(self):
        assert LogLevel.DEBUG == "DEBUG"
        assert LogLevel.INFO == "INFO"
        assert LogLevel.WARNING == "WARNING"
        assert LogLevel.ERROR == "ERROR"
        assert LogLevel.CRITICAL == "CRITICAL"

    def test_log_category_values(self):
        assert LogCategory.SECURITY == "SECURITY"
        assert LogCategory.AUDIT == "AUDIT"
        assert LogCategory.BUSINESS == "BUSINESS"
        assert LogCategory.SYSTEM == "SYSTEM"
        assert LogCategory.DEBUG == "DEBUG"


class TestHybridLogger:
    """Test the HybridLogger class"""

    def test_critical_categories_configuration(self):
        logger = HybridLogger()
        expected_critical = {
            LogCategory.SECURITY,
            LogCategory.AUDIT,
            LogCategory.BUSINESS,
        }
        assert logger.CRITICAL_CATEGORIES == expected_critical

    def test_file_categories_configuration(self):
        logger = HybridLogger()
        expected_file = {
            LogCategory.SYSTEM,
            LogCategory.DEBUG,
        }
        assert logger.FILE_CATEGORIES == expected_file

    @patch("core.hybrid_logging.SessionLocal")
    @patch("core.hybrid_logging.log_db_operation")
    @patch("core.hybrid_logging.logger")
    def test_log_critical_stores_in_database_for_critical_categories(
        self, mock_logger, mock_log_db_operation, mock_session_local
    ):
        """Test that critical categories are stored in database"""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        logger_instance = HybridLogger()

        logger_instance.log_critical(
            LogLevel.ERROR,
            LogCategory.SECURITY,
            "auth",
            "login_attempt",
            "Failed login for user admin",
            user_id=1,
            ip_address="192.168.1.1",
            user_agent="TestAgent",
        )

        # Verify database operations
        mock_session_local.assert_called_once()
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

        # Verify log operation was called
        mock_log_db_operation.assert_called_once_with(
            "LOGIN_ATTEMPT", "auth", "Failed login for user admin"
        )

    @patch("core.hybrid_logging.SessionLocal")
    @patch("core.hybrid_logging.log_db_operation")
    @patch("core.hybrid_logging.logger")
    def test_log_critical_handles_database_error(
        self, mock_logger, mock_log_db_operation, mock_session_local
    ):
        """Test error handling when database operation fails"""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_db.commit.side_effect = Exception("Database error")

        logger_instance = HybridLogger()

        logger_instance.log_critical(
            LogLevel.ERROR,
            LogCategory.SECURITY,
            "auth",
            "login_attempt",
            "Failed login",
            user_id=1,
        )

        # Verify error was logged
        mock_logger.error.assert_called_once()
        assert "Failed to store critical log" in str(mock_logger.error.call_args)

        # Verify database was still closed
        mock_db.close.assert_called_once()

    @patch("core.hybrid_logging.log_db_operation")
    def test_log_critical_skips_database_for_non_critical_categories(
        self, mock_log_db_operation
    ):
        """Test that non-critical categories don't go to database"""
        with patch("core.hybrid_logging.SessionLocal") as mock_session_local:
            logger_instance = HybridLogger()

            logger_instance.log_critical(
                LogLevel.INFO, LogCategory.SYSTEM, "system", "startup", "System started"
            )

            # Database should not be accessed
            mock_session_local.assert_not_called()

            # But operation should still be logged
            mock_log_db_operation.assert_called_once_with(
                "STARTUP", "system", "System started"
            )

    @patch("core.hybrid_logging.get_logger")
    def test_log_system_uses_appropriate_logger_level(self, mock_get_logger):
        """Test that system logging uses correct logger and level"""
        mock_logger_instance = MagicMock()
        mock_get_logger.return_value = mock_logger_instance

        logger_instance = HybridLogger()

        logger_instance.log_system(
            LogLevel.WARNING, "test_component", "test_operation", "test details"
        )

        mock_get_logger.assert_called_once_with("test_component")
        mock_logger_instance.warning.assert_called_once_with(
            "test_operation test details"
        )

    @patch("core.hybrid_logging.get_logger")
    def test_log_system_without_details(self, mock_get_logger):
        """Test system logging without details"""
        mock_logger_instance = MagicMock()
        mock_get_logger.return_value = mock_logger_instance

        logger_instance = HybridLogger()

        logger_instance.log_system(LogLevel.INFO, "test_component", "test_operation")

        mock_logger_instance.info.assert_called_once_with("test_operation")


class TestConvenienceFunctions:
    """Test the convenience logging functions"""

    @patch.object(hybrid_logger, "log_critical")
    def test_log_security_event(self, mock_log_critical):
        """Test security event logging"""
        log_security_event(
            "suspicious_login",
            user_id=123,
            details="Multiple failed attempts",
            ip_address="192.168.1.100",
        )

        mock_log_critical.assert_called_once_with(
            LogLevel.WARNING,
            LogCategory.SECURITY,
            "auth",
            "suspicious_login",
            "Multiple failed attempts",
            123,
            "192.168.1.100",
        )

    @patch.object(hybrid_logger, "log_critical")
    def test_log_user_action(self, mock_log_critical):
        """Test user action logging"""
        log_user_action(
            "file_download", user_id=456, details="Downloaded sensitive.pdf"
        )

        mock_log_critical.assert_called_once_with(
            LogLevel.INFO,
            LogCategory.AUDIT,
            "user_action",
            "file_download",
            "Downloaded sensitive.pdf",
            456,
        )

    @patch.object(hybrid_logger, "log_critical")
    def test_log_business_operation(self, mock_log_critical):
        """Test business operation logging"""
        log_business_operation(
            "order_created", details="Order #12345 for $100", user_id=789
        )

        mock_log_critical.assert_called_once_with(
            LogLevel.INFO,
            LogCategory.BUSINESS,
            "business",
            "order_created",
            "Order #12345 for $100",
            789,
        )

    @patch.object(hybrid_logger, "log_system")
    def test_log_system_performance_with_duration(self, mock_log_system):
        """Test system performance logging with duration"""
        log_system_performance(
            "database", "query_execution", duration=1.234, details="SELECT query"
        )

        mock_log_system.assert_called_once_with(
            LogLevel.INFO, "database", "query_execution", "SELECT query (1.234s)"
        )

    @patch.object(hybrid_logger, "log_system")
    def test_log_system_performance_without_duration(self, mock_log_system):
        """Test system performance logging without duration"""
        log_system_performance("cache", "cache_hit", details="Redis cache")

        mock_log_system.assert_called_once_with(
            LogLevel.INFO, "cache", "cache_hit", "Redis cache"
        )

    @patch.object(hybrid_logger, "log_system")
    def test_log_system_performance_minimal_params(self, mock_log_system):
        """Test system performance logging with minimal parameters"""
        log_system_performance("api", "request_processed")

        mock_log_system.assert_called_once_with(
            LogLevel.INFO, "api", "request_processed", ""
        )


class TestIntegration:
    """Integration tests for hybrid logging"""

    @patch("core.hybrid_logging.SessionLocal")
    @patch("core.hybrid_logging.CriticalLogs")
    def test_critical_log_creation_with_all_fields(
        self, mock_critical_logs, mock_session_local
    ):
        """Test that CriticalLogs is created with all provided fields"""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_log_instance = MagicMock()
        mock_critical_logs.return_value = mock_log_instance

        hybrid_logger.log_critical(
            LogLevel.CRITICAL,
            LogCategory.SECURITY,
            "authentication",
            "brute_force_detected",
            "100 failed attempts in 1 minute",
            user_id=999,
            ip_address="10.0.0.1",
            user_agent="Evil-Bot/1.0",
        )

        mock_critical_logs.assert_called_once_with(
            level="CRITICAL",
            category="SECURITY",
            component="authentication",
            operation="brute_force_detected",
            details="100 failed attempts in 1 minute",
            user_id=999,
            ip_address="10.0.0.1",
            user_agent="Evil-Bot/1.0",
        )

        mock_db.add.assert_called_once_with(mock_log_instance)
