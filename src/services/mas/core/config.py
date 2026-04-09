"""
Configuration Management Module

This module handles all configuration settings for the MAS application,
loading environment variables and providing centralized configuration access.

Key Configuration Areas:
- Database connection settings (PostgreSQL)
- JWT authentication configuration
- Redis cache configuration
- Initial admin user setup
- Application security settings

Environment Variables:
The application expects the following environment variables:

Database Configuration:
- POSTGRES_USER: PostgreSQL username (required)
- POSTGRES_PASSWORD: PostgreSQL password (required)
- POSTGRES_DB: Database name (required)
- DB_PORT: Database port (must be numeric, required)

Authentication Configuration:
- JWT_SECRET_KEY: Secret key for JWT token signing (required)
- JWT_ALGORITHM: JWT signing algorithm (e.g., HS256, required)

Initial Setup Configuration:
- SUPER_USER_USERNAME: Initial admin user username (required)
- SUPER_USER_PASSWORD: Initial admin user password (required)

Cache Configuration:
- REDIS_PASSWORD: Redis authentication password (required)

Message Queue Configuration:
- RABBITMQ_HOST: RabbitMQ host address (default: localhost)

Application Configuration:
- LLM_AUTOINIT: Flag to auto-initialize LLM (default: 0)

Security Notes:
- All sensitive configuration values should be stored in environment variables
- The .env file should never be committed to version control
- JWT_SECRET_KEY should be a strong, randomly generated secret
- Default passwords should be changed in production environments

Loading Priority:
1. /infra/.env (Docker Compose setup)
2. /services/mas/.env (Standalone MAS execution)
3. /src/.env (Project root for local development)
The first existing .env file found will be loaded.
Environment variables always override .env file values.

Usage:
    Import the settings object from this module:

    from core.config import settings

    Access configuration values via:
    - settings.jwt_secret_key
    - settings.db_port
    - settings.postgres_user
    - etc.
"""

from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
SERVICES_DIR = BASE_DIR.parent
SRC_DIR = SERVICES_DIR.parent
INFRA_DIR = SRC_DIR / "infra"


class Settings(BaseSettings):
    # Database Configuration
    postgres_user: str
    postgres_password: str
    postgres_db: str
    db_port: int = 5432
    db_host: str = "localhost"

    # JWT Authentication Configuration
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"

    # Initial Admin User Configuration
    super_user_username: str
    super_user_password: str

    # Redis Cache Configuration
    redis_password: str
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Message Queue Configuration
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = "guest"

    # Application Configuration
    llm_autoinit: int = 0  # Force 0 for tests
    # When 1, load the orchestrator LLM on CPU even if a GPU is visible (Docker can still pass GPU to other services).
    llm_force_cpu: int = 0

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    # Max wall-clock time for a RUNNING task before MAS cancels it (LLM + agent work).
    # Env: TASK_TIMEOUT or TASK_TIMEOUT_SECONDS (Compose). Default 30m; values like 120 are too low for 4B models.
    task_timeout: int = Field(
        default=1800,
        validation_alias=AliasChoices("TASK_TIMEOUT", "TASK_TIMEOUT_SECONDS"),
    )

    model_config = SettingsConfigDict(
        env_file=INFRA_DIR / ".env" if (INFRA_DIR / ".env").exists() else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


# Initialize settings
# This will raise a ValidationError if required environment variables are missing
try:
    settings = Settings()
except Exception as e:
    print(f"Warning: Configuration validation failed: {e}")

    class DummySettings:
        def __getattr__(self, name):
            return None

    settings = DummySettings()
