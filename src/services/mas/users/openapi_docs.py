"""OpenAPI ``responses`` and ``openapi_extra`` dicts for the users router.

Extracted from ``users/routes.py`` to keep that file focused on handler
logic. Dict structure follows FastAPI's route decorator parameters.
"""

# --- POST /users/update_role ---------------------------------------------

UPDATE_ROLE_RESPONSES = {
    200: {
        "description": "Role successfully updated",
        "content": {
            "application/json": {
                "examples": {
                    "success": {
                        "summary": "Successfully updated user role",
                        "value": {"message": "Operation successfully happened"},
                    },
                    "already_has_role": {
                        "summary": "User already has this role (error case)",
                        "value": {"message": "Operation successfully happened"},
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
                        "summary": "Missing or invalid authentication",
                        "value": {"detail": "Authentication Failed"},
                    },
                    "no_token": {
                        "summary": "No authentication token provided",
                        "value": {"detail": "Authentication Failed"},
                    },
                }
            }
        },
    },
    403: {
        "description": "Insufficient permissions or User already has this role",
        "content": {
            "application/json": {
                "examples": {
                    "already_has_role": {
                        "summary": "Target user already has this role",
                        "value": {"detail": "User already has this role"},
                    },
                    "forbidden": {
                        "summary": "Caller does not have permissions",
                        "value": {"detail": "Insufficient permissions"},
                    },
                }
            }
        },
    },
    404: {
        "description": "User not found",
        "content": {
            "application/json": {
                "examples": {
                    "not_found": {
                        "summary": "Target user does not exist",
                        "value": {"detail": "User not found"},
                    },
                }
            }
        },
    },
    500: {
        "description": "Internal Server Error - Database error",
        "content": {
            "application/json": {
                "examples": {
                    "database_error": {
                        "summary": "Database transaction error",
                        "value": {
                            "detail": "Error: could not update user role in database"
                        },
                    },
                    "unexpected_error": {
                        "summary": "Unexpected server error",
                        "value": {
                            "detail": "Error: Internal server error during update"
                        },
                    },
                }
            }
        },
    },
}


# --- GET /users/users_list -----------------------------------------------

USERS_LIST_RESPONSES = {
    200: {
        "description": "List of users retrieved successfully",
        "content": {
            "application/json": {
                "examples": {
                    "success": {
                        "summary": "List of users",
                        "value": [
                            {"id": 1, "username": "admin", "role": "admin"},
                            {"id": 2, "username": "user1", "role": "user"},
                        ],
                    }
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
                        "summary": "Missing or invalid authentication",
                        "value": {"detail": "Authentication Failed"},
                    },
                }
            }
        },
    },
    403: {
        "description": "Insufficient permissions",
        "content": {
            "application/json": {
                "examples": {
                    "forbidden": {
                        "summary": "User does not have admin privileges",
                        "value": {
                            "detail": "You have to use an admin user to handle this action"
                        },
                    },
                }
            }
        },
    },
}


# --- GET /users/user_details/{user_id} -----------------------------------

USER_DETAILS_RESPONSES = {
    200: {
        "description": "User details retrieved successfully",
        "content": {
            "application/json": {
                "examples": {
                    "success": {
                        "summary": "User details",
                        "value": {"id": 2, "username": "user1", "role": "user"},
                    }
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
                        "summary": "Missing or invalid authentication",
                        "value": {"detail": "Authentication Failed"},
                    },
                }
            }
        },
    },
    403: {
        "description": "Insufficient permissions",
        "content": {
            "application/json": {
                "examples": {
                    "forbidden": {
                        "summary": "User does not have admin privileges",
                        "value": {
                            "detail": "You have to use an admin user to handle this action"
                        },
                    },
                }
            }
        },
    },
    404: {
        "description": "User not found",
        "content": {
            "application/json": {
                "examples": {
                    "not_found": {
                        "summary": "User ID does not exist",
                        "value": {"detail": "User not found"},
                    },
                }
            }
        },
    },
}


# --- GET /users/me -------------------------------------------------------

ME_RESPONSES = {
    200: {
        "description": "User profile retrieved successfully",
        "content": {
            "application/json": {
                "examples": {
                    "success": {
                        "summary": "Current user profile",
                        "value": {
                            "id": 1,
                            "username": "current_user",
                            "role": "user",
                        },
                    }
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
                        "summary": "Missing or invalid authentication",
                        "value": {"detail": "Authentication Failed"},
                    },
                }
            }
        },
    },
}


# --- DELETE /users/{user_id} ---------------------------------------------

DELETE_USER_RESPONSES = {
    200: {
        "description": "User successfully deleted",
        "content": {
            "application/json": {
                "examples": {
                    "success": {
                        "summary": "User deleted",
                        "value": {
                            "message": "User successfully deleted",
                            "username": "deleted_user",
                        },
                    }
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
                        "summary": "Missing or invalid authentication",
                        "value": {"detail": "Authentication Failed"},
                    },
                }
            }
        },
    },
    403: {
        "description": "Forbidden",
        "content": {
            "application/json": {
                "examples": {
                    "forbidden_admin": {
                        "summary": "User does not have admin privileges",
                        "value": {
                            "detail": "You have to use an admin user to handle this action"
                        },
                    },
                    "delete_self": {
                        "summary": "Admin attempted to delete themselves",
                        "value": {"detail": "Cannot delete your own account"},
                    },
                    "delete_main_admin": {
                        "summary": "Attempt to delete main admin account",
                        "value": {"detail": "Cannot delete the main admin account"},
                    },
                }
            }
        },
    },
    404: {
        "description": "User not found",
        "content": {
            "application/json": {
                "examples": {
                    "not_found": {
                        "summary": "User ID does not exist",
                        "value": {"detail": "User not found"},
                    },
                }
            }
        },
    },
    500: {
        "description": "Internal Server Error",
        "content": {
            "application/json": {
                "examples": {
                    "server_error": {
                        "summary": "Error deleting user",
                        "value": {"detail": "Error deleting user: ..."},
                    }
                }
            }
        },
    },
}


# --- POST /users/me/password_modification --------------------------------

CHANGE_PASSWORD_RESPONSES = {
    200: {
        "description": "Password successfully changed",
        "content": {
            "application/json": {
                "examples": {
                    "success": {
                        "summary": "Password changed",
                        "value": {"message": "Password successfully changed"},
                    }
                }
            }
        },
    },
    400: {
        "description": "Bad Request",
        "content": {
            "application/json": {
                "examples": {
                    "failed": {
                        "summary": "Failed to change password",
                        "value": {
                            "detail": "Failed to change password. Please check your old password."
                        },
                    }
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
                        "summary": "Missing or invalid authentication",
                        "value": {"detail": "Authentication Failed"},
                    },
                }
            }
        },
    },
    409: {
        "description": "Conflict",
        "content": {
            "application/json": {
                "examples": {
                    "db_error": {
                        "summary": "Database error during update",
                        "value": {
                            "detail": "User Password Modification Error : ..."
                        },
                    }
                }
            }
        },
    },
}

CHANGE_PASSWORD_OPENAPI_EXTRA = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "old_password": {
                            "type": "string",
                            "description": "Current password",
                            "minLength": 1,
                        },
                        "new_password": {
                            "type": "string",
                            "description": "New password",
                            "minLength": 6,
                        },
                    },
                    "required": ["old_password", "new_password"],
                },
                "examples": {
                    "change_password": {
                        "summary": "Change password request",
                        "value": {
                            "old_password": "old_secure_password",
                            "new_password": "New#Secure2026",
                        },
                    }
                },
            }
        },
    }
}


# --- POST /users/me/username_modification/{new_username} -----------------

CHANGE_USERNAME_RESPONSES = {
    200: {
        "description": "Username successfully changed",
        "content": {
            "application/json": {
                "examples": {
                    "success": {
                        "summary": "Username changed",
                        "value": {"message": "Username successfully changed"},
                    }
                }
            }
        },
    },
    400: {
        "description": "Bad Request",
        "content": {
            "application/json": {
                "examples": {
                    "failed": {
                        "summary": "Failed to change username",
                        "value": {
                            "detail": "Failed to change username. Please check the new username."
                        },
                    }
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
                        "summary": "Missing or invalid authentication",
                        "value": {"detail": "Authentication Failed"},
                    },
                }
            }
        },
    },
    409: {
        "description": "Conflict",
        "content": {
            "application/json": {
                "examples": {
                    "username_exists": {
                        "summary": "Username already exists",
                        "value": {"detail": "Username already exists"},
                    }
                }
            }
        },
    },
    500: {
        "description": "Internal Server Error",
        "content": {
            "application/json": {
                "examples": {
                    "server_error": {
                        "summary": "Error changing username",
                        "value": {"detail": "Error changing username: ..."},
                    }
                }
            }
        },
    },
}
