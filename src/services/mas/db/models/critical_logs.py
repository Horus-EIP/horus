"""``CriticalLogs`` — append-only audit log for security and compliance events."""

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from db.database import Base


class CriticalLogs(Base):
    """Indexed on ``timestamp``, ``category``, ``user_id``, ``component``,
    ``operation`` for filtered queries.
    """

    __tablename__ = "critical_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    level = Column(String(20), nullable=False)
    category = Column(String(20), nullable=False)
    component = Column(String(50), nullable=False)
    user_id = Column(Integer, nullable=True)
    operation = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_critical_logs_timestamp", "timestamp"),
        Index("idx_critical_logs_category", "category"),
        Index("idx_critical_logs_user", "user_id"),
        Index("idx_critical_logs_component", "component"),
        Index("idx_critical_logs_operation", "operation"),
    )
