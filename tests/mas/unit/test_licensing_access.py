from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from licensing.access import (
    enforce_registration_license,
    enforce_user_reactivation_license,
)
from licensing.models import LicenseClockState
from licensing.verification import LicenseCheck, LicenseState
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import Users


@pytest.fixture
def licensing_db():
    engine = create_engine("sqlite://")
    Users.__table__.create(engine)
    LicenseClockState.__table__.create(engine)
    with Session(engine) as db:
        db.add(LicenseClockState(id=1, last_seen_clock=datetime.now(UTC)))
        db.commit()
        yield db
    engine.dispose()


def _license(cap: int) -> LicenseCheck:
    return LicenseCheck(
        state=LicenseState.VALID,
        claims=SimpleNamespace(user_cap=cap),
    )


def _add_users(db: Session, active_count: int, inactive_count: int) -> None:
    db.add_all(
        [
            Users(
                username=f"active-{index}",
                hashed_password="hash",
                is_active=True,
            )
            for index in range(active_count)
        ]
        + [
            Users(
                username=f"inactive-{index}",
                hashed_password="hash",
                is_active=False,
            )
            for index in range(inactive_count)
        ]
    )
    db.commit()


@pytest.mark.parametrize(
    "account_change",
    [enforce_registration_license, enforce_user_reactivation_license],
)
def test_inactive_users_do_not_consume_license_seats(licensing_db, account_change):
    _add_users(licensing_db, active_count=1, inactive_count=10)

    account_change(_license(cap=2), licensing_db)


@pytest.mark.parametrize(
    "account_change",
    [enforce_registration_license, enforce_user_reactivation_license],
)
def test_account_change_is_blocked_when_active_user_cap_is_reached(
    licensing_db, account_change
):
    _add_users(licensing_db, active_count=2, inactive_count=10)

    with pytest.raises(HTTPException) as exc_info:
        account_change(_license(cap=2), licensing_db)

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail == "License user limit reached (2)."
