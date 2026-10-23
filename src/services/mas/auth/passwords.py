"""Credential hashing helpers with transparent migration from raw bcrypt hashes."""

import hashlib

from bcrypt import checkpw, gensalt, hashpw


def hash_credential(value: str) -> str:
    """Hash a credential after SHA-256 pre-hashing for bcrypt 5 compatibility."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest().encode("ascii")
    return hashpw(digest, gensalt()).decode("ascii")


def verify_and_upgrade_credential(
    value: str, stored_hash: str | bytes
) -> tuple[bool, str | None]:
    """Verify a current or pre-migration bcrypt hash and return an upgraded hash."""
    try:
        hashed = (
            stored_hash.encode("ascii") if isinstance(stored_hash, str) else stored_hash
        )
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest().encode("ascii")
        if checkpw(digest, hashed):
            return True, None
    except (TypeError, UnicodeEncodeError, ValueError):
        return False, None

    # Older Passlib/bcrypt hashes used the raw input and bcrypt truncated it at 72 bytes.
    legacy_input = value.encode("utf-8")[:72]
    try:
        if checkpw(legacy_input, hashed):
            return True, hash_credential(value)
    except (TypeError, ValueError):
        return False, None
    return False, None
