import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from auth.permissions import Role
from core.logger import get_logger
from db.database import SessionLocal, get_db
from db.models import Users

logger = get_logger("users_tool_functions")


def _get_all_users_internal(db: Session) -> list:
    """
    Internal: Retrieve all users from the database.

    Args:
        db (Session): Database session (explicit)

    Returns:
        list: List of all users objects
    """
    try:
        users = db.query(Users).all()

        for user in users:
            _ = user.username
            _ = user.role
        return users
    except Exception as e:
        logger.error(f"Failed to retrieve available agents: {str(e)}")
        return []


def get_all_users(db: Session) -> list:
    """
    Retrieve all users from the database.

    Args:
        db (Session): Database session (injected by FastAPI)

    Returns:
        list: List of all users objects
    """
    return _get_all_users_internal(db)


def get_user_details(user_id: int, db: Session):
    try:
        user = db.query(Users).filter(Users.id == user_id).first()
        if user is None:
            logger.debug(f"User details not found - User ID: {user_id}")
            return None, None, None

        logger.debug(
            f"User details retrieved - User ID: {user_id}, Name: {user.username}, Role: {user.role}"
        )
        return (
            user_id,
            user.username,
            user.role,
        )
    except Exception as e:
        logger.error(
            f"Failed to retrieve user details - User ID: {user_id}, Error: {str(e)}"
        )
        return None, None, None, None


def delete_user(user_id: int, db: Session):
    target_user = db.query(Users).filter(Users.id == user_id).first()

    if not target_user:
        logger.warning(f"Attempt to delete non-existent user ID: {user_id}")
        raise HTTPException(status_code=404, detail="User not found")

    if target_user.username == Role.ADMIN.value:
        logger.warning(f"Attempt to delete main admin account")
        raise HTTPException(
            status_code=403, detail="Cannot delete the main admin account"
        )

    try:
        username = target_user.username
        db.delete(target_user)
        db.commit()
        logger.info(f"User deleted: {username} (ID: {user_id})")
        return {"message": "User successfully deleted", "username": username}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting user: {str(e)}")


def modify_user_username(user_id: int, new_username: str, db: Session):
    user = db.query(Users).filter(Users.id == user_id).first()

    if not user:
        logger.warning(
            f"Attempt to modify username for non-existent user ID: {user_id}"
        )
        raise HTTPException(status_code=404, detail="User not found")

    existing_user = db.query(Users).filter(Users.username == new_username).first()
    if existing_user:
        logger.warning(
            f"Attempt to change username to an already existing username: {new_username}"
        )
        raise HTTPException(status_code=409, detail="Username already exists")

    old_username = user.username
    user.username = new_username
    try:
        db.commit()
        logger.info(
            f"Username changed from {old_username} to {new_username} for user ID: {user_id}"
        )
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to change username for user ID {user_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error changing username: {str(e)}"
        )
