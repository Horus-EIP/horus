import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from auth.permissions import Permission, check_permission
from core.config import settings
from core.hybrid_logging import log_security_event
from core.logger import get_logger, log_auth_operation, log_error, log_warning
from db.dependency import get_db
from db.models import Agents, Users
from db.redis_client import redis_db

logger = get_logger("auth")

bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_bearer = OAuth2PasswordBearer(tokenUrl="auth/token")

api_key = APIKeyHeader(name="x-api-key")


def authenticate_user(username: str, password: str, db, ip_address: str | None = None):
    """
    Verifies the username and password against stored hashed password.
    Returns the user if authentication is successful, otherwise returns False.
    """
    logger.info(f"Authentication attempt for user: {username}")

    try:
        user = db.query(Users).filter(Users.username == username).first()
    except ProgrammingError as e:
        if 'relation "users" does not exist' in str(e):
            logger.warning("Users table does not exist yet. Skipping authentication.")
            return False
        logger.error(f"Database programming error in authenticate_user: {str(e)}")
        return False

    if not user:
        # DEBUG: Check if any users exist
        try:
            all_users = db.query(Users).all()
            user_list = [u.username for u in all_users]
            logger.error(
                f"DEBUG: User '{username}' not found. Existing users: {user_list}"
            )
            logger.error(
                f"DEBUG: Username type: {type(username)}, length: {len(username)}"
            )
            logger.error(f"DEBUG: DB Session ID: {id(db)}")
        except Exception as e:
            logger.error(f"DEBUG: Failed to list users: {e}")

        log_auth_operation("LOGIN", username, success=False)
        log_security_event(
            "LOGIN_USER_NOT_FOUND",
            details=f"Unknown user: {username}",
            ip_address=ip_address,
        )
        logger.warning(f"Authentication failed - User not found: {username}")
        return False

    if not bcrypt_context.verify(password, user.hashed_password):
        log_auth_operation("LOGIN", username, success=False)
        log_security_event(
            "LOGIN_INVALID_PASSWORD",
            user_id=user.id,
            details=f"Invalid password for: {username}",
            ip_address=ip_address,
        )
        logger.warning(f"Authentication failed - Invalid password for user: {username}")
        return False

    log_auth_operation("LOGIN", username, success=True)
    log_security_event(
        "LOGIN_SUCCESS",
        user_id=user.id,
        details=f"Successful login: {username}",
        ip_address=ip_address,
    )
    return user


def create_access_token(
    username: str, user_id: int, expires_delta: timedelta, user_role: str
):
    """
    Generates a JWT access token with an expiration time.
    """
    logger.info(f"Creating access token for user: {username} (role: {user_role})")

    encode = {"sub": username, "id": user_id, "role": user_role}
    nonce = uuid.uuid4()
    now = datetime.now(UTC)
    exp = now + expires_delta
    encode.update(
        {
            "exp": int(exp.timestamp()),
            "nonce": str(nonce),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
        }
    )

    token = jwt.encode(
        encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    log_auth_operation("TOKEN", username, success=True)
    logger.info(f"Token created successfully for user: {username}, expires: {exp}")

    return token


def get_current_user(
    token: Annotated[str, Depends(oauth2_bearer)], db: Session = Depends(get_db)
):
    """
    Decodes the JWT token and retrieves user details.
    Raises an exception if the token is invalid or expired.
    """
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        raw_username = payload.get("sub")
        raw_user_id = payload.get("id")
        raw_nonce = payload.get("nonce")
        raw_exp = payload.get("exp")

        if (
            not isinstance(raw_username, str)
            or not isinstance(raw_user_id, int)
            or not isinstance(raw_nonce, str)
            or not isinstance(raw_exp, int)
        ):
            raise JWTError("Mandatory fiels missing in the JWT's payload")

        username = raw_username
        user_id = raw_user_id
        nonce = raw_nonce
        exp = raw_exp

        if username is None or user_id is None:
            log_error("auth", "Token validation failed: missing username or user_id")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate user",
            )

        if redis_db.exists(f"jwt:blacklist:{nonce}"):
            log_warning("auth", f"Attempt to use revoked token for user: {username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token revoked",
            )

        user = db.query(Users).filter(Users.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        logger.debug(f"Token validated successfully for user: {username}")
        return {
            "username": username,
            "id": user_id,
            "nonce": nonce,
            "exp": exp,
            "role": user.role,
        }

    except JWTError as e:
        log_error("auth", f"JWT validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate user"
        )


def get_current_user_from_token(token: str) -> dict[str, Any]:
    """Extract user info from token string"""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        username = payload.get("sub")
        user_id = payload.get("id")

        if not username or not user_id:
            log_error("auth", "Token parsing failed: missing username or user_id")
            raise JWTError("Invalid token payload")

        logger.debug(f"User info extracted from token for: {username}")

        return {"username": username, "id": user_id, "payload": payload}

    except JWTError as e:
        log_error("auth", f"Token parsing error: {str(e)}")
        raise


class PermissionChecker:
    def __init__(self, required_permission: Permission):
        self.required_permission = required_permission

    def __call__(self, user: dict = Depends(get_current_user)):
        logger.info(
            f"DEBUG: PermissionChecker called for user {user.get('username')}, required: {self.required_permission}"
        )

        role = user.get("role")
        if not isinstance(role, str):
            raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid user data format: role must be a string"
        )
        
        if not check_permission(user.get("role"), self.required_permission):
            log_warning(
                "auth",
                f"User {user.get('username')} (role: {user.get('role')}) denied permission {self.required_permission}",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )
        return user

    def __eq__(self, other):
        if isinstance(other, PermissionChecker):
            return self.required_permission == other.required_permission
        return False

    def __hash__(self):
        return hash(self.required_permission)


def modify_user_password(
    username: str, old_password: str, new_password: str, db: Session
):
    logger.info(f"Authentication attempt for user: {username}")

    try:
        user = db.query(Users).filter(Users.username == username).first()
    except ProgrammingError:
        logger.warning("Users table does not exist yet. Cannot modify password.")
        return False

    if not user:
        log_auth_operation("LOGIN", username, success=False)
        log_security_event(
            "LOGIN_USER_NOT_FOUND",
            details=f"Unknown user: {username}",
        )
        logger.warning(f"Authentication failed - User not found: {username}")
        return False

    if not bcrypt_context.verify(old_password, user.hashed_password):
        log_auth_operation("LOGIN", username, success=False)
        log_security_event(
            "LOGIN_INVALID_PASSWORD",
            user_id=user.id,
            details=f"Invalid password for: {username}",
        )
        logger.warning(f"Authentication failed - Invalid password for user: {username}")
        return False

    user.hashed_password = bcrypt_context.hash(new_password)
    try:
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        error_message = str(e)
        message = f"User Password Modification Error : {error_message}"
        raise HTTPException(status_code=409, detail=message)


# ---------------------------------------------------------------------------
# Agent API-key verification cache
# ---------------------------------------------------------------------------
# Agent credentials are high-entropy machine tokens presented on every
# authenticated agent request (heartbeats, and hundreds of /tasks/task-step/
# POSTs per streamed answer). Each verify runs bcrypt at passlib's default
# cost factor (~150 ms) — pure CPU on a CPU-bound MAS. Cache successful
# (agent_id, api_key) verifications so bcrypt runs once per credential, not
# once per request: a process-local L1 dict in front of Redis (shared across
# workers). The cache is POSITIVE-ONLY (failures always re-verify) and is
# invalidated on key rotation via ``invalidate_agent_api_key_cache``.
_AGENT_AUTH_L1: dict[str, tuple[str, float]] = {}
_AGENT_AUTH_L1_TTL = 30.0  # seconds (process-local; short to bound rotation lag)
_AGENT_AUTH_REDIS_TTL = 300  # seconds (shared across workers)
_AGENT_AUTH_REDIS_PREFIX = "agent_auth:"


def _agent_auth_cache_key(agent_id: str, presented_key: str) -> str:
    return hashlib.sha256(f"{agent_id}:{presented_key}".encode()).hexdigest()


def _agent_auth_cache_get(agent_id: str, presented_key: str) -> bool:
    """Return True iff this exact (agent_id, key) pair was recently verified.

    Any Redis error is swallowed and treated as a miss so a cache outage
    degrades to "always run bcrypt" rather than failing auth.
    """
    keyhash = _agent_auth_cache_key(agent_id, presented_key)
    now = time.monotonic()
    hit = _AGENT_AUTH_L1.get(keyhash)
    if hit is not None:
        cached_agent_id, expiry = hit
        if expiry > now and cached_agent_id == agent_id:
            return True
        _AGENT_AUTH_L1.pop(keyhash, None)
    try:
        if redis_db.exists(f"{_AGENT_AUTH_REDIS_PREFIX}{agent_id}:{keyhash}"):
            _AGENT_AUTH_L1[keyhash] = (agent_id, now + _AGENT_AUTH_L1_TTL)
            return True
    except Exception as exc:  # noqa: BLE001 - cache must never break auth
        logger.debug(f"Agent auth cache lookup failed, will re-verify: {exc}")
    return False


def _agent_auth_cache_store(agent_id: str, presented_key: str) -> None:
    keyhash = _agent_auth_cache_key(agent_id, presented_key)
    _AGENT_AUTH_L1[keyhash] = (agent_id, time.monotonic() + _AGENT_AUTH_L1_TTL)
    try:
        redis_db.setex(
            f"{_AGENT_AUTH_REDIS_PREFIX}{agent_id}:{keyhash}",
            _AGENT_AUTH_REDIS_TTL,
            "1",
        )
    except Exception as exc:  # noqa: BLE001 - cache must never break auth
        logger.debug(f"Agent auth cache store failed: {exc}")


def invalidate_agent_api_key_cache(agent_id: str) -> None:
    """Drop all cached verifications for ``agent_id`` (call on key rotation).

    Without this a rotated/revoked key would keep authenticating until the TTL
    expires — a security regression. L1 entries in other worker processes
    self-expire within ``_AGENT_AUTH_L1_TTL``.
    """
    stale = [k for k, v in _AGENT_AUTH_L1.items() if v[0] == agent_id]
    for k in stale:
        _AGENT_AUTH_L1.pop(k, None)
    try:
        for rk in redis_db.scan_iter(
            match=f"{_AGENT_AUTH_REDIS_PREFIX}{agent_id}:*"
        ):
            redis_db.delete(rk)
    except Exception as exc:  # noqa: BLE001 - invalidation is best-effort
        logger.debug(f"Agent auth cache invalidation failed for {agent_id}: {exc}")


def verify_agent_api_key(
    key: str = Security(api_key), db: Session = Depends(get_db)
) -> tuple[str, str]:
    """
    Verifies the provided API key against stored agent API keys.
    Returns (agent_id, api_key) if the API key is valid, otherwise raises an HTTPException.
    """
    try:
        if ":" not in key:
            raise ValueError("Invalid API key format")

        agent_id, api_key = key.split(":", 1)

        # Fast path: a recently verified (agent_id, key) pair skips the
        # expensive bcrypt verify (and the DB lookup). Positive-only.
        if _agent_auth_cache_get(agent_id, api_key):
            return agent_id, api_key

        agent = db.query(Agents).filter(Agents.id == agent_id).first()

        if not agent:
            log_security_event(
                "AGENT_API_KEY_INVALID",
                details="Invalid API key provided",
            )
            logger.warning("API key verification failed - Invalid API key")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        if not bcrypt_context.verify(api_key, agent.api_key):
            log_security_event(
                "AGENT_API_KEY_INVALID",
                agent_id=agent.id,
                details="Invalid API key provided",
            )
            logger.warning(f"API key verification failed for agent: {agent.id}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        _agent_auth_cache_store(agent_id, api_key)
    except Exception as e:
        log_error("auth", f"API key verification error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format",
        )

    logger.debug(f"API key verified successfully for agent: {agent.id}")
    return agent_id, api_key


def hash_api_key(api_key: str) -> str:
    """Hash API key for secure storage"""
    return bcrypt_context.hash(api_key)
