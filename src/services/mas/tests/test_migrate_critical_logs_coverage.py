from unittest.mock import MagicMock, patch

import pytest

from db.migrate_critical_logs import create_critical_logs_table


def test_create_critical_logs_table_success():
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn

    with patch("db.migrate_critical_logs.engine.connect", return_value=mock_conn):
        result = create_critical_logs_table()

        assert result is True
        mock_conn.execute.assert_called()
        mock_conn.commit.assert_called_once()


def test_create_critical_logs_table_exception():
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.execute.side_effect = Exception("DB Error")

    with patch("db.migrate_critical_logs.engine.connect", return_value=mock_conn):
        result = create_critical_logs_table()

        assert result is False
