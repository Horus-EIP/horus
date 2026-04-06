"""
Authentication Routes - Multi-Agent System Authentication & Authorization

Provides RESTful endpoints for user authentication, token management, and
authorization checks. Implements JWT-based stateless authentication with
role-based access control (RBAC).

Endpoints:
    POST   /auth/register           - Create new user account
    POST   /auth/token              - Authenticate user and issue JWT token
    POST   /auth/logout             - Invalidate user session

Security Features:
    - JWT (JSON Web Token) based authentication
    - Token expiration with refresh token support
    - Bcrypt password hashing with salt
    - Role-based access control (admin, user, guest)

Request/Response Examples:
    POST /auth/token
    {
        "username": "john_doe",
        "password": "securepassword123"
    }

    Response:
    {
        "access_token": "eyJhbGciOiJIUzI1NiI...",
        "token_type": "bearer"
    }

    POST /auth/register
    {
        "username": "new_user",
        "password": "securepassword123"
    }

Error Codes:
    400 - Bad Request (invalid credentials format)
    401 - Unauthorized (invalid credentials or expired token)
    409 - Conflict (username already exists)
    500 - Internal Server Error
"""

import time
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from starlette import status

from auth.auth_tool_functions import (authenticate_user, bcrypt_context,
                                      create_access_token, get_current_user)
from db.dependency import db_dependency
from db.models import Users
from db.redis_client import redis_db
from schemas.schemas import CreateUserRequest, Token

user_dependency = Annotated[dict, Depends(get_current_user)]

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    summary="Register a new user account",
    description="Create a new user with a hashed password and store it in the database. Username must be unique across the system.",
    status_code=status.HTTP_201_CREATED,
    tags=["Authentication"],
    responses={
        201: {
            "description": "User successfully created",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "User created successfully",
                            "value": {
                                "id": 1,
                                "username": "newuser123",
                                "role": "user",
                            },
                        },
                    }
                }
            },
        },
        409: {
            "description": "Username already exists",
            "content": {
                "application/json": {
                    "examples": {
                        "conflict": {
                            "summary": "Username already taken",
                            "value": {
                                "detail": "User Registration Error : UNIQUE constraint failed: users.username"
                            },
                        },
                    }
                }
            },
        },
        422: {
            "description": "Request body validation error",
            "content": {
                "application/json": {
                    "examples": {
                        "validation_error": {
                            "summary": "Invalid request body",
                            "value": {
                                "detail": [
                                    {
                                        "loc": ["body", "username"],
                                        "msg": "field required",
                                        "type": "value_error.missing",
                                    }
                                ]
                            },
                        },
                    }
                }
            },
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "username": {
                                "type": "string",
                                "description": "Unique username for the new account",
                                "minLength": 3,
                                "maxLength": 50,
                            },
                            "password": {
                                "type": "string",
                                "description": "Password for the new account (will be hashed automatically)",
                                "minLength": 6,
                            },
                        },
                        "required": ["username", "password"],
                    },
                    "examples": {
                        "basic": {
                            "summary": "Basic user registration",
                            "value": {
                                "username": "newuser123",
                                "password": "securepassword123",
                            },
                        },
                        "admin": {
                            "summary": "Admin user registration",
                            "value": {
                                "username": "adminuser",
                                "password": "strongadminpassword",
                            },
                        },
                    },
                }
            },
        }
    },
)
async def create_user(db: db_dependency, create_user_request: CreateUserRequest):
    """
    Register a new user account.

    Creates a new user with a hashed password and stores it in the database.
    The password is automatically hashed using bcrypt for security.
    Username must be unique across the system.

    Args:
        create_user_request: User registration data containing username and password

    Returns:
        Created user object with ID, username (password is not returned for security)

    Raises:
        409 Conflict: Username already exists in the system
    """
    create_user_model = Users(
        username=create_user_request.username,
        hashed_password=bcrypt_context.hash(create_user_request.password),
    )
    db.add(create_user_model)
    try:
        db.commit()
        db.refresh(create_user_model)
        return create_user_model
    except IntegrityError as e:
        db.rollback()
        error_message = str(e.orig)
        message = f"User Registration Error : {error_message}"
        raise HTTPException(status_code=409, detail=message)


@router.post(
    "/token",
    summary="Authenticate user and generate access token",
    description="Validates user credentials and returns a JWT token if authentication is successful. Token expires in 20 minutes. Returns Bearer token for API authorization.",
    response_model=Token,
    tags=["Authentication"],
    responses={
        200: {
            "description": "Authentication successful - JWT token issued",
            "content": {
                "application/json": {
                    "examples": {
                        "user_login": {
                            "summary": "Regular user authentication successful",
                            "value": {
                                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyMTIzIiwiaWQiOjEsInJvbGUiOiJ1c2VyIiwiZXhwIjoxNjM5NzUwODAwfQ...",
                                "token_type": "bearer",
                            },
                        },
                        "admin_login": {
                            "summary": "Admin user authentication successful",
                            "value": {
                                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImlkIjo1LCJyb2xlIjoiYWRtaW4iLCJleHAiOjE2Mzk3NTA4MDB9...",
                                "token_type": "bearer",
                            },
                        },
                    }
                }
            },
        },
        401: {
            "description": "Authentication failed - Invalid credentials",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_credentials": {
                            "summary": "Invalid username or password",
                            "value": {"detail": "Could not validate User"},
                        },
                        "user_not_found": {
                            "summary": "Username does not exist",
                            "value": {"detail": "Could not validate User"},
                        },
                        "inactive_user": {
                            "summary": "User account is inactive",
                            "value": {"detail": "Could not validate User"},
                        },
                    }
                }
            },
        },
        422: {
            "description": "Request body validation error",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_username": {
                            "summary": "Missing username field",
                            "value": {
                                "detail": [
                                    {
                                        "loc": ["body", "username"],
                                        "msg": "field required",
                                        "type": "value_error.missing",
                                    }
                                ]
                            },
                        },
                        "missing_password": {
                            "summary": "Missing password field",
                            "value": {
                                "detail": [
                                    {
                                        "loc": ["body", "password"],
                                        "msg": "field required",
                                        "type": "value_error.missing",
                                    }
                                ]
                            },
                        },
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error - Database or token generation error",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "Database connection error",
                            "value": {"detail": "Error: could not connect to database"},
                        },
                        "token_generation_error": {
                            "summary": "Error generating JWT token",
                            "value": {
                                "detail": "Error: could not generate authentication token"
                            },
                        },
                    }
                }
            },
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "username": {
                                "type": "string",
                                "description": "Username for authentication",
                                "minLength": 1,
                            },
                            "password": {
                                "type": "string",
                                "description": "Password for authentication",
                                "minLength": 1,
                            },
                            "grant_type": {
                                "type": "string",
                                "description": "OAuth2 grant type",
                                "default": "password",
                            },
                            "scope": {
                                "type": "string",
                                "description": "OAuth2 scope (optional)",
                                "default": "",
                            },
                            "client_id": {
                                "type": "string",
                                "description": "OAuth2 client ID (optional)",
                            },
                            "client_secret": {
                                "type": "string",
                                "description": "OAuth2 client secret (optional)",
                            },
                        },
                        "required": ["username", "password"],
                    },
                    "examples": {
                        "user_login": {
                            "summary": "Regular user login",
                            "value": {
                                "username": "john_doe",
                                "password": "securepassword123",
                                "grant_type": "password",
                            },
                        },
                        "admin_login": {
                            "summary": "Admin user login",
                            "value": {
                                "username": "admin",
                                "password": "adminpassword",
                                "grant_type": "password",
                            },
                        },
                        "service_account": {
                            "summary": "Service account with scopes",
                            "value": {
                                "username": "service_user",
                                "password": "service_password",
                                "grant_type": "password",
                                "scope": "api",
                            },
                        },
                    },
                }
            },
        }
    },
)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: db_dependency
):
    """
    Authenticate user and generate access token.

    Validates user credentials (username and password) and returns a JWT token
    if authentication is successful. The token has a 20-minute expiration time
    and includes user information (username, user_id, role).

    Args:
        form_data: OAuth2 password form containing username and password

    Returns:
        JWT access token and token type for API authentication

    Raises:
        401 Unauthorized: Invalid username or password credentials
    """
    user = authenticate_user(form_data.username, form_data.password, db)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate User"
        )
    username = user.username
    user_id = user.id
    role = user.role
    token = create_access_token(username, user_id, timedelta(minutes=20), role)

    return {"access_token": token, "token_type": "bearer"}


@router.post(
    "/logout",
    summary="Log out user by invalidating JWT token",
    description="Adds the current JWT token to a Redis blacklist to prevent further use. The token remains blacklisted until its natural expiration time.",
    tags=["Authentication"],
    responses={
        200: {
            "description": "Successfully logged out",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "Logout successful",
                            "value": {"message": "Successfully logout"},
                        },
                    }
                }
            },
        },
        401: {
            "description": "Authentication Failed",
            "content": {
                "application/json": {
                    "examples": {
                        "auth_failed": {
                            "summary": "Invalid or missing token",
                            "value": {"detail": "Authentication Failed"},
                        },
                    }
                }
            },
        },
    },
)
def user_logout(user: user_dependency):
    """
    Log out user by invalidating their JWT token.

    Adds the current JWT token to a Redis blacklist to prevent further use.
    The token remains blacklisted until its natural expiration time.
    This ensures immediate logout while maintaining security.

    Args:
        user: Current authenticated user information from JWT token

    Returns:
        Confirmation message of successful logout

    Raises:
        401 Unauthorized: Invalid or missing authentication token
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    exp = user.get("exp")
    nonce = user.get("nonce")

    ttl = exp - int(datetime.now().timestamp())
    if ttl > 0:
        redis_db.setex(f"jwt:blacklist:{nonce}", ttl, "revoked")

    return {"message": "Successfully logout"}
