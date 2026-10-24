"""Runtime configuration loader for the MAS service.

Reads environment variables (optionally from ``.env``) into a typed
``settings`` object. Variable list and search order live in
``docs/architecture.md``.
"""

from pathlib import Path

from licensing.config import trusted_license_keys
from pydantic import AliasChoices, Field, computed_field, model_validator
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

    license_path: str = Field(
        default="/run/horus/license/license.jws",
        validation_alias=AliasChoices("HORUS_LICENSE_PATH", "LICENSE_PATH"),
    )
    license_kid: str = Field(
        default="horus-prod-v1",
        validation_alias=AliasChoices("HORUS_LICENSE_KID", "LICENSE_KID"),
    )
    license_pubkey_hex: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "HORUS_LICENSE_PUBKEY_HEX",
            "LICENSE_PUBKEY_HEX",
        ),
    )
    site_id: str | None = None

    # Initial Agent Account Configuration
    super_agent_username: str = "agent"
    super_agent_password: str = ""

    @model_validator(mode="after")
    def use_legacy_agent_password(self):
        if not self.super_agent_password:
            self.super_agent_password = self.super_user_password
        return self

    @computed_field
    @property
    def trusted_license_keys(self) -> dict[str, bytes]:
        """Return configured Ed25519 public keys, indexed by JWS key ID."""
        return trusted_license_keys(self.license_kid, self.license_pubkey_hex)

    # Redis Cache Configuration
    redis_password: str
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Message Queue Configuration
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = "guest"

    # Shared task queue prefix: workers consume ``{prefix}.{agent_type}`` (e.g. horus.work.general).
    agent_work_queue_prefix: str = "horus.work"
    work_queue_max_length: int = Field(default=10, ge=1)

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
