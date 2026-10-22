from __future__ import annotations

import contextlib
import io
import json
import os
import re
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
REPO = Path(__file__).resolve().parents[2]
INFRA = REPO / "src" / "infra"
BASE_COMPOSE = INFRA / "docker-compose.yml"
CPU_OVERLAY = INFRA / "docker-compose.cpu.yml"

import horus_install  # noqa: E402
import preflight  # noqa: E402
from common import EXIT_COMPOSE_MISSING, EXIT_PORTS_BUSY, InstallError, Log, Result  # noqa: E402

GHCR = "https://ghcr.io/v2/"
GHCR_LAYERS = "https://pkg-containers.githubusercontent.com/"

FEATURE_MARKERS = {
    "gpus: all": re.compile(r"^\s*gpus:\s*all\s*$", re.MULTILINE),
    "depends_on with required: false": re.compile(r"^\s*required:\s*false\s*$", re.MULTILINE),
    "the !reset tag": re.compile(r":\s*!reset\b"),
    "${VAR:+...} interpolation": re.compile(r"\$\{[A-Z_][A-Z0-9_]*:\+"),
}


def compose_text() -> str:
    return BASE_COMPOSE.read_text(encoding="utf-8") + CPU_OVERLAY.read_text(encoding="utf-8")


class LogCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.log = Log(self.tmp / "install-log.txt")
        self.addCleanup(self.log.close, 0)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(preflight.MODEL_SERVER_IMAGE_KEY, None)

    def log_text(self) -> str:
        return (self.tmp / "install-log.txt").read_text(encoding="utf-8")

    def check_compose_reporting(self, output: str) -> str:
        answer = Result(0, output, "")
        with mock.patch.object(preflight, "run", return_value=answer):
            return preflight.check_compose(self.log)


class ComposeVersion(LogCase):
    def test_the_minimum_is_the_newest_feature_the_compose_files_use(self):
        self.assertEqual(preflight.MIN_COMPOSE_VERSION, (2, 33, 0))
        self.assertEqual(set(FEATURE_MARKERS), {name for name, _ in preflight.COMPOSE_FEATURES})
        text = compose_text()
        for feature, marker in FEATURE_MARKERS.items():
            with self.subTest(feature):
                self.assertRegex(text, marker)

    def test_the_version_is_read_from_every_known_output(self):
        outputs = {
            "Docker Compose version v2.29.1-desktop.1": (2, 29, 1),
            "Docker Compose version v5.1.0": (5, 1, 0),
            "Docker Compose version 2.24.6+ds1-0ubuntu1~22.04.1": (2, 24, 6),
            "Docker Compose version v2.33.0": (2, 33, 0),
            "Docker Compose version 1f7a9b2": None,
            "": None,
        }
        for output, expected in outputs.items():
            with self.subTest(output):
                self.assertEqual(preflight.compose_version(output), expected)

    def test_a_compose_older_than_the_minimum_is_refused_with_the_reason(self):
        for output in (
            "Docker Compose version v2.32.4\n",
            "Docker Compose version v2.20.2\n",
            "Docker Compose version v2.29.1-desktop.1\n",
        ):
            with self.subTest(output), self.assertRaises(InstallError) as caught:
                self.check_compose_reporting(output)
            error = caught.exception
            self.assertEqual(error.code, EXIT_COMPOSE_MISSING)
            self.assertIn(preflight.dotted(preflight.compose_version(output)), error.headline)
            self.assertIn("2.33.0 or newer", error.headline)
            self.assertIn("gpus: all", error.detail)
            self.assertIn("docker compose version", error.fix)

    def test_the_minimum_and_newer_versions_pass(self):
        for output in (
            "Docker Compose version v2.33.0",
            "Docker Compose version v2.40.3-desktop.1",
            "Docker Compose version v5.1.0",
        ):
            with self.subTest(output):
                self.assertEqual(self.check_compose_reporting(output + "\n"), output)

    def test_an_unreadable_version_warns_and_goes_on(self):
        self.assertEqual(
            self.check_compose_reporting("Docker Compose version 1f7a9b2\n"),
            "Docker Compose version 1f7a9b2",
        )
        self.log.close(0)
        self.assertIn("Could not read a version number", self.log_text())
        self.assertIn("2.33.0", self.log_text())

    def test_a_missing_compose_is_still_reported_as_missing(self):
        with (
            mock.patch.object(preflight, "run", return_value=Result(1, "", "unknown command")),
            self.assertRaises(InstallError) as caught,
        ):
            preflight.check_compose(self.log)
        self.assertEqual(caught.exception.code, EXIT_COMPOSE_MISSING)
        self.assertIn("not available", caught.exception.headline)

    def test_start_and_restart_refuse_an_old_compose_too(self):
        old = Result(0, "Docker Compose version v2.24.6\n", "")
        with (
            mock.patch.object(preflight, "check_docker"),
            mock.patch.object(preflight, "run", return_value=old),
            self.assertRaises(InstallError) as caught,
        ):
            horus_install._require_docker(self.log)
        self.assertEqual(caught.exception.code, EXIT_COMPOSE_MISSING)


class PortsHeldByThisInstall(LogCase):
    def ports(self, busy: set[int], compose_ps: str, holder: str = "") -> dict:
        (self.tmp / ".env").write_text("COMPOSE_PROJECT_NAME=horus_verify\n", encoding="utf-8")
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    preflight, "_port_free", side_effect=lambda port: port not in busy
                )
            )
            stack.enter_context(mock.patch.object(preflight, "_holder", return_value=holder))
            stack.enter_context(
                mock.patch.object(preflight, "run", return_value=Result(0, compose_ps, ""))
            )
            return preflight.check_ports(self.log, self.tmp)

    def published(self, *ports: int) -> str:
        return (
            json.dumps(
                {
                    "Name": "horus_verify-mas-1",
                    "Publishers": [
                        {
                            "URL": "0.0.0.0",
                            "TargetPort": port,
                            "PublishedPort": port,
                            "Protocol": "tcp",
                        }
                        for port in ports
                    ],
                }
            )
            + "\n"
        )

    def test_a_port_held_by_this_installs_own_container_does_not_stop_a_new_run(self):
        report = self.ports({8000, 3000}, self.published(8000, 3000), "com.docker.backend.exe")

        self.assertTrue(report["8000"]["held_by_this_install"])
        self.assertTrue(report["3000"]["held_by_this_install"])

    def test_a_port_held_by_something_else_still_stops_the_install(self):
        with self.assertRaises(InstallError) as caught:
            self.ports({8000, 5432}, self.published(8000), "postgres.exe (PID 7)")

        self.assertEqual(caught.exception.code, EXIT_PORTS_BUSY)
        self.assertIn("5432", caught.exception.detail)
        self.assertNotIn("8000  needed", caught.exception.detail)

    def test_without_a_running_stack_a_busy_port_stops_the_install(self):
        with self.assertRaises(InstallError) as caught:
            self.ports({8000}, "", "nginx (PID 3)")

        self.assertEqual(caught.exception.code, EXIT_PORTS_BUSY)


class PortProbe(unittest.TestCase):
    def test_a_port_published_on_127_0_0_1_only_counts_as_busy(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            self.assertFalse(preflight._port_free(server.getsockname()[1]))


class ModelServerRegistry(LogCase):
    def install_checks(self, image_registry: str | None, cpu_profile: bool) -> list:
        with contextlib.ExitStack() as stack:
            for name in ("check_disk", "check_ports"):
                stack.enter_context(mock.patch.object(preflight, name))
            network = stack.enter_context(mock.patch.object(preflight, "check_network"))
            preflight.run_install_checks(
                self.log, self.tmp, image_registry=image_registry, cpu_profile=cpu_profile
            )
        return network.call_args.args[1]

    def test_the_default_image_is_the_one_the_cpu_overlay_runs(self):
        images = re.findall(
            r"\$\{LLM_SERVER_IMAGE:-([^}]+)\}", CPU_OVERLAY.read_text(encoding="utf-8")
        )
        self.assertTrue(images)
        for image in images:
            with self.subTest(image):
                self.assertTrue(image.startswith(preflight.DEFAULT_MODEL_SERVER_IMAGE + ":"))

    def test_a_cpu_profile_checks_ghcr_even_when_building_from_source(self):
        urls = [url for _label, url in self.install_checks(None, cpu_profile=True)]
        self.assertIn(GHCR, urls)
        self.assertIn(GHCR_LAYERS, urls)
        self.assertIn("https://pypi.org/simple/", urls)

    def test_a_cpu_profile_checks_ghcr_next_to_another_image_registry(self):
        hosts = dict(self.install_checks("registry.example.com/team", cpu_profile=True))
        self.assertEqual(hosts["Horus images"], "https://registry.example.com/v2/")
        self.assertEqual(hosts["llama.cpp server image"], GHCR)
        self.assertEqual(hosts["llama.cpp server image layers"], GHCR_LAYERS)

    def test_ghcr_is_checked_once_when_it_serves_both(self):
        hosts = self.install_checks("ghcr.io/epitechpromo2027", cpu_profile=True)
        urls = [url for _label, url in hosts]
        self.assertEqual(len(urls), len(set(urls)))
        labels = {url: label for label, url in hosts}
        self.assertEqual(labels[GHCR], "Horus images and llama.cpp server image")
        self.assertEqual(
            labels[GHCR_LAYERS], "Horus image layers and llama.cpp server image layers"
        )

    def test_a_gpu_profile_does_not_need_the_llama_server_image(self):
        urls = [
            url
            for _label, url in self.install_checks("registry.example.com/team", cpu_profile=False)
        ]
        self.assertNotIn(GHCR, urls)
        self.assertNotIn(GHCR_LAYERS, urls)

    def test_an_image_override_in_env_moves_the_check_to_its_registry(self):
        (self.tmp / ".env").write_text(
            "LLM_SERVER_IMAGE=mirror.example.com:5000/llama.cpp:server-b11382\n", encoding="utf-8"
        )
        urls = [
            url
            for _label, url in self.install_checks("registry.example.com/team", cpu_profile=True)
        ]
        self.assertIn("https://mirror.example.com:5000/v2/", urls)
        self.assertNotIn(GHCR, urls)

    def test_a_quoted_override_in_env_is_read_without_its_quotes(self):
        (self.tmp / ".env").write_text(
            'LLM_SERVER_IMAGE="mirror.example.com/llama.cpp:x"\n', encoding="utf-8"
        )
        self.assertEqual(preflight.model_server_image(self.tmp), "mirror.example.com/llama.cpp:x")

    def test_the_shell_variable_wins_over_env_like_compose(self):
        (self.tmp / ".env").write_text(
            "LLM_SERVER_IMAGE=mirror.example.com/llama.cpp:x\n", encoding="utf-8"
        )
        os.environ[preflight.MODEL_SERVER_IMAGE_KEY] = "other.example.com/llama.cpp:y"
        self.assertEqual(preflight.model_server_image(self.tmp), "other.example.com/llama.cpp:y")

    def test_an_image_on_docker_hub_adds_no_host_to_the_docker_registry_check(self):
        for image in (
            "ggml/llama.cpp:server",
            "llama.cpp:server",
            "docker.io/ggml/llama.cpp",
            "index.docker.io/ggml/llama.cpp",
        ):
            with self.subTest(image):
                self.assertEqual(preflight.model_server_hosts(image), [])
        self.assertIn("Docker registry", dict(preflight.RUNTIME_HOSTS))


if __name__ == "__main__":
    unittest.main()
