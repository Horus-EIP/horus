#!/usr/bin/env python3
"""Generate a local-only Horus test licence.

The signing key is generated in memory for this run. The script writes only the
signed JWS and prints its public key; it never writes or prints the private key.
Never use this script or its output for production licensing.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DEFAULT_KEY_ID = "horus-test-v1"
DEFAULT_OUTPUT = Path("test-license.jws")


def _base64url(data: bytes) -> str:
    """Encode a JWS base64url segment without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_test_license(
    site_id: uuid.UUID | str,
    *,
    kid: str = DEFAULT_KEY_ID,
    rollback_nonce: uuid.UUID | str | None = None,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Return a local test JWS and its raw Ed25519 public key as hexadecimal."""
    try:
        normalized_site_id = str(uuid.UUID(str(site_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("site_id must be a valid UUID.") from exc

    if not kid or kid != kid.strip():
        raise ValueError("kid must be a non-empty string without surrounding whitespace.")

    normalized_nonce = None
    if rollback_nonce is not None:
        try:
            normalized_nonce = str(uuid.UUID(str(rollback_nonce)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("rollback_nonce must be a valid UUID.") from exc

    issued_at = now if now is not None else datetime.now(UTC)
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware.")
    issued_at = issued_at.astimezone(UTC)

    private_key = Ed25519PrivateKey.generate()
    public_key_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()

    header = {
        "alg": "EdDSA",
        "kid": kid,
        "typ": "HORUS-LICENSE",
    }
    payload = {
        "format_version": 1,
        "license_id": str(uuid.uuid4()),
        "license_type": "commercial",
        "customer_id": str(uuid.uuid4()),
        "customer_name": "Horus Local Test",
        "site_ids": [normalized_site_id],
        "tier": "starter",
        "user_cap": 25,
        "issued_at": issued_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_from": issued_at.date().isoformat(),
        "valid_until": (issued_at.date() + timedelta(days=90)).isoformat(),
        "grace_days": 15,
        "features": ["core"],
    }
    if normalized_nonce is not None:
        payload["clock_reset_nonce"] = normalized_nonce

    protected_segment = _base64url(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    payload_segment = _base64url(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{protected_segment}.{payload_segment}".encode("ascii")
    signature_segment = _base64url(private_key.sign(signing_input))
    return f"{protected_segment}.{payload_segment}.{signature_segment}", public_key_hex


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a local-only Horus test licence. Never use it in production."
    )
    parser.add_argument(
        "site_id",
        type=uuid.UUID,
        help="Installation site UUID returned by GET /license/status.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JWS path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--kid",
        default=DEFAULT_KEY_ID,
        help=f"Test key identifier (default: {DEFAULT_KEY_ID}).",
    )
    parser.add_argument(
        "--rollback-nonce",
        type=uuid.UUID,
        help="Optional signed UUID nonce for a clock-rollback recovery test.",
    )
    args = parser.parse_args(argv)

    try:
        token, public_key_hex = generate_test_license(
            args.site_id,
            kid=args.kid,
            rollback_nonce=args.rollback_nonce,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(token, encoding="ascii")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print("LOCAL TEST LICENSE GENERATED - NEVER USE IN PRODUCTION")
    print(f"Output: {args.out}")
    print(f"HORUS_LICENSE_KID={args.kid}")
    print(f"HORUS_LICENSE_PUBKEY_HEX={public_key_hex}")
    print("The signing private key was not saved and cannot be reused.")
    if args.rollback_nonce is not None:
        print(f"Recovery nonce: {args.rollback_nonce}")
    print("Upload the JWS with an authorized account using POST /license/upload.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
