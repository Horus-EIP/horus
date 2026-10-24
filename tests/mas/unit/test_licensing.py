import base64
import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from licensing.verification import LicenseState, verify_license

SITE_ID = "018f0f6a-7b2c-7d5a-9b8c-0123456789ad"
KEY_ID = "test-key"
NOW = datetime(2026, 10, 23, 17, tzinfo=UTC)


@pytest.fixture
def signing_key():
    return Ed25519PrivateKey.generate()


def public_key_bytes(private_key):
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def payload(**overrides):
    result = {
        "format_version": 1,
        "license_id": "018f0f6a-7b2c-7d5a-9b8c-0123456789ab",
        "license_type": "commercial",
        "customer_id": "018f0f6a-7b2c-7d5a-9b8c-0123456789ac",
        "customer_name": "Example Customer",
        "site_ids": [SITE_ID],
        "tier": "team",
        "user_cap": 100,
        "issued_at": "2026-10-23T17:00:00Z",
        "valid_from": "2026-10-23",
        "valid_until": "2027-01-22",
        "grace_days": 15,
        "features": ["core"],
    }
    result.update(overrides)
    return result


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign(private_key, claims=None, *, header=None, raw_payload=None):
    protected = header or {"alg": "EdDSA", "kid": KEY_ID, "typ": "HORUS-LICENSE"}
    header_segment = b64url(json.dumps(protected, separators=(",", ":")).encode())
    if raw_payload is None:
        raw_payload = json.dumps(
            claims if claims is not None else payload(),
            separators=(",", ":"),
        ).encode()
    payload_segment = b64url(raw_payload)
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    return (
        f"{header_segment}.{payload_segment}."
        f"{b64url(private_key.sign(signing_input))}"
    )


def check(token, private_key, **kwargs):
    return verify_license(
        token,
        {KEY_ID: public_key_bytes(private_key)},
        SITE_ID,
        now=NOW,
        **kwargs,
    )


def test_valid_commercial_license_has_expected_claims(signing_key):
    result = check(sign(signing_key), signing_key, active_user_count=42)

    assert result.state is LicenseState.VALID
    assert result.claims is not None
    assert result.claims.tier == "team"
    assert result.claims.user_cap == 100
    assert result.is_capped is False
    assert result.reason is None


def test_missing_license_is_reported(signing_key):
    result = verify_license(None, {}, SITE_ID, now=NOW)

    assert result.state is LicenseState.MISSING
    assert result.claims is None


@pytest.mark.parametrize(
    ("now", "claims", "expected"),
    [
        (
            datetime(2026, 12, 23, 23, 59, 59, tzinfo=UTC),
            {"valid_from": "2026-12-24"},
            LicenseState.NOT_YET_VALID,
        ),
        (
            datetime(2026, 12, 24, tzinfo=UTC),
            {"valid_from": "2026-12-24"},
            LicenseState.WARNING,
        ),
        (
            datetime(2027, 1, 22, 23, 59, 59, tzinfo=UTC),
            {},
            LicenseState.WARNING,
        ),
        (
            datetime(2027, 1, 23, tzinfo=UTC),
            {},
            LicenseState.GRACE,
        ),
        (
            datetime(2027, 2, 6, 23, 59, 59, tzinfo=UTC),
            {},
            LicenseState.GRACE,
        ),
        (
            datetime(2027, 2, 7, tzinfo=UTC),
            {},
            LicenseState.RESTRICTED,
        ),
    ],
)
def test_license_date_states_at_boundaries(signing_key, now, claims, expected):
    token = sign(signing_key, payload(**claims))
    result = verify_license(
        token,
        {KEY_ID: public_key_bytes(signing_key)},
        SITE_ID,
        now=now,
    )

    assert result.state is expected


def test_warning_starts_at_exactly_30_days_before_expiration(signing_key):
    token = sign(signing_key, payload(valid_until="2026-11-22"))
    before = datetime(2026, 10, 23, 23, 59, 59, tzinfo=UTC)
    threshold = datetime(2026, 10, 24, tzinfo=UTC)

    assert verify_license(token, {KEY_ID: public_key_bytes(signing_key)}, SITE_ID,
                          now=before).state is LicenseState.VALID
    assert verify_license(token, {KEY_ID: public_key_bytes(signing_key)}, SITE_ID,
                          now=threshold).state is LicenseState.WARNING


@pytest.mark.parametrize(
    ("now", "expected_threshold"),
    [
        (datetime(2026, 12, 24, tzinfo=UTC), 30),
        (datetime(2027, 1, 9, tzinfo=UTC), 14),
        (datetime(2027, 1, 16, tzinfo=UTC), 7),
        (datetime(2027, 1, 22, tzinfo=UTC), 1),
    ],
)
def test_warning_reports_the_most_urgent_threshold(signing_key, now, expected_threshold):
    token = sign(signing_key)
    result = verify_license(
        token,
        {KEY_ID: public_key_bytes(signing_key)},
        SITE_ID,
        now=now,
    )

    assert result.state is LicenseState.WARNING
    assert result.warning_threshold_days == expected_threshold


@pytest.mark.parametrize(
    ("active_user_count", "expected_capped"),
    [(99, False), (100, True), (101, True)],
)
def test_user_cap_flag_is_orthogonal_to_license_state(
    signing_key, active_user_count, expected_capped
):
    result = check(sign(signing_key), signing_key, active_user_count=active_user_count)

    assert result.state is LicenseState.VALID
    assert result.is_capped is expected_capped


def test_enterprise_license_has_no_user_cap(signing_key):
    claims = payload(tier="enterprise", user_cap=None, site_ids=[SITE_ID, str(uuid.uuid4())])
    result = check(sign(signing_key, claims), signing_key, active_user_count=100_000)

    assert result.state is LicenseState.VALID
    assert result.is_capped is False


def test_capped_is_unknown_when_user_count_is_not_supplied(signing_key):
    result = check(sign(signing_key), signing_key)

    assert result.is_capped is None


def test_clock_rollback_has_priority_over_missing_license(signing_key):
    result = verify_license(
        None,
        {},
        SITE_ID,
        now=NOW,
        last_seen_clock=NOW + timedelta(hours=48, seconds=1),
    )

    assert result.state is LicenseState.CLOCK_ROLLBACK


def test_clock_rollback_tolerance_is_strictly_more_than_48_hours(signing_key):
    permitted = verify_license(
        sign(signing_key),
        {KEY_ID: public_key_bytes(signing_key)},
        SITE_ID,
        now=NOW,
        last_seen_clock=NOW + timedelta(hours=48),
    )
    rejected = verify_license(
        sign(signing_key),
        {KEY_ID: public_key_bytes(signing_key)},
        SITE_ID,
        now=NOW,
        last_seen_clock=NOW + timedelta(hours=48, microseconds=1),
    )

    assert permitted.state is LicenseState.VALID
    assert rejected.state is LicenseState.CLOCK_ROLLBACK


@pytest.mark.parametrize(
    ("token", "keys", "site_id"),
    [
        ("not-a-jws", {KEY_ID: b"0" * 32}, SITE_ID),
        (None, {}, "bad-site"),
        ("", {KEY_ID: b"0" * 32}, SITE_ID),
    ],
)
def test_malformed_or_missing_tokens_fail_closed(signing_key, token, keys, site_id):
    if token is None:
        result = verify_license(token, keys, site_id, now=NOW)
        assert result.state is LicenseState.MISSING
    else:
        result = verify_license(token, keys, site_id, now=NOW)
        assert result.state is LicenseState.INVALID


def test_signature_tampering_is_rejected(signing_key):
    token = sign(signing_key)
    header, body, signature = token.split(".")
    altered = f"{header}.{body[:-1]}{'A' if body[-1] != 'A' else 'B'}.{signature}"

    assert check(altered, signing_key).state is LicenseState.INVALID


def test_unknown_key_id_is_rejected(signing_key):
    token = sign(signing_key, header={
        "alg": "EdDSA", "kid": "unknown", "typ": "HORUS-LICENSE"
    })

    assert check(token, signing_key).state is LicenseState.INVALID


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "none", "kid": KEY_ID, "typ": "HORUS-LICENSE"},
        {"alg": "EdDSA", "kid": KEY_ID, "typ": "OTHER"},
        {"alg": "EdDSA", "kid": KEY_ID, "typ": "HORUS-LICENSE", "crit": []},
    ],
)
def test_unsupported_header_values_are_rejected(signing_key, header):
    assert check(sign(signing_key, header=header), signing_key).state is LicenseState.INVALID


def test_duplicate_json_keys_are_rejected(signing_key):
    raw_payload = json.dumps(payload(), separators=(",", ":")).encode()
    duplicate_payload = raw_payload.replace(
        b'"format_version":1',
        b'"format_version":1,"format_version":1',
        1,
    )

    assert check(sign(signing_key, raw_payload=duplicate_payload), signing_key).state is (
        LicenseState.INVALID
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"format_version": 2},
        {"tier": "team", "user_cap": 25},
        {"tier": "starter", "user_cap": 25, "site_ids": [SITE_ID, str(uuid.uuid4())]},
        {"site_ids": [str(uuid.uuid4())]},
        {"valid_from": "2026-10-24", "valid_until": "2026-10-23"},
        {"features": ["core", "marketplace"]},
        {"grace_days": 14},
        {"valid_until": "2027-01-21", "license_type": "evaluation"},
    ],
)
def test_semantically_invalid_claims_are_rejected(signing_key, overrides):
    assert check(sign(signing_key, payload(**overrides)), signing_key).state is LicenseState.INVALID


def test_unknown_claims_are_rejected(signing_key):
    claims = payload()
    claims["extra"] = "not allowed"

    assert check(sign(signing_key, claims), signing_key).state is LicenseState.INVALID


def test_noncanonical_dates_and_non_utc_issue_times_are_rejected(signing_key):
    compact_date = payload(valid_from="20261023")
    offset_time = payload(issued_at="2026-10-23T17:00:00+00:00")

    assert check(sign(signing_key, compact_date), signing_key).state is LicenseState.INVALID
    assert check(sign(signing_key, offset_time), signing_key).state is LicenseState.INVALID


def test_file_size_limit_and_whitespace_are_enforced(signing_key):
    oversized = "A" * (16 * 1024 + 1)
    with_whitespace = sign(signing_key) + "\n"

    assert check(oversized, signing_key).state is LicenseState.INVALID
    assert check(with_whitespace, signing_key).state is LicenseState.INVALID


def test_naive_clock_inputs_are_rejected(signing_key):
    with pytest.raises(ValueError, match="timezone-aware"):
        verify_license(sign(signing_key), {KEY_ID: public_key_bytes(signing_key)}, SITE_ID,
                       now=datetime(2026, 10, 23))
