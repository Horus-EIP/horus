from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parents[2]
SERVICES = REPO / "src" / "services"
VERSION_FILE = SERVICES / "PYTHON_VERSION"
VERSION_FILE_INPUT = "src/services/PYTHON_VERSION"
PYTHON_SERVICES = ("mas", "agent", "knowledge-store", "llm-mock")
WORKFLOWS = REPO / ".github" / "workflows"
JOBS_ON_THE_IMAGE_PYTHON = {
    "ci.yml": ("test-mas", "test-agent", "test-knowledge-store", "test-installer", "test-llm-mock",
               "e2e-mock"),
    "images.yml": ("plan", "image"),
    "desktop-release.yml": ("verify", "bundle"),
}
PYTHON_FROM = re.compile(r"(?mi)^FROM\s+python:(\S+)")

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the workflows")


def image_python() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def setup_python_steps(workflow: str, job: str) -> list[dict]:
    jobs = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))["jobs"]
    return [step for step in jobs[job]["steps"]
            if str(step.get("uses", "")).startswith("actions/setup-python@")]


class ImagePython(unittest.TestCase):
    def test_the_version_file_names_one_exact_version(self):
        self.assertRegex(VERSION_FILE.read_text(encoding="utf-8"), r"\A\d+\.\d+\.\d+\n?\Z")

    def test_every_python_image_runs_that_version(self):
        for service in PYTHON_SERVICES:
            bases = PYTHON_FROM.findall((SERVICES / service / "Dockerfile").read_text(encoding="utf-8"))
            with self.subTest(service):
                self.assertTrue(bases)
                self.assertEqual(set(bases), {f"{image_python()}-slim"})

    @needs_yaml
    def test_the_service_and_installer_test_jobs_read_it(self):
        for workflow, jobs in JOBS_ON_THE_IMAGE_PYTHON.items():
            for job in jobs:
                steps = setup_python_steps(workflow, job)
                with self.subTest(f"{workflow} {job}"):
                    self.assertTrue(steps)
                    for step in steps:
                        self.assertEqual(step["with"].get("python-version-file"), VERSION_FILE_INPUT)
                        self.assertNotIn("python-version", step["with"])


if __name__ == "__main__":
    unittest.main()
