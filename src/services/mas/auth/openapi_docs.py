"""OpenAPI ``responses`` and ``openapi_extra`` dicts for the auth router.

Extracted from ``auth/routes.py`` to keep that file focused on handler
logic. Dict structure follows FastAPI's route decorator parameters.
"""
from typing import Any

# --- POST /auth/register -------------------------------------------------

REGISTER_RESPONSES: dict[int | str, dict[str, Any]]= {
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
}

REGISTER_OPENAPI_EXTRA = {
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
                            "password": "Secure#Pass123",
                        },
                    },
                    "admin": {
                        "summary": "Admin user registration",
                        "value": {
                            "username": "adminuser",
                            "password": "Strong#Admin2026",
                        },
                    },
                },
            }
        },
    }
}


# --- POST /auth/token ----------------------------------------------------

TOKEN_RESPONSES: dict[int | str, dict[str, Any]] = {
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
}

TOKEN_OPENAPI_EXTRA = {
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
}


# --- POST /auth/logout ---------------------------------------------------

LOGOUT_RESPONSES: dict[int | str, dict[str, Any]] = {
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
}
