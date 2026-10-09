from __future__ import annotations

import contextlib
import inspect
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware  # noqa: E402
import horus_install  # noqa: E402
import profiles  # noqa: E402
import smoke  # noqa: E402
import unsupported  # noqa: E402
from common import (  # noqa: E402
    EVENT_PREFIX,
    EXIT_ENV_WRITE_FAILED,
    EXIT_OK,
    EXIT_PROFILE_UNKNOWN,
    EXIT_SMOKE_FAILED,
    Events,
    InstallError,
    Log,
)

GIB = 1024 ** 3
LINUX = {"os": {"platform": "linux"}}
WINDOWS = {"os": {"platform": "win32"}}
CPU_FILES = "docker-compose.yml:docker-compose.cpu.yml"
MOCK_FILES = "docker-compose.yml:docker-compose.cpu.yml:docker-compose.mock.yml"
LEAN_MOCK_FILES = f"{MOCK_FILES}:docker-compose.monitoring-off.yml"
MONITORING = list(profiles.MONITORING_SERVICES)
EXPECT_MOCK = [*horus_install.CORE_SERVICES, profiles.MOCK_MODEL_SERVER]


def small_machine() -> dict:
    return {
        "os": {"system": "Linux", "machine": "x86_64", "platform": "linux"},
        "cpu": {"physical_cores": 4, "avx2": True},
        "memory": {"total_bytes": int(7.6 * GIB)},
        "docker": {"mem_total_bytes": int(7.6 * GIB)},
        "gpu": {"vendor": "none", "name": None, "vram_bytes": None},
        "docker_gpu_test": {"usable": None, "skipped_reason": "no GPU"},
        "cuda_usable_in_docker": False,
    }


def big_machine() -> dict:
    probe = small_machine()
    probe["memory"]["total_bytes"] = probe["docker"]["mem_total_bytes"] = 32 * GIB
    return probe


class MockProfile(unittest.TestCase):
    def test_it_is_a_profile_the_hardware_order_never_picks(self):
        self.assertIn(profiles.MOCK_PROFILE, profiles.PROFILES)
        self.assertNotIn(profiles.MOCK_PROFILE, profiles.PROFILE_ORDER)
        self.assertTrue(profiles.is_mock_profile("mock"))
        self.assertFalse(profiles.is_cpu_profile("mock"))

    def test_it_runs_the_cpu_images_under_the_mock_overlay(self):
        self.assertEqual(profiles.env_for("mock", LINUX)["COMPOSE_FILE"], LEAN_MOCK_FILES)
        self.assertEqual(profiles.env_for("mock", WINDOWS)["COMPOSE_FILE"],
                         LEAN_MOCK_FILES.replace(":", ";"))
        self.assertEqual(profiles.image_flavor("mock"), "cpu")
        self.assertEqual(profiles.model_server("mock"), profiles.MOCK_MODEL_SERVER)

    def test_every_setting_says_why(self):
        for key, setting in profiles.settings_for("mock").items():
            with self.subTest(key):
                self.assertIn(setting.provenance, (profiles.MEASURED, profiles.DERIVED))
                self.assertGreater(len(setting.why), 20)
        self.assertEqual(profiles.env_for("mock")["HORUS_AI_MODE"], "mock")
        self.assertIn("llm-mock", profiles.provenance_for("mock")["COMPOSE_FILE"]["why"])
        for key in ("LLM_VLLM_URL", "LLM_VLLM_MODEL"):
            with self.subTest(key):
                self.assertRegex(profiles.settings_for("mock")[key].why,
                                 "overlay|docker-compose.mock.yml")

    def test_the_description_says_the_answers_are_simulated(self):
        text = profiles.describe("mock")
        self.assertIn("Model server:   llm-mock (simulated answers, no language model)", text)
        self.assertIn("simulated", " ".join(text.split()))
        self.assertIn(profiles.MOCK_DOC, " ".join(text.split()))

    def test_a_real_profile_unsets_the_mode_it_does_not_write(self):
        self.assertIn("HORUS_AI_MODE", profiles.MANAGED_KEYS)
        for name in profiles.PROFILE_ORDER:
            with self.subTest(name):
                self.assertNotIn("HORUS_AI_MODE", profiles.env_for(name))

    def test_the_mock_model_server_is_named_from_the_compose_file(self):
        self.assertEqual(profiles.model_server_for_compose_file(MOCK_FILES), "llm-mock")
        self.assertEqual(profiles.model_server_for_compose_file(MOCK_FILES.replace(":", ";")), "llm-mock")
        self.assertEqual(profiles.model_server_for_compose_file(CPU_FILES), "llm")

    def test_the_overlay_goes_right_after_the_cpu_overlay(self):
        cases = {
            ("docker-compose.yml", ":"): MOCK_FILES,
            (CPU_FILES, ":"): MOCK_FILES,
            (MOCK_FILES, ":"): MOCK_FILES,
            (CPU_FILES.replace(":", ";"), ";"): MOCK_FILES.replace(":", ";"),
            (f"{CPU_FILES}:extra.yml", ":"): f"{MOCK_FILES}:extra.yml",
            ("", ":"): MOCK_FILES,
        }
        for (current, sep), expected in cases.items():
            with self.subTest(current):
                self.assertEqual(profiles.with_mock_overlay(current, sep), expected)
        self.assertEqual(profiles.without_mock_overlay(f"{MOCK_FILES}:extra.yml", ":"),
                         f"{CPU_FILES}:extra.yml")
        self.assertEqual(profiles.without_mock_overlay(profiles.MOCK_OVERLAY, ":"), "docker-compose.yml")

    def test_no_model_is_planned_or_checked(self):
        log = mock.MagicMock()
        self.assertIsNone(horus_install.plan_model(log, Path("."), "mock", None))


class Offer(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.record = self.tmp / "horus-profile.json"
        self.events = io.StringIO()
        self.out = io.StringIO()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(horus_install, "PROFILE_JSON", self.record))
        stack.enter_context(mock.patch.object(hardware, "probe", side_effect=lambda *a, **k: small_machine()))
        stack.enter_context(contextlib.redirect_stdout(self.out))
        self.log = Log(self.tmp / "log.txt", events=Events(True, self.events))
        self.addCleanup(self.log.close, 0)

    def args(self, *argv: str):
        return horus_install.build_parser().parse_args(list(argv))

    def decide(self, *argv: str, answer: str | None = None, terminal: bool = True):
        with mock.patch.object(horus_install, "interactive_terminal", return_value=terminal), \
                mock.patch("builtins.input", return_value=answer) as asked:
            try:
                return horus_install.decide_profile(self.log, self.args(*argv), None), asked
            except InstallError as refused:
                return refused, asked

    def test_below_the_floor_the_reasons_offer_mock_mode_and_say_it_is_simulated(self):
        name, reasons = profiles.select_profile(small_machine())
        self.assertEqual(name, profiles.NOT_SUPPORTED)
        self.assertEqual(reasons[-1], profiles.MOCK_OFFER)
        self.assertIn("simulated", reasons[-1])
        self.assertIn("--profile mock", reasons[-1])

    def test_the_refusal_lists_mock_mode_before_trying_anyway(self):
        alternatives = unsupported.refusal(small_machine()).record()["alternatives"]
        self.assertIn("--profile mock", alternatives[-2])
        self.assertIn("--profile cpu-lean", alternatives[-1])

    def test_an_interactive_yes_installs_mock_mode(self):
        (probe, name, reasons), asked = self.decide(answer="y")
        self.assertEqual(name, profiles.MOCK_PROFILE)
        asked.assert_called_once()
        self.assertIn("simulated", asked.call_args[0][0])
        self.assertEqual(json.loads(self.record.read_text(encoding="utf-8"))["profile"]["name"], "mock")
        self.assertIn("MOCK AI MODE", self.out.getvalue())

    def test_an_interactive_no_still_stops_the_install(self):
        refused, asked = self.decide(answer="")
        self.assertIsInstance(refused, unsupported.NotSupported)
        asked.assert_called_once()

    def test_a_run_nobody_can_answer_stops_without_asking(self):
        for argv, terminal in ((("--non-interactive",), True), ((), False)):
            with self.subTest(argv=argv, terminal=terminal):
                refused, asked = self.decide(*argv, answer="y", terminal=terminal)
                self.assertIsInstance(refused, unsupported.NotSupported)
                asked.assert_not_called()

    def test_profile_mock_installs_it_without_asking(self):
        (probe, name, reasons), asked = self.decide("--profile", "mock", answer="n")
        self.assertEqual(name, profiles.MOCK_PROFILE)
        asked.assert_not_called()

    def test_the_images_named_include_llm_mock(self):
        self.assertIn("llm-mock", horus_install.describe_images("ghcr.io/acme", "mock"))
        self.assertNotIn("llm-mock", horus_install.describe_images("ghcr.io/acme", "cpu-standard"))


class InstalledStack(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.infra = self.repo / "src" / "infra"
        self.infra.mkdir(parents=True)
        self.record = self.tmp / "horus-profile.json"
        self.record.write_text('{"profile": {"name": "cpu-standard"}}', encoding="utf-8")
        self.events = io.StringIO()
        self.out = io.StringIO()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(horus_install, "PROFILE_JSON", self.record))
        stack.enter_context(mock.patch.object(horus_install, "_require_docker"))
        stack.enter_context(contextlib.redirect_stdout(self.out))
        self.stopped: list[tuple[list[str], str]] = []
        stack.enter_context(mock.patch.object(
            horus_install, "stop_services",
            side_effect=lambda log, infra, names: self.stopped.append((names, self.compose_file()))))
        self.log = Log(self.tmp / "log.txt", events=Events(True, self.events))
        self.addCleanup(self.log.close, 0)

    def write(self, body: str) -> None:
        (self.infra / ".env").write_text(body, encoding="utf-8")

    def env(self) -> str:
        return (self.infra / ".env").read_text(encoding="utf-8")

    def compose_file(self) -> str:
        return horus_install.env_line_value(self.infra, "COMPOSE_FILE") or ""

    def emitted(self) -> list[dict]:
        return [json.loads(line[len(EVENT_PREFIX):]) for line in self.events.getvalue().splitlines()
                if line.startswith(EVENT_PREFIX)]

    def ai(self, *argv: str) -> int:
        args = horus_install.build_parser().parse_args(["--ai", *argv])
        return horus_install.do_ai(self.log, args, self.repo)


class AiStatus(InstalledStack):
    def test_status_reads_the_mode_from_the_compose_file(self):
        self.write(f"COMPOSE_FILE={MOCK_FILES}\nHORUS_AI_MODE=mock\n")
        self.assertEqual(self.ai("status"), EXIT_OK)
        self.assertIn("AI: Mock", self.out.getvalue())
        self.assertIn("simulated", self.out.getvalue())
        self.assertEqual([e for e in self.emitted() if e["event"] == "ai"][-1]["mode"], "mock")
        self.write(f"COMPOSE_FILE={CPU_FILES}\n")
        self.ai("status")
        self.assertIn("AI: Local", self.out.getvalue())
        self.assertEqual([e for e in self.emitted() if e["event"] == "ai"][-1]["server"], "llm")

    def test_status_warns_when_the_env_and_the_compose_file_disagree(self):
        self.write(f"COMPOSE_FILE={CPU_FILES}\nHORUS_AI_MODE=mock\n")
        with mock.patch.dict("os.environ", {"COMPOSE_FILE": "docker-compose.yml"}):
            self.ai("status")
        text = " ".join(self.out.getvalue().split())
        self.assertIn("HORUS_AI_MODE=mock, but COMPOSE_FILE does not load docker-compose.mock.yml", text)
        self.assertIn("COMPOSE_FILE is set in this shell", text)

    def test_the_parser_knows_the_three_words_only(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            horus_install.build_parser().parse_args(["--ai", "cloud"])
        self.assertEqual(caught.exception.code, 2)

    def test_the_services_waited_for_follow_the_mode(self):
        self.write(f"COMPOSE_FILE={MOCK_FILES}\n")
        self.assertEqual(horus_install.expected_services(self.infra), EXPECT_MOCK)
        self.assertEqual(smoke.model_server_of(self.infra), profiles.MOCK_MODEL_SERVER)
        self.assertIn(profiles.MOCK_MODEL_SERVER, smoke.MODEL_SERVER_HINTS)
        with mock.patch.object(horus_install.model_manager, "plan_from_env") as plan:
            horus_install.ensure_installed_model(self.log, self.infra)
        plan.assert_not_called()

    def test_the_mode_is_written_once_and_the_rest_is_kept(self):
        self.write(f"A=1\nCOMPOSE_FILE=docker-compose.yml\n# note\nCOMPOSE_FILE={CPU_FILES}\n"
                   f"{horus_install.UNSET_MARKER}HORUS_AI_MODE=mock\nB=2\n")
        horus_install.write_ai_mode(self.infra, MOCK_FILES, "mock")
        self.assertEqual(self.env(), f"A=1\nCOMPOSE_FILE={MOCK_FILES}\n# note\nB=2\nHORUS_AI_MODE=mock\n")


class SwitchToMock(InstalledStack):
    ORIGINAL = f"COMPOSE_FILE={CPU_FILES}\nLLM_VLLM_URL=http://llm:8080/v1\n"

    def test_a_switch_stops_llm_under_the_old_files_then_starts_and_checks_mock_mode(self):
        self.write(self.ORIGINAL)
        with mock.patch.object(horus_install, "start_and_check", return_value=EXPECT_MOCK) as start:
            self.assertEqual(self.ai("mock"), EXIT_OK)
        self.assertEqual(self.stopped, [(["llm", "llm-model", *MONITORING], CPU_FILES)])
        self.assertEqual(self.compose_file(), LEAN_MOCK_FILES)
        self.assertEqual(horus_install.env_line_value(self.infra, "HORUS_AI_MODE"), "mock")
        self.assertIn("LLM_VLLM_URL=http://llm:8080/v1", self.env())
        self.assertTrue(list(self.infra.glob(".env.bak.*")))
        self.assertTrue(start.call_args.kwargs["require_answer_quality"])
        self.assertFalse(start.call_args.args[4])
        kinds = [event["event"] for event in self.emitted()]
        self.assertIn("ai", kinds)
        self.assertIn("ready", kinds)

    def test_a_gpu_install_gets_the_cpu_overlay_too_and_rebuilds_from_source(self):
        self.write("COMPOSE_FILE=docker-compose.yml\n")
        with mock.patch.object(horus_install, "start_and_check", return_value=EXPECT_MOCK) as start:
            self.ai("mock")
        self.assertEqual(self.stopped, [(["vllm", *MONITORING], "docker-compose.yml")])
        self.assertEqual(self.compose_file(),
                         LEAN_MOCK_FILES.replace(":", profiles.compose_file_separator(None)))
        self.assertTrue(start.call_args.args[4])

    def test_a_failed_check_rolls_back_to_the_previous_mode(self):
        self.write(self.ORIGINAL)
        failure = InstallError(EXIT_SMOKE_FAILED, "The smoke test did not pass.", "d", "f")
        with mock.patch.object(horus_install, "start_and_check", side_effect=failure), \
                mock.patch.object(horus_install, "up_waiting_out_a_dependency_abort",
                                  return_value=(["up", "-d"], 0)) as up, \
                mock.patch.object(horus_install, "wait_for_health") as health, \
                self.assertRaises(InstallError) as caught:
            self.ai("mock")
        self.assertEqual(caught.exception.code, EXIT_SMOKE_FAILED)
        self.assertIn("rolled back", caught.exception.headline)
        self.assertEqual(self.env(), self.ORIGINAL)
        self.assertEqual(self.stopped[-1], (["llm-mock"], LEAN_MOCK_FILES))
        up.assert_called_once()
        self.assertIn("llm", health.call_args[0][2])

    def test_an_interrupted_switch_puts_the_previous_env_back_without_restarting(self):
        self.write(self.ORIGINAL)
        with mock.patch.object(horus_install, "start_and_check", side_effect=KeyboardInterrupt), \
                mock.patch.object(horus_install, "up_waiting_out_a_dependency_abort") as up, \
                self.assertRaises(KeyboardInterrupt):
            self.ai("mock")
        self.assertEqual(self.env(), self.ORIGINAL)
        self.assertEqual(self.stopped[-1], (["llm-mock"], LEAN_MOCK_FILES))
        up.assert_not_called()
        self.assertIn("Start Horus again with --start", self.out.getvalue())

    def test_a_failure_writing_env_is_rolled_back_too(self):
        self.write(self.ORIGINAL)
        with mock.patch.object(horus_install, "write_ai_mode", side_effect=PermissionError("locked")), \
                mock.patch.object(horus_install, "up_waiting_out_a_dependency_abort",
                                  return_value=(["up", "-d"], 0)) as up, \
                mock.patch.object(horus_install, "wait_for_health"), \
                self.assertRaises(InstallError) as caught:
            self.ai("mock")
        self.assertEqual(caught.exception.code, EXIT_ENV_WRITE_FAILED)
        self.assertIn("rolled back", caught.exception.headline)
        self.assertEqual(self.env(), self.ORIGINAL)
        up.assert_called_once()

    def test_a_rollback_rebuilds_what_the_failed_switch_rebuilt(self):
        self.write("COMPOSE_FILE=docker-compose.yml\n")
        failure = InstallError(EXIT_SMOKE_FAILED, "The smoke test did not pass.")
        with mock.patch.object(horus_install, "start_and_check", side_effect=failure), \
                mock.patch.object(horus_install, "up_waiting_out_a_dependency_abort",
                                  return_value=(["up", "-d"], 0)) as up, \
                mock.patch.object(horus_install, "wait_for_health"), \
                self.assertRaises(InstallError):
            self.ai("mock")
        self.assertIn("--build", up.call_args[0][2])
        self.assertEqual(self.env(), "COMPOSE_FILE=docker-compose.yml\n")

    def test_nothing_changes_when_the_mode_is_already_on(self):
        self.write(f"COMPOSE_FILE={LEAN_MOCK_FILES}\n")
        with mock.patch.object(horus_install, "start_and_check") as start:
            self.assertEqual(self.ai("mock"), EXIT_OK)
        start.assert_not_called()
        self.assertEqual(self.stopped, [])
        self.assertIn("already mock", self.out.getvalue())


class FakePlan:
    def env(self, repo: Path) -> dict[str, str]:
        return {"HORUS_MODELS_DIR": "../../models", "LLM_GGUF_FILE": "model.gguf",
                "LLM_GGUF_URL": "https://example.invalid/model.gguf", "LLM_GGUF_SHA256": "0" * 64,
                "LLM_GGUF_SIZE": "1"}


class SwitchToLocal(InstalledStack):
    MOCK_ENV = (f"COMPOSE_FILE={MOCK_FILES}\nHORUS_AI_MODE=mock\nLLM_VLLM_URL=http://llm:8080/v1\n"
                "HORUS_REGISTRY=ghcr.io/acme\nREDIS_PASSWORD=keep\n")

    def switch(self, start=None):
        self.write(self.MOCK_ENV)
        with mock.patch.object(horus_install.hardware, "probe", side_effect=lambda *a, **k: big_machine()), \
                mock.patch.object(horus_install.preflight, "run_install_checks") as checks, \
                mock.patch.object(horus_install, "plan_model", return_value=FakePlan()), \
                mock.patch.object(horus_install, "download_model") as download, \
                mock.patch.object(horus_install, "start_and_check",
                                  side_effect=start, return_value=[*horus_install.CORE_SERVICES, "llm"]), \
                mock.patch.object(horus_install, "up_waiting_out_a_dependency_abort",
                                  return_value=(["up", "-d"], 0)), \
                mock.patch.object(horus_install, "wait_for_health"):
            code = self.ai("local")
        return code, checks, download

    def test_local_checks_the_machine_downloads_the_model_and_writes_its_profile(self):
        code, checks, download = self.switch()
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(checks.call_args.kwargs["cpu_profile"], True)
        self.assertEqual(checks.call_args.kwargs["image_registry"], "ghcr.io/acme")
        download.assert_called_once()
        self.assertEqual(self.stopped[0], (["llm-mock"], MOCK_FILES))
        self.assertEqual(self.compose_file(), profiles.env_for("cpu-standard", big_machine())["COMPOSE_FILE"])
        self.assertIsNone(horus_install.env_line_value(self.infra, "HORUS_AI_MODE"))
        self.assertIn(f"{horus_install.UNSET_MARKER}HORUS_AI_MODE=mock", self.env())
        self.assertEqual(horus_install.env_line_value(self.infra, "LLM_GGUF_FILE"), "model.gguf")
        self.assertEqual(horus_install.env_line_value(self.infra, "HORUS_REGISTRY"), "ghcr.io/acme")
        self.assertEqual(horus_install.env_line_value(self.infra, "REDIS_PASSWORD"), "keep")
        record = json.loads(self.record.read_text(encoding="utf-8"))
        self.assertEqual(record["profile"]["name"], "cpu-standard")

    def test_a_failed_check_brings_mock_mode_back(self):
        failure = InstallError(EXIT_SMOKE_FAILED, "The smoke test did not pass.")
        with self.assertRaises(InstallError) as caught:
            self.switch(start=failure)
        self.assertIn("Mock AI mode is back", caught.exception.headline)
        self.assertEqual(self.env(), self.MOCK_ENV)
        self.assertEqual(json.loads(self.record.read_text(encoding="utf-8")),
                         {"profile": {"name": "cpu-standard"}})
        self.assertEqual(self.stopped[-1][0], ["llm", "llm-model"])

    def test_a_failure_writing_the_profile_settings_brings_mock_mode_back(self):
        failure = InstallError(EXIT_ENV_WRITE_FAILED, "Could not write src/infra/.env.")
        with mock.patch.object(horus_install, "apply_env", side_effect=failure), \
                self.assertRaises(InstallError) as caught:
            self.switch()
        self.assertEqual(caught.exception.code, EXIT_ENV_WRITE_FAILED)
        self.assertIn("Mock AI mode is back", caught.exception.headline)
        self.assertEqual(self.env(), self.MOCK_ENV)
        self.assertEqual(self.stopped[0], (["llm-mock"], MOCK_FILES))

    def test_an_interrupted_switch_to_local_restores_the_profile_record(self):
        with self.assertRaises(KeyboardInterrupt):
            self.switch(start=KeyboardInterrupt)
        self.assertEqual(self.env(), self.MOCK_ENV)
        self.assertEqual(json.loads(self.record.read_text(encoding="utf-8")),
                         {"profile": {"name": "cpu-standard"}})

    def test_local_refuses_the_mock_profile_and_a_machine_too_small(self):
        self.write(self.MOCK_ENV)
        args = horus_install.build_parser().parse_args(["--ai", "local", "--profile", "mock"])
        with self.assertRaises(InstallError) as caught:
            horus_install.do_ai(self.log, args, self.repo)
        self.assertEqual(caught.exception.code, EXIT_PROFILE_UNKNOWN)
        with mock.patch.object(horus_install.hardware, "probe", side_effect=lambda *a, **k: small_machine()), \
                self.assertRaises(unsupported.NotSupported):
            self.ai("local")
        self.assertEqual(self.env(), self.MOCK_ENV)
        self.assertEqual(json.loads(self.record.read_text(encoding="utf-8")),
                         {"profile": {"name": "cpu-standard"}})


class MonitoringSetting(unittest.TestCase):
    def test_unset_means_off_in_mock_mode_and_on_in_local_mode(self):
        self.assertFalse(profiles.monitoring_wanted(None, mock=True))
        self.assertTrue(profiles.monitoring_wanted(None, mock=False))
        self.assertTrue(profiles.monitoring_wanted("", mock=False))

    def test_an_explicit_value_wins_in_both_modes(self):
        for value in ("on", "ON", " 1 ", "true", "yes"):
            for mock_mode in (True, False):
                with self.subTest(value=value, mock=mock_mode):
                    self.assertTrue(profiles.monitoring_wanted(value, mock_mode))
        for value in ("off", "Off", "0", "false", "no"):
            for mock_mode in (True, False):
                with self.subTest(value=value, mock=mock_mode):
                    self.assertFalse(profiles.monitoring_wanted(value, mock_mode))

    def test_the_overlay_goes_last_and_only_once(self):
        cases = {
            (MOCK_FILES, ":", False): LEAN_MOCK_FILES,
            (LEAN_MOCK_FILES, ":", False): LEAN_MOCK_FILES,
            (LEAN_MOCK_FILES, ":", True): MOCK_FILES,
            (MOCK_FILES, ":", True): MOCK_FILES,
            (CPU_FILES.replace(":", ";"), ";", False):
                f"{CPU_FILES};docker-compose.monitoring-off.yml".replace(":", ";"),
            ("", ":", False): "docker-compose.yml:docker-compose.monitoring-off.yml",
            ("", ":", True): "docker-compose.yml",
        }
        for (current, sep, on), expected in cases.items():
            with self.subTest(current=current, on=on):
                self.assertEqual(profiles.with_monitoring(current, sep, on), expected)
        self.assertFalse(profiles.compose_file_runs_monitoring(LEAN_MOCK_FILES))
        self.assertTrue(profiles.compose_file_runs_monitoring(MOCK_FILES))

    def test_only_the_mock_profile_turns_monitoring_off(self):
        for name in profiles.PROFILE_ORDER:
            with self.subTest(name):
                self.assertTrue(profiles.compose_file_runs_monitoring(profiles.env_for(name)["COMPOSE_FILE"]))
        self.assertIn(profiles.MONITORING_OVERLAY, profiles.provenance_for("mock")["COMPOSE_FILE"]["why"])

    def test_the_uninstall_offers_the_monitoring_volumes_a_lean_install_left(self):
        for volume in ("loki_data", "tempo_data", "prometheus_data", "alloy_data"):
            with self.subTest(volume):
                self.assertIn(volume, horus_install.LEFT_BEHIND_VOLUMES)


class MonitoringOnASwitch(InstalledStack):
    def test_mock_mode_keeps_monitoring_on_when_the_setting_asks(self):
        self.write(f"COMPOSE_FILE={CPU_FILES}\nHORUS_MONITORING=on\n")
        with mock.patch.object(horus_install, "start_and_check", return_value=EXPECT_MOCK):
            self.assertEqual(self.ai("mock"), EXIT_OK)
        self.assertEqual(self.compose_file(), MOCK_FILES)
        self.assertEqual(self.stopped, [(["llm", "llm-model"], CPU_FILES)])
        self.assertIn("Monitoring: on (HORUS_MONITORING=on)", self.out.getvalue())

    def test_mock_mode_says_monitoring_is_off_by_default(self):
        self.write(f"COMPOSE_FILE={CPU_FILES}\n")
        with mock.patch.object(horus_install, "start_and_check", return_value=EXPECT_MOCK):
            self.ai("mock")
        self.assertIn("Monitoring: off (HORUS_MONITORING=unset, off in mock mode)", self.out.getvalue())

    def switch_to_local(self, env: str) -> None:
        self.write(env)
        with mock.patch.object(horus_install.hardware, "probe", side_effect=lambda *a, **k: big_machine()), \
                mock.patch.object(horus_install.preflight, "run_install_checks"), \
                mock.patch.object(horus_install, "plan_model", return_value=FakePlan()), \
                mock.patch.object(horus_install, "download_model"), \
                mock.patch.object(horus_install, "start_and_check",
                                  return_value=[*horus_install.CORE_SERVICES, "llm"]):
            self.assertEqual(self.ai("local"), EXIT_OK)

    def failed_switch(self, env: str, target: str, failure):
        self.write(env)
        with mock.patch.object(horus_install.hardware, "probe", side_effect=lambda *a, **k: big_machine()), \
                mock.patch.object(horus_install.preflight, "run_install_checks"), \
                mock.patch.object(horus_install, "plan_model", return_value=FakePlan()), \
                mock.patch.object(horus_install, "download_model"), \
                mock.patch.object(horus_install, "start_and_check", side_effect=failure), \
                mock.patch.object(horus_install, "up_waiting_out_a_dependency_abort",
                                  return_value=(["up", "-d"], 0)), \
                mock.patch.object(horus_install, "wait_for_health"), \
                self.assertRaises((InstallError, KeyboardInterrupt)):
            self.ai(target)

    def test_a_failed_switch_that_turned_monitoring_on_stops_it_again(self):
        failure = InstallError(EXIT_SMOKE_FAILED, "The smoke test did not pass.")
        self.failed_switch(f"COMPOSE_FILE={LEAN_MOCK_FILES}\nHORUS_AI_MODE=mock\n", "local", failure)
        self.assertEqual(self.stopped[-1][0], ["llm", "llm-model", *MONITORING])
        self.assertEqual(self.compose_file(), LEAN_MOCK_FILES)

    def test_an_interrupted_switch_that_turned_monitoring_on_stops_it_again(self):
        self.failed_switch(f"COMPOSE_FILE={CPU_FILES}\nHORUS_MONITORING=on\n", "mock", KeyboardInterrupt)
        self.assertEqual(self.stopped[-1][0], ["llm-mock"])
        self.failed_switch(f"COMPOSE_FILE={CPU_FILES}\nHORUS_MONITORING=off\n", "mock", KeyboardInterrupt)
        self.assertEqual(self.stopped[-1][0], ["llm-mock"])

    def test_local_mode_turns_monitoring_back_on(self):
        self.switch_to_local(f"COMPOSE_FILE={LEAN_MOCK_FILES}\nHORUS_AI_MODE=mock\n")
        self.assertEqual(self.compose_file(), profiles.env_for("cpu-standard", big_machine())["COMPOSE_FILE"])
        self.assertEqual(self.stopped, [(["llm-mock"], LEAN_MOCK_FILES)])

    def test_local_mode_keeps_monitoring_off_when_the_setting_asks(self):
        self.switch_to_local(f"COMPOSE_FILE={MOCK_FILES}\nHORUS_AI_MODE=mock\nHORUS_MONITORING=off\n")
        local = profiles.env_for("cpu-standard", big_machine())["COMPOSE_FILE"]
        self.assertEqual(self.compose_file(),
                         profiles.with_monitoring(local, horus_install.separator_of(local), False))
        self.assertEqual(self.stopped, [(["llm-mock", *MONITORING], MOCK_FILES)])

    def test_status_shows_monitoring_and_warns_when_the_setting_is_not_applied(self):
        self.write(f"COMPOSE_FILE={LEAN_MOCK_FILES}\nHORUS_MONITORING=on\n")
        self.assertEqual(self.ai("status"), EXIT_OK)
        text = " ".join(self.out.getvalue().split())
        self.assertIn("Monitoring: Off", text)
        self.assertIn("HORUS_MONITORING=on, so monitoring should be on, but COMPOSE_FILE keeps it off. "
                      "Run --restart to apply it.", text)
        self.assertEqual([e for e in self.emitted() if e["event"] == "ai"][-1]["monitoring"], "off")


class MonitoringOnAStart(InstalledStack):
    def start(self, env: str, action) -> list[list[str]]:
        self.write(env)
        streamed: list[list[str]] = []
        self.ups: list[list[str]] = []
        with mock.patch.object(horus_install, "ensure_installed_model"), \
                mock.patch.object(horus_install, "up_waiting_out_a_dependency_abort",
                                  side_effect=lambda log, infra, up, timeout:
                                  self.ups.append(up) or (up, 0)), \
                mock.patch.object(horus_install, "_stream",
                                  side_effect=lambda cmd, *rest, **kw: streamed.append(cmd) or 0), \
                mock.patch.object(horus_install, "wait_for_health"):
            self.assertEqual(action(self.log, self.infra, 60), EXIT_OK)
        return streamed

    def test_a_start_applies_a_setting_changed_in_the_env(self):
        self.start(f"COMPOSE_FILE={LEAN_MOCK_FILES}\nHORUS_MONITORING=on\n", horus_install.do_start)
        self.assertEqual(self.compose_file(), MOCK_FILES)
        self.assertEqual(self.stopped, [])
        self.start(f"COMPOSE_FILE={CPU_FILES}\nHORUS_MONITORING=off\n", horus_install.do_start)
        self.assertEqual(self.compose_file(), f"{CPU_FILES}:docker-compose.monitoring-off.yml")
        self.assertEqual(self.stopped, [(MONITORING, CPU_FILES)])

    def test_a_start_leaves_an_install_that_follows_its_mode_alone(self):
        for env in (f"COMPOSE_FILE={LEAN_MOCK_FILES}\n", f"COMPOSE_FILE={CPU_FILES}\n"):
            with self.subTest(env):
                self.start(env, horus_install.do_start)
                self.assertEqual(self.env(), env)
        self.assertEqual(self.stopped, [])

    def test_a_restart_that_changes_monitoring_restarts_then_recreates_the_stack(self):
        streamed = self.start(f"COMPOSE_FILE={LEAN_MOCK_FILES}\nHORUS_MONITORING=on\n",
                              horus_install.do_restart)
        self.assertEqual([cmd[-1] for cmd in streamed], ["restart"])
        self.assertEqual(self.ups, [["up", "-d"]])
        self.assertEqual(self.compose_file(), MOCK_FILES)

    def test_a_restart_with_nothing_to_change_only_restarts(self):
        streamed = self.start(f"COMPOSE_FILE={LEAN_MOCK_FILES}\n", horus_install.do_restart)
        self.assertEqual([cmd[-1] for cmd in streamed], ["restart"])
        self.assertEqual(self.ups, [])

    def test_a_windows_path_and_an_unchanged_setting_leave_compose_file_as_written(self):
        written = "docker-compose.yml;docker-compose.cpu.yml;C:\\Users\\me\\override.yml;"
        self.start(f"COMPOSE_FILE={written}\n", horus_install.do_start)
        self.assertEqual(self.compose_file(), written)
        self.start(f"COMPOSE_FILE={written}\nHORUS_MONITORING=off\n", horus_install.do_start)
        self.assertEqual(self.compose_file(), f"{written}docker-compose.monitoring-off.yml")

    def test_a_quoted_or_commented_setting_is_understood(self):
        for value in ('"on"', "'on'", "on # keep it"):
            with self.subTest(value=value):
                self.start(f"COMPOSE_FILE={LEAN_MOCK_FILES}\nHORUS_MONITORING={value}\n",
                           horus_install.do_start)
                self.assertEqual(self.compose_file(), MOCK_FILES)

    def test_a_setting_that_is_neither_on_nor_off_says_so(self):
        self.start(f"COMPOSE_FILE={LEAN_MOCK_FILES}\nHORUS_MONITORING=enabled\n", horus_install.do_start)
        self.assertEqual(self.compose_file(), LEAN_MOCK_FILES)
        self.assertIn("HORUS_MONITORING=enabled in src/infra/.env is neither on nor off",
                      " ".join(self.out.getvalue().split()))

    def test_ai_mock_on_a_mock_install_applies_the_monitoring_default(self):
        self.write(f"COMPOSE_FILE={MOCK_FILES}\n")
        with mock.patch.object(horus_install, "do_start") as start:
            self.assertEqual(self.ai("mock"), EXIT_OK)
        start.assert_called_once()
        self.write(f"COMPOSE_FILE={LEAN_MOCK_FILES}\n")
        with mock.patch.object(horus_install, "do_start") as start:
            self.ai("mock")
        start.assert_not_called()


class InstallOverAnotherMode(InstalledStack):
    def test_the_server_the_new_files_drop_is_stopped_when_mock_mode_is_involved(self):
        cases = {
            (CPU_FILES, MOCK_FILES): ["llm", "llm-model"],
            ("docker-compose.yml", MOCK_FILES): ["vllm"],
            (MOCK_FILES, CPU_FILES): ["llm-mock"],
            (MOCK_FILES, MOCK_FILES): [],
            (CPU_FILES, "docker-compose.yml"): [],
            (CPU_FILES, CPU_FILES): [],
        }
        for (current, target), stopped in cases.items():
            with self.subTest(current=current, target=target):
                self.write(f"COMPOSE_FILE={current}\n")
                self.assertEqual(horus_install.model_servers_left_behind(self.infra, target), stopped)
        (self.infra / ".env").unlink()
        self.assertEqual(horus_install.model_servers_left_behind(self.infra, MOCK_FILES), [])

    def test_an_install_keeps_the_setting_a_reset_env_would_drop(self):
        source = inspect.getsource(horus_install._dispatch)
        self.assertIn("env[profiles.MONITORING_KEY] = monitoring_setting(infra)", source)
        self.assertLess(source.index("env[profiles.MONITORING_KEY] = monitoring_setting(infra)"),
                        source.index("apply_env(log, infra, env, reset=args.reset_env)"))

    def test_the_monitoring_the_new_files_turn_off_is_stopped_too(self):
        cases = {
            (CPU_FILES, LEAN_MOCK_FILES): MONITORING,
            (CPU_FILES, MOCK_FILES): [],
            (LEAN_MOCK_FILES, CPU_FILES): [],
            (LEAN_MOCK_FILES, LEAN_MOCK_FILES): [],
        }
        for (current, target), stopped in cases.items():
            with self.subTest(current=current, target=target):
                self.write(f"COMPOSE_FILE={current}\n")
                self.assertEqual(horus_install.monitoring_left_behind(self.infra, target), stopped)
        self.write("COMPOSE_PROJECT_NAME=old\n")
        self.assertEqual(horus_install.monitoring_left_behind(self.infra, LEAN_MOCK_FILES), MONITORING)
        (self.infra / ".env").unlink()
        self.assertEqual(horus_install.monitoring_left_behind(self.infra, LEAN_MOCK_FILES), [])

    def test_the_install_stops_it_under_the_old_files_before_writing_the_new_ones(self):
        source = inspect.getsource(horus_install._dispatch)
        stop = source.index("stop_services(log, infra, left_behind)")
        self.assertLess(source.index("model_servers_left_behind(infra, env[COMPOSE_FILE_KEY])"), stop)
        self.assertLess(source.index("monitoring_left_behind(infra, env[COMPOSE_FILE_KEY])"), stop)
        self.assertLess(source.index("with_wanted_monitoring(log, infra, env[COMPOSE_FILE_KEY]"),
                        source.index("monitoring_left_behind(infra, env[COMPOSE_FILE_KEY])"))
        self.assertLess(stop, source.index("apply_env(log, infra, env, reset=args.reset_env)"))


if __name__ == "__main__":
    unittest.main()
