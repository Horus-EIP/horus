"""``Users`` ORM model + CRUD audit listeners."""

from sqlalchemy import Column, Integer, String, event
from sqlalchemy.orm import relationship

from auth.permissions import Role
from core.logger import log_db_operation
from db.database import Base


class Users(Base):
    """Authenticated user (bcrypt password, RBAC role).

    Passwords are always stored hashed. Owns 0..N ``Conversations``.
    """

    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default=Role.USER.value, nullable=False)

    conversations = relationship(
        "Conversations",
        back_populates="owner",
        passive_deletes=True,
        cascade="save-update",
    )


@event.listens_for(Users, "after_insert")
def log_user_insert(mapper, connection, target):
    """Log user creation events for security auditing."""
    log_db_operation(
        "CREATE", "users", f"username: {target.username}, role: {target.role}"
    )


@event.listens_for(Users, "after_update")
def log_user_update(mapper, connection, target):
    """Log user modification events for security auditing."""
    log_db_operation("UPDATE", "users", f"username: {target.username}")


@event.listens_for(Users, "after_delete")
def log_user_delete(mapper, connection, target):
    """Log user deletion events for security auditing."""
    log_db_operation("DELETE", "users", f"username: {target.username}")
