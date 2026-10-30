from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import horus_install  # noqa: E402
from common import EXIT_ENV_WRITE_FAILED, InstallError, Result  # noqa: E402


class MissingEnvSafety(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.infra = Path(self.tmp.name) / "src" / "infra"
        self.infra.mkdir(parents=True)
        (self.infra / ".env.example").write_text(
            "COMPOSE_PROJECT_NAME=horus_test\n", encoding="utf-8"
        )
        self.log = mock.Mock()

    def test_latest_backup_is_shown_and_restored_only_after_confirmation(self):
        older = self.infra / ".env.bak.20261024-120000"
        latest = self.infra / ".env.bak.20261025-120000"
        older.write_text("REDIS_PASSWORD=old\n", encoding="utf-8")
        latest.write_text("REDIS_PASSWORD=latest\n", encoding="utf-8")

        with (
            mock.patch.object(horus_install, "interactive_terminal", return_value=True),
            mock.patch("builtins.input", return_value="y") as prompt,
        ):
            horus_install.checking_backup_env_attendance(self.log, self.infra)

        self.assertEqual((self.infra / ".env").read_text(encoding="utf-8"),
                         "REDIS_PASSWORD=latest\n")
        self.assertIn(latest.name, prompt.call_args.args[0])
        self.log.say.assert_any_call(f"  {older.name}  (2026-10-24 12:00:00)")
        self.log.say.assert_any_call(f"Selected backup: {latest}")

    def test_declining_backup_restore_does_not_create_env(self):
        backup = self.infra / ".env.bak.20261025-120000"
        backup.write_text("REDIS_PASSWORD=secret\n", encoding="utf-8")

        with (
            mock.patch.object(horus_install, "interactive_terminal", return_value=True),
            mock.patch("builtins.input", return_value="n"),
        ):
            with self.assertRaises(InstallError) as caught:
                horus_install.checking_backup_env_attendance(self.log, self.infra)

        self.assertEqual(caught.exception.code, EXIT_ENV_WRITE_FAILED)
        self.assertFalse((self.infra / ".env").exists())

    def test_non_interactive_run_never_restores_a_backup_automatically(self):
        backup = self.infra / ".env.bak.20261025-120000"
        backup.write_text("REDIS_PASSWORD=secret\n", encoding="utf-8")

        with self.assertRaises(InstallError) as caught:
            horus_install.checking_backup_env_attendance(
                self.log, self.infra, non_interactive=True
            )

        self.assertEqual(caught.exception.code, EXIT_ENV_WRITE_FAILED)
        self.assertIn(backup.name, caught.exception.detail)
        self.assertFalse((self.infra / ".env").exists())

    def test_data_volume_check_is_filtered_to_this_compose_project(self):
        with mock.patch.object(
            horus_install,
            "run",
            return_value=Result(0, "horus_test_postgresql_data postgresql_data\n", ""),
        ) as run:
            volumes = horus_install.existing_volumes(self.log, "horus_test")

        self.assertEqual(volumes, [("horus_test_postgresql_data", "postgresql_data")])
        args = run.call_args.args[0]
        self.assertIn("--filter", args)
        self.assertIn("label=com.docker.compose.project=horus_test", args)

    def test_missing_env_checks_only_the_example_project_volumes(self):
        with mock.patch.object(
            horus_install,
            "existing_volumes",
            return_value=[("horus_test_postgresql_data", "postgresql_data")],
        ) as volumes:
            with self.assertRaises(InstallError):
                horus_install.checking_backup_env_attendance(self.log, self.infra)

        volumes.assert_called_once_with(self.log, "horus_test")

    def test_docker_volume_check_failure_stops_the_install(self):
        with mock.patch.object(
            horus_install,
            "existing_volumes",
            side_effect=horus_install.DockerCommandError("daemon unavailable"),
        ):
            with self.assertRaises(InstallError) as caught:
                horus_install.checking_backup_env_attendance(self.log, self.infra)

        self.assertEqual(caught.exception.code, EXIT_ENV_WRITE_FAILED)
        self.assertIn("daemon unavailable", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
