import hashlib

from bcrypt import checkpw, gensalt, hashpw


def _bcrypt_input(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().encode("ascii")


def hash_password(value: str) -> bytes:
    return hashpw(_bcrypt_input(value), gensalt())


def verify_password(value: str, hashed: str | bytes) -> bool:
    hashed_bytes = hashed.encode("ascii") if isinstance(hashed, str) else hashed
    return checkpw(_bcrypt_input(value), hashed_bytes)


def hash_legacy_password(value: str) -> bytes:
    return hashpw(value.encode("utf-8"), gensalt())
