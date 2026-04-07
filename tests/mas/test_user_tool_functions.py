"""
Tests for user tool functions
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from users.user_tool_functions import (delete_user, get_all_users,
                                       get_user_details, modify_user_username)


class TestUserToolFunctions:

    def setup_method(self):
        self.mock_db = MagicMock()
        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.mock_user.username = "testuser"
        self.mock_user.role = "user"

    def test_get_all_users(self):
        self.mock_db.query().all.return_value = [self.mock_user]

        users = get_all_users(self.mock_db)

        assert len(users) == 1
        assert users[0].username == "testuser"

    def test_get_all_users_exception(self):
        self.mock_db.query().all.side_effect = Exception("DB Error")

        users = get_all_users(self.mock_db)

        assert users == []

    def test_get_user_details_success(self):
        self.mock_db.query().filter().first.return_value = self.mock_user

        details = get_user_details(1, self.mock_db)

        assert details == (1, "testuser", "user")

    def test_get_user_details_not_found(self):
        self.mock_db.query().filter().first.return_value = None

        details = get_user_details(999, self.mock_db)

        assert details == (None, None, None)

    def test_get_user_details_exception(self):
        self.mock_db.query().filter().first.side_effect = Exception("DB Error")

        details = get_user_details(1, self.mock_db)

        assert details == (None, None, None, None)

    def test_delete_user_success(self):
        self.mock_db.query().filter().first.return_value = self.mock_user

        result = delete_user(1, self.mock_db)

        assert result == {
            "message": "User successfully deleted",
            "username": "testuser",
        }
        self.mock_db.delete.assert_called_once_with(self.mock_user)
        self.mock_db.commit.assert_called_once()

    def test_delete_user_not_found(self):
        self.mock_db.query().filter().first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            delete_user(999, self.mock_db)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found"

    def test_delete_user_admin_forbidden(self):
        admin_user = MagicMock()
        admin_user.username = "admin"
        self.mock_db.query().filter().first.return_value = admin_user

        with pytest.raises(HTTPException) as exc_info:
            delete_user(1, self.mock_db)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Cannot delete the main admin account"

    def test_delete_user_exception(self):
        self.mock_db.query().filter().first.return_value = self.mock_user
        self.mock_db.commit.side_effect = Exception("DB Error")

        with pytest.raises(HTTPException) as exc_info:
            delete_user(1, self.mock_db)

        assert exc_info.value.status_code == 500
        assert "Error deleting user" in exc_info.value.detail
        self.mock_db.rollback.assert_called_once()

    def test_modify_user_username_success(self):
        self.mock_db.query().filter().first.return_value = self.mock_user
        # Mock check for existing username (should return None)
        self.mock_db.query().filter().filter().first.return_value = None

        # We need to handle the multiple filter calls.
        # First call is filter(Users.id == user_id).first() -> returns user
        # Second call is filter(Users.username == new_username).first() -> returns None

        # Let's mock the query object more carefully
        mock_query = self.mock_db.query.return_value

        # We can use side_effect on filter to distinguish calls if needed,
        # or just rely on the order if we know it.
        # But here, the code does:
        # user = db.query(Users).filter(Users.id == user_id).first()
        # existing_user = db.query(Users).filter(Users.username == new_username).first()

        # Since both use db.query(Users), they return the SAME mock object.
        # So filter().first() will be called twice.

        mock_query.filter.return_value.first.side_effect = [self.mock_user, None]

        result = modify_user_username(1, "newname", self.mock_db)

        assert result is True
        assert self.mock_user.username == "newname"
        self.mock_db.commit.assert_called_once()

    def test_modify_user_username_user_not_found(self):
        mock_query = self.mock_db.query.return_value
        mock_query.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            modify_user_username(999, "newname", self.mock_db)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found"

    def test_modify_user_username_conflict(self):
        mock_query = self.mock_db.query.return_value
        existing_user = MagicMock()

        # First call returns user, second call returns existing_user (conflict)
        mock_query.filter.return_value.first.side_effect = [
            self.mock_user,
            existing_user,
        ]

        with pytest.raises(HTTPException) as exc_info:
            modify_user_username(1, "existingname", self.mock_db)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "Username already exists"

    def test_modify_user_username_exception(self):
        mock_query = self.mock_db.query.return_value
        mock_query.filter.return_value.first.side_effect = [self.mock_user, None]
        self.mock_db.commit.side_effect = Exception("DB Error")

        with pytest.raises(HTTPException) as exc_info:
            modify_user_username(1, "newname", self.mock_db)

        assert exc_info.value.status_code == 500
        assert "Error changing username" in exc_info.value.detail
        self.mock_db.rollback.assert_called_once()
