from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from licensing.models import ConsumedResetNonce, LicenseClockState


def get_last_seen_clock(db: Session) -> datetime | None:
    """Return the persisted UTC high-water mark, if one has been recorded."""
    clock_entry = db.query(LicenseClockState).filter_by(id=1).first()
    return clock_entry.last_seen_clock if clock_entry is not None else None


def advance_last_seen_clock(db: Session, current_time: datetime) -> None:
    """Advance the high-water mark without committing the caller's transaction."""
    clock_entry = db.query(LicenseClockState).filter_by(id=1).with_for_update().first()
    if clock_entry is None:
        clock_entry = LicenseClockState(
            id=1,
            last_seen_clock=current_time,
        )
        db.add(clock_entry)
        return

    if current_time > clock_entry.last_seen_clock:
        clock_entry.last_seen_clock = current_time


def consume_reset_nonce(db: Session, nonce: str) -> bool:
    """Record a recovery nonce in the current transaction unless it was used."""
    try:
        with db.begin_nested():
            db.add(ConsumedResetNonce(nonce=nonce))
            db.flush()
        return True
    except IntegrityError:
        return False


def force_reset_last_seen_clock(db: Session, current_time: datetime) -> None:
    """Replace the stored high-water mark as part of an authorized recovery."""
    clock_entry = db.query(LicenseClockState).filter_by(id=1).with_for_update().first()
    if clock_entry is not None:
        clock_entry.last_seen_clock = current_time
    else:
        clock_entry = LicenseClockState(
            id=1,
            last_seen_clock=current_time,
        )
        db.add(clock_entry)
