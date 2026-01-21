"""
Structured Logging Module - JSON-based logging with correlation ID support.

This module provides structured JSON logging for the MAS application with:
- JSON formatted log output for log aggregation systems
- Correlation ID tracking across requests
- Context variable support for request tracing
- Both console (colored) and JSON file output

Usage:
    from core.structured_logging import get_structured_logger, set_correlation_id
    
    set_correlation_id("request-123")
    logger = get_structured_logger("my_module")
    logger.info("Processing request", extra={"user_id": 42, "action": "login"})
"""

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Context variable for correlation ID - thread-safe and async-safe
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def set_correlation_id(corr_id: Optional[str] = None) -> str:
    """
    Set correlation ID for current context.
    
    Args:
        corr_id: Optional correlation ID. If None, generates a new UUID.
    
    Returns:
        The correlation ID that was set.
    """
    if corr_id is None:
        corr_id = str(uuid.uuid4())
    correlation_id_var.set(corr_id)
    return corr_id


def get_correlation_id() -> Optional[str]:
    """Get correlation ID from current context."""
    return correlation_id_var.get()


def clear_correlation_id():
    """Clear correlation ID from current context."""
    correlation_id_var.set(None)


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging.
    
    Outputs logs as JSON objects with consistent fields for easy parsing
    by log aggregation systems like ELK, Loki, or CloudWatch.
    """
    
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
            "process_id": record.process,
            "thread_id": record.thread,
        }
        
        # Add correlation ID if available
        corr_id = get_correlation_id()
        if corr_id:
            log_data["correlation_id"] = corr_id
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            log_data["exception_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        
        # Add extra fields from record
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "asctime"
            }:
                try:
                    # Ensure value is JSON serializable
                    json.dumps(value)
                    extra_fields[key] = value
                except (TypeError, ValueError):
                    extra_fields[key] = str(value)
        
        if extra_fields:
            log_data["extra"] = extra_fields
        
        return json.dumps(log_data, default=str)


class StructuredLogger:
    """
    Singleton structured logger manager.
    
    Provides centralized logger configuration with support for both
    JSON file output and colored console output.
    """
    
    _instance = None
    _loggers: Dict[str, logging.Logger] = {}
    _configured = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StructuredLogger, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._configured:
            self._configure()
            self._configured = True
    
    def _configure(self):
        """Configure logging handlers."""
        # Get configuration from environment
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        json_logging = os.getenv("JSON_LOGGING", "true").lower() == "true"
        log_dir = Path(os.getenv("LOG_DIR", "logs"))
        log_dir.mkdir(exist_ok=True)
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level, logging.INFO))
        
        # Clear existing handlers
        root_logger.handlers.clear()
        
        # Console handler - colored output for development
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level, logging.INFO))
        
        if json_logging:
            console_handler.setFormatter(JSONFormatter())
        else:
            # Colored console format for development
            from core.logger import ColoredFormatter
            console_handler.setFormatter(ColoredFormatter())
        
        root_logger.addHandler(console_handler)
        
        # JSON file handler - always JSON for log aggregation
        json_log_file = log_dir / f"mas_structured_{datetime.now().strftime('%Y%m%d')}.json"
        json_handler = logging.FileHandler(json_log_file, encoding="utf-8")
        json_handler.setLevel(logging.DEBUG)
        json_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(json_handler)
        
        # Error-only JSON file
        error_log_file = log_dir / f"mas_errors_{datetime.now().strftime('%Y%m%d')}.json"
        error_handler = logging.FileHandler(error_log_file, encoding="utf-8")
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(error_handler)
    
    def get_logger(self, name: str) -> logging.Logger:
        """Get or create a logger instance."""
        if name not in self._loggers:
            self._loggers[name] = logging.getLogger(name)
        return self._loggers[name]


# Module-level singleton instance
_structured_logger = StructuredLogger()


def get_structured_logger(name: str) -> logging.Logger:
    """Get a structured logger instance."""
    return _structured_logger.get_logger(name)


def log_with_context(
    logger: logging.Logger,
    level: int,
    message: str,
    **extra_fields
):
    """
    Log a message with additional context fields.
    
    Args:
        logger: Logger instance
        level: Log level (logging.INFO, logging.ERROR, etc.)
        message: Log message
        **extra_fields: Additional fields to include in the log
    """
    logger.log(level, message, extra=extra_fields)


# Convenience functions for structured logging
def log_request(
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    client_ip: str = None,
    user_id: int = None,
    **extra
):
    """Log an HTTP request with structured fields."""
    logger = get_structured_logger("http")
    logger.info(
        f"{method} {path} -> {status_code}",
        extra={
            "type": "http_request",
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
            "client_ip": client_ip,
            "user_id": user_id,
            **extra
        }
    )


def log_task_event(
    task_id: str,
    event: str,
    agent_id: str = None,
    conversation_id: int = None,
    duration_ms: float = None,
    **extra
):
    """Log a task lifecycle event."""
    logger = get_structured_logger("task")
    logger.info(
        f"Task {event}: {task_id}",
        extra={
            "type": "task_event",
            "task_id": task_id,
            "event": event,
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "duration_ms": round(duration_ms, 2) if duration_ms else None,
            **extra
        }
    )


def log_agent_event(
    agent_id: str,
    event: str,
    agent_name: str = None,
    **extra
):
    """Log an agent lifecycle event."""
    logger = get_structured_logger("agent")
    logger.info(
        f"Agent {event}: {agent_id}",
        extra={
            "type": "agent_event",
            "agent_id": agent_id,
            "event": event,
            "agent_name": agent_name,
            **extra
        }
    )


def log_security_event(
    event: str,
    username: str = None,
    client_ip: str = None,
    success: bool = True,
    **extra
):
    """Log a security-related event."""
    logger = get_structured_logger("security")
    level = logging.INFO if success else logging.WARNING
    logger.log(
        level,
        f"Security {event}: {'success' if success else 'failed'}",
        extra={
            "type": "security_event",
            "event": event,
            "username": username,
            "client_ip": client_ip,
            "success": success,
            **extra
        }
    )
