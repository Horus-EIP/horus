from __future__ import annotations

import sys
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parents[2]
INFRA = REPO / "src" / "infra"
WEB_CLIENT = REPO / "src" / "services" / "web-client"
TRACED = ("mas", "agent", "knowledge_store")
LLM_SCRAPE_TARGET = "/etc/prometheus/scrape.d/llm.yaml"

sys.path.insert(0, str(REPO / "installer"))
import profiles  # noqa: E402

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the compose files")


def compose_tag(loader, _tag: str, node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


def services(name: str) -> dict:
    loader = type("ComposeLoader", (yaml.SafeLoader,), {})
    loader.add_multi_constructor("!", compose_tag)
    return yaml.load((INFRA / name).read_text(encoding="utf-8"), Loader=loader)["services"]


def environment(spec: dict) -> dict[str, str]:
    listed = spec.get("environment") or []
    if isinstance(listed, dict):
        return {str(key): str(value) for key, value in listed.items()}
    return dict(item.split("=", 1) if "=" in item else (item, "") for item in listed)


def dependencies(spec: dict) -> list[str]:
    needs = spec.get("depends_on") or {}
    return list(needs) if isinstance(needs, (dict, list)) else []


def mount_targets(spec: dict) -> dict[str, str]:
    return {mount.split(":")[1]: mount.split(":")[0] for mount in spec.get("volumes", [])}


@needs_yaml
class MonitoringOffOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = services(profiles.BASE_COMPOSE)
        cls.cpu = services(profiles.CPU_OVERLAY)
        cls.mock = services(profiles.MOCK_OVERLAY)
        cls.off = services(profiles.MONITORING_OVERLAY)

    def test_the_four_monitoring_services_do_not_run(self):
        backends = {name for name, spec in self.base.items()
                    if str(spec.get("image", "")).startswith(("grafana/", "prom/"))}
        self.assertEqual(backends, set(profiles.MONITORING_SERVICES))
        for name in profiles.MONITORING_SERVICES:
            with self.subTest(name):
                spec = self.off[name]
                self.assertEqual(spec["deploy"], {"replicas": 0})
                self.assertTrue(spec["profiles"])
                self.assertNotIn("dev-tools", spec["profiles"])

    def test_whatever_waits_for_them_no_longer_needs_them(self):
        for name, spec in self.base.items():
            if name in profiles.MONITORING_SERVICES:
                continue
            for needed in set(dependencies(spec)) & set(profiles.MONITORING_SERVICES):
                with self.subTest(f"{name} -> {needed}"):
                    self.assertIs(self.off[name]["depends_on"][needed]["required"], False)

    def test_the_services_stop_exporting_traces(self):
        exporting = {name for name, spec in self.base.items()
                     if "tempo" in environment(spec).get("OTEL_EXPORTER_OTLP_ENDPOINT", "")}
        self.assertEqual(exporting, set(TRACED))
        for name in TRACED:
            with self.subTest(name):
                env = environment(self.off[name])
                self.assertEqual(env["OTEL_SDK_DISABLED"], "true")
                self.assertEqual(env["OTEL_ENABLED"], "false")

    def test_the_web_client_is_told_monitoring_is_off(self):
        self.assertEqual(environment(self.off["web-client"])["HORUS_MONITORING"], "off")
        self.assertNotIn("HORUS_MONITORING", environment(self.base["web-client"]))
        reader = (WEB_CLIENT / "lib" / "server" / "monitoring.ts").read_text(encoding="utf-8")
        self.assertIn("process.env.HORUS_MONITORING", reader)

    def test_the_overlay_only_turns_off_and_quiets(self):
        allowed = {*profiles.MONITORING_SERVICES, "web-client", *TRACED}
        self.assertEqual(set(self.off), allowed)


@needs_yaml
class MockModeScrapesNoLlm(unittest.TestCase):
    def test_mock_mode_replaces_the_llm_scrape_with_an_empty_one(self):
        cpu = mount_targets(services(profiles.CPU_OVERLAY)["prometheus"])
        mock = mount_targets(services(profiles.MOCK_OVERLAY)["prometheus"])
        self.assertIn(LLM_SCRAPE_TARGET, cpu)
        empty = mock[LLM_SCRAPE_TARGET]
        self.assertNotEqual(empty, cpu[LLM_SCRAPE_TARGET])
        scrape = yaml.safe_load((INFRA / empty).read_text(encoding="utf-8"))
        self.assertEqual(scrape, {"scrape_configs": []})


if __name__ == "__main__":
    unittest.main()
