import logging
import os
from pathlib import Path

LOG_LEVELS = {
    "development": logging.DEBUG,
    "testing": logging.INFO,
    "production": logging.WARNING,
}

DEFAULT_LOG_LEVEL = LOG_LEVELS.get(
    os.getenv("ENVIRONMENT", "development"), logging.INFO
)

MODULE_LOG_LEVELS = {
    "auth": logging.INFO,
    "database": logging.INFO,
    "agent": logging.INFO,
    "api": logging.INFO,
    "chat": logging.INFO,
    "task": logging.INFO,
    "conversation": logging.INFO,
    "user": logging.INFO,
    "core": logging.INFO,
}

SQL_LOGGING = os.getenv("SQL_LOGGING", "false").lower() == "true"

LOG_DIR = Path("logs")

LOG_ROTATION = {
    "max_files": 30,
    "max_size_mb": 100,
}

LOG_FORMATS = {
    "console": "%(asctime)s [%(levelname:8s}] [%(name:10s}] %(message)s",
    "file": "%(asctime)s [%(levelname:8s}] [%(name:15s}] [%(filename)s:%(lineno)d] %(message)s",
    "error": "%(asctime)s [%(levelname:8s}] [%(name:15s}] [%(filename)s:%(lineno)d] %(funcName)s() - %(message)s",
}

EXTERNAL_HANDLERS = {
    "syslog": {
        "enabled": os.getenv("SYSLOG_ENABLED", "false").lower() == "true",
        "address": os.getenv("SYSLOG_ADDRESS", "/dev/log"),
        "facility": "local0",
    },
    "email": {
        "enabled": os.getenv("EMAIL_LOGGING", "false").lower() == "true",
        "smtp_server": os.getenv("SMTP_SERVER"),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "username": os.getenv("SMTP_USERNAME"),
        "password": os.getenv("SMTP_PASSWORD"),
        "to_emails": os.getenv("LOG_EMAIL_RECIPIENTS", "").split(","),
        "subject": "MAS Critical Error",
    },
}

LOG_FILTERS = {
    "exclude_healthcheck": True,
    "exclude_static": True,
    "exclude_paths": ["/health", "/metrics", "/favicon.ico"],
}

SECURITY_CONFIG = {
    "mask_sensitive_data": True,
    "sensitive_fields": ["password", "token", "secret", "key", "authorization"],
    "max_log_length": 1000,
}
