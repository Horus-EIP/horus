from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packaging"))

import build_bundle  # noqa: E402
import horus_install  # noqa: E402
import images  # noqa: E402
import preflight  # noqa: E402
import profiles  # noqa: E402
from common import (  # noqa: E402
    EXIT_OK,
    EXIT_REGISTRY_LOGIN_FAILED,
    VERSION,
    InstallError,
    Log,
    Result,
    run,
)

SECRET = "ghp_not-a-real-token-0123456789"

IMAGE_VARIABLES = (images.REGISTRY_KEY, images.BUILD_FROM_SOURCE_KEY, images.TOKEN_KEY,
                   images.USERNAME_KEY)

def environment_without_image_variables():
    patcher = mock.patch.dict(os.environ)
    patcher.start()
    for key in IMAGE_VARIABLES:
        os.environ.pop(key, None)
    return patcher

class TempDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        patcher = environment_without_image_variables()
        self.addCleanup(patcher.stop)

    def log(self) -> Log:
        log = Log(self.tmp / "install-log.txt")
        self.addCleanup(log.close, 0)
        return log

    def log_text(self) -> str:
        return (self.tmp / "install-log.txt").read_text(encoding="utf-8")

class RegistryChoice(unittest.TestCase):
    def test_without_any_choice_it_is_ghcr_under_the_org(self):
        self.assertEqual(images.registry_to_use(None, {}, None), "ghcr.io/epitechpromo2027")
        self.assertEqual(images.DEFAULT_REGISTRY, "ghcr.io/epitechpromo2027")

    def test_the_flag_beats_the_variable_which_beats_the_previous_install(self):
        env = {images.REGISTRY_KEY: "env.example/team"}
        self.assertEqual(images.registry_to_use("flag.example/team", env, "old.example/x"),
                         "flag.example/team")
        self.assertEqual(images.registry_to_use(None, env, "old.example/x"), "env.example/team")
        self.assertEqual(images.registry_to_use("", {}, "old.example/x"), "old.example/x")

    def test_case_and_a_trailing_slash_are_normalised(self):
        self.assertEqual(images.registry_to_use("GHCR.io/EpitechPromo2027/", {}, None),
                         "ghcr.io/epitechpromo2027")

    def test_the_host_is_the_first_path_segment(self):
        self.assertEqual(images.registry_host("ghcr.io/acme/team"), "ghcr.io")
        self.assertEqual(images.registry_host("registry.example:5000"), "registry.example:5000")

class BuildFromSourceSwitch(unittest.TestCase):
    def test_the_flag_turns_it_on(self):
        self.assertTrue(images.build_from_source_requested(True, {}))

    def test_the_variable_turns_it_on(self):
        for value in ("1", "true", "YES", " on "):
            with self.subTest(value):
                self.assertTrue(images.build_from_source_requested(
                    False, {images.BUILD_FROM_SOURCE_KEY: value}))

    def test_it_is_off_by_default_and_for_other_values(self):
        self.assertFalse(images.build_from_source_requested(False, {}))
        for value in ("", "0", "false", "no"):
            with self.subTest(value):
                self.assertFalse(images.build_from_source_requested(
                    False, {images.BUILD_FROM_SOURCE_KEY: value}))

class ImageNames(unittest.TestCase):
    def test_each_app_service_has_a_repository_under_the_registry(self):
        expected = {
            "mas": "ghcr.io/acme/horus-mas:1.2.3-cpu",
            "agent": "ghcr.io/acme/horus-agent:1.2.3-cpu",
            "knowledge_store": "ghcr.io/acme/horus-knowledge-store:1.2.3-cpu",
            "web-client": "ghcr.io/acme/horus-web-client:1.2.3-cpu",
        }
        for service in images.APP_SERVICES:
            with self.subTest(service):
                self.assertEqual(images.image_name("ghcr.io/acme", service, "1.2.3", "cpu"),
                                 expected[service])

    def test_the_tag_is_split_off_even_behind_a_registry_port(self):
        self.assertEqual(images.split_tag("ghcr.io/acme/horus-mas:1.2.3-cpu"),
                         ("ghcr.io/acme/horus-mas", "1.2.3-cpu"))
        self.assertEqual(images.split_tag("registry:5000/team/horus-mas:1.2.3-gpu"),
                         ("registry:5000/team/horus-mas", "1.2.3-gpu"))
        self.assertEqual(images.split_tag("registry:5000/team/horus-mas"),
                         ("registry:5000/team/horus-mas", ""))
        self.assertEqual(images.split_tag("infra-mas"), ("infra-mas", ""))

    def test_the_tag_suffix_follows_the_profile(self):
        for name in profiles.PROFILE_ORDER:
            with self.subTest(name):
                expected = "cpu" if profiles.is_cpu_profile(name) else "gpu"
                self.assertEqual(profiles.image_flavor(name), expected)

    def test_the_installer_describes_the_four_images_it_pulls(self):
        text = horus_install.describe_images("ghcr.io/acme", "cpu-standard")
        self.assertIn(f"ghcr.io/acme/horus-{{mas,agent,knowledge-store,web-client}}:"
                      f"{VERSION}-cpu", text)
        self.assertIn("built from source", horus_install.describe_images(None, "gpu-8g"))

    def test_a_source_install_switch_deactivates_the_registry(self):
        self.assertIn(images.REGISTRY_KEY, profiles.MANAGED_KEYS)

class RegistryCredentials(TempDirCase):
    def default_file(self) -> Path:
        return self.tmp / images.TOKEN_FILE_NAME

    def read(self, token_file=None, username=None, environ=None):
        return images.read_credentials(token_file, username, environ or {},
                                       self.default_file())

    def test_no_token_anywhere_means_no_sign_in(self):
        self.assertIsNone(self.read())

    def test_the_default_file_holds_user_and_token(self):
        self.default_file().write_text(f"tester:{SECRET}\n", encoding="utf-8")
        found = self.read()
        self.assertEqual((found.username, found.token), ("tester", SECRET))
        self.assertEqual(found.source, images.TOKEN_FILE_NAME)

    def test_a_bare_token_takes_the_user_from_the_flag_or_the_variable(self):
        self.default_file().write_text(SECRET + "\n", encoding="utf-8")
        self.assertEqual(self.read(username="flag-user").username, "flag-user")
        self.assertEqual(self.read(environ={images.USERNAME_KEY: "env-user"}).username,
                         "env-user")

    def test_a_byte_order_mark_from_a_windows_editor_is_ignored(self):
        self.default_file().write_bytes(f"tester:{SECRET}\r\n".encode("utf-8-sig"))
        self.assertEqual(self.read().username, "tester")

    def test_the_variable_holds_the_token(self):
        found = self.read(environ={images.TOKEN_KEY: SECRET, images.USERNAME_KEY: "u"})
        self.assertEqual((found.username, found.token), ("u", SECRET))
        self.assertNotIn(SECRET, found.source)

    def test_an_explicit_file_beats_the_variable_which_beats_the_default_file(self):
        explicit = self.tmp / "given.txt"
        explicit.write_text("a:explicit-token", encoding="utf-8")
        self.default_file().write_text("c:default-token", encoding="utf-8")
        environ = {images.TOKEN_KEY: "env-token", images.USERNAME_KEY: "b"}
        self.assertEqual(self.read(str(explicit), environ=environ).token, "explicit-token")
        self.assertEqual(self.read(environ=environ).token, "env-token")
        self.assertEqual(self.read().token, "default-token")

    def test_a_missing_explicit_file_stops_with_its_own_exit_code(self):
        with self.assertRaises(InstallError) as caught:
            self.read(str(self.tmp / "nope.txt"))
        self.assertEqual(caught.exception.code, EXIT_REGISTRY_LOGIN_FAILED)

    def test_an_empty_file_stops(self):
        self.default_file().write_text("\n\n", encoding="utf-8")
        with self.assertRaises(InstallError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, EXIT_REGISTRY_LOGIN_FAILED)

    def test_a_token_without_a_user_name_stops_without_showing_the_token(self):
        self.default_file().write_text(SECRET, encoding="utf-8")
        with self.assertRaises(InstallError) as caught:
            self.read()
        error = caught.exception
        self.assertEqual(error.code, EXIT_REGISTRY_LOGIN_FAILED)
        self.assertIn("USERNAME:TOKEN", error.fix)
        for text in (error.headline, error.detail, error.fix):
            self.assertNotIn(SECRET, text)

class SignIn(TempDirCase):
    def sign_in(self, result: Result):
        calls = []

        def fake_run(cmd, log, **kwargs):
            calls.append((cmd, kwargs))
            return result

        credentials = images.Credentials("tester", SECRET, images.TOKEN_FILE_NAME)
        log = self.log()
        with mock.patch.object(images, "run", fake_run), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                images.sign_in(log, "ghcr.io/acme", credentials)
                raised = None
            except InstallError as exc:
                raised = exc
        return calls, raised

    def test_the_token_goes_to_docker_login_on_stdin_and_not_into_the_log(self):
        calls, raised = self.sign_in(Result(0, "Login Succeeded", ""))
        self.assertIsNone(raised)
        (cmd, kwargs), = calls
        self.assertEqual(cmd, ["docker", "login", "ghcr.io", "--username", "tester",
                               "--password-stdin"])
        self.assertEqual(kwargs["stdin_text"], SECRET)
        self.assertIs(kwargs["log_output"], False)
        self.assertNotIn(SECRET, " ".join(cmd))
        self.assertNotIn(SECRET, self.log_text())

    def test_a_refused_token_stops_with_its_own_code_and_hides_the_token(self):
        _calls, raised = self.sign_in(
            Result(1, "", f"Error response from daemon: denied for {SECRET}"))
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, EXIT_REGISTRY_LOGIN_FAILED)
        self.assertIn("denied", raised.detail)
        for text in (raised.headline, raised.detail, raised.fix):
            self.assertNotIn(SECRET, text)

    def test_run_hands_stdin_to_the_process_and_can_keep_it_out_of_the_log(self):
        log = self.log()
        result = run([sys.executable, "-c", "import sys; print(sys.stdin.read())"], log,
                     log_output=False, stdin_text=SECRET)
        log.close(0)
        self.assertEqual(result.out, SECRET)
        self.assertNotIn(SECRET, self.log_text())

class DispatchChoosesTheImageSource(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        (self.tmp / "src" / "infra").mkdir(parents=True)

    def dispatch(self, *extra: str):
        args = horus_install.build_parser().parse_args(
            ["--profile", "gpu-8g", "--non-interactive", "--skip-smoke", *extra])
        mocks = {}
        with contextlib.ExitStack() as stack:
            patch = stack.enter_context
            patch(mock.patch.object(horus_install, "find_repo", return_value=self.tmp))
            patch(mock.patch.object(horus_install, "banner"))
            for name in ("preflight", "sign_in_to_registry", "apply_env", "pull_and_build",
                         "wait_for_health", "_success"):
                mocks[name] = patch(mock.patch.object(horus_install, name))
            consent = patch(mock.patch.object(horus_install, "consent"))
            consent.choose.return_value = {"corpus_dir": "../../demo_assets"}
            hardware = patch(mock.patch.object(horus_install, "hardware"))
            hardware.probe.return_value = dict(horus_install.SIMULATIONS["nvidia-8gb"])
            patch(contextlib.redirect_stdout(io.StringIO()))
            code = horus_install._dispatch(self.log(), args)
        self.assertEqual(code, EXIT_OK)
        return mocks

    def written(self, mocks) -> dict[str, str]:
        return mocks["apply_env"].call_args.args[2]

    def test_a_default_install_pulls_signed_images_from_the_default_registry(self):
        mocks = self.dispatch()
        self.assertEqual(self.written(mocks)[images.REGISTRY_KEY], images.DEFAULT_REGISTRY)
        self.assertEqual(self.written(mocks)["HORUS_VERSION"], VERSION)
        self.assertIs(mocks["pull_and_build"].call_args.kwargs["from_source"], False)
        self.assertEqual(mocks["sign_in_to_registry"].call_args.args[2],
                         images.DEFAULT_REGISTRY)
        self.assertEqual(mocks["preflight"].run_install_checks.call_args.kwargs["image_registry"],
                         images.DEFAULT_REGISTRY)
        self.assertIs(mocks["_success"].call_args.kwargs["built_here"], False)

    def test_the_flag_builds_from_source_and_writes_no_registry(self):
        mocks = self.dispatch("--build-from-source")
        self.assertNotIn(images.REGISTRY_KEY, self.written(mocks))
        self.assertIs(mocks["pull_and_build"].call_args.kwargs["from_source"], True)
        mocks["sign_in_to_registry"].assert_not_called()
        self.assertIsNone(mocks["preflight"].run_install_checks.call_args.kwargs["image_registry"])
        self.assertIs(mocks["_success"].call_args.kwargs["built_here"], True)

    def test_the_variable_builds_from_source_too(self):
        os.environ[images.BUILD_FROM_SOURCE_KEY] = "1"
        mocks = self.dispatch()
        self.assertNotIn(images.REGISTRY_KEY, self.written(mocks))
        self.assertIs(mocks["pull_and_build"].call_args.kwargs["from_source"], True)

    def test_a_reinstall_keeps_the_registry_the_last_install_used(self):
        (self.tmp / "src" / "infra" / ".env").write_text(
            "HORUS_REGISTRY=registry.example.com/team\n", encoding="utf-8")
        self.assertEqual(self.written(self.dispatch())[images.REGISTRY_KEY],
                         "registry.example.com/team")

    def test_the_registry_flag_wins_over_the_last_install(self):
        (self.tmp / "src" / "infra" / ".env").write_text(
            "HORUS_REGISTRY=registry.example.com/team\n", encoding="utf-8")
        mocks = self.dispatch("--registry", "other.example.com/x")
        self.assertEqual(self.written(mocks)[images.REGISTRY_KEY], "other.example.com/x")

class SignInToRegistry(TempDirCase):
    def call(self, *argv: str, token_file_text: str | None = None):
        default_file = self.tmp / images.TOKEN_FILE_NAME
        if token_file_text is not None:
            default_file.write_text(token_file_text, encoding="utf-8")
        args = horus_install.build_parser().parse_args(list(argv))
        with mock.patch.object(horus_install, "BUNDLE_DIR", self.tmp), \
                mock.patch.object(images, "sign_in") as sign_in:
            horus_install.sign_in_to_registry(self.log(), args, "ghcr.io/acme")
        return sign_in

    def test_without_a_token_docker_is_not_asked_to_sign_in(self):
        self.call().assert_not_called()

    def test_the_token_file_next_to_start_here_is_used(self):
        sign_in = self.call(token_file_text=f"tester:{SECRET}")
        credentials = sign_in.call_args.args[2]
        self.assertEqual((credentials.username, credentials.token), ("tester", SECRET))
        self.assertNotIn(SECRET, self.log_text())

    def test_the_flags_name_the_file_and_the_user(self):
        given = self.tmp / "token.txt"
        given.write_text(SECRET, encoding="utf-8")
        sign_in = self.call("--registry-token-file", str(given), "--registry-user", "me")
        self.assertEqual(sign_in.call_args.args[2].username, "me")

class EmulatedImagesWarning(TempDirCase):
    def warnings(self, simulation: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            horus_install.warn_if_images_are_emulated(
                self.log(), horus_install.SIMULATIONS[simulation])
        return out.getvalue()

    def test_an_arm_machine_is_told_how_to_build_for_its_processor(self):
        text = self.warnings("macos-arm")
        self.assertIn("linux/amd64", text)
        self.assertIn("--build-from-source", text)

    def test_an_x86_machine_is_not_warned(self):
        self.assertEqual(self.warnings("nvidia-8gb"), "")

class SwitchingImageSourceRewritesTheEnv(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ.pop(horus_install.PROJECT_NAME_KEY, None)
        self.infra = self.tmp / "src" / "infra"
        self.infra.mkdir(parents=True)
        (self.infra / ".env").write_text("HORUS_REGISTRY=ghcr.io/acme\n", encoding="utf-8")

    def apply(self, updates: dict[str, str]) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            horus_install.apply_env(self.log(), self.infra, updates, reset=False)

    def test_a_source_install_deactivates_the_registry_so_start_never_pulls(self):
        self.assertTrue(horus_install.installed_from_registry(self.infra))
        self.apply({"COMPOSE_FILE": "docker-compose.yml"})
        self.assertFalse(horus_install.installed_from_registry(self.infra))
        self.assertEqual(horus_install.start_command(self.infra), ["up", "-d"])

    def test_going_back_to_prebuilt_images_reactivates_it(self):
        self.apply({"COMPOSE_FILE": "docker-compose.yml"})
        self.apply({images.REGISTRY_KEY: "ghcr.io/acme"})
        self.assertTrue(horus_install.installed_from_registry(self.infra))
        self.assertEqual(horus_install.start_command(self.infra), ["up", "-d", "--no-build"])

class PreflightNetworkHosts(unittest.TestCase):
    def test_building_from_source_needs_the_package_indexes(self):
        hosts = dict(preflight.network_hosts(None))
        for label in ("PyPI (Python deps)", "npm (web client deps)",
                      "Debian apt (image packages)"):
            self.assertIn(label, hosts)

    def test_prebuilt_images_need_their_registry_instead_of_the_package_indexes(self):
        hosts = dict(preflight.network_hosts("ghcr.io/acme"))
        self.assertEqual(hosts["Horus images"], "https://ghcr.io/v2/")
        self.assertIn("Docker registry", hosts)
        self.assertIn("Hugging Face (model weights)", hosts)
        for label in ("PyPI (Python deps)", "npm (web client deps)",
                      "Debian apt (image packages)"):
            self.assertNotIn(label, hosts)

    def test_ghcr_also_needs_the_host_that_serves_its_layers(self):
        hosts = dict(preflight.network_hosts("ghcr.io/acme"))
        self.assertEqual(hosts["Horus image layers"],
                         "https://pkg-containers.githubusercontent.com/")

    def test_another_registry_is_checked_on_its_own_host_only(self):
        hosts = dict(preflight.network_hosts("registry.example.com/team"))
        self.assertEqual(hosts["Horus images"], "https://registry.example.com/v2/")
        self.assertNotIn("Horus image layers", hosts)

    def test_the_install_checks_reach_the_hosts_of_the_chosen_image_source(self):
        with contextlib.ExitStack() as stack:
            for name in ("check_disk", "check_ports"):
                stack.enter_context(mock.patch.object(preflight, name))
            network = stack.enter_context(mock.patch.object(preflight, "check_network"))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            with tempfile.TemporaryDirectory() as name:
                log = Log(Path(name) / "log.txt")
                preflight.run_install_checks(log, Path(name), image_registry="ghcr.io/acme")
                log.close(0)
        self.assertEqual(network.call_args.args[1], preflight.network_hosts("ghcr.io/acme"))

    def test_the_engine_checks_contact_no_registry(self):
        with contextlib.ExitStack() as stack:
            for name in ("check_python", "check_docker", "check_compose"):
                stack.enter_context(mock.patch.object(preflight, name))
            network = stack.enter_context(mock.patch.object(preflight, "check_network"))
            disk = stack.enter_context(mock.patch.object(preflight, "check_disk"))
            with tempfile.TemporaryDirectory() as name:
                log = Log(Path(name) / "log.txt")
                preflight.run_engine_checks(log)
                log.close(0)
        network.assert_not_called()
        disk.assert_not_called()

class Parser(unittest.TestCase):
    def parse(self, argv):
        return horus_install.build_parser().parse_args(argv)

    def test_the_image_flags_default_off(self):
        args = self.parse([])
        self.assertFalse(args.build_from_source)
        self.assertIsNone(args.registry)
        self.assertIsNone(args.registry_user)
        self.assertIsNone(args.registry_token_file)

    def test_the_image_flags_are_accepted(self):
        args = self.parse(["--build-from-source", "--registry", "r.example/x",
                           "--registry-user", "u", "--registry-token-file", "t.txt"])
        self.assertTrue(args.build_from_source)
        self.assertEqual((args.registry, args.registry_user, args.registry_token_file),
                         ("r.example/x", "u", "t.txt"))

    def test_there_is_no_flag_that_takes_the_token_itself(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.parse(["--registry-token", SECRET])

class DryRunShowsTheImages(TempDirCase):
    def dry_run(self, *extra: str) -> str:
        (self.tmp / "src" / "infra").mkdir(parents=True, exist_ok=True)
        args = horus_install.build_parser().parse_args(
            ["--dry-run", "--simulate", "nvidia-8gb", *extra])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = horus_install.do_dry_run(self.log(), args, self.tmp)
        self.assertEqual(code, EXIT_OK)
        return out.getvalue()

    def test_the_prebuilt_images_and_their_registry_are_shown(self):
        text = self.dry_run()
        self.assertIn(f"{images.DEFAULT_REGISTRY}/horus-{{mas,agent,knowledge-store,"
                      f"web-client}}:{VERSION}-gpu", text)
        self.assertIn(f"{images.REGISTRY_KEY}={images.DEFAULT_REGISTRY}", text)

    def test_building_from_source_is_shown_and_writes_no_registry(self):
        text = self.dry_run("--build-from-source")
        self.assertIn("built from source", text)
        self.assertNotIn(f"{images.REGISTRY_KEY}=", text)

    def test_an_arm_machine_is_told_the_images_are_emulated(self):
        (self.tmp / "src" / "infra").mkdir(parents=True, exist_ok=True)
        args = horus_install.build_parser().parse_args(
            ["--dry-run", "--simulate", "macos-arm", "--profile", "gpu-8g"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            horus_install.do_dry_run(self.log(), args, self.tmp)
        self.assertIn("Docker emulates them", out.getvalue())
        self.assertNotIn("Docker emulates them", self.dry_run())

class TokenStaysOutOfTheBundle(unittest.TestCase):
    def test_a_token_file_is_never_archived(self):
        for name in (images.TOKEN_FILE_NAME, f"installer/{images.TOKEN_FILE_NAME}",
                     f"src/infra/{images.TOKEN_FILE_NAME}"):
            with self.subTest(name):
                self.assertTrue(build_bundle.pruned(Path(name)))

if __name__ == "__main__":
    unittest.main()
