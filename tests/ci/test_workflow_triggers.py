from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
PULL_REQUEST_WORKFLOWS = ("ci.yml", "eval-testset.yml")
BRANCHES = ["main", "master"]
GROUP = (
    "${{ github.workflow }}-${{ github.event_name == 'pull_request' && "
    "format('pr-{0}', github.event.pull_request.number) || github.run_id }}"
)
CANCEL = "${{ github.event_name == 'pull_request' }}"
SECRETS = re.compile(r"\bsecrets\b|github\.token|GITHUB_TOKEN", re.IGNORECASE)

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the workflows")


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))


def evaluate(expression: str, context: dict[str, object]) -> object:
    python = re.sub(r"github(?:\.[\w-]+)+", lambda match: repr(context[match.group(0)]), expression)
    python = re.sub(r"format\('([^']*)', ([^)]*)\)", r"'\1'.format(\2)", python)
    python = python.replace("&&", " and ").replace("||", " or ")
    return eval(python, {"__builtins__": {}})


def resolved(template: object, context: dict[str, object]) -> str:
    return re.sub(
        r"\$\{\{(.*?)\}\}", lambda match: str(evaluate(match.group(1), context)), str(template)
    )


def run(
    event: str, run_id: int, pull_request: int | None = None, workflow: str = "CI"
) -> dict[str, object]:
    return {
        "github.workflow": workflow,
        "github.event_name": event,
        "github.run_id": run_id,
        "github.event.pull_request.number": pull_request,
        "github.ref": "refs/heads/main",
        "github.head_ref": "feature" if pull_request else "",
        "github.sha": f"sha-{run_id}",
    }


@needs_yaml
class Triggers(unittest.TestCase):
    def test_ci_runs_on_main_master_pull_requests_and_by_hand(self):
        on = triggers(load("ci.yml"))
        self.assertEqual(set(on), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(on["push"], {"branches": BRANCHES})
        self.assertIsNone(on["pull_request"])

    def test_the_evaluation_set_runs_on_the_same_branches_when_its_files_change(self):
        on = triggers(load("eval-testset.yml"))
        self.assertEqual(set(on), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(on["push"]["branches"], BRANCHES)
        self.assertEqual(on["push"]["paths"], on["pull_request"]["paths"])
        self.assertEqual(set(on["pull_request"]), {"paths"})

    def test_no_workflow_names_a_retired_branch(self):
        for path in sorted(WORKFLOWS.glob("*.y*ml")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path.name):
                self.assertNotIn("Sprint#1_September2026_Tek5", text)
                self.assertNotIn("pre-release-fix", text)


@needs_yaml
class Concurrency(unittest.TestCase):
    def test_a_new_commit_cancels_only_the_older_run_of_the_same_pull_request(self):
        for name in PULL_REQUEST_WORKFLOWS:
            with self.subTest(name):
                self.assertEqual(
                    load(name)["concurrency"], {"group": GROUP, "cancel-in-progress": CANCEL}
                )

    def test_two_commits_to_one_pull_request_share_a_group_and_cancel(self):
        for name in PULL_REQUEST_WORKFLOWS:
            workflow = load(name)
            group, cancel = (
                workflow["concurrency"]["group"],
                workflow["concurrency"]["cancel-in-progress"],
            )
            title = workflow["name"]
            first, second = run("pull_request", 101, 7, title), run("pull_request", 102, 7, title)
            with self.subTest(name):
                self.assertEqual(resolved(group, first), f"{title}-pr-7")
                self.assertEqual(resolved(group, first), resolved(group, second))
                self.assertEqual(resolved(cancel, second), "True")
                self.assertNotEqual(
                    resolved(group, first), resolved(group, run("pull_request", 103, 8, title))
                )

    def test_pushes_and_manual_runs_never_share_a_group_or_cancel(self):
        for name in PULL_REQUEST_WORKFLOWS:
            workflow = load(name)
            group, cancel = (
                workflow["concurrency"]["group"],
                workflow["concurrency"]["cancel-in-progress"],
            )
            title = workflow["name"]
            for event in ("push", "workflow_dispatch"):
                first, second = run(event, 101, workflow=title), run(event, 102, workflow=title)
                with self.subTest(f"{name} {event}"):
                    self.assertEqual(resolved(group, first), f"{title}-101")
                    self.assertNotEqual(resolved(group, first), resolved(group, second))
                    self.assertEqual(resolved(cancel, first), "False")


@needs_yaml
class ForkPullRequests(unittest.TestCase):
    def test_no_workflow_runs_pull_request_target(self):
        for path in sorted(WORKFLOWS.glob("*.y*ml")):
            with self.subTest(path.name):
                self.assertNotIn("pull_request_target", triggers(load(path.name)))

    def test_a_pull_request_run_reads_the_repository_and_needs_no_secret(self):
        for name in PULL_REQUEST_WORKFLOWS:
            workflow = load(name)
            with self.subTest(name):
                self.assertIn("pull_request", triggers(workflow))
                self.assertEqual(workflow["permissions"], {"contents": "read"})
                self.assertIsNone(SECRETS.search((WORKFLOWS / name).read_text(encoding="utf-8")))
                for job_name, job in workflow["jobs"].items():
                    with self.subTest(f"{name} {job_name}"):
                        self.assertNotIn("permissions", job)

    def test_only_the_pull_request_workflows_run_on_pull_requests(self):
        running = [
            path.name
            for path in sorted(WORKFLOWS.glob("*.y*ml"))
            if "pull_request" in triggers(load(path.name))
        ]
        self.assertEqual(running, list(PULL_REQUEST_WORKFLOWS))


if __name__ == "__main__":
    unittest.main()
