from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parents[2]
GITHUB = REPO / ".github"
FORM_TYPES = {"markdown", "textarea", "input", "dropdown", "checkboxes"}
FORM_KEYS = {"name", "description", "title", "labels", "assignees", "projects", "type", "body"}
CONTACT_KEYS = {"name", "url", "about"}

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the templates")


def form_problems(path: Path) -> list[str]:
    form = yaml.safe_load(path.read_text(encoding="utf-8"))
    problems = []
    if not isinstance(form, dict):
        return [f"{path.name}: not a mapping"]
    problems += [f"{path.name}: unknown key {key}" for key in set(form) - FORM_KEYS]
    for key in ("name", "description"):
        if not isinstance(form.get(key), str) or not form[key].strip():
            problems.append(f"{path.name}: {key} must be a non-empty string")
    if isinstance(form.get("name"), str) and len(form["name"].strip()) <= 3:
        problems.append(f"{path.name}: name must be more than 3 characters")
    labels = form.get("labels", [])
    if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
        problems.append(f"{path.name}: labels must be a list of strings")
    body = form.get("body")
    if not isinstance(body, list) or not body:
        return problems + [f"{path.name}: body must be a non-empty list"]
    ids = []
    for number, element in enumerate(body, 1):
        where = f"{path.name} body {number}"
        kind = element.get("type")
        attributes = element.get("attributes") or {}
        if kind not in FORM_TYPES:
            problems.append(f"{where}: type {kind!r}")
            continue
        if kind == "markdown":
            if (
                not isinstance(attributes.get("value"), str)
                or "id" in element
                or "validations" in element
            ):
                problems.append(
                    f"{where}: a markdown element has a value, and no id or validations"
                )
            continue
        if not isinstance(attributes.get("label"), str) or not attributes["label"].strip():
            problems.append(f"{where}: no label")
        ids.append(element.get("id"))
        if (
            not isinstance(element.get("id"), str)
            or not element["id"].replace("-", "").replace("_", "").isalnum()
        ):
            problems.append(f"{where}: the id must be letters, digits, - or _")
        required = (element.get("validations") or {}).get("required", False)
        if not isinstance(required, bool):
            problems.append(f"{where}: validations.required must be true or false")
        options = attributes.get("options")
        if kind == "dropdown" and (
            not isinstance(options, list)
            or not options
            or not all(isinstance(option, str) for option in options)
        ):
            problems.append(f"{where}: a dropdown needs a list of options")
        if kind == "checkboxes" and (
            not isinstance(options, list)
            or not options
            or not all(isinstance(option, dict) and option.get("label") for option in options)
        ):
            problems.append(f"{where}: checkboxes need options with a label each")
    if len(ids) != len(set(ids)):
        problems.append(f"{path.name}: ids repeat")
    if all(element.get("type") == "markdown" for element in body):
        problems.append(f"{path.name}: the body needs one field that is not markdown")
    return problems


def config_problems(path: Path) -> list[str]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    problems = []
    if set(config) - {"blank_issues_enabled", "contact_links"}:
        problems.append(
            f"{path.name}: unknown keys {set(config) - {'blank_issues_enabled', 'contact_links'}}"
        )
    if not isinstance(config.get("blank_issues_enabled"), bool):
        problems.append(f"{path.name}: blank_issues_enabled must be true or false")
    for link in config.get("contact_links", []):
        if set(link) != CONTACT_KEYS or not str(link["url"]).startswith("https://"):
            problems.append(f"{path.name}: a contact link has name, an https url and about: {link}")
    return problems


@needs_yaml
class IssueForms(unittest.TestCase):
    def test_every_issue_form_has_the_fields_github_expects(self):
        forms = sorted((GITHUB / "ISSUE_TEMPLATE").glob("*.yml"))
        self.assertEqual([form.name for form in forms], ["bug.yml", "config.yml", "task.yml"])
        for form in forms:
            if form.name == "config.yml":
                continue
            with self.subTest(form.name):
                self.assertEqual(form_problems(form), [])

    def test_blank_issues_are_off_and_benchmarks_go_to_the_public_kit(self):
        path = GITHUB / "ISSUE_TEMPLATE" / "config.yml"
        self.assertEqual(config_problems(path), [])
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertIs(config["blank_issues_enabled"], False)
        self.assertIn(
            "https://github.com/Horus-EIP/horus-bench-kit",
            [link["url"] for link in config["contact_links"]],
        )

    def test_the_validator_catches_a_broken_form(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        broken = Path(folder.name) / "broken.yml"
        broken.write_text(
            "name: Bug\nbody:\n  - type: textarea\n    id: a\n  - type: dropdown\n    id: a\n"
            "    attributes:\n      label: Pick\n",
            encoding="utf-8",
        )
        problems = " | ".join(form_problems(broken))
        for expected in (
            "description must be",
            "name must be more than 3",
            "body 1: no label",
            "a dropdown needs",
            "ids repeat",
        ):
            with self.subTest(expected):
                self.assertIn(expected, problems)


class OwnersAndPullRequests(unittest.TestCase):
    def test_the_maintainers_team_owns_every_file(self):
        lines = [
            line.strip()
            for line in (GITHUB / "CODEOWNERS").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertEqual(lines, ["* @Horus-EIP/maintainers"])

    def test_the_pull_request_template_has_the_checklist(self):
        text = (GITHUB / "pull_request_template.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("Fixes #"))
        checklist = [line for line in text.splitlines() if line.startswith("- [ ] ")]
        for expected in (
            "Fixes #N",
            "commit norm",
            "tests",
            "CHANGELOG.md",
            "Contributor Agreement",
        ):
            with self.subTest(expected):
                self.assertTrue(any(expected in line for line in checklist), checklist)


if __name__ == "__main__":
    unittest.main()
