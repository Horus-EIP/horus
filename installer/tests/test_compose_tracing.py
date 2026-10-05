from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parent.parent.parent
INFRA = REPO / "src" / "infra"
TRACED_SERVICES = {"mas": "mas", "agent": "agent", "knowledge_store": "knowledge-store"}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def environment(spec: dict) -> dict[str, str]:
    entries = spec.get("environment", [])
    if isinstance(entries, dict):
        return {key: str(value) for key, value in entries.items()}
    return dict(entry.split("=", 1) for entry in entries)


def is_traced(env: dict[str, str], url: str) -> bool:
    patterns = [p.strip() for p in env.get("OTEL_PYTHON_EXCLUDED_URLS", "").split(",") if p.strip()]
    return not (patterns and re.search("|".join(patterns), url))


def probe_url(spec: dict) -> str:
    test = spec["healthcheck"]["test"]
    command = " ".join(test) if isinstance(test, list) else test
    return re.search(r"https?://[^\s'\"]+", command).group(0)


@unittest.skipUnless(yaml is not None, "needs PyYAML to read the compose file")
class ComposeTracing(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.services = load_yaml(INFRA / "docker-compose.yml")["services"]
        cls.scrape_jobs = load_yaml(INFRA / "observability" / "prometheus.yaml")["scrape_configs"]

    def env(self, service: str) -> dict[str, str]:
        return environment(self.services[service])

    def test_each_python_service_reports_the_name_the_traces_page_filters_on(self):
        for service, name in TRACED_SERVICES.items():
            with self.subTest(service):
                self.assertEqual(self.env(service)["OTEL_SERVICE_NAME"], name)

    def test_healthcheck_probes_are_not_traced(self):
        for service in TRACED_SERVICES:
            url = probe_url(self.services[service])
            with self.subTest(service):
                self.assertFalse(is_traced(self.env(service), url), url)

    def test_prometheus_scrapes_are_not_traced(self):
        scraped = 0
        for job in self.scrape_jobs:
            for static_config in job.get("static_configs", []):
                for target in static_config["targets"]:
                    service = target.split(":")[0]
                    if service not in TRACED_SERVICES:
                        continue
                    scraped += 1
                    url = f"http://{target}{job.get('metrics_path', '/metrics')}"
                    with self.subTest(job["job_name"]):
                        self.assertFalse(is_traced(self.env(service), url), url)
        self.assertEqual(scraped, len(TRACED_SERVICES))

    def test_agent_heartbeats_are_not_traced_on_either_end(self):
        url = "http://mas:8000/agents/heartbeat/3f6c2a"
        for service in ("agent", "mas"):
            with self.subTest(service):
                self.assertFalse(is_traced(self.env(service), url))

    def test_chat_traffic_is_still_traced(self):
        chat_urls = {
            "mas": [
                "http://localhost:8000/tasks/new_task/",
                "http://localhost:8000/tasks/task-result/",
                "http://localhost:8000/chat/12/",
            ],
            "agent": [
                "http://localhost:8001/task",
                "http://knowledge_store:8080/?query=hotel+limit&n_results=10",
                "http://mas:8000/tasks/task-result/",
            ],
            "knowledge_store": [
                "http://knowledge_store:8080/",
                "http://knowledge_store:8080/file/resolve",
            ],
        }
        for service, urls in chat_urls.items():
            for url in urls:
                with self.subTest(url):
                    self.assertTrue(is_traced(self.env(service), url))


if __name__ == "__main__":
    unittest.main()
