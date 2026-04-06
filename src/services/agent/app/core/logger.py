"""
Structured logging for the agent service.

Provides structured logging with JSON output support and correlation ID tracking.
"""

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from contextvars import ContextVar

# Context variable for correlation ID
correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add correlation ID if available
        corr_id = correlation_id.get()
        if corr_id:
            log_data["correlation_id"] = corr_id

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        return json.dumps(log_data, default=str)


class AgentLogger:
    """Structured logger for agent service."""

    _loggers: Dict[str, logging.Logger] = {}
    _configured = False

    @classmethod
    def configure(
        cls,
        level: str = "INFO",
        json_output: bool = False,
        log_file: Optional[str] = None,
    ):
        """Configure logging for the agent service."""
        if cls._configured:
            return

        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

        # Remove existing handlers
        root_logger.handlers.clear()

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        if json_output:
            console_handler.setFormatter(StructuredFormatter())
        else:
            console_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)8s] [%(name)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
        root_logger.addHandler(console_handler)

        # File handler if specified
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(StructuredFormatter())
            root_logger.addHandler(file_handler)

        cls._configured = True

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get or create a logger instance."""
        if name not in cls._loggers:
            logger = logging.getLogger(name)
            cls._loggers[name] = logger
        return cls._loggers[name]


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return AgentLogger.get_logger(name)


def set_correlation_id(corr_id: Optional[str]):
    """Set correlation ID for current context."""
    correlation_id.set(corr_id)


def get_correlation_id() -> Optional[str]:
    """Get correlation ID from current context."""
    return correlation_id.get()


# Configure logging on import
import os

json_logging = os.getenv("AGENT_JSON_LOGGING", "false").lower() == "true"
log_level = os.getenv("AGENT_LOG_LEVEL", "INFO")
log_file = os.getenv("AGENT_LOG_FILE")

AgentLogger.configure(level=log_level, json_output=json_logging, log_file=log_file)

