from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from db.models import Users
from licensing.models import LicenseClockState
from licensing.verification import LicenseCheck, LicenseState

ACTIVE_LICENSE_STATES = {
    LicenseState.VALID,
    LicenseState.WARNING,
    LicenseState.GRACE,
}


def require_active_license(connection: HTTPConnection) -> LicenseCheck:
    license_check = getattr(connection.app.state, "license", None)
    if license_check is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="License status is not available.",
        )

    if license_check.state not in ACTIVE_LICENSE_STATES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"License is not active (state: {license_check.state.value}). "
                f"{license_check.reason or ''}"
            ).strip(),
        )

    return license_check


def enforce_registration_license(
    license_check: LicenseCheck | None,
    db: Session,
) -> None:
    if license_check is None or license_check.state not in ACTIVE_LICENSE_STATES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Account creation is unavailable because the license is missing, "
                "invalid, not yet valid, restricted, or in clock rollback."
            ),
        )

    claims = license_check.claims
    user_cap = claims.user_cap if claims is not None else None
    if user_cap is None:
        return

    db.query(LicenseClockState).filter_by(id=1).with_for_update().first()
    current_users_count = db.query(Users).count()
    if current_users_count >= user_cap:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"License user limit reached ({user_cap}).",
        )