"""Singleton installation configuration persisted in the MAS database."""

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from db.database import Base


class GlobalConfig(Base):
    """Installation-wide identity that must survive restarts and upgrades."""

    __tablename__ = "global_config"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_global_config_singleton"),
    )

    id = Column(Integer, primary_key=True, default=1)
    site_id = Column(String(36), nullable=False, unique=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
