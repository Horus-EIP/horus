"""JSON-formatted structured logging with correlation ID support for request tracing."""

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Context variable for correlation ID
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def set_correlation_id(corr_id: str | None = None) -> str:
    """Set correlation ID for current context."""
    if corr_id is None:
        corr_id = str(uuid.uuid4())
    correlation_id_var.set(corr_id)
    return corr_id


def get_correlation_id() -> str | None:
    """Get correlation ID from current context."""
    return correlation_id_var.get()


def clear_correlation_id():
    """Clear correlation ID from current context."""
    correlation_id_var.set(None)


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "service": "knowledge-store",
        }

        corr_id = get_correlation_id()
        if corr_id:
            log_data["correlation_id"] = corr_id

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "asctime"
            }:
                try:
                    json.dumps(value)
                    log_data[key] = value
                except (TypeError, ValueError):
                    log_data[key] = str(value)

        return json.dumps(log_data, default=str)


class KnowledgeStoreLogger:
    """Singleton logger for Knowledge Store."""

    _instance = None
    _loggers: dict[str, logging.Logger] = {}
    _configured = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._configured:
            self._configure()
            self._configured = True

    def _configure(self):
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        json_logging = os.getenv("JSON_LOGGING", "true").lower() == "true"
        log_dir = Path(os.getenv("LOG_DIR", "logs"))
        log_dir.mkdir(exist_ok=True)

        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level, logging.INFO))
        root_logger.handlers.clear()

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level, logging.INFO))

        if json_logging:
            console_handler.setFormatter(JSONFormatter())
        else:
            console_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)8s] [%(name)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )

        root_logger.addHandler(console_handler)

        if os.getenv("TEST_MODE") != "1":
            json_log_file = (
                log_dir / f"knowledge_store_{datetime.now().strftime('%Y%m%d')}.json"
            )
            json_handler = logging.FileHandler(json_log_file, encoding="utf-8")
            json_handler.setLevel(logging.DEBUG)
            json_handler.setFormatter(JSONFormatter())
            root_logger.addHandler(json_handler)

    def get_logger(self, name: str) -> logging.Logger:
        if name not in self._loggers:
            self._loggers[name] = logging.getLogger(name)
        return self._loggers[name]


_logger_instance = KnowledgeStoreLogger()


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return _logger_instance.get_logger(name)


def log_document_operation(operation: str, doc_id: str = None, **extra):
    """Log a document operation."""
    logger = get_logger("document")
    logger.info(
        f"Document {operation}: {doc_id or 'N/A'}",
        extra={
            "type": "document_operation",
            "operation": operation,
            "document_id": doc_id,
            **extra
        }
    )


def log_query_operation(query: str, results_count: int, duration_ms: float, **extra):
    """Log a query operation."""
    logger = get_logger("query")
    logger.info(
        f"Query completed: {results_count} results in {duration_ms:.2f}ms",
        extra={
            "type": "query_operation",
            "query_preview": query[:100] if query else None,
            "results_count": results_count,
            "duration_ms": round(duration_ms, 2),
            **extra
        }
    )
