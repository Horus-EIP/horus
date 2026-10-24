"""Offline verification and evaluation of signed Horus licence files."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)

from core.config import settings
from core.logger import get_logger

logger = get_logger("licensing_verification")

MAX_LICENSE_BYTES = 16 * 1024
GRACE_DAYS = 15
WARNING_THRESHOLDS = (1, 7, 14, 30)
CLOCK_ROLLBACK_TOLERANCE = timedelta(hours=48)
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EXPECTED_HEADER_KEYS = frozenset({"alg", "kid", "typ"})
_REQUIRED_PAYLOAD_KEYS = frozenset(
    {
        "format_version",
        "license_id",
        "license_type",
        "customer_id",
        "customer_name",
        "site_ids",
        "tier",
        "user_cap",
        "issued_at",
        "valid_from",
        "valid_until",
        "grace_days",
        "features",
    }
)
_OPTIONAL_PAYLOAD_KEYS = frozenset({"clock_reset_nonce"})
_ALLOWED_PAYLOAD_KEYS = _REQUIRED_PAYLOAD_KEYS | _OPTIONAL_PAYLOAD_KEYS
_TIER_CAPS: dict[str, int | None] = {
    "starter": 25,
    "team": 100,
    "enterprise": None,
}


class LicenseState(str, Enum):
    MISSING = "missing"
    INVALID = "invalid"
    NOT_YET_VALID = "not_yet_valid"
    VALID = "valid"
    WARNING = "warning"
    GRACE = "grace"
    RESTRICTED = "restricted"
    CLOCK_ROLLBACK = "clock_rollback"


@dataclass(frozen=True)
class LicenseClaims:
    format_version: int
    license_id: uuid.UUID
    license_type: str
    customer_id: uuid.UUID
    customer_name: str
    site_ids: tuple[uuid.UUID, ...]
    tier: str
    user_cap: int | None
    issued_at: datetime
    valid_from: date
    valid_until: date
    grace_days: int
    features: tuple[str, ...]
    clock_reset_nonce: uuid.UUID | None = None


@dataclass(frozen=True)
class LicenseCheck:
    state: LicenseState
    claims: LicenseClaims | None = None
    reason: str | None = None
    is_capped: bool | None = None
    warning_threshold_days: int | None = None


class _InvalidLicense(ValueError):
    pass


def editing_license_file(content: bytes) -> None:
    license_path = Path(settings.license_path)
    temporary_path: Path | None = None
    try:
        license_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=license_path.parent,
            prefix=f".{license_path.name}.",
            delete=False,
            mode="wb"
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
        os.replace(temporary_path, license_path)
    except OSError as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                logger.warning(f"Could not remove temporary license file: {cleanup_error}")
        logger.error(f"Failed to write the license file: {exc}")
        raise


def verify_license(
    license_file: bytes | str | None,
    trusted_keys: Mapping[str, Ed25519PublicKey | bytes],
    site_id: uuid.UUID | str,
    *,
    now: datetime | None = None,
    last_seen_clock: datetime | None = None,
    active_user_count: int | None = None,
) -> LicenseCheck:
    """Verify a compact JWS and evaluate its state without performing I/O.

    ``trusted_keys`` maps protected-header ``kid`` values to Ed25519 public
    keys, supplied either as key objects or raw 32-byte public keys.
    ``last_seen_clock`` is supplied by the caller; persistence is deliberately
    outside this pure verification function.
    """
    if license_file is None:
        if last_seen_clock is not None:
            current_time = _as_utc(
                now if now is not None else datetime.now(UTC), "now"
            )
            if _clock_rollback_detected(current_time, last_seen_clock):
                return LicenseCheck(
                    LicenseState.CLOCK_ROLLBACK,
                    reason="System clock is more than 48 hours behind its stored high-water mark.",
                )
        return LicenseCheck(LicenseState.MISSING, reason="No licence file is configured.")

    installation_site = _as_uuid(site_id, "site_id")
    if active_user_count is not None and (
        type(active_user_count) is not int or active_user_count < 0
    ):
        raise ValueError("active_user_count must be a non-negative integer.")

    try:
        token = _license_text(license_file)
        header, payload_bytes, signing_input, signature = _decode_jws(token)
        key_id = header["kid"]
        if not isinstance(key_id, str) or not key_id:
            raise _InvalidLicense("JWS kid must be a non-empty string.")
        key = trusted_keys.get(key_id)
        if key is None:
            raise _InvalidLicense("JWS kid is not trusted.")
        public_key = (
            Ed25519PublicKey.from_public_bytes(key)
            if isinstance(key, bytes)
            else key
        )
        if not isinstance(public_key, Ed25519PublicKey):
            raise _InvalidLicense("Trusted key is not an Ed25519 public key.")
        public_key.verify(signature, signing_input)

        claims = _parse_claims(payload_bytes)
        _validate_claims(claims, installation_site)
    except InvalidSignature:
        return LicenseCheck(
            LicenseState.INVALID,
            reason="Licence signature verification failed.",
        )
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        _InvalidLicense,
        ValueError,
        RecursionError,
    ) as exc:
        return LicenseCheck(LicenseState.INVALID, reason=str(exc))

    current_time = _as_utc(now if now is not None else datetime.now(UTC), "now")

    state = _evaluate_dates(claims, current_time)

    capped = None
    warning_threshold = None
    if active_user_count is not None and state in {
        LicenseState.VALID,
        LicenseState.WARNING,
        LicenseState.GRACE,
    }:
        capped = claims.user_cap is not None and active_user_count >= claims.user_cap
    if state is LicenseState.WARNING:
        expiry = datetime.combine(claims.valid_until + timedelta(days=1), time.min, UTC)
        remaining = expiry - current_time
        warning_threshold = next(
            threshold
            for threshold in WARNING_THRESHOLDS
            if remaining <= timedelta(days=threshold)
        )

    if _clock_rollback_detected(current_time, last_seen_clock):
        return LicenseCheck(
            LicenseState.CLOCK_ROLLBACK,
            claims=claims,
            is_capped=capped,
            warning_threshold_days=warning_threshold,
            reason="System clock is more than 48 hours behind its stored high-water mark.",
        )
    return LicenseCheck(
        state,
        claims=claims,
        is_capped=capped,
        warning_threshold_days=warning_threshold,
    )


def _clock_rollback_detected(
    current_time: datetime,
    last_seen_clock: datetime | None,
) -> bool:
    if last_seen_clock is None:
        return False
    high_water = _as_utc(last_seen_clock, "last_seen_clock")
    return current_time < high_water - CLOCK_ROLLBACK_TOLERANCE


def _license_text(license_file: bytes | str) -> str:
    if isinstance(license_file, bytes):
        raw = license_file
    elif isinstance(license_file, str):
        try:
            raw = license_file.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise _InvalidLicense("Licence file is not valid UTF-8.") from exc
    else:
        raise _InvalidLicense("Licence file must be bytes or text.")

    if len(raw) > MAX_LICENSE_BYTES:
        raise _InvalidLicense("Licence file exceeds the 16 KiB limit.")
    if raw.startswith(b"\xef\xbb\xbf") or any(byte in raw for byte in b"\r\n\t "):
        raise _InvalidLicense("Licence file must be a compact token without whitespace or BOM.")
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise _InvalidLicense("Compact JWS must contain ASCII characters only.") from exc


def _decode_jws(token: str) -> tuple[dict[str, object], bytes, bytes, bytes]:
    parts = token.split(".")
    if len(parts) != 3 or any(not part or not _BASE64URL.fullmatch(part) for part in parts):
        raise _InvalidLicense("Licence must be a three-segment compact JWS.")

    header_segment, payload_segment, signature_segment = parts
    header_data = _decode_segment(header_segment)
    payload_data = _decode_segment(payload_segment)
    signature = _decode_segment(signature_segment)
    header_value = _strict_json(header_data)
    if not isinstance(header_value, dict):
        raise _InvalidLicense("JWS protected header must be a JSON object.")
    if set(header_value) != _EXPECTED_HEADER_KEYS:
        raise _InvalidLicense("JWS protected header has missing or unsupported fields.")
    if header_value.get("alg") != "EdDSA" or header_value.get("typ") != "HORUS-LICENSE":
        raise _InvalidLicense("JWS protected header must use EdDSA and HORUS-LICENSE.")
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    return header_value, payload_data, signing_input, signature


def _decode_segment(segment: str) -> bytes:
    if len(segment) % 4 == 1:
        raise _InvalidLicense("Compact JWS contains invalid base64url.")
    padded = segment + "=" * (-len(segment) % 4)
    try:
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    except binascii.Error as exc:
        raise _InvalidLicense("Compact JWS contains invalid base64url.") from exc
    if _base64url(decoded) != segment:
        raise _InvalidLicense("Compact JWS contains non-canonical base64url.")
    return decoded


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _strict_json(data: bytes) -> object:
    try:
        text = data.decode("utf-8")

        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise _InvalidLicense(f"JSON contains duplicate key {key!r}.")
                result[key] = value
            return result

        def reject_constant(value: str) -> object:
            raise _InvalidLicense(f"JSON contains unsupported constant {value}.")

        return json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except UnicodeDecodeError as exc:
        raise _InvalidLicense("JWS JSON is not valid UTF-8.") from exc
    except RecursionError as exc:
        raise _InvalidLicense("JWS JSON nesting is too deep.") from exc


def _parse_claims(payload_bytes: bytes) -> LicenseClaims:
    payload = _strict_json(payload_bytes)
    if not isinstance(payload, dict):
        raise _InvalidLicense("Licence payload must be a JSON object.")
    payload_keys = set(payload)
    if not _REQUIRED_PAYLOAD_KEYS.issubset(payload_keys) or not payload_keys.issubset(_ALLOWED_PAYLOAD_KEYS):
        missing = sorted(_REQUIRED_PAYLOAD_KEYS - payload_keys)
        extra = sorted(payload_keys - _ALLOWED_PAYLOAD_KEYS)
        raise _InvalidLicense(f"Payload fields mismatch (missing={missing}, extra={extra}).")

    if type(payload["format_version"]) is not int or payload["format_version"] != 1:
        raise _InvalidLicense("Unsupported licence format_version.")

    license_type = payload["license_type"]
    if not isinstance(license_type, str) or license_type not in {"commercial", "evaluation"}:
        raise _InvalidLicense("license_type must be commercial or evaluation.")

    customer_name = payload["customer_name"]
    if not isinstance(customer_name, str) or not 1 <= len(customer_name) <= 200:
        raise _InvalidLicense("customer_name must contain 1 to 200 characters.")

    raw_site_ids = payload["site_ids"]
    if not isinstance(raw_site_ids, list) or not raw_site_ids:
        raise _InvalidLicense("site_ids must be a non-empty array.")
    site_ids = tuple(_as_uuid(value, "site_ids item") for value in raw_site_ids)
    if len(set(site_ids)) != len(site_ids):
        raise _InvalidLicense("site_ids must not contain duplicates.")

    tier = payload["tier"]
    if not isinstance(tier, str) or tier not in _TIER_CAPS:
        raise _InvalidLicense("tier must be starter, team, or enterprise.")
    user_cap = payload["user_cap"]
    if user_cap is not None and type(user_cap) is not int:
        raise _InvalidLicense("user_cap must be an integer or null.")
    if user_cap != _TIER_CAPS[tier]:
        raise _InvalidLicense("user_cap does not match the licence tier.")

    grace_days = payload["grace_days"]
    if type(grace_days) is not int or grace_days != GRACE_DAYS:
        raise _InvalidLicense("grace_days must equal 15.")

    features = payload["features"]
    if (
        not isinstance(features, list)
        or not features
        or any(not isinstance(feature, str) for feature in features)
        or len(set(features)) != len(features)
        or set(features) != {"core"}
    ):
        raise _InvalidLicense("features must contain the unique core feature only.")

    clock_reset = payload.get("clock_reset_nonce")
    clock_reset_uuid: uuid.UUID | None = None
    if clock_reset is not None:
            clock_reset_uuid = _as_uuid(clock_reset, "clock_reset_nonce")


    return LicenseClaims(
        format_version=1,
        license_id=_as_uuid(payload["license_id"], "license_id"),
        license_type=license_type,
        customer_id=_as_uuid(payload["customer_id"], "customer_id"),
        customer_name=customer_name,
        site_ids=site_ids,
        tier=tier,
        user_cap=user_cap,
        issued_at=_parse_timestamp(payload["issued_at"]),
        valid_from=_parse_date(payload["valid_from"], "valid_from"),
        valid_until=_parse_date(payload["valid_until"], "valid_until"),
        grace_days=grace_days,
        features=tuple(features),
        clock_reset_nonce=clock_reset_uuid
    )


def _validate_claims(claims: LicenseClaims, installation_site: uuid.UUID) -> None:
    if claims.tier in {"starter", "team"} and len(claims.site_ids) != 1:
        raise _InvalidLicense("Starter and Team licences must authorize exactly one site.")
    if installation_site not in claims.site_ids:
        raise _InvalidLicense("Licence does not authorize this installation site.")
    if claims.valid_until < claims.valid_from:
        raise _InvalidLicense("valid_until must be on or after valid_from.")
    if claims.valid_until == date.max:
        raise _InvalidLicense("valid_until is too late to represent its expiry instant.")
    if claims.license_type == "evaluation":
        duration = (claims.valid_until - claims.valid_from).days
        if duration >= 90:
            raise _InvalidLicense("Evaluation licences may span at most 90 calendar dates.")


def _evaluate_dates(claims: LicenseClaims, now: datetime) -> LicenseState:
    starts_at = datetime.combine(claims.valid_from, time.min, UTC)
    expires_at = datetime.combine(claims.valid_until + timedelta(days=1), time.min, UTC)
    grace_ends_at = expires_at + timedelta(days=claims.grace_days)

    if now < starts_at:
        return LicenseState.NOT_YET_VALID
    if now < expires_at:
        if expires_at - now <= timedelta(days=30):
            return LicenseState.WARNING
        return LicenseState.VALID
    if now < grace_ends_at:
        return LicenseState.GRACE
    return LicenseState.RESTRICTED


def _parse_date(value: object, field: str) -> date:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise _InvalidLicense(f"{field} must be an ISO 8601 date (YYYY-MM-DD).")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise _InvalidLicense(f"{field} is not a valid calendar date.") from exc
    if parsed.isoformat() != value:
        raise _InvalidLicense(f"{field} must use canonical YYYY-MM-DD form.")
    return parsed


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not _UTC_TIMESTAMP.fullmatch(value):
        raise _InvalidLicense("issued_at must be an RFC 3339 UTC timestamp ending in Z.")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise _InvalidLicense("issued_at is not a valid timestamp.") from exc


def _as_uuid(value: object, field: str) -> uuid.UUID:
    if not isinstance(value, (str, uuid.UUID)):
        raise _InvalidLicense(f"{field} must be a UUID.")
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise _InvalidLicense(f"{field} must be a UUID.") from exc
    if isinstance(value, str) and str(parsed) != value.lower():
        raise _InvalidLicense(f"{field} must use canonical UUID form.")
    return parsed


def _as_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware.")
    return value.astimezone(UTC)
