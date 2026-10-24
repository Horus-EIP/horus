"""Application-startup initialization for the installation licence."""

from datetime import UTC, datetime
from pathlib import Path

from core.config import settings
from core.logger import get_logger
from db.database import SessionLocal
from licensing.clock import advance_last_seen_clock, get_last_seen_clock
from licensing.site import get_or_create_site_id
from licensing.verification import LicenseCheck, LicenseState, verify_license

logger = get_logger("licensing_lifecycle")


def initialize_license_state() -> LicenseCheck:
    """Load and verify the configured licence and persist its clock state."""
    try:
        with SessionLocal() as db:
            last_seen_clock = get_last_seen_clock(db)
            site_id = get_or_create_site_id(db)

        trusted_keys = settings.trusted_license_keys
        license_path = Path(settings.license_path)

        try:
            license_bytes = license_path.read_bytes()
        except OSError:
            license_bytes = None
            logger.warning(f"License file is missing or unreadable: {license_path}")

        current_time = datetime.now(UTC)
        license_check = verify_license(
            license_file=license_bytes,
            trusted_keys=trusted_keys,
            site_id=site_id,
            now=current_time,
            last_seen_clock=last_seen_clock,
        )

        if license_check.state not in {
            LicenseState.INVALID,
            LicenseState.MISSING,
            LicenseState.CLOCK_ROLLBACK,
        }:
            with SessionLocal() as db:
                advance_last_seen_clock(db, current_time)

        logger.info(
            "License state at startup: %s",
            license_check.state.value,
        )
        return license_check
    except Exception as exc:
        logger.error("Critical error while initializing the license: %s", exc)
        return LicenseCheck(
            state=LicenseState.INVALID,
            reason=f"Internal startup error: {exc}",
        )
