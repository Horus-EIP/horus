import sys
from unittest.mock import MagicMock, patch

import pytest

from alembic_helper import main, run_command


class TestAlembicHelperCoverage:

    @patch("alembic_helper.subprocess.run")
    def test_run_command_success(self, mock_run):
        mock_run.return_value.returncode = 0
        assert run_command("ls") is True

    @patch("alembic_helper.subprocess.run")
    def test_run_command_failure(self, mock_run):
        mock_run.return_value.returncode = 1
        assert run_command("ls") is False

    @patch("alembic_helper.subprocess.run")
    def test_run_command_exception(self, mock_run):
        mock_run.side_effect = Exception("Error")
        assert run_command("ls") is False

    @patch("sys.argv", ["alembic_helper.py"])
    def test_main_no_args(self):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    @patch("sys.argv", ["alembic_helper.py", "status"])
    @patch("alembic_helper.run_command")
    def test_main_status(self, mock_run):
        main()
        mock_run.assert_called_with("alembic current", "Current Migration Status")

    @patch("sys.argv", ["alembic_helper.py", "history"])
    @patch("alembic_helper.run_command")
    def test_main_history(self, mock_run):
        main()
        mock_run.assert_called_with("alembic history", "Migration History")

    @patch("sys.argv", ["alembic_helper.py", "upgrade"])
    @patch("alembic_helper.run_command")
    def test_main_upgrade(self, mock_run):
        main()
        mock_run.assert_called_with(
            "alembic upgrade head", "Applying all pending migrations"
        )

    @patch("sys.argv", ["alembic_helper.py", "downgrade"])
    @patch("alembic_helper.run_command")
    def test_main_downgrade(self, mock_run):
        main()
        mock_run.assert_called_with(
            "alembic downgrade base", "Rolling back all migrations to base"
        )

    @patch("sys.argv", ["alembic_helper.py", "rollback-1"])
    @patch("alembic_helper.run_command")
    def test_main_rollback_1(self, mock_run):
        main()
        mock_run.assert_called_with(
            "alembic downgrade -1", "Rolling back last migration"
        )

    @patch("sys.argv", ["alembic_helper.py", "create"])
    def test_main_create_no_desc(self):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    @patch("sys.argv", ["alembic_helper.py", "create", "my", "migration"])
    @patch("alembic_helper.run_command")
    def test_main_create_success(self, mock_run):
        main()
        mock_run.assert_called()
        assert (
            'alembic revision --autogenerate -m "my migration"'
            in mock_run.call_args[0][0]
        )

    @patch("sys.argv", ["alembic_helper.py", "test"])
    @patch("alembic_helper.run_command")
    def test_main_test(self, mock_run):
        main()
        assert mock_run.call_count == 5

    @patch("sys.argv", ["alembic_helper.py", "current"])
    @patch("alembic_helper.run_command")
    def test_main_current(self, mock_run):
        main()
        mock_run.assert_called_with("alembic current", "Current Revision Details")

    @patch("sys.argv", ["alembic_helper.py", "unknown"])
    def test_main_unknown(self):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
