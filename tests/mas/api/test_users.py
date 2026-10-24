"""Consolidated user-management API tests (hermetic).

User routes under test (``src/services/mas/users/routes.py``):

* ``POST   /users/update_role``                          (body: UpdateRole)
* ``GET    /users/users_list``
* ``GET    /users/user_details/{user_id:int}``
* ``GET    /users/me``
* ``DELETE /users/{user_id:int}``
* ``POST   /users/me/password_modification``             (body: UserPasswordModification)
* ``POST   /users/me/username_modification/{new_username}``

The licence API cases use ``src/services/mas/licensing/routes.py`` and the
dedicated ``/license`` API paths.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from licensing.routes import router as license_router
from licensing.verification import LicenseCheck, LicenseState
from sqlalchemy.exc import SQLAlchemyError

from users.routes import router


class TestUsersList:
    def test_admin_can_list_users(self, make_client, mock_db, as_admin):
        mock_db.query.return_value.all.return_value = []
        client = make_client(router, current_user=as_admin)
        r = client.get("/users/users_list")
        assert r.status_code == 200
        assert r.json() == []

    @patch("users.routes.get_user_details", return_value=None)
    def test_user_details_returns_404_for_unknown_user(self, _gud, make_client, as_admin):
        client = make_client(router, current_user=as_admin)
        r = client.get("/users/user_details/9999")  # int path
        assert r.status_code == 404


class TestUserUpdateRole:
    def test_admin_can_promote_a_user(self, make_client, mock_db, as_admin):
        target = MagicMock()
        # The handler does two lookups: role-existence then user. side_effect
        # returns None (no existing role) then the user model.
        mock_db.query.return_value.filter.return_value.first.side_effect = [None, target]
        client = make_client(router, current_user=as_admin)
        r = client.post(
            "/users/update_role",
            json={"user_id": "target-id", "new_role": "admin"},
        )
        assert r.status_code == 200

    def test_update_role_returns_404_when_user_missing(self, make_client, mock_db, as_admin):
        mock_db.query.return_value.filter.return_value.first.side_effect = [None, None]
        client = make_client(router, current_user=as_admin)
        r = client.post(
            "/users/update_role",
            json={"user_id": "ghost", "new_role": "admin"},
        )
        assert r.status_code == 404

    def test_admin_cannot_change_the_agent_account_role(
        self, make_client, mock_db, as_admin, monkeypatch
    ):
        monkeypatch.setattr("users.routes.settings.super_agent_username", "agent")
        client = make_client(router, current_user=as_admin)

        response = client.post(
            "/users/update_role",
            json={"user_id": "agent", "new_role": "admin"},
        )

        assert response.status_code == 403
        mock_db.query.assert_not_called()

    @pytest.mark.parametrize("bad_role", ["root", "", "ADMIN", "xx"])
    def test_update_role_rejects_invalid_role_string(self, make_client, mock_db, as_admin, bad_role):
        client = make_client(router, current_user=as_admin)
        r = client.post(
            "/users/update_role",
            json={"user_id": "target-id", "new_role": bad_role},
        )
        assert r.status_code == 422  # Pydantic Role(str, Enum) validation


class TestUserSelfService:
    @patch("users.routes.modify_user_password", return_value=True)
    def test_password_change_with_valid_payload(self, _mod, make_client, as_user):
        client = make_client(router, current_user=as_user)
        r = client.post(
            "/users/me/password_modification",
            json={"old_password": "Olds3cret!", "new_password": "News3cret!"},
        )
        assert r.status_code == 200

    @pytest.mark.parametrize("body", [{"old_password": "x"}, {"new_password": "y"}, {}])
    def test_password_change_rejects_invalid_body(self, make_client, as_user, body):
        client = make_client(router, current_user=as_user)
        r = client.post("/users/me/password_modification", json=body)
        assert r.status_code == 422  # Pydantic rejects missing fields

    @patch("users.routes.modify_user_username", return_value=True)
    def test_username_change_returns_200_on_success(self, _mod, make_client, as_user):
        client = make_client(router, current_user=as_user)
        r = client.post("/users/me/username_modification/newname")
        assert r.status_code == 200


class TestUserDelete:
    @patch("users.routes.delete_user_tool", return_value={"message": "deleted"})
    def test_admin_can_delete_a_user(self, mock_del, make_client, as_admin):
        # Targeting user_id != admin's id (admin has id=1, we delete id=99)
        client = make_client(router, current_user=as_admin)
        r = client.delete("/users/99")
        assert r.status_code == 200
        mock_del.assert_called_once()

    def test_delete_returns_403_when_targeting_self(self, make_client, as_admin):
        # as_admin has id=1; deleting /users/1 hits the self-check guard.
        client = make_client(router, current_user=as_admin)
        r = client.delete(f"/users/{as_admin['id']}")
        assert r.status_code == 403


class TestLicenseUpload:
    def test_admin_can_read_license_status_and_site_id(
        self, make_client, as_admin, mock_db
    ):
        client = make_client(license_router, current_user=as_admin)
        client.app.state.license = LicenseCheck(
            state=LicenseState.INVALID,
            reason="Public key configuration is invalid",
        )
        with patch(
            "licensing.routes.get_or_create_site_id", return_value="site-id"
        ):
            response = client.get("/license/status")

        assert response.status_code == 200
        assert response.json() == {
            "site_id": "site-id",
            "state": "invalid",
            "reason": "Public key configuration is invalid",
            "license": None,
        }

    def test_admin_can_read_verified_license_summary(
        self, make_client, as_admin
    ):
        claims = SimpleNamespace(
            license_id=UUID("018f0f6a-7b2c-7d5a-9b8c-0123456789ab"),
            license_type="commercial",
            customer_id=UUID("018f0f6a-7b2c-7d5a-9b8c-0123456789ac"),
            customer_name="Example Customer",
            site_ids=(UUID("018f0f6a-7b2c-7d5a-9b8c-0123456789ad"),),
            tier="team",
            user_cap=100,
            issued_at=datetime(2026, 10, 24, 12, tzinfo=UTC),
            valid_from=date(2026, 1, 1),
            valid_until=date(2026, 12, 31),
            grace_days=15,
            features=("core",),
            clock_reset_nonce=UUID("018f0f6a-7b2c-7d5a-9b8c-0123456789ae"),
        )
        client = make_client(license_router, current_user=as_admin)
        client.app.state.license = LicenseCheck(
            state=LicenseState.VALID,
            claims=claims,
        )
        with patch(
            "licensing.routes.get_or_create_site_id",
            return_value="018f0f6a-7b2c-7d5a-9b8c-0123456789ad",
        ):
            response = client.get("/license/status")

        assert response.status_code == 200
        assert response.json() == {
            "site_id": "018f0f6a-7b2c-7d5a-9b8c-0123456789ad",
            "state": "valid",
            "reason": None,
            "license": {
                "license_id": "018f0f6a-7b2c-7d5a-9b8c-0123456789ab",
                "license_type": "commercial",
                "customer_id": "018f0f6a-7b2c-7d5a-9b8c-0123456789ac",
                "customer_name": "Example Customer",
                "site_ids": ["018f0f6a-7b2c-7d5a-9b8c-0123456789ad"],
                "tier": "team",
                "user_cap": 100,
                "issued_at": "2026-10-24T12:00:00+00:00",
                "valid_from": "2026-01-01",
                "valid_until": "2026-12-31",
                "grace_days": 15,
                "features": ["core"],
            },
        }

    def test_admin_can_install_a_valid_license(
        self, make_client, as_admin, mock_db, monkeypatch, tmp_path
    ):
        license_path = tmp_path / "license.jws"
        trusted_keys = {"test-key": b"\x00" * 32}
        monkeypatch.setattr(
            "licensing.routes.settings",
            SimpleNamespace(
                license_path=str(license_path),
                trusted_license_keys=trusted_keys,
            ),
        )
        license_check = LicenseCheck(state=LicenseState.VALID)

        with (
            patch("licensing.routes.get_last_seen_clock", return_value=None),
            patch("licensing.routes.get_or_create_site_id", return_value="site-id"),
            patch("licensing.routes.advance_last_seen_clock") as advance_clock,
            patch("licensing.routes.verify_license", return_value=license_check) as verify,
            patch(
                "licensing.routes.editing_license_file",
                side_effect=lambda content: license_path.write_bytes(content),
            ),
        ):
            client = make_client(license_router, current_user=as_admin)
            response = client.post(
                "/license/upload",
                files={"file": ("license.jws", b"signed-license")},
            )

        assert response.status_code == 200
        assert response.json() == {
            "message": "License installed successfully",
            "state": "valid",
        }
        assert license_path.read_bytes() == b"signed-license"
        verify.assert_called_once()
        assert verify.call_args.kwargs["trusted_keys"] == trusted_keys
        advance_clock.assert_called_once_with(
            mock_db, verify.call_args.kwargs["now"]
        )

    def test_invalid_public_key_configuration_has_actionable_error(
        self, make_client, as_admin, monkeypatch, tmp_path
    ):
        license_path = tmp_path / "license.jws"

        class InvalidLicenseSettings:
            def __init__(self):
                self.license_path = str(license_path)

            @property
            def trusted_license_keys(self):
                raise ValueError(
                    "HORUS_LICENSE_PUBKEY_HEX must be a hexadecimal Ed25519 public key."
                )

        monkeypatch.setattr("licensing.routes.settings", InvalidLicenseSettings())
        with (
            patch("licensing.routes.get_last_seen_clock", return_value=None),
            patch("licensing.routes.get_or_create_site_id", return_value="site-id"),
            patch("licensing.routes.verify_license") as verify,
        ):
            client = make_client(license_router, current_user=as_admin)
            response = client.post(
                "/license/upload",
                files={"file": ("license.jws", b"signed-license")},
            )

        assert response.status_code == 500
        assert "HORUS_LICENSE_PUBKEY_HEX" in response.json()["detail"]
        assert not license_path.exists()
        verify.assert_not_called()

    def test_invalid_license_is_not_installed(
        self, make_client, as_admin, monkeypatch, tmp_path
    ):
        license_path = tmp_path / "license.jws"
        monkeypatch.setattr(
            "licensing.routes.settings",
            SimpleNamespace(
                license_path=str(license_path),
                trusted_license_keys={"test-key": b"\x00" * 32},
            ),
        )

        with (
            patch("licensing.routes.get_last_seen_clock", return_value=None),
            patch("licensing.routes.get_or_create_site_id", return_value="site-id"),
            patch("licensing.routes.advance_last_seen_clock") as advance_clock,
            patch(
                "licensing.routes.verify_license",
                return_value=LicenseCheck(
                    state=LicenseState.INVALID,
                    reason="Invalid signature",
                ),
            ),
        ):
            client = make_client(license_router, current_user=as_admin)
            response = client.post(
                "/license/upload",
                files={"file": ("license.jws", b"invalid-license")},
            )

        assert response.status_code == 400
        assert not license_path.exists()
        advance_clock.assert_not_called()

    def test_replayed_reset_nonce_does_not_replace_existing_license(
        self, make_client, as_admin, monkeypatch, tmp_path
    ):
        license_path = tmp_path / "license.jws"
        original_license = b"currently-installed-license"
        license_path.write_bytes(original_license)
        monkeypatch.setattr(
            "licensing.routes.settings",
            SimpleNamespace(
                license_path=str(license_path),
                trusted_license_keys={"test-key": b"\x00" * 32},
            ),
        )
        rollback_check = LicenseCheck(
            state=LicenseState.CLOCK_ROLLBACK,
            claims=SimpleNamespace(
                clock_reset_nonce=UUID("018f0f6a-7b2c-7d5a-9b8c-0123456789ab")
            ),
        )

        with (
            patch("licensing.routes.get_last_seen_clock", return_value=None),
            patch("licensing.routes.get_or_create_site_id", return_value="site-id"),
            patch("licensing.routes.verify_license", return_value=rollback_check),
            patch("licensing.routes.consume_reset_nonce", return_value=False) as consume,
            patch("licensing.routes.force_reset_last_seen_clock") as reset_clock,
            patch("licensing.routes.editing_license_file") as write_license,
        ):
            client = make_client(license_router, current_user=as_admin)
            response = client.post(
                "/license/upload",
                files={"file": ("license.jws", b"replayed-recovery-license")},
            )

        assert response.status_code == 400
        assert "already been used" in response.json()["detail"]
        assert license_path.read_bytes() == original_license
        consume.assert_called_once()
        reset_clock.assert_not_called()
        write_license.assert_not_called()

    def test_commit_failure_restores_existing_license_file(
        self, make_client, as_admin, mock_db, monkeypatch, tmp_path
    ):
        license_path = tmp_path / "license.jws"
        original_license = b"currently-installed-license"
        license_path.write_bytes(original_license)
        monkeypatch.setattr(
            "licensing.routes.settings",
            SimpleNamespace(
                license_path=str(license_path),
                trusted_license_keys={"test-key": b"\x00" * 32},
            ),
        )
        rollback_check = LicenseCheck(
            state=LicenseState.CLOCK_ROLLBACK,
            claims=SimpleNamespace(
                clock_reset_nonce=UUID("018f0f6a-7b2c-7d5a-9b8c-0123456789ac")
            ),
        )
        valid_check = LicenseCheck(state=LicenseState.VALID)

        def replace_license(content: bytes) -> None:
            license_path.write_bytes(content)

        mock_db.commit.side_effect = SQLAlchemyError("simulated commit failure")
        with (
            patch("licensing.routes.get_last_seen_clock", return_value=None),
            patch("licensing.routes.get_or_create_site_id", return_value="site-id"),
            patch(
                "licensing.routes.verify_license",
                side_effect=[rollback_check, valid_check],
            ),
            patch("licensing.routes.consume_reset_nonce", return_value=True),
            patch("licensing.routes.force_reset_last_seen_clock"),
            patch(
                "licensing.routes.editing_license_file",
                side_effect=replace_license,
            ) as write_license,
        ):
            client = make_client(license_router, current_user=as_admin)
            response = client.post(
                "/license/upload",
                files={"file": ("license.jws", b"new-recovery-license")},
            )

        assert response.status_code == 500
        assert license_path.read_bytes() == original_license
        assert write_license.call_count == 2
        mock_db.rollback.assert_called_once()

    def test_upload_rejects_files_over_the_size_limit(
        self, make_client, as_admin
    ):
        with patch("licensing.routes.verify_license") as verify:
            client = make_client(license_router, current_user=as_admin)
            response = client.post(
                "/license/upload",
                files={"file": ("license.jws", b"x" * (16 * 1024 + 1))},
            )

        assert response.status_code == 413
        verify.assert_not_called()


class TestUserErrors:
    def test_unauthenticated_caller_is_rejected(self, make_client):
        client = make_client(router, current_user=None)
        for path in ("/users/users_list", "/users/me"):
            assert client.get(path).status_code == 401

    def test_update_role_rejects_user_role(self, make_client, as_user):
        client = make_client(router, current_user=as_user)
        r = client.post(
            "/users/update_role",
            json={"user_id": "x", "new_role": "admin"},
        )
        assert r.status_code == 403

    def test_delete_rejects_manager_role(self, make_client, as_manager):
        client = make_client(router, current_user=as_manager)
        r = client.delete("/users/99")
        assert r.status_code == 403

    def test_agent_role_is_denied_user_routes(self, make_client, mock_db, as_agent):
        client = make_client(router, current_user=as_agent)

        response = client.get("/users/users_list")

        assert response.status_code == 403
        mock_db.query.assert_not_called()

    def test_agent_role_is_denied_admin_routes(self, make_client, mock_db, as_agent):
        client = make_client(router, current_user=as_agent)

        response = client.post(
            "/users/update_role",
            json={"user_id": "target-user", "new_role": "admin"},
        )

        assert response.status_code == 403
        mock_db.query.assert_not_called()
