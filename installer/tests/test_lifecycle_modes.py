from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import horus_install  # noqa: E402
import profiles  # noqa: E402
from common import (  # noqa: E402
    EVENT_PREFIX,
    EXIT_NOT_INSTALLED,
    Events,
    InstallError,
    Log,
    exit_name,
)

def write_env(tmp: Path, body: str) -> Path:
    infra = tmp / "src" / "infra"
    infra.mkdir(parents=True, exist_ok=True)
    (infra / ".env").write_text(body, encoding="utf-8")
    return infra

class ExpectedServices(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_gpu_env_expects_vllm(self):
        infra = write_env(self.tmp, "COMPOSE_FILE=docker-compose.yml\n")
        self.assertIn("vllm", horus_install.expected_services(infra))

    def test_cpu_overlay_posix_separator_drops_vllm(self):
        infra = write_env(
            self.tmp,
            f"COMPOSE_FILE=docker-compose.yml:{profiles.CPU_OVERLAY}\n",
        )
        self.assertNotIn("vllm", horus_install.expected_services(infra))

    def test_cpu_overlay_windows_separator_drops_vllm(self):
        infra = write_env(
            self.tmp,
            f"COMPOSE_FILE=docker-compose.yml;{profiles.CPU_OVERLAY}\n",
        )
        self.assertNotIn("vllm", horus_install.expected_services(infra))

    def test_core_services_are_always_expected(self):
        infra = write_env(self.tmp, f"COMPOSE_FILE=a:{profiles.CPU_OVERLAY}\n")
        expected = horus_install.expected_services(infra)
        for service in horus_install.CORE_SERVICES:
            self.assertIn(service, expected)

    def test_last_occurrence_wins(self):
        infra = write_env(
            self.tmp,
            f"COMPOSE_FILE=docker-compose.yml:{profiles.CPU_OVERLAY}\n"
            "COMPOSE_FILE=docker-compose.yml\n",
        )
        self.assertIn("vllm", horus_install.expected_services(infra))

    def test_deactivated_line_is_not_read(self):
        infra = write_env(
            self.tmp,
            "#[horus-installer-unset] COMPOSE_FILE=docker-compose.yml:"
            f"{profiles.CPU_OVERLAY}\n",
        )
        self.assertIn("vllm", horus_install.expected_services(infra))

    def test_missing_env_does_not_raise(self):
        infra = self.tmp / "src" / "infra"
        infra.mkdir(parents=True)
        self.assertIn("vllm", horus_install.expected_services(infra))

class RequireInstalled(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_missing_env_raises_its_own_exit_code(self):
        infra = self.tmp / "src" / "infra"
        infra.mkdir(parents=True)
        with self.assertRaises(InstallError) as caught:
            horus_install.require_installed(infra)
        self.assertEqual(caught.exception.code, EXIT_NOT_INSTALLED)

    def test_error_names_the_launcher_rather_than_a_command(self):
        infra = self.tmp / "src" / "infra"
        infra.mkdir(parents=True)
        with self.assertRaises(InstallError) as caught:
            horus_install.require_installed(infra)
        self.assertIn("START-HERE", caught.exception.fix)

    def test_present_env_is_accepted(self):
        infra = write_env(self.tmp, "LLM_BACKEND=vllm\n")
        horus_install.require_installed(infra)

class EventStream(unittest.TestCase):
    def test_disabled_emits_nothing(self):
        buffer = io.StringIO()
        Events(False, buffer).emit("step", text="hello")
        self.assertEqual(buffer.getvalue(), "")

    def test_enabled_emits_one_prefixed_json_line(self):
        buffer = io.StringIO()
        Events(True, buffer).emit("step", text="hello")
        line = buffer.getvalue().rstrip("\n")
        self.assertTrue(line.startswith(EVENT_PREFIX))
        self.assertEqual(
            json.loads(line[len(EVENT_PREFIX):]),
            {"event": "step", "text": "hello"},
        )

    def test_one_line_per_event(self):
        buffer = io.StringIO()
        events = Events(True, buffer)
        events.emit("a")
        events.emit("b")
        lines = [line for line in buffer.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 2)

    def test_unserialisable_value_does_not_raise(self):
        buffer = io.StringIO()
        Events(True, buffer).emit("located", repo=Path("/tmp/x"), odd=object())
        payload = json.loads(buffer.getvalue().split(EVENT_PREFIX, 1)[1])
        self.assertIsInstance(payload["repo"], str)

    def test_a_broken_stream_is_survivable(self):

        class Broken(io.StringIO):
            def write(self, _text):  # noqa: D102
                raise OSError("broken pipe")

        Events(True, Broken()).emit("step", text="hello")

class LogMirrorsToEvents(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.buffer = io.StringIO()

    def make_log(self, enabled: bool = True) -> Log:
        log = Log(self.tmp / "log.txt", events=Events(enabled, self.buffer))
        self.addCleanup(log.close, 0)
        return log

    def events_from(self, log: Log) -> list[dict]:
        del log
        return [
            json.loads(line[len(EVENT_PREFIX):])
            for line in self.buffer.getvalue().splitlines()
            if line.startswith(EVENT_PREFIX)
        ]

    def test_every_console_level_is_mirrored(self):
        log = self.make_log()
        with contextlib.redirect_stdout(io.StringIO()):
            log.step("Starting Horus")
            log.ok("all up")
            log.warn("careful")
            log.fail("no")
            log.say("plain")
        kinds = [event["event"] for event in self.events_from(log)]
        for expected in ("step", "ok", "warn", "fail", "say"):
            self.assertIn(expected, kinds)

    def test_colour_codes_are_stripped_before_emission(self):
        log = self.make_log()
        with contextlib.redirect_stdout(io.StringIO()):
            log.say("\033[1mbold\033[0m")
        texts = [e.get("text") for e in self.events_from(log) if e["event"] == "say"]
        self.assertIn("bold", texts)

    def test_default_log_emits_nothing(self):
        log = self.make_log(enabled=False)
        self.assertFalse(log.events.enabled)
        buffer = io.StringIO()
        log.events._stream = buffer  # noqa: SLF001 - would-be destination
        with contextlib.redirect_stdout(io.StringIO()):
            log.step("Starting Horus")
            log.ok("all up")
        self.assertEqual(buffer.getvalue(), "")

    def test_close_reports_the_code_it_was_given(self):
        log = self.make_log()
        log.close(EXIT_NOT_INSTALLED)
        exits = [e for e in self.events_from(log) if e["event"] == "exit"]
        self.assertEqual(exits[-1]["code"], EXIT_NOT_INSTALLED)
        self.assertEqual(exits[-1]["name"], exit_name(EXIT_NOT_INSTALLED))

    def test_close_is_idempotent(self):
        log = self.make_log()
        log.close(EXIT_NOT_INSTALLED)
        log.close(0)
        exits = [e for e in self.events_from(log) if e["event"] == "exit"]
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0]["code"], EXIT_NOT_INSTALLED)

    def test_close_still_reports_when_the_file_could_not_be_opened(self):
        blocker = self.tmp / "not-a-directory"
        blocker.write_text("", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            log = Log(blocker / "log.txt", events=Events(True, self.buffer))
        self.assertIsNone(log._fh)  # noqa: SLF001 - the branch under test
        log.close(EXIT_NOT_INSTALLED)
        exits = [e for e in self.events_from(log) if e["event"] == "exit"]
        self.assertEqual(len(exits), 1)

class LogRecordsTheRealExitCode(unittest.TestCase):

    def test_failed_run_records_its_own_code(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            (tmp / "src" / "infra").mkdir(parents=True)
            (tmp / "src" / "infra" / "docker-compose.yml").write_text(
                "services: {}\n", encoding="utf-8"
            )
            log_path = tmp / "install-log.txt"
            original = horus_install.LOG_PATH
            horus_install.LOG_PATH = log_path
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = horus_install.main(["--start", "--repo", str(tmp)])
            finally:
                horus_install.LOG_PATH = original

            self.assertEqual(code, EXIT_NOT_INSTALLED)
            last = [
                line for line in log_path.read_text(encoding="utf-8").splitlines()
                if " EXIT " in line
            ][-1]
            self.assertIn(str(EXIT_NOT_INSTALLED), last)
            self.assertIn("EXIT_NOT_INSTALLED", last)

class Parser(unittest.TestCase):
    def parse(self, argv):
        return horus_install.build_parser().parse_args(argv)

    def test_new_flags_default_off(self):
        args = self.parse([])
        self.assertFalse(args.start)
        self.assertFalse(args.restart)
        self.assertFalse(args.json_events)

    def test_flags_are_accepted(self):
        args = self.parse(["--start", "--json-events"])
        self.assertTrue(args.start)
        self.assertTrue(args.json_events)
        args = self.parse(["--restart"])
        self.assertTrue(args.restart)

    def test_unknown_flag_still_exits_two(self):
        with self.assertRaises(SystemExit) as caught:
            self.parse(["--not-a-flag"])
        self.assertEqual(caught.exception.code, 2)

if __name__ == "__main__":
    unittest.main()
