"""HTTP routes for user admin and self-service profile operations.

Admin operations are gated by ``PermissionChecker``. See
``docs/architecture.md`` for the full endpoint list and
error codes.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from licensing.access import enforce_user_reactivation_license
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth.auth_tool_functions import (
    PermissionChecker,
    get_current_user,
    modify_user_password,
)
from auth.permissions import Permission, Role
from core.config import settings
from core.logger import get_logger
from db.database import get_db
from db.models import Users
from schemas.schemas import UpdateRole, UserActiveStatusUpdate, UserPasswordModification
from users.openapi_docs import (
    CHANGE_PASSWORD_OPENAPI_EXTRA,
    CHANGE_PASSWORD_RESPONSES,
    CHANGE_USERNAME_RESPONSES,
    DELETE_USER_RESPONSES,
    ME_RESPONSES,
    SET_USER_ACTIVE_STATUS_RESPONSES,
    UPDATE_ROLE_RESPONSES,
    USER_DETAILS_RESPONSES,
    USERS_LIST_RESPONSES,
)
from users.user_tool_functions import delete_user as delete_user_tool
from users.user_tool_functions import (
    get_all_users,
    get_user_details,
    modify_user_username,
)

router = APIRouter(prefix="/users", tags=["Users"])
logger = get_logger("users_routes")

user_dependency = Annotated[dict, Depends(get_current_user)]


@router.post(
    "/update_role",
    summary="Update user role",
    description="Update a user's role. Only existing admin users can perform this operation.",
    status_code=200,
    tags=["Users"],
    responses=UPDATE_ROLE_RESPONSES,
)
async def update_roles(
    user_info: UpdateRole,
    user: Annotated[dict, Depends(PermissionChecker(Permission.USER_UPDATE))],
    db: Session = Depends(get_db),
):
    """Change a user's role (admin-only).

    Raises 403 if the user already has the target role, 404 if unknown.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    try:
        if user_info.user_id == settings.super_agent_username:
            logger.warning(
                f"Failed to update user role: User {user_info.user_id} can't have an another role than {user_info.new_role.value}"
            )
            raise HTTPException(
                status_code=403,
                detail=f"Agent already has role {user_info.new_role.value} and it can't be modified",
            )
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
    responses=USERS_LIST_RESPONSES,
)
def obtain_users_details(
    user: Annotated[dict, Depends(PermissionChecker(Permission.USER_READ))],
    db: Session = Depends(get_db),
):
    """List all users (admin-only)."""
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
    responses=USER_DETAILS_RESPONSES,
)
def user_details(
    user_id: int,
    user: Annotated[dict, Depends(PermissionChecker(Permission.USER_READ))],
    db: Session = Depends(get_db),
):
    """Return ``{id, username, role, is_active}`` for a given user (admin-only)."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    details = get_user_details(user_id, db)

    if not details or details[0] is None:
        logger.warning(f"User details not found for ID: {user_id}")
        raise HTTPException(status_code=404, detail="User not found")

    logger.info(
        f"User details retrieved for ID: {user_id} by admin: {user.get('username', 'unknown')}"
    )
    return {
        "id": details[0],
        "username": details[1],
        "role": details[2],
        "is_active": details[3],
    }


@router.get(
    "/me",
    summary="Get current user profile",
    description="Retrieve the profile information of the currently authenticated user.",
    status_code=200,
    tags=["Users"],
    responses=ME_RESPONSES,
)
def get_current_user_info(user: user_dependency, db: Session = Depends(get_db)):
    """Return the current authenticated user's identity and active status."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    logger.info(f"User profile requested by: {user.get('username', 'unknown')}")
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "role": user.get("role"),
        "is_active": user.get("is_active", True),
    }


@router.patch(
    "/{user_id}/active",
    summary="Activate or suspend a user",
    description=(
        "Change a user's active status. Only administrators can perform this "
        "operation. Reactivating a user requires an active license and an "
        "available user seat."
    ),
    status_code=200,
    responses=SET_USER_ACTIVE_STATUS_RESPONSES,
)
def set_user_active_status(
    user_id: int,
    payload: UserActiveStatusUpdate,
    request: Request,
    user: Annotated[dict, Depends(PermissionChecker(Permission.USER_UPDATE))],
    db: Session = Depends(get_db),
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    target_user = db.query(Users).filter(Users.id == user_id).first()
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if not payload.is_active and (
        str(user.get("id")) == str(user_id)
        or target_user.username == Role.ADMIN.value
        or target_user.username == settings.super_agent_username
        or target_user.role == Role.AGENT.value
    ):
        raise HTTPException(
            status_code=403,
            detail="Cannot suspend your own account or a protected system account.",
        )

    if target_user.is_active == payload.is_active:
        return {
            "id": target_user.id,
            "username": target_user.username,
            "is_active": target_user.is_active,
            "message": "User status is unchanged.",
        }

    if payload.is_active:
        enforce_user_reactivation_license(
            getattr(request.app.state, "license", None), db
        )

    target_user.is_active = payload.is_active
    try:
        db.commit()
        db.refresh(target_user)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(f"Failed to update active status for user {user_id}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Failed to update user status.",
        ) from exc

    logger.info(
        "User status updated: %s is_active=%s by %s",
        target_user.username,
        target_user.is_active,
        user.get("username", "unknown"),
    )
    return {
        "id": target_user.id,
        "username": target_user.username,
        "is_active": target_user.is_active,
        "message": "User status updated successfully.",
    }


@router.delete(
    "/{user_id}",
    summary="Delete a user",
    description="Permanently delete a user account. Requires admin privileges. Cannot delete the main 'admin' account or yourself.",
    status_code=200,
    tags=["Users"],
    responses=DELETE_USER_RESPONSES,
)
def delete_user(
    user_id: int,
    user: Annotated[dict, Depends(PermissionChecker(Permission.USER_DELETE))],
    db: Session = Depends(get_db),
):
    """Delete a user account (admin-only).

    403 if the caller targets themselves or the bootstrap admin.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    if user.get("id") == user_id:
        logger.warning(f"Admin {user.get('username')} attempted to delete themselves")
        raise HTTPException(status_code=403, detail="Cannot delete your own account")

    if user_id == settings.super_agent_username:
        logger.warning(f"{user.get('username')} attempted to delete Agent profile")
        raise HTTPException(status_code=403, detail="Cannot delete your agent account")

    return delete_user_tool(user_id, db)


@router.post(
    "/me/password_modification",
    summary="Change user password",
    description="Change the password for the currently authenticated user. Requires the old password for verification.",
    status_code=200,
    tags=["Users"],
    responses=CHANGE_PASSWORD_RESPONSES,
    openapi_extra=CHANGE_PASSWORD_OPENAPI_EXTRA,
)
def obtain_new_password(
    password_info: UserPasswordModification,
    user: user_dependency,
    db: Session = Depends(get_db),
):
    """Change the caller's password. 400 if the old password is wrong."""
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
    responses=CHANGE_USERNAME_RESPONSES,
)
def obtain_new_username(
    new_username: str, user: user_dependency, db: Session = Depends(get_db)
):
    """Change the caller's username. 400 if ``new_username`` is taken/invalid."""
    current_username = user.get("username")
    if modify_user_username(user.get("id"), new_username, db):
        return {"message": "Username successfully changed"}
    else:
        logger.warning(f"Failed username change attempt for user: {current_username}")
        raise HTTPException(
            status_code=400,
            detail="Failed to change username. Please check the new username.",
        )
