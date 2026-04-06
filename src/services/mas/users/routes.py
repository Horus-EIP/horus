"""
User Management Routes - Multi-Agent System User Administration

Provides RESTful endpoints for user account management, profile administration,
and role management. Includes advanced features like user statistics and
activity tracking.

Endpoints:
    POST   /users/make-admin/{user_id}          - Grant admin rights to a user (admin only)
    POST   /users/remove-admin-grant/{user_id}  - Revoke admin rights from a user (admin only)

Security:
    - User management operations restricted to admin users
    - Role changes require explicit admin authorization

Request/Response Examples:
    POST /users/make-admin/john_doe
    Response:
    {
        "message": "Operation successfully happened"
    }

    POST /users/remove-admin-grant/john_doe
    Response:
    {
        "message": "Operation successfully happened"
    }

User Roles:
    - admin: Full system access, user management
    - user: Standard user, limited access

Error Codes:
    401 - Unauthorized (authentication required)
    403 - Forbidden (insufficient permissions)
    404 - Not Found (user does not exist)
    500 - Internal Server Error
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth.auth_tool_functions import (PermissionChecker, get_current_user,
                                      modify_user_password)
from auth.permissions import Permission
from core.logger import get_logger
from db.database import get_db
from db.models import Users
from schemas.schemas import UpdateRole, UserPasswordModification
from users.user_tool_functions import delete_user as delete_user_tool
from users.user_tool_functions import (get_all_users, get_user_details,
                                       modify_user_username)

router = APIRouter(prefix="/users", tags=["Users"])
logger = get_logger("users_routes")

user_dependency = Annotated[dict, Depends(get_current_user)]


@router.post(
    "/update_role",
    summary="Update user role",
    description="Update a user's role. Only existing admin users can perform this operation.",
    status_code=200,
    tags=["Users"],
    responses={
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
    },
)
async def update_roles(
    user_info: UpdateRole,
    user: Annotated[dict, Depends(PermissionChecker(Permission.USER_UPDATE))],
    db: Session = Depends(get_db),
):
    """
    Update the role of a specific user.

    Allows administrators to elevate or demote users (e.g. USER -> ADMIN).
    Validates that the target user exists and doesn't already have the role.

    Args:
        user_info (UpdateRole): Payload containing target user ID and new role.
        user (dict): Authenticated admin user.
        db (Session): Database session.

    Returns:
        dict: Success message.

    Raises:
        HTTPException:
            - 403: If user already has the role or permission is denied.
            - 404: If target user is not found.
            - 500: Database error.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    try:
        existing_user_with_role = (
            db.query(Users)
            .filter(
                Users.username == user_info.user_id,
                Users.role == user_info.new_role.value,
            )
            .first()
        )

        if existing_user_with_role:
            logger.warning(
                f"Failed to update user role: User {user_info.user_id} already has role {user_info.new_role.value}"
            )
            raise HTTPException(
                status_code=403,
                detail=f"User already has role {user_info.new_role.value}",
            )

        target_user = (
            db.query(Users).filter(Users.username == user_info.user_id).first()
        )
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        target_user.role = user_info.new_role.value
        db.commit()
        db.refresh(target_user)
        logger.info(
            f"User role updated: {user_info.user_id} to {user_info.new_role.value} by {user.get('username', 'unknown')}"
        )
        return {"message": "Operation successfully happened"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating role for {user_info.user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get(
    "/users_list",
    summary="List all users",
    description="Retrieve a list of all registered users in the system. Requires admin privileges.",
    status_code=200,
    tags=["Users"],
    responses={
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
    },
)
def obtain_users_details(
    user: Annotated[dict, Depends(PermissionChecker(Permission.USER_READ))],
    db: Session = Depends(get_db),
):
    """
    Retrieve listing of all system users.

    Provides administrative overview of all registered accounts.
    Includes role and status information.

    Args:
        user (dict): Authenticated admin user.
        db (Session): Database session.

    Returns:
        list[dict]: List of user objects.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    logger.info(f"User list requested by admin: {user.get('username', 'unknown')}")
    return get_all_users(db)


@router.get(
    "/user_details/{user_id}",
    summary="Get user details",
    description="Retrieve detailed information for a specific user by ID. Requires admin privileges.",
    status_code=200,
    tags=["Users"],
    responses={
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
    },
)
def user_details(
    user_id: int,
    user: Annotated[dict, Depends(PermissionChecker(Permission.USER_READ))],
    db: Session = Depends(get_db),
):
    """
    Get detailed profile of a specific user by their ID.

    Returns extended profile information useful for user management.

    Args:
        user_id (int): Numeric ID of the user.
        user (dict): Authenticated admin user.
        db (Session): Database session.

    Returns:
        dict: User profile (id, username, role).

    Raises:
        HTTPException:
            - 404: If user is not found.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    details = get_user_details(user_id, db)

    if not details or details[0] is None:
        logger.warning(f"User details not found for ID: {user_id}")
        raise HTTPException(status_code=404, detail="User not found")

    logger.info(
        f"User details retrieved for ID: {user_id} by admin: {user.get('username', 'unknown')}"
    )
    return {"id": details[0], "username": details[1], "role": details[2]}


@router.get(
    "/me",
    summary="Get current user profile",
    description="Retrieve the profile information of the currently authenticated user.",
    status_code=200,
    tags=["Users"],
    responses={
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
    },
)
def get_current_user_info(user: user_dependency, db: Session = Depends(get_db)):
    """
    Get profile information for the authenticated session.

    Used by the frontend to display current user identity and permissions.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    logger.info(f"User profile requested by: {user.get('username', 'unknown')}")
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "role": user.get("role"),
    }


@router.delete(
    "/{user_id}",
    summary="Delete a user",
    description="Permanently delete a user account. Requires admin privileges. Cannot delete the main 'admin' account or yourself.",
    status_code=200,
    tags=["Users"],
    responses={
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
    },
)
def delete_user(
    user_id: int,
    user: Annotated[dict, Depends(PermissionChecker(Permission.USER_DELETE))],
    db: Session = Depends(get_db),
):
    """
    Permanently remove a user account from the system.

    This action is irreversible.
    It contains safeguards to prevent administrators from deleting themselves
    or the main admin account.

    Args:
        user_id (int): ID of the user to delete.
        user (dict): Authenticated admin user performing the action.
        db (Session): Database session.

    Returns:
        bool: True on success.

    Raises:
        HTTPException:
            - 403: If attempting to delete self or protected admin account.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    if user.get("id") == user_id:
        logger.warning(f"Admin {user.get('username')} attempted to delete themselves")
        raise HTTPException(status_code=403, detail="Cannot delete your own account")

    return delete_user_tool(user_id, db)


@router.post(
    "/me/password_modification",
    summary="Change user password",
    description="Change the password for the currently authenticated user. Requires the old password for verification.",
    status_code=200,
    tags=["Users"],
    responses={
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
    },
    openapi_extra={
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
                                "new_password": "new_secure_password",
                            },
                        }
                    },
                }
            },
        }
    },
)
def obtain_new_password(
    password_info: UserPasswordModification,
    user: user_dependency,
    db: Session = Depends(get_db),
):
    """
    Allow authenticated users to change their account password.

    Requires verification of the old password before setting the new one.
    Updates the hashed password in the database.

    Args:
        password_info (UserPasswordModification): Old and new password container.
        user (dict): Authenticated user.
        db (Session): Database session.

    Returns:
        dict: Success message.

    Raises:
        HTTPException:
            - 400: If old password validation fails.
    """
    if modify_user_password(
        user.get("username"), password_info.old_password, password_info.new_password, db
    ):
        logger.info(f"Password changed for user: {user.get('username')}")
        return {"message": "Password successfully changed"}
    else:
        logger.warning(
            f"Failed password change attempt for user: {user.get('username')}"
        )
        raise HTTPException(
            status_code=400,
            detail="Failed to change password. Please check your old password.",
        )


@router.post(
    "/me/username_modification/{new_username}",
    summary="Change user username",
    description="Change the username for the currently authenticated user. The new username must be unique.",
    status_code=200,
    tags=["Users"],
    responses={
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
    },
)
def obtain_new_username(
    new_username: str, user: user_dependency, db: Session = Depends(get_db)
):
    """
    Update the username for the current account.

    Checks for uniqueness constraint before applying the change.
    Use with caution as this may affect client-side caching or session state.

    Args:
        new_username (str): The desired unique username.
        user (dict): Authenticated user.
        db (Session): Database session.

    Returns:
        dict: Success message.

    Raises:
        HTTPException:
            - 400: If username is already taken or invalid.
    """
    current_username = user.get("username")
    if modify_user_username(user.get("id"), new_username, db):
        return {"message": "Username successfully changed"}
    else:
        logger.warning(f"Failed username change attempt for user: {current_username}")
        raise HTTPException(
            status_code=400,
            detail="Failed to change username. Please check the new username.",
        )
