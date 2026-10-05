from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import horus_install  # noqa: E402
import profiles  # noqa: E402
from common import (  # noqa: E402
    EVENT_PREFIX,
    EXIT_COMPOSE_PULL_FAILED,
    EXIT_COMPOSE_UP_FAILED,
    EXIT_HEALTH_TIMEOUT,
    EXIT_NOT_INSTALLED,
    Events,
    InstallError,
    Log,
    Result,
    exit_name,
    run,
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

    def test_cpu_overlay_expects_llama_server_as_llm(self):
        for separator in (":", ";"):
            with self.subTest(separator=separator):
                infra = write_env(
                    self.tmp,
                    f"COMPOSE_FILE=docker-compose.yml{separator}{profiles.CPU_OVERLAY}\n",
                )
                self.assertIn("llm", horus_install.expected_services(infra))

    def test_gpu_env_does_not_expect_llm(self):
        infra = write_env(self.tmp, "COMPOSE_FILE=docker-compose.yml\n")
        self.assertNotIn("llm", horus_install.expected_services(infra))

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
            horus_install.require_installed(infra, self.tmp / "horus-profile.json")
        self.assertEqual(caught.exception.code, EXIT_NOT_INSTALLED)

    def test_error_names_the_launcher_rather_than_a_command(self):
        infra = self.tmp / "src" / "infra"
        infra.mkdir(parents=True)
        with self.assertRaises(InstallError) as caught:
            horus_install.require_installed(infra, self.tmp / "horus-profile.json")
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
            with mock.patch.object(horus_install, "LOG_PATH", log_path),                     mock.patch.object(horus_install, "PROFILE_JSON", tmp / "horus-profile.json"),                     contextlib.redirect_stdout(io.StringIO()):
                code = horus_install.main(["--start", "--repo", str(tmp)])

            self.assertEqual(code, EXIT_NOT_INSTALLED)
            last = [
                line for line in log_path.read_text(encoding="utf-8").splitlines()
                if " EXIT " in line
            ][-1]
            self.assertIn(str(EXIT_NOT_INSTALLED), last)
            self.assertIn("EXIT_NOT_INSTALLED", last)

class CpuProfileDoesNotFailTheInstall(unittest.TestCase):
    """A CPU install must finish and report success.

    65 of the 68 acceptance-test scenarios work on a CPU; only the three that
    need the model do not. Exiting 50 made a working stack look like a failed
    install, so answer quality is a warning there and a hard failure on GPU.
    """

    SPIRAL = ("I couldn't extract a consistent answer from the retrieved "
              "content for this step.")

    def make_steps(self):
        import smoke
        recorded = []
        steps = smoke.Steps.__new__(smoke.Steps)
        steps.entries = []
        steps._t0 = 0.0
        steps._current = None
        steps.log = type("Quiet", (), {
            "say": lambda self, msg="": None,
            "ok": lambda self, msg: recorded.append(("ok", msg)),
            "warn": lambda self, msg: recorded.append(("warn", msg)),
            "fail": lambda self, msg: recorded.append(("fail", msg)),
        })()
        return steps, recorded

    def test_cpu_profiles_are_recognised(self):
        for name in profiles.PROFILES:
            expected = name.startswith("cpu")
            self.assertEqual(profiles.is_cpu_profile(name), expected, name)

    def test_a_bad_answer_stops_a_gpu_install(self):
        import smoke
        steps, _ = self.make_steps()
        with self.assertRaises(InstallError) as caught:
            smoke.step_check_answer(steps, self.SPIRAL, True)
        self.assertEqual(caught.exception.code, smoke.EXIT_SMOKE_FAILED)

    def test_the_same_answer_only_warns_on_cpu(self):
        import smoke
        steps, recorded = self.make_steps()
        smoke.step_check_answer(steps, self.SPIRAL, False)
        self.assertEqual([kind for kind, _ in recorded], ["warn"])
        self.assertTrue(steps.entries[-1].get("warning"))

    def test_the_cpu_warning_says_it_is_not_a_failure(self):
        import smoke
        steps, recorded = self.make_steps()
        smoke.step_check_answer(steps, self.SPIRAL, False)
        message = recorded[0][1]
        self.assertIn("EXPECTED on a CPU profile", message)
        self.assertIn("not an install failure", message)
        self.assertIn("F41", message)

    def test_a_good_answer_passes_on_either_profile(self):
        import smoke
        for require in (True, False):
            steps, recorded = self.make_steps()
            smoke.step_check_answer(steps, "**$4.2M**", require)
            self.assertEqual([kind for kind, _ in recorded], ["ok"])

    def test_the_installer_warns_before_a_cpu_install(self):
        lines = []
        log = type("Cap", (), {"say": lambda self, msg="": lines.append(msg)})()
        horus_install.warn_cpu_expectations(log)
        joined = " ".join(lines)
        self.assertIn("run on the CPU", joined)
        self.assertIn("65 of the 68", joined)
        self.assertIn("F41", joined)
        self.assertIn("14 minutes", joined)
        self.assertIn("llama-server", joined)

    def unanswered_chat(self, model_server):
        import smoke
        steps, _ = self.make_steps()
        deadline = smoke.time.monotonic() + 600
        with mock.patch.object(smoke, "ask", return_value=("", "no answer in 480s")), \
                self.assertRaises(InstallError) as caught:
            smoke.step_chat(steps, None, "http://localhost:8000", deadline, "token",
                            model_server)
        return caught.exception.fix

    def test_an_unanswered_cpu_chat_points_at_the_llm_container(self):
        fix = self.unanswered_chat("llm")
        self.assertIn("docker compose ps llm", fix)
        self.assertIn("docker compose logs --tail 80 llm", fix)
        self.assertIn("LLM_SERVER_MEM_LIMIT", fix)
        self.assertNotIn("vllm", fix)

    def test_an_unanswered_gpu_chat_points_at_the_vllm_container(self):
        fix = self.unanswered_chat("vllm")
        self.assertIn("docker compose ps vllm", fix)
        self.assertIn("--profile cpu-standard", fix)

    def test_the_smoke_test_reads_the_model_server_from_the_compose_files(self):
        import smoke
        with tempfile.TemporaryDirectory() as name:
            cpu = write_env(Path(name), f"COMPOSE_FILE=docker-compose.yml:{profiles.CPU_OVERLAY}\n")
            self.assertEqual(smoke.model_server_of(cpu), "llm")
        with tempfile.TemporaryDirectory() as name:
            gpu = write_env(Path(name), "COMPOSE_FILE=docker-compose.yml\n")
            self.assertEqual(smoke.model_server_of(gpu), "vllm")


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

REPO_ROOT = Path(__file__).resolve().parents[2]

ABORT = "dependency failed to start: container mas is unhealthy"

PULLABLE = {"postgres": {"image": "postgres:latest"}, "redis": {"image": "redis:7"}}
BUILT = {"mas": {"build": {"context": "../services/mas"}, "image": "infra-mas"}}
PREBUILT = {"mas": {"build": {"context": "../services/mas"},
                    "image": "ghcr.io/acme/horus-mas:0.1.2-cpu"}}
UNNAMED = {"mas": {"build": {"context": "../services/mas"}}}

UP = "up -d --no-build"
SOURCE_UP = "up -d"

REFUSED = 'Error response from daemon: Head "https://ghcr.io/v2/acme/horus-mas/manifests/0.1.2-cpu": unauthorized'

def compose_config(services):
    return {"name": "infra", "services": dict(services)}

def ps_row(service, health, state="running"):
    return {"Service": service, "State": state, "Health": health}

def watched(line, watch_for, found):
    if found is not None:
        for phrase in watch_for:
            if phrase in line:
                found.add(phrase)

class FakeDocker:

    def __init__(self, config=None, pulls=(), ups=((0, ""),), ps=((),), local_images=(),
                 builds=(), vanishing=None, image_ids=None):
        self.config = config
        self.pulls = list(pulls)
        self.builds = list(builds)
        self.ups = list(ups)
        self.ps = [list(rows) for rows in ps]
        self.local_images = set(local_images)
        self.vanishing = dict(vanishing or {})
        self.image_ids = dict(image_ids or {})
        self.history: list[str] = []
        self.labels: list[str] = []
        self.pull_envs: list[dict | None] = []
        self.config_logged: list[bool] = []

    def image_of(self, service):
        spec = ((self.config or {}).get("services") or {}).get(service) or {}
        return spec.get("image")

    def land(self, args):
        for service in args:
            image = self.image_of(service)
            if image is None:
                continue
            if self.vanishing.get(service, 0) > 0:
                self.vanishing[service] -= 1
                continue
            self.local_images.add(image)

    def stream(self, cmd, log, cwd, label, heartbeat=30, watch_for=(), found=None, env=None):
        self.history.append(" ".join(cmd[2:]))
        self.labels.append(label)
        if cmd[2] == "pull":
            self.pull_envs.append(env)
            outcome = self.pulls.pop(0) if self.pulls else 0
            code, line = outcome if isinstance(outcome, tuple) else (outcome, "")
            watched(line, watch_for, found)
            if code == 0:
                self.land(cmd[3:])
            return code
        if cmd[2] == "build":
            return self.builds.pop(0) if self.builds else 0
        code, line = self.ups.pop(0)
        watched(line, watch_for, found)
        return code

    def run(self, cmd, log, timeout=60, cwd=None, env=None, log_output=True):
        if cmd[1:3] == ["compose", "config"]:
            self.history.append("config")
            self.config_logged.append(log_output)
            if self.config is None:
                return Result(1, "", "no configuration file provided")
            return Result(0, json.dumps(self.config), "")
        if cmd[1:3] == ["compose", "ps"]:
            self.history.append("ps")
            rows = self.ps.pop(0) if len(self.ps) > 1 else self.ps[0]
            return Result(0, json.dumps(rows), "")
        if cmd[1:3] == ["image", "inspect"]:
            self.history.append("inspect " + cmd[-1])
            return Result(0 if cmd[-1] in self.local_images else 1, "", "")
        if cmd[1:3] == ["image", "ls"]:
            repository = cmd[-1]
            self.history.append("ls " + repository)
            rows = [f"{self.image_ids.get(image, 'id-' + image)} {image}"
                    for image in sorted(self.local_images)
                    if image.rpartition(":")[0] == repository]
            return Result(0, "\n".join(rows), "")
        raise AssertionError(f"unexpected command {cmd}")

    def pulled(self) -> list[str]:
        return [entry for entry in self.history if entry.startswith("pull")]

    def started(self) -> list[str]:
        return [entry for entry in self.history if entry.startswith("up")]

    def built(self) -> list[str]:
        return [entry for entry in self.history if entry.startswith("build")]

class FakeDockerCase(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.log = Log(self.tmp / "install-log.txt")
        self.addCleanup(self.log.close, 0)
        for name in ("_stream", "run"):
            self.addCleanup(setattr, horus_install, name, getattr(horus_install, name))
        sleeper = mock.patch.object(horus_install.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def run_it(self, docker, **kwargs):
        horus_install._stream = docker.stream
        horus_install.run = docker.run
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                horus_install.pull_and_build(self.log, self.tmp, **kwargs)
                raised = None
            except InstallError as exc:
                raised = exc
        return buf.getvalue(), raised

class ImagePulls(FakeDockerCase):

    def test_each_image_is_pulled_on_its_own_one_at_a_time(self):
        docker = FakeDocker(config=compose_config(PULLABLE))
        _out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertEqual(docker.pulled(), ["pull postgres", "pull redis"])
        for env in docker.pull_envs:
            self.assertEqual(env, {"COMPOSE_PARALLEL_LIMIT": "1"})

    def test_building_from_source_leaves_our_services_to_the_build(self):
        docker = FakeDocker(config=compose_config({**PULLABLE, **BUILT}))
        self.run_it(docker, from_source=True)
        self.assertNotIn("pull mas", docker.pulled())
        self.assertEqual(docker.built(), ["build"])

    def test_a_failed_pull_is_retried_then_succeeds(self):
        docker = FakeDocker(config=compose_config(PULLABLE), pulls=[1, 0, 0])
        out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertEqual(docker.pulled(), ["pull postgres", "pull postgres", "pull redis"])
        self.assertIn("attempt 2 of 3", docker.labels[1])
        self.assertIn("trying again", out)
        self.assertEqual(docker.started(), [UP])

    def test_each_image_gets_three_tries_with_a_growing_short_pause(self):
        docker = FakeDocker(config=compose_config(PULLABLE), pulls=[1, 1, 0, 0])
        _out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertEqual(docker.pulled().count("pull postgres"), 3)
        pauses = [call.args[0] for call in self.sleep.call_args_list]
        self.assertEqual(len(pauses), 2)
        self.assertLess(pauses[0], pauses[1])
        self.assertLessEqual(pauses[-1], 60)

    def test_an_image_still_failing_after_three_tries_stops_with_what_to_do_next(self):
        docker = FakeDocker(config=compose_config(PULLABLE), pulls=[0, 1, 1, 1])
        _out, raised = self.run_it(docker)
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, EXIT_COMPOSE_PULL_FAILED)
        self.assertEqual(docker.pulled().count("pull redis"), 3)
        self.assertIn("redis", raised.detail)
        self.assertNotIn("postgres", raised.detail)
        self.assertIn("docker compose pull redis", raised.fix)
        self.assertIn("START-HERE", raised.fix)
        self.assertEqual(docker.started(), [])

    def test_an_image_already_on_this_machine_is_used_when_the_pull_keeps_failing(self):
        docker = FakeDocker(config=compose_config(PULLABLE), pulls=[1, 1, 1, 0],
                            local_images={"postgres:latest"})
        out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertIn("inspect postgres:latest", docker.history)
        self.assertIn("already on this machine", out)
        self.assertEqual(docker.started(), [UP])

    def test_the_service_list_is_read_without_logging_the_secrets_it_holds(self):
        docker = FakeDocker(config=compose_config(PULLABLE))
        self.run_it(docker)
        self.assertEqual(docker.config_logged, [False])

    def test_without_a_service_list_one_pull_for_everything_is_retried(self):
        docker = FakeDocker(config=None, pulls=[1, 0])
        _out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertEqual(docker.pulled(), ["pull"] * 2)
        self.assertEqual(docker.pull_envs, [{"COMPOSE_PARALLEL_LIMIT": "1"}] * 2)
        self.assertEqual(docker.started(), [UP])

    def test_from_source_without_a_service_list_the_one_pull_skips_our_images(self):
        docker = FakeDocker(config=None, pulls=[1, 0])
        _out, raised = self.run_it(docker, from_source=True)
        self.assertIsNone(raised)
        self.assertEqual(docker.pulled(), ["pull --ignore-buildable"] * 2)
        self.assertEqual(docker.started(), [SOURCE_UP])

class PrebuiltImagePulls(FakeDockerCase):

    def test_an_install_pulls_our_images_first_and_never_builds(self):
        docker = FakeDocker(config=compose_config({**PULLABLE, **PREBUILT}))
        _out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertEqual(docker.pulled(), ["pull mas", "pull postgres", "pull redis"])
        self.assertEqual(docker.built(), [])
        self.assertEqual(docker.started(), [UP])

    def test_our_images_are_pulled_one_at_a_time_like_the_others(self):
        docker = FakeDocker(config=compose_config({**PULLABLE, **PREBUILT}))
        self.run_it(docker)
        self.assertEqual(docker.pull_envs, [{"COMPOSE_PARALLEL_LIMIT": "1"}] * 3)

    def test_a_pull_that_reports_success_without_the_image_is_retried(self):
        docker = FakeDocker(config=compose_config(PREBUILT), vanishing={"mas": 1})
        _out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertEqual(docker.pulled(), ["pull mas", "pull mas"])
        self.assertIn("attempt 2 of 3", docker.labels[1])
        self.assertEqual(docker.started(), [UP])

    def test_a_pull_that_never_lands_the_image_stops_the_install(self):
        docker = FakeDocker(config=compose_config(PREBUILT), vanishing={"mas": 3})
        _out, raised = self.run_it(docker)
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, EXIT_COMPOSE_PULL_FAILED)
        self.assertEqual(docker.pulled(), ["pull mas"] * 3)
        self.assertEqual(docker.started(), [])

    def test_a_refused_image_stops_at_once_and_the_fix_names_the_token(self):
        docker = FakeDocker(config=compose_config({**PULLABLE, **PREBUILT}),
                            pulls=[(1, REFUSED)])
        _out, raised = self.run_it(docker)
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, EXIT_COMPOSE_PULL_FAILED)
        self.assertEqual(docker.pulled(), ["pull mas"])
        self.assertIn("ghcr.io/acme/horus-mas:0.1.2-cpu", raised.detail)
        for hint in ("registry-token.txt", "HORUS_REGISTRY_TOKEN", "--registry-token-file",
                     "--build-from-source"):
            self.assertIn(hint, raised.fix)
        self.assertEqual(docker.started(), [])

    def test_a_refusal_behind_a_successful_exit_is_still_a_refusal(self):
        docker = FakeDocker(config=compose_config(PREBUILT), pulls=[(0, REFUSED)],
                            vanishing={"mas": 1})
        _out, raised = self.run_it(docker)
        self.assertIsNotNone(raised)
        self.assertEqual(docker.pulled(), ["pull mas"])
        self.assertIn("registry-token.txt", raised.fix)

    def test_a_copy_already_on_this_machine_is_used_when_the_registry_refuses(self):
        docker = FakeDocker(config=compose_config(PREBUILT), pulls=[(1, REFUSED)],
                            local_images={"ghcr.io/acme/horus-mas:0.1.2-cpu"})
        out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertIn("already on this machine", out)
        self.assertEqual(docker.started(), [UP])

    def test_our_service_without_an_image_name_stops_before_any_download(self):
        docker = FakeDocker(config=compose_config({**PULLABLE, **UNNAMED}))
        _out, raised = self.run_it(docker)
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, EXIT_COMPOSE_PULL_FAILED)
        self.assertIn("mas", raised.detail)
        self.assertIn("HORUS_REGISTRY", raised.detail)
        self.assertEqual(docker.pulled(), [])

    def test_building_from_source_pulls_the_others_then_builds_and_starts(self):
        docker = FakeDocker(config=compose_config({**PULLABLE, **UNNAMED}))
        _out, raised = self.run_it(docker, from_source=True)
        self.assertIsNone(raised)
        self.assertEqual(docker.pulled(), ["pull postgres", "pull redis"])
        self.assertEqual(docker.built(), ["build"])
        self.assertEqual(docker.started(), [SOURCE_UP])

    def test_no_build_from_source_skips_the_build(self):
        docker = FakeDocker(config=compose_config({**PULLABLE, **UNNAMED}))
        _out, raised = self.run_it(docker, from_source=True, no_build=True)
        self.assertIsNone(raised)
        self.assertEqual(docker.built(), [])
        self.assertEqual(docker.started(), [SOURCE_UP])

    def test_the_installer_says_which_images_it_downloads(self):
        out, _raised = self.run_it(FakeDocker(config=compose_config(PREBUILT)))
        self.assertIn("ghcr.io/acme/horus-mas:0.1.2-cpu", out)
        self.assertIn("prebuilt", out)

    def test_images_an_earlier_install_built_are_named_once_the_stack_runs(self):
        docker = FakeDocker(config=compose_config({**PULLABLE, **PREBUILT}),
                            local_images={"infra-mas"})
        out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertIn("docker image rm infra-mas", out)
        self.assertGreater(out.index("docker image rm"), out.index("Starting the stack"))

    def test_nothing_is_pointed_out_when_no_earlier_build_is_left(self):
        out, _raised = self.run_it(FakeDocker(config=compose_config(PREBUILT)))
        self.assertNotIn("docker image rm", out)

    def test_a_source_install_never_calls_its_own_images_unused(self):
        docker = FakeDocker(config=compose_config(UNNAMED), local_images={"infra-mas"})
        out, _raised = self.run_it(docker, from_source=True)
        self.assertNotIn("docker image rm", out)

    def test_other_releases_and_flavors_of_our_images_are_named_once_the_stack_runs(self):
        docker = FakeDocker(config=compose_config(PREBUILT),
                            local_images={"ghcr.io/acme/horus-mas:0.1.1-cpu",
                                          "ghcr.io/acme/horus-mas:0.1.2-gpu"})
        out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertIn("docker image rm ghcr.io/acme/horus-mas:0.1.1-cpu "
                      "ghcr.io/acme/horus-mas:0.1.2-gpu\n", out)
        self.assertNotIn("horus-mas:0.1.2-cpu", out.split("docker image rm", 1)[1])

    def test_old_source_builds_and_old_releases_are_named_together(self):
        docker = FakeDocker(config=compose_config(PREBUILT),
                            local_images={"infra-mas", "ghcr.io/acme/horus-mas:0.1.1-cpu"})
        out, _raised = self.run_it(docker)
        self.assertIn("docker image rm infra-mas ghcr.io/acme/horus-mas:0.1.1-cpu\n", out)

    def test_another_tag_of_the_image_in_use_is_not_called_unused(self):
        commit_tag = "ghcr.io/acme/horus-mas:sha-0123456789ab-cpu"
        docker = FakeDocker(config=compose_config(PREBUILT), local_images={commit_tag},
                            image_ids={commit_tag: "same",
                                       "ghcr.io/acme/horus-mas:0.1.2-cpu": "same"})
        out, _raised = self.run_it(docker)
        self.assertNotIn("docker image rm", out)

    def test_an_untagged_image_is_not_offered_for_removal_by_name(self):
        docker = FakeDocker(config=compose_config(PREBUILT),
                            local_images={"ghcr.io/acme/horus-mas:<none>"})
        out, _raised = self.run_it(docker)
        self.assertNotIn("docker image rm", out)

class RunCanKeepOutputOutOfTheLog(unittest.TestCase):

    SECRET = "JWT_SECRET_KEY=not-for-the-log"

    def run_and_read_log(self, **kwargs):
        with tempfile.TemporaryDirectory() as name:
            log_path = Path(name) / "install-log.txt"
            log = Log(log_path)
            result = run(
                [sys.executable, "-c", "import os; print(os.environ['HORUS_TEST_SECRET'])"],
                log, env={"HORUS_TEST_SECRET": self.SECRET}, **kwargs,
            )
            log.close(0)
            return result, log_path.read_text(encoding="utf-8")

    def test_output_is_logged_by_default(self):
        _result, text = self.run_and_read_log()
        self.assertIn(self.SECRET, text)

    def test_output_can_be_kept_out_of_the_log_and_still_returned(self):
        result, text = self.run_and_read_log(log_output=False)
        self.assertEqual(result.out, self.SECRET)
        self.assertNotIn(self.SECRET, text)
        self.assertIn("output not logged", text)

class DependencyAbort(FakeDockerCase):

    def test_a_dependency_abort_is_retried_once_and_can_succeed(self):
        docker = FakeDocker(config=compose_config({}), ups=[(1, ABORT), (0, "")])
        out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertEqual(len(docker.started()), 2)
        self.assertIn("second attempt", docker.labels[-1])
        self.assertIn("still starting", out)

    def test_a_dependency_abort_waits_for_the_starting_service_then_starts_the_rest(self):
        docker = FakeDocker(
            config=compose_config({}),
            ups=[(1, ABORT), (0, "")],
            ps=[
                [ps_row("mas", "unhealthy"), ps_row("postgres", "healthy"),
                 ps_row("agent", "", state="created")],
                [ps_row("mas", "starting")],
                [ps_row("mas", "healthy")],
            ],
        )
        patcher = mock.patch.object(horus_install, "wait_for_health",
                                    wraps=horus_install.wait_for_health)
        waited = patcher.start()
        self.addCleanup(patcher.stop)
        _out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertEqual(waited.call_count, 1)
        self.assertEqual(waited.call_args.args[2], ["mas"])
        self.assertTrue(self.sleep.called)
        second_up = len(docker.history) - 1
        self.assertEqual(docker.history[second_up], UP)
        self.assertLess(docker.history.index("ps"), second_up)

    def test_from_source_the_images_build_once_before_the_first_start(self):
        docker = FakeDocker(config=compose_config({}), ups=[(1, ABORT), (0, "")])
        _out, raised = self.run_it(docker, from_source=True)
        self.assertIsNone(raised)
        self.assertEqual(docker.history.count("build"), 1)
        self.assertLess(docker.history.index("build"), docker.history.index(SOURCE_UP))
        self.assertEqual(docker.started(), [SOURCE_UP, SOURCE_UP])

    def test_the_prebuilt_path_never_builds_not_even_on_the_second_start(self):
        docker = FakeDocker(config=compose_config({}), ups=[(1, ABORT), (0, "")])
        _out, raised = self.run_it(docker)
        self.assertIsNone(raised)
        self.assertEqual(docker.built(), [])
        self.assertEqual(docker.started(), [UP, UP])

    def test_the_no_build_path_from_source_never_builds(self):
        docker = FakeDocker(config=compose_config({}), ups=[(1, ABORT), (0, "")])
        _out, raised = self.run_it(docker, from_source=True, no_build=True)
        self.assertIsNone(raised)
        self.assertEqual(docker.built(), [])
        self.assertEqual(docker.started(), [SOURCE_UP, SOURCE_UP])

    def test_a_service_that_never_becomes_healthy_stops_with_the_health_timeout(self):
        docker = FakeDocker(config=compose_config({}), ups=[(1, ABORT), (0, "")],
                            ps=[[ps_row("mas", "unhealthy")]])
        _out, raised = self.run_it(docker, timeout=0)
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, EXIT_HEALTH_TIMEOUT)
        self.assertIn("mas", raised.detail)
        self.assertEqual(len(docker.started()), 1)

    def test_the_retry_happens_at_most_once(self):
        docker = FakeDocker(config=compose_config({}),
                            ups=[(1, ABORT), (1, ABORT), (1, ABORT)])
        _out, raised = self.run_it(docker)
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, EXIT_COMPOSE_UP_FAILED)
        self.assertEqual(len(docker.started()), 2)

    def test_a_failure_that_is_not_a_dependency_abort_is_not_retried(self):
        docker = FakeDocker(config=compose_config({}), ups=[(1, "no space left on device")])
        _out, raised = self.run_it(docker)
        self.assertIsNotNone(raised)
        self.assertEqual(len(docker.started()), 1)
        self.assertNotIn("ps", docker.history)

    def test_the_final_message_names_the_recovery_command(self):
        docker = FakeDocker(config=compose_config({}), ups=[(1, ABORT), (1, ABORT)])
        _out, raised = self.run_it(docker)
        self.assertIsNotNone(raised)
        self.assertIn("--start", raised.fix)
        self.assertIn("retried once", raised.fix)

class ModelBeforeTheFirstStart(FakeDockerCase):

    def test_from_source_the_model_downloads_after_the_build_and_before_the_first_start(self):
        docker = FakeDocker(config=compose_config(PULLABLE))
        _out, raised = self.run_it(
            docker, from_source=True, before_start=lambda: docker.history.append("model"))
        self.assertIsNone(raised)
        self.assertEqual(docker.history,
                         ["config", "pull postgres", "pull redis", "build", "model", SOURCE_UP])

    def test_the_model_downloads_after_the_prebuilt_images_and_before_the_first_start(self):
        docker = FakeDocker(config=compose_config({**PULLABLE, **PREBUILT}))
        _out, raised = self.run_it(
            docker, before_start=lambda: docker.history.append("model"))
        self.assertIsNone(raised)
        self.assertEqual(
            docker.history,
            ["config", "pull mas", "inspect ghcr.io/acme/horus-mas:0.1.2-cpu",
             "pull postgres", "pull redis", "inspect infra-mas", "ls ghcr.io/acme/horus-mas",
             "model", UP],
        )

    def test_without_a_build_the_model_still_comes_before_the_start(self):
        docker = FakeDocker(config=compose_config(PULLABLE))
        self.run_it(docker, from_source=True, no_build=True,
                    before_start=lambda: docker.history.append("model"))
        self.assertEqual(docker.history[-2:], ["model", SOURCE_UP])

    def test_a_failed_model_download_starts_nothing(self):
        docker = FakeDocker(config=compose_config(PULLABLE))

        def fail() -> None:
            raise InstallError(44, "The language model could not be downloaded.")

        _out, raised = self.run_it(docker, before_start=fail)
        self.assertEqual(raised.code, 44)
        self.assertEqual(docker.started(), [])

    def test_a_failed_build_stops_before_the_model_and_the_start(self):
        docker = FakeDocker(config=compose_config(PULLABLE), builds=[1])
        steps = []
        _out, raised = self.run_it(docker, from_source=True,
                                   before_start=lambda: steps.append("model"))
        self.assertEqual(raised.code, EXIT_COMPOSE_UP_FAILED)
        self.assertIn("did not build", raised.headline)
        self.assertEqual(steps, [])
        self.assertEqual(docker.started(), [])

class FullInstallPassesTheTimeoutOn(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        (self.repo / "src" / "infra").mkdir(parents=True)
        self.log = Log(self.repo / "install-log.txt")
        self.addCleanup(self.log.close, 0)

    def test_the_wait_after_a_dependency_abort_uses_the_users_timeout(self):
        args = horus_install.build_parser().parse_args(
            ["--profile", "gpu-8g", "--non-interactive", "--skip-smoke", "--timeout", "4200"]
        )
        with contextlib.ExitStack() as stack:
            patch = stack.enter_context
            patch(mock.patch.object(horus_install, "find_repo", return_value=self.repo))
            patch(mock.patch.object(horus_install, "banner"))
            patch(mock.patch.object(horus_install, "preflight"))
            patch(mock.patch.object(horus_install, "sign_in_to_registry"))
            consent = patch(mock.patch.object(horus_install, "consent"))
            consent.choose.return_value = {"corpus_dir": "../../demo_assets"}
            hardware = patch(mock.patch.object(horus_install, "hardware"))
            hardware.probe.return_value = dict(horus_install.SIMULATIONS["nvidia-8gb"])
            patch(mock.patch.object(horus_install, "apply_env"))
            pull_and_build = patch(mock.patch.object(horus_install, "pull_and_build"))
            patch(mock.patch.object(horus_install, "wait_for_health"))
            patch(mock.patch.object(horus_install, "_success"))
            patch(contextlib.redirect_stdout(io.StringIO()))
            code = horus_install._dispatch(self.log, args)
        self.assertEqual(code, horus_install.EXIT_OK)
        self.assertEqual(pull_and_build.call_args.kwargs["timeout"], 4200)

class StartWaitsOutADependencyAbort(FakeDockerCase):

    def setUp(self) -> None:
        super().setUp()
        self.infra = write_env(self.tmp, "COMPOSE_FILE=docker-compose.yml\n")
        for name in ("_require_docker", "wait_for_health"):
            patcher = mock.patch.object(horus_install, name)
            setattr(self, name.strip("_"), patcher.start())
            self.addCleanup(patcher.stop)

    def start_it(self, docker, timeout=1800, build=False):
        horus_install._stream = docker.stream
        horus_install.run = docker.run
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                code = horus_install.do_start(self.log, self.infra, timeout=timeout, build=build)
                raised = None
            except InstallError as exc:
                code, raised = exc.code, exc
        return code, buf.getvalue(), raised

    def test_start_waits_for_the_starting_service_then_starts_the_rest(self):
        docker = FakeDocker(
            ups=[(1, ABORT), (0, "")],
            ps=[[ps_row("mas", "starting"), ps_row("postgres", "healthy"),
                 ps_row("agent", "", state="created")]],
        )
        code, out, raised = self.start_it(docker, timeout=2400)
        self.assertIsNone(raised)
        self.assertEqual(code, horus_install.EXIT_OK)
        self.assertEqual(docker.started(), ["up -d", "up -d"])
        self.assertIn("second attempt", docker.labels[-1])
        self.assertIn("still starting", out)
        first_wait, last_wait = self.wait_for_health.call_args_list
        self.assertEqual(first_wait.args[2], ["mas"])
        self.assertEqual(first_wait.kwargs["timeout"], 2400)
        self.assertEqual(last_wait.args[2], horus_install.expected_services(self.infra))
        self.assertLess(docker.history.index("ps"), len(docker.history) - 1)

    def test_start_retries_a_dependency_abort_at_most_once(self):
        docker = FakeDocker(ups=[(1, ABORT), (1, ABORT), (1, ABORT)])
        code, _out, raised = self.start_it(docker)
        self.assertIsNotNone(raised)
        self.assertEqual(code, EXIT_COMPOSE_UP_FAILED)
        self.assertEqual(len(docker.started()), 2)

    def test_start_does_not_retry_a_failure_that_is_not_a_dependency_abort(self):
        docker = FakeDocker(ups=[(1, "no space left on device")])
        code, _out, raised = self.start_it(docker)
        self.assertEqual(code, EXIT_COMPOSE_UP_FAILED)
        self.assertEqual(len(docker.started()), 1)
        self.assertNotIn("ps", docker.history)
        self.wait_for_health.assert_not_called()

    def test_a_start_with_build_does_not_rebuild_on_the_second_attempt(self):
        docker = FakeDocker(ups=[(1, ABORT), (0, "")])
        code, _out, raised = self.start_it(docker, build=True)
        self.assertIsNone(raised)
        self.assertEqual(docker.started(), ["up -d --build", "up -d"])

    def test_a_source_install_starts_with_a_plain_up(self):
        docker = FakeDocker()
        _code, _out, raised = self.start_it(docker)
        self.assertIsNone(raised)
        self.assertEqual(docker.started(), [SOURCE_UP])

    def test_a_prebuilt_install_never_builds_on_start_not_even_on_the_second_attempt(self):
        self.infra = write_env(self.tmp, "COMPOSE_FILE=docker-compose.yml\n"
                                         "HORUS_REGISTRY=ghcr.io/acme\n")
        docker = FakeDocker(ups=[(1, ABORT), (0, "")])
        _code, _out, raised = self.start_it(docker)
        self.assertIsNone(raised)
        self.assertEqual(docker.started(), [UP, UP])

    def test_a_deactivated_registry_line_means_a_source_install(self):
        self.infra = write_env(self.tmp, "COMPOSE_FILE=docker-compose.yml\n"
                                         "#[horus-installer-unset] HORUS_REGISTRY=ghcr.io/acme\n")
        docker = FakeDocker()
        self.start_it(docker)
        self.assertEqual(docker.started(), [SOURCE_UP])

class RestartFallsBackWithoutBuilding(FakeDockerCase):

    def setUp(self) -> None:
        super().setUp()
        for name in ("_require_docker", "wait_for_health", "ensure_installed_model"):
            patcher = mock.patch.object(horus_install, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def restart(self, env_text):
        infra = write_env(self.tmp, env_text)
        docker = FakeDocker(ups=[(1, "restart failed"), (0, "")])
        horus_install._stream = docker.stream
        horus_install.run = docker.run
        with contextlib.redirect_stdout(io.StringIO()):
            horus_install.do_restart(self.log, infra, timeout=60)
        return docker.history

    def test_a_prebuilt_install_falls_back_to_up_without_building(self):
        history = self.restart("HORUS_REGISTRY=ghcr.io/acme\n")
        self.assertEqual(history, ["restart", UP])

    def test_a_source_install_falls_back_to_a_plain_up(self):
        history = self.restart("COMPOSE_FILE=docker-compose.yml\n")
        self.assertEqual(history, ["restart", SOURCE_UP])

class FirstInstallTime(FakeDockerCase):

    DOCUMENTS = (
        "packaging/README-FIRST.txt",
        "packaging/RELEASE-NOTES.md",
        "README.md",
        "docs/getting-started.md",
    )
    STALE = ("10-30 minutes", "10-15 minutes", "10–15 minutes", "30–60 minutes",
             "30-60 minutes", "under 30 minutes")

    def test_the_figure_is_the_one_the_beta_testers_measured(self):
        self.assertEqual(horus_install.FIRST_INSTALL_TIME, "1.5 to 2 hours")

    def test_the_installer_states_it_before_the_long_part(self):
        out, raised = self.run_it(FakeDocker(config=compose_config({})))
        self.assertIsNone(raised)
        self.assertIn(horus_install.FIRST_INSTALL_TIME, out)

    def test_the_cpu_warning_uses_the_same_figure(self):
        lines = []
        log = type("Cap", (), {"say": lambda self, msg="": lines.append(msg)})()
        horus_install.warn_cpu_expectations(log)
        joined = " ".join(lines)
        self.assertIn(horus_install.FIRST_INSTALL_TIME, joined)
        self.assertNotIn("an hour", joined)

    def test_every_document_gives_the_same_figure(self):
        for relative in self.DOCUMENTS:
            with self.subTest(document=relative):
                text = (REPO_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(horus_install.FIRST_INSTALL_TIME, text)
                for stale in self.STALE:
                    self.assertNotIn(stale, text)


class ReclaimBuildCache(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.log = Log(self.tmp / "install-log.txt")
        self.addCleanup(self.log.close, 0)
        self.addCleanup(setattr, horus_install, "run", horus_install.run)
        self.addCleanup(setattr, horus_install, "reclaimable_build_cache",
                        horus_install.reclaimable_build_cache)
        self.commands = []

    def stub(self, sizes, answer=None):
        remaining = list(sizes)

        def cache(_log):
            return remaining.pop(0) if len(remaining) > 1 else remaining[0]

        def run(cmd, _log, timeout=60, cwd=None, env=None):
            self.commands.append(cmd)
            return type("R", (), {"ok": True, "out": "", "err": "", "code": 0})()

        horus_install.reclaimable_build_cache = cache
        horus_install.run = run
        if answer is not None:
            patcher = mock.patch("builtins.input", lambda _prompt: answer)
            patcher.start()
            self.addCleanup(patcher.stop)

    def call(self, non_interactive=False, built_here=True):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            horus_install.offer_to_reclaim(self.log, non_interactive=non_interactive,
                                           built_here=built_here)
        return buf.getvalue()

    def succeed(self, built_here):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            horus_install._success(self.log, self.tmp, "cpu-standard", {"mode": "demo"},
                                   non_interactive=True, built_here=built_here)
        return buf.getvalue()

    def test_a_small_cache_is_not_mentioned_at_all(self):
        self.stub([500 * 1024**2])
        self.assertEqual(self.call().strip(), "")
        self.assertEqual(self.commands, [])

    def test_a_non_interactive_run_never_deletes_anything(self):
        self.stub([30 * 1024**3])
        out = self.call(non_interactive=True)
        self.assertIn("docker builder prune -f", out)
        self.assertEqual(self.commands, [])

    def test_declining_leaves_the_cache_alone(self):
        self.stub([30 * 1024**3], answer="n")
        out = self.call()
        self.assertIn("Left alone", out)
        self.assertEqual(self.commands, [])

    def test_accepting_prunes_and_reports_what_it_freed(self):
        self.stub([30 * 1024**3, 0], answer="y")
        out = self.call()
        self.assertEqual(self.commands, [["docker", "builder", "prune", "-f"]])
        self.assertIn("Reclaimed", out)

    def test_after_prebuilt_images_the_cache_is_put_down_to_an_earlier_build(self):
        self.stub([30 * 1024**3])
        out = self.call(non_interactive=True, built_here=False)
        self.assertIn("built\n  on this machine before", out)
        self.assertNotIn("The build left", out)
        self.assertIn("docker builder prune -f", out)

    def test_a_prebuilt_install_still_offers_a_large_cache_back(self):
        self.stub([30 * 1024**3])
        self.assertIn("docker builder prune -f", self.succeed(built_here=False))
        self.assertEqual(self.commands, [])

    def test_a_prebuilt_install_with_a_small_cache_says_nothing_about_it(self):
        self.stub([500 * 1024**2])
        self.assertNotIn("build cache", self.succeed(built_here=False))


if __name__ == "__main__":
    unittest.main()
