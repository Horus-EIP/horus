import uuid

import pytest
from licensing.models import GlobalConfig
from licensing.site import get_or_create_site_id
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.config import Settings
from db.database import Base


def make_settings(**overrides):
    values = {
        "postgres_user": "horus",
        "postgres_password": "db-password",
        "postgres_db": "horus",
        "jwt_secret_key": "test-secret",
        "super_user_username": "admin",
        "super_user_password": "admin-password",
        "redis_password": "redis-password",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[GlobalConfig.__table__])
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_site_id_is_generated_once_and_persisted(db_session):
    first = get_or_create_site_id(db_session)
    db_session.expire_all()
    second = get_or_create_site_id(db_session)

    assert uuid.UUID(first)
    assert second == first
    assert db_session.query(GlobalConfig).count() == 1


def test_configured_license_public_key_is_returned_as_raw_bytes():
    settings = make_settings(
        HORUS_LICENSE_KID="deployment-key",
        HORUS_LICENSE_PUBKEY_HEX="ab" * 32,
    )

    assert settings.trusted_license_keys == {"deployment-key": bytes.fromhex("ab" * 32)}


def test_missing_public_key_configuration_returns_no_trusted_keys():
    assert make_settings().trusted_license_keys == {}


@pytest.mark.parametrize("public_key", ["not-hex", "ab" * 31, "ab" * 33])
def test_invalid_public_key_configuration_is_rejected(public_key):
    settings = make_settings(HORUS_LICENSE_PUBKEY_HEX=public_key)

    with pytest.raises(ValueError, match="HORUS_LICENSE_PUBKEY_HEX"):
        _ = settings.trusted_license_keys


def test_license_path_reads_horus_environment_alias():
    settings = make_settings(HORUS_LICENSE_PATH="/run/horus/licence.jws")

    assert settings.license_path == "/run/horus/licence.jws"
