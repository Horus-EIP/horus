from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parents[2]
NOT_OURS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    "target",
    "dist",
    "build",
}
ROOT_WORKFLOWS = ["ci.yml", "desktop-release.yml", "eval-testset.yml", "images.yml"]
KIT_WORKFLOWS = ["ci.yml", "claims.yml", "dco.yml", "stale-claims.yml", "welcome.yml"]


def workflow_files() -> list[Path]:
    found = []
    for folder, children, files in os.walk(REPO):
        children[:] = [child for child in children if child not in NOT_OURS]
        here = Path(folder)
        if here.name == "workflows" and here.parent.name == ".github":
            found += [here / name for name in files if name.endswith((".yml", ".yaml"))]
    return sorted(found)


WORKFLOWS = workflow_files()
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s+#\s+v\d+(?:\.\d+){0,2}\s*$")

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the workflows")


def uses_lines():
    for path in WORKFLOWS:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = USES.match(line)
            if match:
                yield (
                    f"{path.relative_to(REPO).as_posix()}:{number}",
                    match.group(1),
                    match.group(2),
                )


class WorkflowPins(unittest.TestCase):
    def test_every_workflow_file_in_the_repository_is_checked(self):
        found = [path.relative_to(REPO).as_posix() for path in WORKFLOWS]
        self.assertEqual(
            found,
            [f".github/workflows/{name}" for name in ROOT_WORKFLOWS]
            + [f"opensource/horus-bench-kit/.github/workflows/{name}" for name in KIT_WORKFLOWS],
        )

    def test_every_action_is_pinned_by_commit_with_its_version_in_a_comment(self):
        found = list(uses_lines())
        self.assertTrue(found)
        for where, action, rest in found:
            with self.subTest(where):
                self.assertRegex(action, PINNED)
                self.assertRegex(rest, VERSION_COMMENT)

    def test_an_action_is_pinned_to_one_commit_everywhere(self):
        pins: dict[str, set[str]] = {}
        for _where, action, rest in uses_lines():
            name, _, sha = action.partition("@")
            pins.setdefault(name, set()).add(f"{sha}{rest.strip()}")
        for name, versions in pins.items():
            with self.subTest(name):
                self.assertEqual(len(versions), 1, versions)

    def test_no_workflow_runs_on_ubuntu_latest(self):
        for path in WORKFLOWS:
            with self.subTest(path.name):
                self.assertNotIn("ubuntu-latest", path.read_text(encoding="utf-8"))

    @needs_yaml
    def test_every_job_names_a_fixed_runner_image(self):
        for path in WORKFLOWS:
            jobs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]
            for name, job in jobs.items():
                runner = str(job["runs-on"])
                images = job.get("strategy", {}).get("matrix", {}).get("include", [])
                values = [str(row["os"]) for row in images] if "matrix.os" in runner else [runner]
                for value in values:
                    with self.subTest(f"{path.name} {name} {value}"):
                        self.assertNotRegex(value, r"^ubuntu-latest$")
                        if value.startswith("ubuntu-"):
                            self.assertRegex(value, r"^ubuntu-\d{2}\.\d{2}$")


if __name__ == "__main__":
    unittest.main()
