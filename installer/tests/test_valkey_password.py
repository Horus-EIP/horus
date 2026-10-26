from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import yaml
except ImportError:
    yaml = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware  # noqa: E402
import horus_install  # noqa: E402
import smoke  # noqa: E402
from common import EXIT_OK, Log  # noqa: E402

try:
    import pty
except ImportError:
    pty = None

REPO = Path(__file__).resolve().parent.parent.parent
INFRA = REPO / "src" / "infra"
OLD_DEFAULT = "redis_password"
GENERATED = re.compile(r"[0-9a-f]{64}")

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the compose file")

class InfraCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        self.infra = self.repo / "src" / "infra"
        self.infra.mkdir(parents=True)
        self.log = Log(self.repo / "install-log.txt")
        self.addCleanup(self.log.close, 0)
        self.out = io.StringIO()
        quiet = contextlib.redirect_stdout(self.out)
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def write_env(self, text: str) -> None:
        (self.infra / ".env").write_text(text, encoding="utf-8")

    def env_value(self, key: str) -> str:
        return smoke.read_env(self.infra / ".env").get(key, "")

    def log_text(self) -> str:
        self.log.close(0)
        return (self.repo / "install-log.txt").read_text(encoding="utf-8")

    def assertGenerated(self, value: str) -> None:
        self.assertIsNotNone(GENERATED.fullmatch(value), f"not a generated password: {value!r}")

class ValkeyPassword(InfraCase):
    def password(self) -> str:
        return horus_install.valkey_password(self.log, self.infra)

    def test_a_first_install_generates_a_long_random_password(self):
        first, second = self.password(), self.password()
        self.assertGenerated(first)
        self.assertGenerated(second)
        self.assertNotEqual(first, second)

    def test_a_reinstall_keeps_the_password_it_generated(self):
        kept = "0123456789abcdef" * 4
        self.write_env(f"REDIS_PASSWORD={kept}\n")
        self.assertEqual(self.password(), kept)

    def test_a_password_the_user_chose_is_kept(self):
        self.write_env("REDIS_PASSWORD=chosen-by-the-tester\n")
        self.assertEqual(self.password(), "chosen-by-the-tester")

    def test_a_kept_password_is_written_back_exactly_as_it_was_quoted(self):
        for raw in ('"p#ss word"', "'pa$$word'"):
            with self.subTest(raw):
                self.write_env(f"REDIS_PASSWORD={raw}\n")
                self.assertEqual(self.password(), raw)

    def test_the_shipped_default_and_an_empty_password_are_replaced(self):
        for line in (f"REDIS_PASSWORD={OLD_DEFAULT}", f'REDIS_PASSWORD="{OLD_DEFAULT}"',
                     "REDIS_PASSWORD=", "REDIS_PASSWORD=   "):
            with self.subTest(line):
                self.write_env(line + "\n")
                self.assertGenerated(self.password())

    def test_replacing_the_default_is_said_on_screen(self):
        self.write_env(f"REDIS_PASSWORD={OLD_DEFAULT}\n")
        self.password()
        self.assertIn("Valkey password", self.out.getvalue())

    def test_the_password_is_never_logged(self):
        self.write_env(f"REDIS_PASSWORD={OLD_DEFAULT}\n")
        password = self.password()
        self.assertNotIn(password, self.log_text())
        self.assertNotIn(password, self.out.getvalue())

class AnUpgradeReplacesTheShippedDefault(InfraCase):
    def test_the_old_default_is_rewritten_in_place(self):
        self.write_env(f"REDIS_HOST=redis\nREDIS_PASSWORD={OLD_DEFAULT}\nPOSTGRES_DB=mas_db\n")
        password = horus_install.valkey_password(self.log, self.infra)
        horus_install.apply_env(self.log, self.infra, {"REDIS_PASSWORD": password}, reset=False)
        text = (self.infra / ".env").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"(?m)^REDIS_PASSWORD=.*$", text),
                         [f"REDIS_PASSWORD={password}"])
        self.assertNotIn(OLD_DEFAULT, text)

    def test_the_profile_json_never_holds_the_password(self):
        password = horus_install.valkey_password(self.log, self.infra)
        path = self.repo / "horus-profile.json"
        hardware.write_profile_json(path, dict(horus_install.SIMULATIONS["nvidia-8gb"]),
                                    "gpu-8g", {"REDIS_PASSWORD": password}, ["test"])
        self.assertNotIn(password, path.read_text(encoding="utf-8"))

class InstallWritesTheValkeyPassword(InfraCase):
    def install(self) -> mock.Mock:
        args = horus_install.build_parser().parse_args(
            ["--profile", "gpu-8g", "--non-interactive", "--skip-smoke"])
        order = mock.Mock()
        with contextlib.ExitStack() as stack:
            patch = stack.enter_context
            patch(mock.patch.object(horus_install, "find_repo", return_value=self.repo))
            patch(mock.patch.object(horus_install, "banner"))
            patch(mock.patch.object(horus_install, "preflight"))
            patch(mock.patch.object(horus_install, "sign_in_to_registry"))
            consent = patch(mock.patch.object(horus_install, "consent"))
            consent.choose.return_value = {"corpus_dir": "../../demo_assets"}
            machine = patch(mock.patch.object(horus_install, "hardware"))
            machine.probe.return_value = dict(horus_install.SIMULATIONS["nvidia-8gb"])
            order.attach_mock(patch(mock.patch.object(horus_install, "apply_env")), "apply_env")
            order.attach_mock(patch(mock.patch.object(horus_install, "pull_and_build")),
                              "pull_and_build")
            patch(mock.patch.object(horus_install, "wait_for_health"))
            patch(mock.patch.object(horus_install, "_success"))
            code = horus_install._dispatch(self.log, args)
        self.assertEqual(code, EXIT_OK)
        return order

    def written(self, order: mock.Mock) -> dict[str, str]:
        return order.apply_env.call_args.args[2]

    def test_a_full_install_writes_a_generated_password(self):
        self.assertGenerated(self.written(self.install())["REDIS_PASSWORD"])

    def test_an_upgrade_replaces_the_shipped_default(self):
        self.write_env(f"REDIS_PASSWORD={OLD_DEFAULT}\n")
        self.assertGenerated(self.written(self.install())["REDIS_PASSWORD"])

    def test_an_upgrade_keeps_a_generated_password(self):
        kept = "fedcba9876543210" * 4
        self.write_env(f"REDIS_PASSWORD={kept}\n")
        self.assertEqual(self.written(self.install())["REDIS_PASSWORD"], kept)

    def test_the_stack_starts_only_after_the_password_is_written(self):
        names = [call[0] for call in self.install().mock_calls if call[0]]
        self.assertEqual(names, ["apply_env", "pull_and_build"])

    def test_a_dry_run_never_shows_a_password(self):
        args = horus_install.build_parser().parse_args(
            ["--dry-run", "--simulate", "nvidia-8gb"])
        self.assertEqual(horus_install.do_dry_run(self.log, args, self.repo), EXIT_OK)
        self.assertNotIn("REDIS_PASSWORD", self.out.getvalue())

class TheTemplateShipsNoPassword(InfraCase):
    def test_the_env_example_leaves_the_password_empty(self):
        self.assertEqual(smoke.read_env(INFRA / ".env.example")["REDIS_PASSWORD"], "")

    def test_the_env_example_never_holds_the_old_default(self):
        self.assertNotIn(OLD_DEFAULT, (INFRA / ".env.example").read_text(encoding="utf-8"))

    def test_the_built_in_bootstrap_generates_it(self):
        shutil.copy(INFRA / ".env.example", self.infra / ".env.example")
        with mock.patch.object(horus_install.shutil, "which", return_value=None):
            horus_install._bootstrap_env(self.log, self.infra, reset=False)
        self.assertGenerated(self.env_value("REDIS_PASSWORD"))
        self.assertGenerated(self.env_value("JWT_SECRET_KEY"))
        self.assertNotEqual(self.env_value("REDIS_PASSWORD"), self.env_value("JWT_SECRET_KEY"))

    @unittest.skipUnless(shutil.which("bash"), "needs bash to run init-env.sh")
    def test_init_env_generates_it(self):
        for name in (".env.example", "init-env.sh"):
            shutil.copy(INFRA / name, self.infra / name)
        result = subprocess.run([shutil.which("bash"), "init-env.sh", "--quiet"],
                                cwd=self.infra, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGenerated(self.env_value("REDIS_PASSWORD"))
        self.assertGenerated(self.env_value("JWT_SECRET_KEY"))
        self.assertNotEqual(self.env_value("REDIS_PASSWORD"), self.env_value("JWT_SECRET_KEY"))
        self.assertEqual(self.env_value("HORUS_LAN_TLS"), "0")
        self.assertFalse((self.infra / "certs/horus.crt").exists())
        self.assertFalse((self.infra / "certs/horus.key").exists())

    @unittest.skipUnless(shutil.which("bash"), "needs bash to run init-env.sh")
    def test_init_env_can_enable_lan_access(self):
        for name in (".env.example", "init-env.sh"):
            shutil.copy(INFRA / name, self.infra / name)
        result = self.run_init_env_interactively("y\n192.168.1.55\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.env_value("HORUS_WEB_BIND"), "0.0.0.0")
        self.assertEqual(self.env_value("HORUS_LAN_TLS"), "0")
        self.assertIn("LAN HTTPS stays disabled", result.stdout)
        self.assertFalse((self.infra / "certs/horus.crt").exists())
        self.assertFalse((self.infra / "certs/horus.key").exists())

    @unittest.skipUnless(shutil.which("bash") and os.name == "posix" and pty is not None,
                         "needs bash and a POSIX pseudo-terminal")
    def test_init_env_keeps_lan_access_disabled_by_default(self):
        for name in (".env.example", "init-env.sh"):
            shutil.copy(INFRA / name, self.infra / name)
        result = self.run_init_env_interactively("\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.env_value("HORUS_WEB_BIND"), "127.0.0.1")
        self.assertIn("LAN access disabled", result.stdout)

    @unittest.skipUnless(shutil.which("bash"), "needs bash to run init-env.sh")
    def test_existing_env_without_certificate_does_not_block_bootstrap(self):
        shutil.copy(INFRA / ".env.example", self.infra / ".env.example")
        (self.infra / ".env").write_text("HORUS_WEB_BIND=127.0.0.1\n", encoding="utf-8")
        shutil.copy(INFRA / "init-env.sh", self.infra / "init-env.sh")
        result = subprocess.run([shutil.which("bash"), "init-env.sh", "--quiet"],
                                cwd=self.infra, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.infra / "certs/horus.crt").exists())
        self.assertFalse((self.infra / "certs/horus.key").exists())

    @unittest.skipUnless(shutil.which("bash") and os.name == "posix" and pty is not None,
                         "needs bash and a POSIX pseudo-terminal")
    def test_existing_install_can_enable_lan_without_a_self_signed_certificate(self):
        for name in (".env.example", "init-env.sh"):
            shutil.copy(INFRA / name, self.infra / name)
        (self.infra / ".env").write_text("HORUS_WEB_BIND=127.0.0.1\n", encoding="utf-8")
        local = subprocess.run([shutil.which("bash"), "init-env.sh", "--quiet"],
                               cwd=self.infra, capture_output=True, text=True, timeout=60)
        self.assertEqual(local.returncode, 0, local.stderr)

        result = self.run_init_env_interactively("y\n192.168.1.55\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.env_value("HORUS_WEB_BIND"), "0.0.0.0")
        self.assertEqual(self.env_value("HORUS_LAN_TLS"), "0")
        self.assertIn("LAN HTTPS stays disabled", result.stdout)
        self.assertFalse((self.infra / "certs/horus.crt").exists())
        self.assertFalse((self.infra / "certs/horus.key").exists())

    def run_init_env_interactively(self, answer: str) -> subprocess.CompletedProcess:
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen(
                [shutil.which("bash"), "init-env.sh"],
                cwd=self.infra,
                stdin=slave,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        finally:
            os.close(slave)
        os.write(master, answer.encode())
        try:
            stdout, stderr = process.communicate(timeout=60)
        finally:
            os.close(master)
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)

@needs_yaml
class ComposePassesThePassword(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        text = (INFRA / "docker-compose.yml").read_text(encoding="utf-8")
        cls.services = yaml.safe_load(text)["services"]

    def test_valkey_requires_the_password_from_the_env(self):
        self.assertIn("${REDIS_PASSWORD}", self.services["redis"]["command"])

    def test_mas_and_the_agent_send_that_same_password(self):
        for name in ("mas", "agent"):
            with self.subTest(name):
                self.assertIn("REDIS_PASSWORD=${REDIS_PASSWORD}",
                              self.services[name]["environment"])

    def test_an_empty_password_fails_the_valkey_healthcheck(self):
        test = self.services["redis"]["healthcheck"]["test"]
        self.assertEqual(test[0], "CMD")
        self.assertEqual(test[-1], "${REDIS_PASSWORD}")
        self.assertIn('test -n "$$1" && ', test[3])

if __name__ == "__main__":
    unittest.main()
