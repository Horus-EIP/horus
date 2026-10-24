"""HTTP routes for installation-wide licence status and installation."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth.auth_tool_functions import PermissionChecker
from auth.permissions import Permission
from core.config import settings
from core.logger import get_logger
from db.database import get_db
from licensing.access import ACTIVE_LICENSE_STATES
from licensing.clock import (
    advance_last_seen_clock,
    consume_reset_nonce,
    force_reset_last_seen_clock,
    get_last_seen_clock,
)
from licensing.openapi_docs import (
    LICENSE_STATUS_RESPONSES,
    LICENSE_UPLOAD_RESPONSES,
    LicenseLiveStatusResponse,
    LicenseStatusResponse,
    LicenseUploadResponse,
)
from licensing.site import get_or_create_site_id
from licensing.verification import LicenseState, editing_license_file, verify_license

router = APIRouter(prefix="/license", tags=["License"])
logger = get_logger("licensing_routes")

MAX_LICENSE_SIZE = 16 * 1024


@router.get(
    "/live-status",
    summary="Get current license status",
    description="Return the current license state for UI warnings and restrictions.",
    response_model=LicenseLiveStatusResponse,
    responses={
        200: {
            "description": "Current evaluated status for license-aware UI.",
            "content": {
                "application/json": {
                    "examples": {
                        "warning": {
                            "summary": "License is approaching expiration",
                            "value": {
                                "state": "warning",
                                "warning_threshold_days": 14,
                                "tier": "team",
                                "features": ["core"],
                            },
                        },
                        "missing": {
                            "summary": "License state is not initialized",
                            "value": {
                                "state": "missing",
                                "warning_threshold_days": None,
                                "tier": None,
                                "features": [],
                            },
                        },
                    }
                }
            },
        }
    },
)
def get_live_license_status(request: Request) -> LicenseLiveStatusResponse:
    license_check = getattr(request.app.state, "license", None)
    if license_check is None:
        return LicenseLiveStatusResponse(state=LicenseState.MISSING.value)

    return LicenseLiveStatusResponse(
        state=license_check.state.value,
        warning_threshold_days=license_check.warning_threshold_days,
        tier=license_check.claims.tier if license_check.claims else None,
        features=list(license_check.claims.features) if license_check.claims else [],
    )


@router.get(
    "/status",
    summary="Get license status",
    description=(
        "Return the persistent installation site ID and evaluated license state. "
        "The verified claim summary is null if no signed license is loaded."
    ),
    response_model=LicenseStatusResponse,
    responses=LICENSE_STATUS_RESPONSES,
)
def get_license_status(
    request: Request,
    user: Annotated[dict, Depends(PermissionChecker(Permission.SYSTEM_CONFIG))],
    db: Session = Depends(get_db),
) -> LicenseStatusResponse:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    license_check = getattr(request.app.state, "license", None)
    if license_check is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="License status is not initialized yet.",
        )

    claims = license_check.claims
    license_summary = None
    if claims is not None:
        license_summary = {
            "license_id": str(claims.license_id),
            "license_type": claims.license_type,
            "customer_id": str(claims.customer_id),
            "customer_name": claims.customer_name,
            "site_ids": [str(site_id) for site_id in claims.site_ids],
            "tier": claims.tier,
            "user_cap": claims.user_cap,
            "issued_at": claims.issued_at.isoformat(),
            "valid_from": claims.valid_from.isoformat(),
            "valid_until": claims.valid_until.isoformat(),
            "grace_days": claims.grace_days,
            "features": list(claims.features),
        }

    return LicenseStatusResponse(
        site_id=get_or_create_site_id(db),
        state=license_check.state.value,
        reason=license_check.reason,
        license=license_summary,
    )


@router.post(
    "/upload",
    summary="Upload license file",
    description=(
        "Install a compact signed JWS license. The license must verify against "
        "the configured trusted key and authorize this installation's site ID."
    ),
    response_model=LicenseUploadResponse,
    responses=LICENSE_UPLOAD_RESPONSES,
)
async def upload_license(
    request: Request,
    user: Annotated[dict, Depends(PermissionChecker(Permission.SYSTEM_CONFIG))],
    file: UploadFile = File(
        ...,
        description="Compact signed JWS license file; maximum size is 16 KiB.",
    ),
    db: Session = Depends(get_db),
) -> LicenseUploadResponse:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    content = await file.read(MAX_LICENSE_SIZE + 1)
    if len(content) > MAX_LICENSE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="The file is too large. Maximum allowed: 16 KiB.",
        )

    try:
        trusted_keys = settings.trusted_license_keys
    except ValueError as exc:
        logger.error(f"Invalid license key configuration: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if not trusted_keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No trusted license key is configured.",
        )

    last_seen_clock = get_last_seen_clock(db)
    site_id = get_or_create_site_id(db)
    current_time = datetime.now(UTC)

    license_check = verify_license(
        license_file=content,
        trusted_keys=trusted_keys,
        site_id=site_id,
        now=current_time,
        last_seen_clock=last_seen_clock,
    )

    if license_check.state == LicenseState.INVALID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"License rejected: {license_check.reason}",
        )

    license_path = Path(settings.license_path)
    previous_license: bytes | None = None
    license_write_attempted = False

    try:
        if license_path.exists():
            previous_license = license_path.read_bytes()

        if license_check.state == LicenseState.CLOCK_ROLLBACK:
            nonce = license_check.claims.clock_reset_nonce if license_check.claims else None
            if not nonce:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Clock rollback detected: a recovery token is required.",
                )
            try:
                nonce_uuid = uuid.UUID(str(nonce))
            except (ValueError, TypeError, AttributeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid recovery token format; expected a UUID.",
                ) from exc

            if not consume_reset_nonce(db, str(nonce_uuid)):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This clock recovery token has already been used.",
                )
            force_reset_last_seen_clock(db, current_time)

            license_check = verify_license(
                license_file=content,
                trusted_keys=trusted_keys,
                site_id=site_id,
                now=current_time,
                last_seen_clock=current_time,
            )

            if license_check.state not in ACTIVE_LICENSE_STATES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "The recovery license is not active "
                        f"(state: {license_check.state.value})."
                    ),
                )
        else:
            advance_last_seen_clock(db, current_time)

        license_write_attempted = True
        editing_license_file(content)
        db.commit()

    except HTTPException:
        db.rollback()
        _restore_license_file(
            license_path, previous_license, license_write_attempted
        )
        raise
    except (SQLAlchemyError, OSError) as exc:
        db.rollback()
        _restore_license_file(
            license_path, previous_license, license_write_attempted
        )
        logger.error(f"License installation failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="License installation failed because of an internal or file-system error.",
        ) from exc

    request.app.state.license = license_check
    return LicenseUploadResponse(
        message="License installed successfully",
        state=license_check.state.value,
    )


def _restore_license_file(
    license_path: Path,
    previous_license: bytes | None,
    license_write_attempted: bool,
) -> None:
    if not license_write_attempted:
        return

    try:
        if previous_license is None:
            license_path.unlink(missing_ok=True)
        else:
            editing_license_file(previous_license)
    except OSError as restore_exc:
        logger.error(f"Could not restore license file {license_path}: {restore_exc}")
