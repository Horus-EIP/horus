"""Structured (JSON) logging for the MAS service.

Based on ``structlog`` with correlation-id propagation via contextvars and
daily rotating files under ``logs/``. See
``docs/architecture.md`` for output paths and usage examples.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import colorama
import structlog
from colorama import Fore, Style

colorama.init(autoreset=True)


class ColoredFormatter(logging.Formatter):
    """Color-coded terminal formatter (dev-only; unused in JSON mode)."""

    COLORS = {
        "DEBUG": Fore.CYAN,
        "INFO": Fore.GREEN,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
        "CRITICAL": Fore.MAGENTA + Style.BRIGHT,
    }

    COMPONENT_COLORS = {
        "AUTH": Fore.BLUE,
        "DB": Fore.MAGENTA,
        "AGENT": Fore.CYAN,
        "CHAT": Fore.GREEN,
        "TASK": Fore.YELLOW,
        "CONV": Fore.WHITE,
        "API": Fore.LIGHTBLUE_EX,
        "CORE": Fore.LIGHTMAGENTA_EX,
        "USER": Fore.LIGHTGREEN_EX,
    }

    def format(self, record):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        colored_timestamp = f"{Fore.WHITE}{Style.DIM}[{timestamp}]{Style.RESET_ALL}"

        level_color = self.COLORS.get(record.levelname, Fore.WHITE)
        colored_level = (
            f"{level_color}{Style.BRIGHT}[{record.levelname:8}]{Style.RESET_ALL}"
        )

        module_name = record.name.split(".")[-1].upper()
        component_color = self.COMPONENT_COLORS.get(module_name, Fore.WHITE)
        colored_component = f"{component_color}[{module_name:8}]{Style.RESET_ALL}"

        message = record.getMessage()

        formatted_message = (
            f"{colored_timestamp} {colored_level} {colored_component} {message}"
        )

        if record.exc_info:
            formatted_message += (
                f"\n{Style.DIM}{self.formatException(record.exc_info)}{Style.RESET_ALL}"
            )

        return formatted_message


class MASLogger:
    """Singleton coordinator for structlog-based MAS loggers."""

    _instance = None
    _loggers = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)

        # Configure structlog to use standard library logger
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.dev.set_exc_info,
                structlog.processors.TimeStamper(fmt="iso", utc=False),
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

        self._setup_root_logger()

    def _setup_root_logger(self):
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.handlers.clear()

        # Console Handler - Pretty printing
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.dev.ConsoleRenderer(colors=True)
            )
        )
        root_logger.addHandler(console_handler)

        # File handlers leak open FDs in short-lived pytest processes; skip in TEST_MODE.
        if os.getenv("TEST_MODE") != "1":
            log_file = self.log_dir / f"mas_{datetime.now().strftime('%Y%m%d')}.log"
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                structlog.stdlib.ProcessorFormatter(
                    processor=structlog.processors.JSONRenderer(ensure_ascii=False)
                )
            )
            root_logger.addHandler(file_handler)

            error_file = (
                self.log_dir / f"mas_errors_{datetime.now().strftime('%Y%m%d')}.log"
            )
            error_handler = logging.FileHandler(error_file, encoding="utf-8")
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(
                structlog.stdlib.ProcessorFormatter(
                    processor=structlog.processors.JSONRenderer(ensure_ascii=False)
                )
            )
            root_logger.addHandler(error_handler)

    def get_logger(self, name: str, level: int | None = None) -> logging.Logger:
        """
        Get or create a structlog logger instance with the specified name.
        """
        # Ensure standard logger exists to capture messages
        if name not in self._loggers:
            logger = logging.getLogger(name)
            if level:
                logger.setLevel(level)
            self._loggers[name] = logger

        return structlog.get_logger(name)

    def log_startup(self, component: str, message: str):
        """
        Log a startup event.

        Args:
            component (str): Component name
            message (str): Startup message
        """
        logger = self.get_logger(component)
        logger.info(
            "startup_event", component=component.upper(), message=message, icon="🚀"
        )

    def log_success(self, component: str, message: str):
        """
        Log a success event.

        Args:
            component (str): Component name
            message (str): Success message
        """
        logger = self.get_logger(component)
        logger.info("success_event", component=component, message=message, icon="✅")

    def log_warning(self, component: str, message: str):
        """
        Log a warning event.

        Args:
            component (str): Component name
            message (str): Warning message
        """
        logger = self.get_logger(component)
        logger.warning("warning_event", component=component, message=message, icon="⚠️")

    def log_error(self, component: str, message: str, exc_info=False):
        """
        Log an error event.

        Args:
            component (str): Component name
            message (str): Error message
            exc_info (bool): Whether to include exception info
        """
        logger = self.get_logger(component)
        logger.error(
            "error_event",
            component=component,
            message=message,
            icon="❌",
            exc_info=exc_info,
        )

    def log_db_operation(self, operation: str, table: str, details: str = ""):
        """
        Log a database operation with emoji and formatted details.

        Args:
            operation (str): Operation type (CREATE, READ, UPDATE, DELETE, QUERY, INIT)
            table (str): Table name or entity being operated on
            details (str): Additional operation details

        Example:
            log_db_operation("CREATE", "users", "New user: john_doe")
        """
        logger = self.get_logger("db")
        emoji = {
            "CREATE": "➕",
            "READ": "👁️",
            "UPDATE": "✏️",
            "DELETE": "🗑️",
            "QUERY": "🔍",
            "INIT": "🏗️",
        }.get(operation.upper(), "💾")

        # logger.info(f"{emoji} {operation.upper()} {table} {details}")
        logger.info(
            "db_operations",
            icon=emoji,
            operation=operation.upper(),
            table=table,
            details=details,
        )

    def log_auth_operation(self, operation: str, username: str, success: bool = True):
        """
        Log an authentication operation.

        Args:
            operation (str): Operation type (LOGIN, LOGOUT, REGISTER, TOKEN)
            username (str): Username involved
            success (bool): Whether the operation was successful
        """
        logger = self.get_logger("auth")
        if success:
            emoji = {
                "LOGIN": "🔐",
                "LOGOUT": "🚪",
                "REGISTER": "📝",
                "TOKEN": "🎫",
            }.get(operation.upper(), "🔑")
            description = f"{operation.upper()} successful for user: {username}"
            logger.info(
                "authentification_event",
                icon=emoji,
                operation=operation.upper(),
                details=description,
            )
        else:
            emoji = "🚫"
            description = f"{operation.upper()} failed for user: {username}"
            logger.warning(
                "authentification_event_failure",
                icon=emoji,
                operation=operation.upper(),
                details=description,
            )

    def log_api_request(
        self, method: str, endpoint: str, status_code: int, duration: float = None
    ):
        """
        Log an API request.

        Args:
            method (str): HTTP method
            endpoint (str): Request endpoint
            status_code (int): HTTP status code
            duration (float): Request duration in ms
        """
        logger = self.get_logger("api")

        if 200 <= status_code < 300:
            emoji = "✅"
            level = "info"
        elif 300 <= status_code < 400:
            emoji = "↩️"
            level = "info"
        elif 400 <= status_code < 500:
            emoji = "⚠️"
            level = "warning"
        else:
            emoji = "❌"
            level = "error"

        duration_str = f" ({duration:.2f}ms)" if duration else ""

        getattr(logger, level)(
            "api_request",
            icon=emoji,
            method=method,
            endpoint=endpoint,
            status_code=status_code,
            duration=duration_str,
        )

    def log_agent_operation(self, agent_name: str, operation: str, details: str = ""):
        """
        Log an agent operation.

        Args:
            agent_name (str): Name of the agent
            operation (str): Operation type (START, STOP, HEARTBEAT, TASK, ERROR)
            details (str): Additional details
        """
        logger = self.get_logger("agent")
        emoji = {
            "START": "🤖",
            "STOP": "⏹️",
            "HEARTBEAT": "💓",
            "TASK": "📋",
            "ERROR": "💥",
        }.get(operation.upper(), "🔧")

        logger.info(
            "agent_operation",
            icon=emoji,
            agent_name=agent_name,
            operation=operation.upper(),
            details=details,
        )


mas_logger = MASLogger()


def get_logger(name: str) -> logging.Logger:
    return mas_logger.get_logger(name)


def log_startup(component: str, message: str):
    mas_logger.log_startup(component, message)


def log_success(component: str, message: str):
    mas_logger.log_success(component, message)


def log_warning(component: str, message: str):
    mas_logger.log_warning(component, message)


def log_error(component: str, message: str, exc_info=False):
    mas_logger.log_error(component, message, exc_info)


def log_db_operation(operation: str, table: str, details: str = ""):
    mas_logger.log_db_operation(operation, table, details)


def log_auth_operation(operation: str, username: str, success: bool = True):
    mas_logger.log_auth_operation(operation, username, success)


def log_api_request(
    method: str, endpoint: str, status_code: int, duration: float = None
):
    mas_logger.log_api_request(method, endpoint, status_code, duration)


def log_agent_operation(agent_name: str, operation: str, details: str = ""):
    mas_logger.log_agent_operation(agent_name, operation, details)
