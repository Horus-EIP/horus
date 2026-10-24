from datetime import UTC, datetime

import pytest
from licensing.models import LicenseClockState
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.database import Base


@pytest.fixture
def clock_state_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[LicenseClockState.__table__])
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_license_clock_state_persists_the_high_water_mark(clock_state_session):
    observed_at = datetime(2026, 10, 23, 19, 0, tzinfo=UTC)
    clock_state_session.add(LicenseClockState(id=1, last_seen_clock=observed_at))
    clock_state_session.commit()

    saved = clock_state_session.get(LicenseClockState, 1)

    assert saved is not None
    assert saved.last_seen_clock == observed_at.replace(tzinfo=None)
    assert saved.updated_at is not None


def test_license_clock_state_rejects_a_second_row(clock_state_session):
    clock_state_session.add(
        LicenseClockState(id=1, last_seen_clock=datetime(2026, 10, 23, tzinfo=UTC))
    )
    clock_state_session.commit()
    clock_state_session.add(
        LicenseClockState(id=2, last_seen_clock=datetime(2026, 10, 24, tzinfo=UTC))
    )

    with pytest.raises(IntegrityError):
        clock_state_session.commit()
