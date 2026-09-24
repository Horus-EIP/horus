"""Consolidated user-management API tests (hermetic).

Routes under test (``src/services/mas/users/routes.py``):

* ``POST   /users/update_role``                          (body: UpdateRole)
* ``GET    /users/users_list``
* ``GET    /users/user_details/{user_id:int}``
* ``GET    /users/me``
* ``DELETE /users/{user_id:int}``
* ``POST   /users/me/password_modification``             (body: UserPasswordModification)
* ``POST   /users/me/username_modification/{new_username}``
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
