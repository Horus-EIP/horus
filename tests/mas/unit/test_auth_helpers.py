"""
Tests for auth tool functions
"""

import time
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from jose import jwt
from starlette import status

from auth.auth_tool_functions import (
    authenticate_user,
    create_access_token,
    get_current_user,
    get_current_user_from_token,
    hash_api_key,
    modify_user_password,
    verify_agent_api_key,
)
from core.config import settings
from db.models import Agents
from unit.password_test_helpers import (
    hash_password,
    verify_password,
)


class TestAuthenticateUser:
    """Test user authentication functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_db = MagicMock()
        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.mock_user.username = "testuser"
        self.mock_user.hashed_password = hash_password("password123").decode("ascii")

    @patch("auth.auth_tool_functions.log_auth_operation")
    @patch("auth.auth_tool_functions.log_security_event")
    def test_authenticate_user_success(self, mock_log_security, mock_log_auth):
        """Test successful user authentication."""
        self.mock_db.query().filter().first.return_value = self.mock_user

        result = authenticate_user("testuser", "password123", self.mock_db, "127.0.0.1")

        assert result == self.mock_user
        mock_log_auth.assert_called_with("LOGIN", "testuser", success=True)
        mock_log_security.assert_called_with(
            "LOGIN_SUCCESS",
            user_id=1,
            details="Successful login: testuser",
            ip_address="127.0.0.1",
        )

    @patch("auth.auth_tool_functions.log_auth_operation")
    @patch("auth.auth_tool_functions.log_security_event")
    def test_authenticate_user_supports_passwords_longer_than_bcrypt_limit(
        self, mock_log_security, mock_log_auth
    ):
        password = "p" * 200
        self.mock_user.hashed_password = hash_password(password).decode("ascii")
        self.mock_db.query().filter().first.return_value = self.mock_user

        result = authenticate_user("testuser", password, self.mock_db)

        assert result == self.mock_user
        mock_log_auth.assert_called_with("LOGIN", "testuser", success=True)

    @patch("auth.auth_tool_functions.log_auth_operation")
    @patch("auth.auth_tool_functions.log_security_event")
    def test_authenticate_user_not_found(self, mock_log_security, mock_log_auth):
        """Test authentication with non-existent user."""
        self.mock_db.query().filter().first.return_value = None

        result = authenticate_user(
            "nonexistent", "password123", self.mock_db, "127.0.0.1"
        )

        assert result is False
        mock_log_auth.assert_called_with("LOGIN", "nonexistent", success=False)
        mock_log_security.assert_called_with(
            "LOGIN_USER_NOT_FOUND",
            details="Unknown user: nonexistent",
            ip_address="127.0.0.1",
        )

    @patch("auth.auth_tool_functions.log_auth_operation")
    @patch("auth.auth_tool_functions.log_security_event")
    def test_authenticate_user_invalid_password(self, mock_log_security, mock_log_auth):
        """Test authentication with invalid password."""
        self.mock_db.query().filter().first.return_value = self.mock_user

        result = authenticate_user(
            "testuser", "wrongpassword", self.mock_db, "127.0.0.1"
        )

        assert result is False
        mock_log_auth.assert_called_with("LOGIN", "testuser", success=False)
        mock_log_security.assert_called_with(
            "LOGIN_INVALID_PASSWORD",
            user_id=1,
            details="Invalid password for: testuser",
            ip_address="127.0.0.1",
        )

    @patch("auth.auth_tool_functions.log_auth_operation")
    @patch("auth.auth_tool_functions.log_security_event")
    def test_authenticate_user_without_ip_address(
        self, mock_log_security, mock_log_auth
    ):
        """Test authentication without IP address."""
        self.mock_db.query().filter().first.return_value = self.mock_user

        result = authenticate_user("testuser", "password123", self.mock_db)

        assert result == self.mock_user
        mock_log_security.assert_called_with(
            "LOGIN_SUCCESS",
            user_id=1,
            details="Successful login: testuser",
            ip_address=None,
        )

    @patch("auth.auth_tool_functions.log_auth_operation")
    @patch("auth.auth_tool_functions.log_security_event")
    def test_authenticate_user_table_not_exist(self, mock_log_security, mock_log_auth):
        """Test authentication when Users table does not exist."""
        from sqlalchemy.exc import ProgrammingError

        # Mock the query to raise ProgrammingError
        # The error needs to be raised when first() is called
        self.mock_db.query().filter().first.side_effect = ProgrammingError(
            "SELECT ...", {}, None
        )

        result = authenticate_user("testuser", "password", self.mock_db)

        assert result is False


class TestCreateAccessToken:
    """Test JWT token creation functionality."""

    @patch("auth.auth_tool_functions.log_auth_operation")
    def test_create_access_token_success(self, mock_log_auth):
        """Test successful token creation."""
        expires_delta = timedelta(hours=1)

        token = create_access_token("testuser", 1, expires_delta, "user")

        # Decode token to verify contents
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )

        assert payload["sub"] == "testuser"
        assert payload["id"] == 1
        assert payload["role"] == "user"
        assert "nonce" in payload
        assert "exp" in payload
        assert "iat" in payload
        assert "nbf" in payload

        mock_log_auth.assert_called_with("TOKEN", "testuser", success=True)

    @patch("auth.auth_tool_functions.log_auth_operation")
    def test_create_access_token_admin_role(self, mock_log_auth):
        """Test token creation with admin role."""
        expires_delta = timedelta(hours=1)

        token = create_access_token("adminuser", 2, expires_delta, "admin")

        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )

        assert payload["sub"] == "adminuser"
        assert payload["id"] == 2
        assert payload["role"] == "admin"

    def test_create_access_token_expiration(self):
        """Test token expiration time is correctly set."""
        expires_delta = timedelta(minutes=30)
        before_creation = datetime.now(UTC)

        token = create_access_token("testuser", 1, expires_delta, "user")

        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        token_exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        expected_exp = before_creation + expires_delta

        time_diff = abs((token_exp - expected_exp).total_seconds())
        assert time_diff < 5  # same clock, UTC numeric dates


class TestGetCurrentUser:
    """Test current user retrieval from token."""

    def setup_method(self):
        """Set up valid token for tests."""
        self.valid_payload = {
            "sub": "testuser",
            "id": 1,
            "role": "user",
            "nonce": "test-nonce-123",
            "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
            "iat": int(time.time()),
            "nbf": int(datetime.now().timestamp()),
        }
        self.valid_token = jwt.encode(
            self.valid_payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        self.mock_db = MagicMock()
        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.mock_user.username = "testuser"
        self.mock_user.role = "user"
        self.mock_db.query.return_value.filter.return_value.first.return_value = (
            self.mock_user
        )

    @patch("auth.auth_tool_functions.redis_db")
    def test_get_current_user_success(self, mock_redis):
        """Test successful user retrieval from valid token."""
        mock_redis.exists.return_value = False

        result = get_current_user(self.valid_token, self.mock_db)

        assert result["username"] == "testuser"
        assert result["id"] == 1
        assert result["nonce"] == "test-nonce-123"
        assert result["exp"] == self.valid_payload["exp"]
        assert result["role"] == "user"

    @patch("auth.auth_tool_functions.redis_db")
    def test_get_current_user_revoked_token(self, mock_redis):
        """Test user retrieval with revoked token."""
        mock_redis.exists.return_value = True

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(self.valid_token, self.mock_db)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Token revoked"

    def test_get_current_user_invalid_token(self):
        """Test user retrieval with invalid token."""
        invalid_token = "invalid.token.here"

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(invalid_token, self.mock_db)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Could not validate user"

    def test_get_current_user_missing_username(self):
        """Test user retrieval with token missing username."""
        payload_without_username = {
            "id": 1,
            "role": "user",
            "nonce": "test-nonce-123",
            "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(
            payload_without_username,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(token, self.mock_db)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Could not validate user"

    def test_get_current_user_missing_user_id(self):
        """Test user retrieval with token missing user ID."""
        payload_without_id = {
            "sub": "testuser",
            "role": "user",
            "nonce": "test-nonce-123",
            "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(
            payload_without_id,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(token, self.mock_db)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Could not validate user"


class TestGetCurrentUserFromToken:
    """Test user info extraction from token string."""

    def setup_method(self):
        """Set up valid token for tests."""
        self.valid_payload = {
            "sub": "testuser",
            "id": 1,
            "role": "user",
            "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
        }
        self.valid_token = jwt.encode(
            self.valid_payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

    def test_get_current_user_from_token_success(self):
        """Test successful user info extraction from token."""
        result = get_current_user_from_token(self.valid_token)

        assert result["username"] == "testuser"
        assert result["id"] == 1
        assert result["payload"] == self.valid_payload

    def test_get_current_user_from_token_invalid_token(self):
        """Test user info extraction from invalid token."""
        invalid_token = "invalid.token.here"

        with pytest.raises(Exception):  # JWTError
            get_current_user_from_token(invalid_token)

    def test_get_current_user_from_token_missing_username(self):
        """Test user info extraction from token missing username."""
        payload_without_username = {
            "id": 1,
            "role": "user",
            "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(
            payload_without_username,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

        with pytest.raises(Exception):  # JWTError
            get_current_user_from_token(token)

    def test_get_current_user_from_token_missing_user_id(self):
        """Test user info extraction from token missing user ID."""
        payload_without_id = {
            "sub": "testuser",
            "role": "user",
            "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(
            payload_without_id,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

        with pytest.raises(Exception):  # JWTError
            get_current_user_from_token(token)


class TestPasswordHashing:
    """Test password hashing functionality."""

    def test_bcrypt_hash_and_verify(self):
        """Test password hashing and verification."""
        password = "test_password_123"

        # Hash the password
        hashed = hash_password(password)

        # Verify the password
        assert verify_password(password, hashed) is True
        assert verify_password("wrong_password", hashed) is False

    def test_bcrypt_hashes_are_salted(self):
        """Test that same password produces different hashes."""
        password = "test_password_123"

        hash1 = hash_password(password)
        hash2 = hash_password(password)

        # Hashes should be different (due to salt)
        assert hash1 != hash2

        # But both should verify correctly
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True


class TestModifyUserPassword:
    """Test password modification functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_db = MagicMock()
        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.mock_user.username = "testuser"
        self.mock_user.hashed_password = hash_password("old_password").decode("ascii")

    @patch("auth.auth_tool_functions.log_auth_operation")
    @patch("auth.auth_tool_functions.log_security_event")
    def test_modify_user_password_success(self, mock_log_security, mock_log_auth):
        """Test successful password modification."""
        self.mock_db.query().filter().first.return_value = self.mock_user

        result = modify_user_password(
            "testuser", "old_password", "new_password", self.mock_db
        )

        assert result is True
        assert verify_password("new_password", self.mock_user.hashed_password)
        self.mock_db.commit.assert_called_once()

    @patch("auth.auth_tool_functions.log_auth_operation")
    @patch("auth.auth_tool_functions.log_security_event")
    def test_modify_user_password_user_not_found(
        self, mock_log_security, mock_log_auth
    ):
        """Test password modification with non-existent user."""
        self.mock_db.query().filter().first.return_value = None

        result = modify_user_password(
            "nonexistent", "old_password", "new_password", self.mock_db
        )

        assert result is False
        mock_log_auth.assert_called_with("LOGIN", "nonexistent", success=False)
        mock_log_security.assert_called_with(
            "LOGIN_USER_NOT_FOUND",
            details="Unknown user: nonexistent",
        )
        self.mock_db.commit.assert_not_called()

    @patch("auth.auth_tool_functions.log_auth_operation")
    @patch("auth.auth_tool_functions.log_security_event")
    def test_modify_user_password_invalid_old_password(
        self, mock_log_security, mock_log_auth
    ):
        """Test password modification with invalid old password."""
        self.mock_db.query().filter().first.return_value = self.mock_user

        result = modify_user_password(
            "testuser", "wrong_password", "new_password", self.mock_db
        )

        assert result is False
        mock_log_auth.assert_called_with("LOGIN", "testuser", success=False)
        mock_log_security.assert_called_with(
            "LOGIN_INVALID_PASSWORD",
            user_id=1,
            details="Invalid password for: testuser",
        )
        self.mock_db.commit.assert_not_called()
        # Password should remain unchanged
        assert verify_password("old_password", self.mock_user.hashed_password)

    def test_modify_user_password_db_error(self):
        """Test password modification with database error."""
        self.mock_db.query().filter().first.return_value = self.mock_user

        # Mock the commit to raise an exception
        # We need to mock the exception structure to match what the code expects (e.orig)
        mock_exception = Exception("DB Error")
        mock_exception.orig = Exception("Constraint violation")
        self.mock_db.commit.side_effect = mock_exception

        with pytest.raises(HTTPException) as exc_info:
            modify_user_password(
                "testuser", "old_password", "new_password", self.mock_db
            )

        assert exc_info.value.status_code == 409
        assert "User Password Modification Error" in exc_info.value.detail
        self.mock_db.rollback.assert_called_once()

    @patch("auth.auth_tool_functions.log_auth_operation")
    @patch("auth.auth_tool_functions.log_security_event")
    def test_modify_user_password_table_not_exist(
        self, mock_log_security, mock_log_auth
    ):
        """Test password modification when Users table does not exist."""
        from sqlalchemy.exc import ProgrammingError

        # Mock the query to raise ProgrammingError
        self.mock_db.query().filter().first.side_effect = ProgrammingError(
            "SELECT ...", {}, None
        )

        result = modify_user_password(
            "testuser", "old_password", "new_password", self.mock_db
        )

        assert result is False


class TestAgentAuthentication:
    """Test agent authentication functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_db = MagicMock()
        self.mock_agent = MagicMock(spec=Agents)
        self.mock_agent.id = "test-agent-id"
        self.mock_agent.api_key = hash_password("valid-api-key").decode("ascii")

    @patch("auth.auth_tool_functions.log_security_event")
    def test_verify_agent_api_key_success(self, mock_log_security):
        """Test successful API key verification."""
        self.mock_db.query().filter().first.return_value = self.mock_agent

        agent_id = "test-agent-id"
        api_key = "valid-api-key"
        header_value = f"{agent_id}:{api_key}"

        result = verify_agent_api_key(header_value, self.mock_db)

        assert result == (agent_id, api_key)

    @patch("auth.auth_tool_functions.log_security_event")
    def test_verify_agent_api_key_invalid_format(self, mock_log_security):
        """Test API key with invalid format."""
        header_value = "invalid-format-no-colon"

        with pytest.raises(HTTPException) as exc_info:
            verify_agent_api_key(header_value, self.mock_db)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid API key format" in exc_info.value.detail

    @patch("auth.auth_tool_functions.log_security_event")
    def test_verify_agent_api_key_agent_not_found(self, mock_log_security):
        """Test API key for non-existent agent."""
        self.mock_db.query().filter().first.return_value = None

        header_value = "unknown-agent:some-key"

        with pytest.raises(HTTPException) as exc_info:
            verify_agent_api_key(header_value, self.mock_db)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid API key" in exc_info.value.detail
        mock_log_security.assert_called_with(
            "AGENT_API_KEY_INVALID",
            details="Invalid API key provided",
        )

    @patch("auth.auth_tool_functions.log_security_event")
    def test_verify_agent_api_key_wrong_key(self, mock_log_security):
        """Test incorrect API key for existing agent."""
        self.mock_db.query().filter().first.return_value = self.mock_agent

        agent_id = "test-agent-id"
        api_key = "wrong-key"
        header_value = f"{agent_id}:{api_key}"

        with pytest.raises(HTTPException) as exc_info:
            verify_agent_api_key(header_value, self.mock_db)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid API key" in exc_info.value.detail
        mock_log_security.assert_called_with(
            "AGENT_API_KEY_INVALID",
            agent_id=agent_id,
            details="Invalid API key provided",
        )

    def test_hash_api_key(self):
        """Test API key hashing."""
        api_key = "test-key"
        hashed = hash_api_key(api_key)

        assert hashed != api_key
        assert verify_password(api_key, hashed) is True
