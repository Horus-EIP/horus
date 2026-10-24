"""Trusted signing-key configuration helpers for licence verification."""

import binascii


def trusted_license_keys(
    key_id: str,
    public_key_hex: str | None,
) -> dict[str, bytes]:
    """Build the Ed25519 key map used to verify compact licence JWS files."""
    if public_key_hex is None or not public_key_hex.strip():
        return {}
    if not key_id.strip():
        raise ValueError("HORUS_LICENSE_KID must not be empty.")

    try:
        public_key = binascii.unhexlify(public_key_hex.strip())
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            "HORUS_LICENSE_PUBKEY_HEX must be a hexadecimal Ed25519 public key."
        ) from exc

    if len(public_key) != 32:
        raise ValueError(
            "HORUS_LICENSE_PUBKEY_HEX must decode to exactly 32 bytes."
        )
    return {key_id.strip(): public_key}
