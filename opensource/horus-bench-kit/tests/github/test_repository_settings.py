# SPDX-License-Identifier: Apache-2.0
import importlib.util
import itertools
import json
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

GITHUB = Path(__file__).resolve().parents[2] / ".github"
WORKFLOWS = GITHUB / "workflows"
PINNED = re.compile(r"^[ \t-]*uses:\s*(actions/[\w.-]+)@([0-9a-f]{40}) # v\d+(\.\d+)*\s*$")
USES = re.compile(r"^[ \t-]*uses:", re.MULTILINE)
MATRIX = re.compile(r"\$\{\{\s*matrix\.(\w+)\s*\}\}")
GITHUB_ACTIONS_APP = 15368
LABELS = {
    "good first issue",
    "help wanted",
    "bug",
    "enhancement",
    "documentation",
    "needs triage",
    "claimed",
}


def load_claims():
    spec = importlib.util.spec_from_file_location(
        "kit_settings_claims", GITHUB / "scripts" / "claims.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def triggers(data):
    return data.get("on", data.get(True))


def steps(data):
    return [step for job in data["jobs"].values() for step in job.get("steps", [])]


def check_names(data):
    names = []
    for key, job in data["jobs"].items():
        name = job.get("name", key)
        matrix = {
            axis: values
            for axis, values in job.get("strategy", {}).get("matrix", {}).items()
            if isinstance(values, list)
        }
        if not MATRIX.search(name):
            names.append(name)
            continue
        axes = sorted(matrix)
        for values in itertools.product(*(matrix[axis] for axis in axes)):
            chosen = dict(zip(axes, values, strict=True))
            names.append(MATRIX.sub(lambda match, chosen=chosen: str(chosen[match.group(1)]), name))
    return names


@pytest.fixture(scope="module")
def ruleset():
    return json.loads((GITHUB / "rulesets" / "main.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def labels():
    return json.loads((GITHUB / "labels.json").read_text(encoding="utf-8"))


def claim_labels():
    claims = load_claims()
    return {*claims.ELIGIBLE_LABELS, claims.CLAIMED}


def test_the_workflows_are_the_five_we_expect():
    assert sorted(path.name for path in WORKFLOWS.iterdir()) == [
        "ci.yml",
        "claims.yml",
        "dco.yml",
        "stale-claims.yml",
        "welcome.yml",
    ]


@pytest.mark.parametrize(
    "name", ["ci.yml", "claims.yml", "dco.yml", "stale-claims.yml", "welcome.yml"]
)
def test_every_action_is_an_official_one_pinned_by_commit_with_its_version(name):
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if USES.match(line)]
    assert lines
    assert [line for line in lines if not PINNED.match(line)] == []


def test_one_commit_per_action_across_the_workflows():
    pins = {}
    for path in WORKFLOWS.iterdir():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = PINNED.match(line)
            if match:
                pins.setdefault(match.group(1), set()).add(match.group(2))
    assert {action: len(shas) for action, shas in pins.items()} == {
        "actions/checkout": 1,
        "actions/setup-python": 1,
        "actions/first-interaction": 1,
    }


class TestPermissions:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("ci.yml", {"contents": "read"}),
            ("dco.yml", {"contents": "read"}),
            ("claims.yml", {"contents": "read", "issues": "write"}),
            ("stale-claims.yml", {"contents": "read", "issues": "write"}),
            ("welcome.yml", {"issues": "write", "pull-requests": "write"}),
        ],
    )
    def test_each_workflow_gets_only_what_it_needs(self, name, expected):
        data = workflow(name)
        assert data["permissions"] == expected
        assert all("permissions" not in job for job in data["jobs"].values())

    def test_no_workflow_reads_a_secret(self):
        for path in WORKFLOWS.iterdir():
            assert "secrets." not in path.read_text(encoding="utf-8"), path.name

    def test_only_the_welcome_runs_on_pull_request_target_and_it_runs_no_code(self):
        uses_target = [
            path.name
            for path in WORKFLOWS.iterdir()
            if "pull_request_target" in triggers(workflow(path.name))
        ]
        assert uses_target == ["welcome.yml"]
        welcome = steps(workflow("welcome.yml"))
        assert [step["uses"].split("@")[0] for step in welcome] == ["actions/first-interaction"]
        assert all("run" not in step for step in welcome)

    def test_the_sign_off_check_runs_on_pull_request_without_keeping_the_token(self):
        data = workflow("dco.yml")
        assert triggers(data) == {"pull_request": None}
        checkout = steps(data)[0]
        assert checkout["with"]["persist-credentials"] is False
        assert checkout["with"]["fetch-depth"] == 0

    @pytest.mark.parametrize("name", ["claims.yml", "stale-claims.yml"])
    def test_the_claim_bot_runs_the_default_branch_code_only(self, name):
        checkout = steps(workflow(name))[0]
        assert checkout["uses"].startswith("actions/checkout@")
        assert "ref" not in checkout["with"] and "repository" not in checkout["with"]
        assert checkout["with"]["persist-credentials"] is False


class TestTriggers:
    def test_ci_runs_on_pull_requests_and_on_main_and_cancels_older_pull_request_runs(self):
        data = workflow("ci.yml")
        assert triggers(data) == {"push": {"branches": ["main"]}, "pull_request": None}
        assert "github.event.pull_request.number" in data["concurrency"]["group"]
        assert "github.run_id" in data["concurrency"]["group"]
        assert (
            data["concurrency"]["cancel-in-progress"]
            == "${{ github.event_name == 'pull_request' }}"
        )

    def test_ci_tests_and_zips_the_kit_on_the_oldest_and_newest_python(self):
        job = workflow("ci.yml")["jobs"]["tests"]
        assert job["strategy"]["matrix"]["python"] == ["3.10", "3.13"]
        commands = " ".join(step.get("run", "") for step in job["steps"])
        assert (
            '".[test]"' in commands
            and "-m pytest" in commands
            and "scripts/make-zip.py" in commands
        )

    def test_claims_answer_new_comments_on_issues_only_and_never_from_a_bot(self):
        data = workflow("claims.yml")
        assert triggers(data) == {"issue_comment": {"types": ["created"]}}
        condition = data["jobs"]["claim"]["if"]
        assert "!github.event.issue.pull_request" in condition
        assert "github.event.comment.user.type != 'Bot'" in condition
        assert steps(data)[-1]["run"] == "python .github/scripts/claims.py comment"

    @pytest.mark.parametrize("name", ["claims.yml", "stale-claims.yml"])
    def test_the_claim_workflows_run_one_at_a_time_and_queue_the_rest(self, name):
        assert workflow(name)["concurrency"] == {"group": "claims", "queue": "max"}

    def test_stale_claims_run_every_day(self):
        data = workflow("stale-claims.yml")
        assert set(triggers(data)) == {"schedule", "workflow_dispatch"}
        assert re.fullmatch(r"\d+ \d+ \* \* \*", triggers(data)["schedule"][0]["cron"])
        assert steps(data)[-1]["run"] == "python .github/scripts/claims.py stale"

    def test_the_welcome_greets_a_first_issue_and_a_first_pull_request(self):
        data = workflow("welcome.yml")
        assert triggers(data) == {
            "issues": {"types": ["opened"]},
            "pull_request_target": {"types": ["opened"]},
        }
        options = steps(data)[0]["with"]
        assert options["issue_message"].strip() and options["pr_message"].strip()

    def test_the_welcome_skips_the_team_and_pull_requests_from_past_contributors(self):
        condition = " ".join(workflow("welcome.yml")["jobs"]["welcome"]["if"].split())
        assert condition.startswith("${{") and condition.endswith("}}")
        assert (
            'github.event_name == \'issues\' && !contains(fromJSON(\'["OWNER", "MEMBER", "COLLABORATOR"]\'), '
            "github.event.issue.author_association)"
        ) in condition
        assert (
            "github.event_name == 'pull_request_target' && contains(fromJSON('[\"FIRST_TIME_CONTRIBUTOR\", "
            '"FIRST_TIMER"]\'), github.event.pull_request.author_association)'
        ) in condition


class TestRuleset:
    def rule(self, ruleset, kind):
        found = [rule for rule in ruleset["rules"] if rule["type"] == kind]
        assert len(found) == 1, kind
        return found[0].get("parameters", {})

    def test_the_required_checks_are_the_job_names_of_ci_and_sign_off(self, ruleset):
        checks = self.rule(ruleset, "required_status_checks")["required_status_checks"]
        expected = check_names(workflow("ci.yml")) + check_names(workflow("dco.yml"))
        assert expected == [
            "Tests and zip (Python 3.10)",
            "Tests and zip (Python 3.13)",
            "Sign-off",
        ]
        assert [check["context"] for check in checks] == expected
        assert {check["integration_id"] for check in checks} == {GITHUB_ACTIONS_APP}

    def test_a_reviewed_pull_request_is_the_only_way_into_the_default_branch(self, ruleset):
        assert ruleset["target"] == "branch"
        assert ruleset["enforcement"] == "active"
        assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
        assert ruleset["bypass_actors"] == []
        assert self.rule(ruleset, "deletion") == {}
        assert self.rule(ruleset, "non_fast_forward") == {}
        review = self.rule(ruleset, "pull_request")
        assert review["required_approving_review_count"] == 1
        assert review["require_code_owner_review"] is True
        assert review["dismiss_stale_reviews_on_push"] is True
        assert review["required_review_thread_resolution"] is True
        assert review["allowed_merge_methods"] == ["merge"]


class TestLabelsAndTemplates:
    def test_the_labels_have_a_colour_and_a_short_description(self, labels):
        assert {label["name"] for label in labels} == LABELS
        assert len(labels) == len(LABELS)
        for label in labels:
            assert set(label) == {"name", "color", "description"}
            assert re.fullmatch(r"[0-9a-f]{6}", label["color"])
            assert 0 < len(label["description"]) <= 100

    def test_the_bot_creates_claimed_as_the_labels_file_describes_it(self, labels):
        claims = load_claims()
        claimed = next(label for label in labels if label["name"] == claims.CLAIMED)
        assert (claimed["color"], claimed["description"]) == (
            claims.CLAIMED_COLOR,
            claims.CLAIMED_DESCRIPTION,
        )
        assert {claims.SUGGESTED_LABEL, *claims.ELIGIBLE_LABELS} <= LABELS

    def test_every_form_has_a_body_and_only_known_labels(self):
        forms = sorted((GITHUB / "ISSUE_TEMPLATE").glob("*.yml"))
        assert [form.name for form in forms] == [
            "bug.yml",
            "config.yml",
            "feature.yml",
            "good-first-issue.yml",
        ]
        for form in forms:
            if form.name == "config.yml":
                continue
            data = yaml.safe_load(form.read_text(encoding="utf-8"))
            assert len(data["name"]) > 3 and data["description"].strip(), form.name
            assert set(data.get("labels", [])) <= LABELS - claim_labels(), form.name
            fields = [element for element in data["body"] if element["type"] != "markdown"]
            assert fields and len({element["id"] for element in fields}) == len(fields), form.name

    def test_blank_issues_are_off_and_questions_go_to_discussions(self):
        config = yaml.safe_load(
            (GITHUB / "ISSUE_TEMPLATE" / "config.yml").read_text(encoding="utf-8")
        )
        assert config["blank_issues_enabled"] is False
        urls = [link["url"] for link in config["contact_links"]]
        assert "https://github.com/Horus-EIP/horus-bench-kit/discussions" in urls

    def test_the_maintainers_own_every_file(self):
        lines = [
            line.strip()
            for line in (GITHUB / "CODEOWNERS").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        assert lines == ["* @Horus-EIP/maintainers"]

    def test_the_pull_request_template_asks_for_the_issue_and_the_sign_off(self):
        text = (GITHUB / "pull_request_template.md").read_text(encoding="utf-8")
        assert text.startswith("Fixes #")
        checklist = "\n".join(line for line in text.splitlines() if line.startswith("- [ ] "))
        for expected in ("Fixes #N", "git commit -s", "pytest", "make-zip.py", "CHANGELOG.md"):
            assert expected in checklist
