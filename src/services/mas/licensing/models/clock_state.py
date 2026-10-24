"""Persistent high-water mark used to detect system clock rollback."""

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from db.database import Base


class LicenseClockState(Base):
    """Singleton row holding the last UTC time observed by the licence check."""

    __tablename__ = "license_clock_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_license_clock_state_singleton"),
    )

    id = Column(Integer, primary_key=True, default=1)
    last_seen_clock = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ConsumedResetNonce(Base):
    """Stores clock-recovery nonces to prevent replay."""

    __tablename__ = "consumed_reset_nonces"

    nonce = Column(String(36), primary_key=True)
    consumed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )