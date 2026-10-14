from __future__ import annotations

import contextlib
import io
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware  # noqa: E402
import horus_install  # noqa: E402
import smoke  # noqa: E402
from common import EXIT_OK, Events, Log, Result  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
INFRA = REPO / "src" / "infra"
KEY = "SUPER_USER_PASSWORD"
CHOSEN = "Chosen-Pass-2026!"
MAS_OUTPUT = ("Starting MAS Service Container...\n"
              '{"event": "Admin user already exists: admin", "level": "info"}\n')


def policy_shaped(value: str) -> bool:
    return (len(value) >= 10 and bool(re.match("[A-Za-z0-9]", value))
            and all(re.search(pattern, value) for pattern in ("[a-z]", "[A-Z]", "[0-9]", "[-_]")))


class InfraCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        self.infra = self.repo / "src" / "infra"
        self.infra.mkdir(parents=True)
        self.events = io.StringIO()
        self.log = Log(self.repo / "install-log.txt", events=Events(True, stream=self.events))
        self.addCleanup(self.log.close, 0)
        self.out = io.StringIO()
        quiet = contextlib.redirect_stdout(self.out)
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def write_env(self, text: str) -> None:
        (self.infra / ".env").write_text(text, encoding="utf-8")

    def env_text(self) -> str:
        return (self.infra / ".env").read_text(encoding="utf-8")

    def env_value(self, key: str) -> str:
        return smoke.read_env(self.infra / ".env").get(key, "")

    def log_text(self) -> str:
        self.log.close(0)
        return (self.repo / "install-log.txt").read_text(encoding="utf-8")

    def assertGenerated(self, value: str) -> None:
        self.assertTrue(policy_shaped(value), f"not a generated password: {value!r}")


class AdminPassword(InfraCase):
    def password(self) -> tuple[str, bool]:
        return horus_install.admin_password(self.log, self.infra)

    def test_a_first_install_generates_one_that_meets_the_password_policy(self):
        (first, generated), (second, _again) = self.password(), self.password()
        self.assertTrue(generated)
        self.assertGenerated(first)
        self.assertGenerated(second)
        self.assertNotEqual(first, second)

    def test_every_generated_password_meets_the_policy(self):
        for _ in range(200):
            self.assertGenerated(horus_install.generated_admin_password())

    def test_the_shipped_password_and_an_empty_one_are_replaced(self):
        for line in (f"{KEY}=admin", f'{KEY}="admin"', f"{KEY}= admin ", f"{KEY}=", f"{KEY}=   "):
            with self.subTest(line):
                self.write_env(line + "\n")
                password, generated = self.password()
                self.assertTrue(generated)
                self.assertGenerated(password)

    def test_a_password_the_admin_set_is_kept(self):
        self.write_env(f"{KEY}={CHOSEN}\n")
        self.assertEqual(self.password(), (CHOSEN, False))

    def test_a_kept_password_is_written_back_exactly_as_it_was_quoted(self):
        for raw in ('"p#ss word"', "'pa$$word'"):
            with self.subTest(raw):
                self.write_env(f"{KEY}={raw}\n")
                self.assertEqual(self.password(), (raw, False))

    def test_replacing_the_shipped_password_is_said_on_screen(self):
        self.write_env(f"{KEY}=admin\n")
        self.password()
        self.assertIn("shipped admin password", self.out.getvalue())

    def test_the_password_is_never_logged(self):
        self.write_env(f"{KEY}=admin\n")
        password, _generated = self.password()
        self.assertNotIn(password, self.log_text())
        self.assertNotIn(password, self.out.getvalue())
        self.assertNotIn(password, self.events.getvalue())


class AgentPassword(InfraCase):
    key = horus_install.AGENT_PASSWORD_KEY

    def password(self) -> tuple[str, bool]:
        return horus_install.agent_password(self.log, self.infra)

    def test_a_first_install_generates_one_that_meets_the_password_policy(self):
        password, generated = self.password()
        self.assertTrue(generated)
        self.assertGenerated(password)

    def test_every_generated_password_meets_the_policy(self):
        for _ in range(200):
            self.assertGenerated(horus_install.generated_agent_password())

    def test_the_shipped_password_and_an_empty_one_are_replaced(self):
        for value in ("agent", "", "   "):
            with self.subTest(value=value):
                self.write_env(f"{self.key}={value}\n")
                password, generated = self.password()
                self.assertTrue(generated)
                self.assertGenerated(password)

    def test_a_password_the_admin_set_is_kept(self):
        self.write_env(f"{self.key}={CHOSEN}\n")
        self.assertEqual(self.password(), (CHOSEN, False))

    def test_agent_username_defaults_to_agent(self):
        self.assertEqual(horus_install.agent_username(self.infra), "agent")


class AnUpgradeRewritesOnlyTheShippedPassword(InfraCase):
    def upgrade(self) -> str:
        password, _generated = horus_install.admin_password(self.log, self.infra)
        horus_install.apply_env(self.log, self.infra, {KEY: password}, reset=False)
        return password

    def test_admin_is_replaced_in_place(self):
        self.write_env(f"SUPER_USER_USERNAME=admin\n{KEY}=admin\nJWT_ALGORITHM=HS256\n")
        password = self.upgrade()
        self.assertEqual(re.findall(rf"(?m)^{KEY}=.*$", self.env_text()), [f"{KEY}={password}"])
        self.assertNotIn(f"{KEY}=admin", self.env_text())

    def test_a_chosen_password_line_is_left_as_it_was(self):
        line = f'{KEY}="p#ss word"'
        self.write_env(f"SUPER_USER_USERNAME=admin\n{line}\n")
        self.upgrade()
        self.assertEqual(re.findall(rf"(?m)^{KEY}=.*$", self.env_text()), [line])
        self.assertEqual(self.env_value(KEY), "p#ss word")

    def test_reset_env_keeps_the_password_the_account_already_has(self):
        shutil.copy(INFRA / ".env.example", self.infra / ".env.example")
        self.write_env(f"{KEY}={CHOSEN}\n")
        password, _generated = horus_install.admin_password(self.log, self.infra)
        with mock.patch.object(horus_install.shutil, "which", return_value=None):
            horus_install.apply_env(self.log, self.infra, {KEY: password}, reset=True)
        self.assertEqual(self.env_value(KEY), CHOSEN)

    def test_the_profile_json_never_holds_it(self):
        password, _generated = horus_install.admin_password(self.log, self.infra)
        path = self.repo / "horus-profile.json"
        hardware.write_profile_json(path, dict(horus_install.SIMULATIONS["nvidia-8gb"]),
                                    "gpu-8g", {KEY: password}, ["test"])
        self.assertNotIn(password, path.read_text(encoding="utf-8"))


class TheAdminAccountCheck(InfraCase):
    def outcome(self, out: str, code: int = 0) -> tuple[str, list]:
        calls = []

        def run(cmd, _log, timeout=60, cwd=None, env=None, log_output=True, stdin_text=None):
            calls.append((cmd, log_output, stdin_text))
            return Result(code, out, "")

        with mock.patch.object(horus_install, "run", run):
            return horus_install.check_admin_account(self.log, self.infra), calls

    def test_it_runs_the_mas_command_with_stdin_closed_and_without_the_password(self):
        self.write_env(f"{KEY}={CHOSEN}\n")
        outcome, calls = self.outcome(MAS_OUTPUT + "admin-account: matches\n")
        self.assertEqual(outcome, "matches")
        self.assertEqual(calls, [(["docker", "compose", "exec", "-T", "mas", "python", "-m",
                                   "db.admin_account"], False, "")])
        self.assertNotIn(CHOSEN, self.log_text())

    def test_each_outcome_is_read_from_the_last_line(self):
        for word in ("created", "replaced", "matches", "differs", "shipped", "refused"):
            with self.subTest(word):
                self.assertEqual(self.outcome(MAS_OUTPUT + f"admin-account: {word}\n")[0], word)

    def test_no_outcome_line_is_an_unknown_outcome(self):
        self.assertEqual(self.outcome("No module named db.admin_account\n", code=1)[0], "")
        self.assertIn("Could not check the admin account", self.out.getvalue())

    def test_a_password_changed_in_horus_is_reported_with_the_fix(self):
        self.write_env("SUPER_USER_USERNAME=root\n")
        self.outcome("admin-account: differs\n")
        said = self.out.getvalue()
        self.assertIn("The password of root is not the SUPER_USER_PASSWORD", said)
        self.assertIn("--start", said)

    def test_a_refused_password_is_reported_with_the_fix(self):
        self.outcome("admin-account: refused\n")
        self.assertIn("MAS refused the SUPER_USER_PASSWORD", self.out.getvalue())


class TheAgentAccountCheck(InfraCase):
    def outcome(self, out: str, code: int = 0) -> tuple[str, list]:
        calls = []

        def run(cmd, _log, timeout=60, cwd=None, env=None, log_output=True, stdin_text=None):
            calls.append((cmd, log_output, stdin_text))
            return Result(code, out, "")

        with mock.patch.object(horus_install, "run", run):
            return horus_install.check_agent_account(self.log, self.infra), calls

    def test_it_runs_the_mas_agent_account_command(self):
        outcome, calls = self.outcome("agent-account: matches\n")
        self.assertEqual(outcome, "matches")
        self.assertEqual(calls, [(["docker", "compose", "exec", "-T", "mas", "python", "-m",
                                   "db.agent_account"], False, "")])
        self.assertNotIn("Could not check the agent account", self.out.getvalue())

    def test_a_missing_outcome_is_reported_as_unverified(self):
        self.outcome("No module named db.agent_account\n", code=1)
        self.assertIn("Could not check the agent account", self.out.getvalue())

    def test_a_refused_agent_password_is_reported_as_agent_password(self):
        self.outcome("agent-account: refused\n")
        self.assertIn("SUPER_AGENT_PASSWORD", self.out.getvalue())
        self.assertIn("'agent'", self.out.getvalue())
        self.assertNotIn("SUPER_USER_PASSWORD", self.out.getvalue())


class TheEndOfTheInstallShowsThePasswordOnce(InfraCase):
    def succeed(self, password: str | None, terminal: bool = True, outcome: str = "") -> str:
        self.write_env("SUPER_USER_USERNAME=root\n")
        with mock.patch.object(horus_install, "terminal_output", return_value=terminal), \
                mock.patch.object(horus_install, "offer_to_reclaim"):
            horus_install._success(self.log, self.infra, "gpu-8g", {"mode": "demo"},
                                   non_interactive=True, admin_password=password,
                                   admin_outcome=outcome)
        return self.out.getvalue()

    def test_an_account_on_another_password_is_not_pointed_at_the_env(self):
        out = self.succeed(None, outcome="differs")
        self.assertIn("not the one in .env; see the warning above", out)
        self.assertNotIn("the SUPER_USER_PASSWORD in", out)

    def test_a_generated_password_is_shown_with_the_login_name_and_where_it_is(self):
        out = self.succeed(CHOSEN)
        self.assertIn("Sign in as  root", out)
        self.assertIn(f"Password    {CHOSEN}", out)
        self.assertIn("Shown only this once", out)
        self.assertIn(str(self.infra / ".env"), out)

    def test_it_never_reaches_the_log_or_the_events(self):
        self.succeed(CHOSEN)
        self.assertNotIn(CHOSEN, self.log_text())
        self.assertNotIn(CHOSEN, self.events.getvalue())

    def test_output_that_is_not_a_terminal_only_says_where_it_is(self):
        out = self.succeed(CHOSEN, terminal=False)
        self.assertNotIn(CHOSEN, out)
        self.assertIn("generated, stored as SUPER_USER_PASSWORD in", out)

    def test_a_password_the_admin_set_is_never_shown(self):
        self.write_env(f"SUPER_USER_USERNAME=root\n{KEY}={CHOSEN}\n")
        out = self.succeed(None)
        self.assertNotIn(CHOSEN, out)
        self.assertIn("the SUPER_USER_PASSWORD in", out)


class InstallChecksTheAdminAccount(InfraCase):
    def install(self, outcome: str) -> mock.Mock:
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
            for name in ("apply_env", "pull_and_build", "wait_for_health", "_success"):
                order.attach_mock(patch(mock.patch.object(horus_install, name)), name)
            order.attach_mock(patch(mock.patch.object(horus_install, "check_admin_account",
                                                      return_value=outcome)),
                              "check_admin_account")
            order.attach_mock(patch(mock.patch.object(horus_install, "check_agent_account",
                                                      return_value="matches")),
                              "check_agent_account")
            code = horus_install._dispatch(self.log, args)
        self.assertEqual(code, EXIT_OK)
        return order

    def written(self, order: mock.Mock) -> str:
        return order.apply_env.call_args.args[2][KEY]

    def shown(self, order: mock.Mock) -> str | None:
        return order._success.call_args.kwargs["admin_password"]

    def test_a_new_install_shows_the_password_it_generated(self):
        order = self.install("created")
        self.assertGenerated(self.written(order))
        self.assertGenerated(order.apply_env.call_args.args[2][horus_install.AGENT_PASSWORD_KEY])
        self.assertEqual(self.shown(order), self.written(order))

    def test_an_upgrade_from_admin_shows_the_new_password(self):
        self.write_env(f"{KEY}=admin\n")
        order = self.install("matches")
        self.assertGenerated(self.written(order))
        self.assertEqual(self.shown(order), self.written(order))

    def test_an_upgrade_where_the_password_was_changed_keeps_it_and_shows_nothing(self):
        self.write_env(f"{KEY}={CHOSEN}\n")
        order = self.install("matches")
        self.assertEqual(self.written(order), CHOSEN)
        self.assertIsNone(self.shown(order))

    def test_a_generated_password_the_account_does_not_use_is_not_shown(self):
        self.write_env(f"{KEY}=admin\n")
        for outcome in ("differs", "shipped", "refused"):
            with self.subTest(outcome):
                order = self.install(outcome)
                self.assertIsNone(self.shown(order))
                self.assertEqual(order._success.call_args.kwargs["admin_outcome"], outcome)

    def test_the_account_is_checked_once_the_stack_is_healthy(self):
        names = [call[0] for call in self.install("matches").mock_calls if call[0]]
        self.assertEqual(names, ["apply_env", "pull_and_build", "wait_for_health",
                                 "check_admin_account", "check_agent_account", "_success"])


class TheTemplateShipsNoInitialPasswords(InfraCase):
    def test_the_env_example_leaves_it_empty(self):
        self.assertEqual(smoke.read_env(INFRA / ".env.example")[KEY], "")
        self.assertEqual(smoke.read_env(INFRA / ".env.example")[
            horus_install.AGENT_PASSWORD_KEY], "")

    def test_the_built_in_bootstrap_generates_it(self):
        shutil.copy(INFRA / ".env.example", self.infra / ".env.example")
        with mock.patch.object(horus_install.shutil, "which", return_value=None):
            horus_install._bootstrap_env(self.log, self.infra, reset=False)
        self.assertGenerated(self.env_value(KEY))
        self.assertGenerated(self.env_value(horus_install.AGENT_PASSWORD_KEY))

    @unittest.skipUnless(shutil.which("bash"), "needs bash to run init-env.sh")
    def test_init_env_generates_it(self):
        for name in (".env.example", "init-env.sh"):
            shutil.copy(INFRA / name, self.infra / name)
        result = subprocess.run([shutil.which("bash"), "init-env.sh", "--quiet"],
                                cwd=self.infra, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGenerated(self.env_value(KEY))
        self.assertGenerated(self.env_value(horus_install.AGENT_PASSWORD_KEY))
        self.assertEqual(len(re.findall(rf"(?m)^{KEY}=", self.env_text())), 1)
        self.assertNotIn(self.env_value(KEY), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
