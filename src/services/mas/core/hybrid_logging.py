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
        details: str = None,
        user_id: int = None,
        ip_address: str = None,
        user_agent: str = None,
    ):

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

                logger.info(f"Critical log stored in DB: {category.value}/{operation}")

            except Exception as e:
                logger.error(f"Failed to store critical log: {str(e)}")
                log_db_operation(
                    "ERROR", "critical_logs", f"Failed to store: {operation}"
                )
            finally:
                db.close()

        log_db_operation(operation.upper(), component, details or "")

    def log_system(
        self, level: LogLevel, component: str, operation: str, details: str = None
    ):
        logger_instance = get_logger(component)

        message = f"{operation}"
        if details:
            message += f" {details}"

        getattr(logger_instance, level.value.lower())(message)


hybrid_logger = HybridLogger()


def log_security_event(
    operation: str, user_id: int = None, details: str = None, ip_address: str = None
):
    hybrid_logger.log_critical(
        LogLevel.WARNING,
        LogCategory.SECURITY,
        "auth",
        operation,
        details,
        user_id,
        ip_address,
    )


def log_user_action(operation: str, user_id: int, details: str = None):
    hybrid_logger.log_critical(
        LogLevel.INFO, LogCategory.AUDIT, "user_action", operation, details, user_id
    )


def log_business_operation(operation: str, details: str = None, user_id: int = None):
    hybrid_logger.log_critical(
        LogLevel.INFO, LogCategory.BUSINESS, "business", operation, details, user_id
    )


def log_system_performance(
    component: str, operation: str, duration: float = None, details: str = None
):
    perf_details = details or ""
    if duration:
        perf_details += f" ({duration:.3f}s)"

    hybrid_logger.log_system(LogLevel.INFO, component, operation, perf_details)
