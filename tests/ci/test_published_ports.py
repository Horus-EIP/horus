from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INFRA = REPO / "src" / "infra"
BASE_COMPOSE = INFRA / "docker-compose.yml"
CPU_OVERLAY = INFRA / "docker-compose.cpu.yml"
LOOPBACK = "127.0.0.1:"
BROWSER_FACING = "web-client"
WEB_MAPPING = "${HORUS_WEB_BIND:-127.0.0.1}:3000:3000"
DEV_TOOLS = ("pgadmin",)
PUBLISHING_SERVICES = {"rabbitmq", "mas", "web-client", "agent", "vllm", "knowledge_store",
                       "postgres", "redis", "pgadmin", "tempo"}

sys.path.insert(0, str(REPO / "installer"))
import preflight  # noqa: E402
import smoke  # noqa: E402

SERVICE = re.compile(r"^  ([\w-]+):\s*$")
PORTS = re.compile(r"^    ports:\s*$")
MAPPING = re.compile(r'^      - "?([^"#\s]+)"?')


def published_ports(path: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    service, listing = None, False
    for line in path.read_text(encoding="utf-8").splitlines():
        if SERVICE.match(line):
            service, listing = SERVICE.match(line).group(1), False
        elif PORTS.match(line):
            listing = True
        elif listing and MAPPING.match(line):
            found.setdefault(service, []).append(MAPPING.match(line).group(1))
        elif listing and line.strip() and not line.startswith("      "):
            listing = False
    return found


def default_host_port(mapping: str) -> int:
    return int(re.sub(r"\$\{\w+:-(\d+)\}", r"\1", mapping).split(":")[-2])


class PublishedPorts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = published_ports(BASE_COMPOSE)
        cls.overlay = published_ports(CPU_OVERLAY)

    def test_the_ports_found_are_the_ones_the_stack_publishes(self):
        self.assertEqual(set(self.base), PUBLISHING_SERVICES)

    def test_the_web_client_listens_where_horus_web_bind_says_127_0_0_1_by_default(self):
        self.assertEqual(self.base[BROWSER_FACING], [WEB_MAPPING])

    def test_no_port_listens_on_every_interface_except_3000_through_horus_web_bind(self):
        for service, mappings in self.base.items():
            for mapping in mappings:
                with self.subTest(f"{service} {mapping}"):
                    self.assertTrue(mapping.startswith(LOOPBACK) or mapping == WEB_MAPPING)

    def test_the_template_keeps_the_web_client_on_this_machine(self):
        self.assertEqual(smoke.read_env(INFRA / ".env.example")["HORUS_WEB_BIND"], "127.0.0.1")

    def test_the_cpu_overlay_publishes_no_port(self):
        self.assertEqual(self.overlay, {})

    def test_the_installer_checks_every_port_the_stack_publishes(self):
        published = {default_host_port(mapping)
                     for service, mappings in self.base.items() if service not in DEV_TOOLS
                     for mapping in mappings}
        self.assertEqual(published, {port for port, _service, _key in preflight.PORTS})


LAUNCHERS = (
    REPO / "installer" / "horus_install.py",
    REPO / "desktop" / "src-tauri" / "src" / "windows.rs",
    REPO / "packaging" / "START-HERE-Windows.bat",
    REPO / "packaging" / "START-HERE-Linux.sh",
    REPO / "packaging" / "START-HERE-macOS.command",
    REPO / "packaging" / "README-FIRST.txt",
    REPO / "packaging" / "RELEASE-NOTES.md",
)
WEB_CLIENT_URL = re.compile(r"https?://[^/\s\"'`]+:3000")


class LaunchersOpenLocalhost(unittest.TestCase):
    def test_every_launcher_opens_localhost_3000_never_a_network_address(self):
        for path in LAUNCHERS:
            with self.subTest(path.name):
                found = set(WEB_CLIENT_URL.findall(path.read_text(encoding="utf-8")))
                self.assertLessEqual(found, {"http://localhost:3000"})

    def test_the_installer_and_the_desktop_app_name_that_address(self):
        for path in LAUNCHERS[:2]:
            with self.subTest(path.name):
                self.assertIn("WEB_URL", path.read_text(encoding="utf-8"))
                self.assertIn('"http://localhost:3000"', path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
