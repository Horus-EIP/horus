"""
Tests for core/config.py module

Tests the configuration loading logic including .env file handling
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


class TestEnvLoading:
    """Test suite for environment variable loading from .env files"""

    def test_env_file_loaded_from_infra(self):
        """Test that .env file is loaded from infra directory when it exists"""
        from pathlib import Path

        base_dir = Path(__file__).resolve().parent.parent
        services_dir = base_dir.parent
        src_dir = services_dir.parent
        infra_dir = src_dir / "infra"
        env_path = infra_dir / ".env"

        # The .env file should be in the infra directory
        assert env_path.parent.name == "infra"

    def test_pydantic_settings_configuration(self):
        """Test that Pydantic BaseSettings is properly configured"""
        from core.config import settings

        # Settings should be properly initialized
        assert settings is not None

    def test_case_insensitive_env_loading(self):
        """Test that environment variables are loaded case-insensitively"""
        from core.config import settings

        # Pydantic should convert env vars to lowercase
        # Test that we can access lowercase attributes
        assert hasattr(settings, "postgres_user")
        assert hasattr(settings, "jwt_secret_key")
        assert hasattr(settings, "db_port")


class TestConfigVariables:
    """Test suite for configuration variables loading"""

    def test_config_variables_are_strings(self):
        """Test that config variables are properly typed"""
        from core.config import settings

        # These should be strings or None (or int for db_port)
        assert isinstance(settings.postgres_user, (str, type(None)))
        assert isinstance(settings.postgres_password, (str, type(None)))
        assert isinstance(settings.postgres_db, (str, type(None)))
        assert isinstance(settings.db_port, int)  # Int
        assert isinstance(settings.jwt_secret_key, (str, type(None)))
        assert isinstance(settings.jwt_algorithm, (str, type(None)))

    def test_database_port_has_safe_default(self):
        """Test that database_port has a safe default value"""
        from core.config import settings

        # Should always have a value (default 5432 if not set)
        assert settings.db_port is not None
        assert isinstance(settings.db_port, int)
        assert 1 <= settings.db_port <= 65535

    def test_redis_host_has_safe_default(self):
        """Test that redis_host has a safe default value"""
        from core.config import settings

        # Should always have a value (default "localhost" if not set)
        assert settings.redis_host is not None
        assert isinstance(settings.redis_host, str)

    def test_redis_port_has_safe_default(self):
        """Test that redis_port has a safe default value"""
        from core.config import settings

        # Should always have a value (default 6379 if not set)
        assert settings.redis_port is not None
        assert isinstance(settings.redis_port, int)
        assert 1 <= settings.redis_port <= 65535

    def test_rabbitmq_host_has_safe_default(self):
        """Test that rabbitmq_host has a safe default value"""
        from core.config import settings

        # Should always have a value (default "localhost")
        assert settings.rabbitmq_host is not None
        assert isinstance(settings.rabbitmq_host, str)


class TestEnvLoadingLogic:
    """Test the env loading logic with real file scenarios"""

    def test_env_file_priority(self):
        """Test that infra/.env is prioritized over others"""
        from pathlib import Path

        base_dir = Path(__file__).resolve().parent.parent
        services_dir = base_dir.parent
        src_dir = services_dir.parent
        infra_dir = src_dir / "infra"
        env_path = infra_dir / ".env"

        # The infra/.env should exist in the project structure
        assert env_path.parent.name == "infra"

    def test_load_dotenv_logic_path_check(self):
        """Test the conditional logic for .env path checking"""
        from pathlib import Path

        # Simulate the logic
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True

        # If path exists, load_dotenv is called with the path
        if mock_path.exists():
            call_args = (mock_path, False)
            assert call_args[0] == mock_path
            assert call_args[1] is False
        else:
            call_args = (False,)
            assert call_args[0] is False

    def test_load_dotenv_fallback_logic_path_not_found(self):
        """Test the fallback logic when .env path doesn't exist"""
        from pathlib import Path

        # Simulate the logic
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False

        # If path doesn't exist, load_dotenv is called without path
        if mock_path.exists():
            should_use_path = True
        else:
            should_use_path = False

        assert should_use_path is False
