"""
Stratégie hybride de logging pour MAS
"""

from enum import Enum

from core.logger import get_logger, log_db_operation
from db.database import SessionLocal
from db.models import CriticalLogs

logger = get_logger("hybrid_logging")


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogCategory(str, Enum):
    SECURITY = "SECURITY"
    AUDIT = "AUDIT"
    BUSINESS = "BUSINESS"
    SYSTEM = "SYSTEM"
    DEBUG = "DEBUG"


class HybridLogger:
    """
    Logger that routes logs to different destinations based on category and severity.

    - Critical logs (SECURITY, AUDIT, BUSINESS) -> Database + File
    - System logs (SYSTEM, DEBUG) -> File only
    """

    CRITICAL_CATEGORIES = {
        LogCategory.SECURITY,
        LogCategory.AUDIT,
        LogCategory.BUSINESS,
    }

    FILE_CATEGORIES = {
        LogCategory.SYSTEM,
        LogCategory.DEBUG,
    }

    def log_critical(
        self,
        level: LogLevel,
        category: LogCategory,
        component: str,
        operation: str,
        details: str | None = None,
        user_id: int | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ):
        """
        Log a critical event to the database and standard logger.

        Args:
            level (LogLevel): Severity level
            category (LogCategory): Event category
            component (str): Source component
            operation (str): Operation name
            details (str): Additional details
            user_id (int): User ID if applicable
            ip_address (str): IP address if applicable
            user_agent (str): User agent if applicable
        """

        if category in self.CRITICAL_CATEGORIES:
            try:
                db = SessionLocal()

                critical_log = CriticalLogs(
                    level=level.value,
                    category=category.value,
                    component=component,
                    operation=operation,
                    details=details,
                    user_id=user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )

                db.add(critical_log)
                db.commit()

                # logger.info(f"Critical log stored in DB: {category.value}/{operation}")
                logger.info(
                    "critical_log_stored", category=category.value, operation=operation
                )

            except Exception as e:
                # logger.error(f"Failed to store critical log: {str(e)}")
                logger.error("critical_log_storage_failed", details=str(e))
                log_db_operation(
                    operation="ERROR",
                    table="critical_logs",
                    details=f"Failed to store: {operation}",
                )
            finally:
                db.close()

        log_db_operation(
            operation=operation.upper(), table=component, details=details or ""
        )

    def log_system(
        self, level: LogLevel, component: str, operation: str, details: str | None = None
    ):
        """
        Log a system event to the standard logger.

        Args:
            level (LogLevel): Severity level
            component (str): Source component
            operation (str): Operation name
            details (str): Additional details
        """
        logger_instance = get_logger(component)

        message = f"{operation}"
        if details:
            message += f" {details}"

        getattr(logger_instance, level.value.lower())("system_log", message=message)


hybrid_logger = HybridLogger()


def log_security_event(
    operation: str, user_id: int | None = None, details: str | None = None, ip_address: str | None = None
):
    """
    Convenience function for logging security events.

    Args:
        operation (str): Security operation (e.g., LOGIN_ATTEMPT)
        user_id (int): User ID involved
        details (str): Details
        ip_address (str): Source IP
    """
    hybrid_logger.log_critical(
        LogLevel.WARNING,
        LogCategory.SECURITY,
        "auth",
        operation,
        details,
        user_id,
        ip_address,
    )


def log_user_action(operation: str, user_id: int, details: str | None = None):
    """
    Convenience function for logging user actions (audit trail).

    Args:
        operation (str): Action name
        user_id (int): User ID
        details (str): Details
    """
    hybrid_logger.log_critical(
        LogLevel.INFO, LogCategory.AUDIT, "user_action", operation, details, user_id
    )


def log_business_operation(operation: str, details: str | None = None, user_id: int | None = None):
    """
    Convenience function for logging business logic events.

    Args:
        operation (str): Business operation name
        details (str): Details
        user_id (int): User ID if applicable
    """
    hybrid_logger.log_critical(
        LogLevel.INFO, LogCategory.BUSINESS, "business", operation, details, user_id
    )


def log_system_performance(
    component: str, operation: str, duration: float | None = None, details: str | None = None
):
    """
    Convenience function for logging system performance metrics.

    Args:
        component (str): Component name
        operation (str): Operation name
        duration (float): Duration in seconds
        details (str): Additional details
    """
    perf_details = details or ""
    if duration:
        perf_details += f" ({duration:.3f}s)"

    hybrid_logger.log_system(LogLevel.INFO, component, operation, perf_details)
