from unittest.mock import MagicMock, patch

import pytest

from db.init_setup import init_db
from db.models import Users


def test_init_db_create_admin():
    mock_db = MagicMock()
    # Admin user does not exist
    mock_db.query.return_value.filter_by.return_value.first.return_value = None

    with patch("db.init_setup.SessionLocal", return_value=mock_db):
        with patch("db.init_setup.create_critical_logs_table", return_value=True):
            with patch(
                "db.init_setup.bcrypt_context.hash", return_value="hashed_password"
            ):
                with patch(
                    "db.init_setup.seed_default_agents", return_value=0
                ) as mock_seed:
                    init_db()

                    # Admin row added; agent seeding stubbed to keep this test
                    # focused on the admin path.
                    mock_db.add.assert_called_once()
                    mock_db.commit.assert_called_once()
                    mock_db.refresh.assert_called_once()
                    mock_seed.assert_called_once_with(mock_db)


def test_init_db_admin_exists():
    mock_db = MagicMock()
    # Admin user exists
    mock_admin = MagicMock()
    mock_admin.username = "admin"
    mock_db.query.return_value.filter_by.return_value.first.return_value = mock_admin

    with patch("db.init_setup.SessionLocal", return_value=mock_db):
        with patch("db.init_setup.create_critical_logs_table", return_value=True):
            with patch("db.init_setup.seed_default_agents", return_value=0):
                init_db()

                mock_db.add.assert_not_called()


def test_init_db_exception():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    with patch("db.init_setup.SessionLocal", return_value=mock_db):
        with patch("db.init_setup.create_critical_logs_table", return_value=True):
            with pytest.raises(Exception):
                init_db()

            mock_db.rollback.assert_called_once()


def test_init_db_create_critical_logs_fail():
    mock_db = MagicMock()
    mock_admin = MagicMock()
    mock_db.query.return_value.filter_by.return_value.first.return_value = mock_admin

    with patch("db.init_setup.SessionLocal", return_value=mock_db):
        with patch("db.init_setup.create_critical_logs_table", return_value=False):
            init_db()
            # Should continue even if critical logs table creation fails (based on code)
            mock_db.query.assert_called()
