from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "opensource" / "horus-bench-kit"
ROOT_LICENCE = REPO / "LICENSE"
KIT_CARVE_OUT = (
    "The folder opensource/horus-bench-kit/ is not part of the Software: it is licensed separately "
    "under the Apache License 2.0, in the LICENSE file of that folder."
)
PROMPT_SOURCES = (
    REPO / "src" / "services" / "agent" / "app" / "ai_agents" / "answer_contract.py",
    REPO / "src" / "services" / "mas" / "tasks" / "prompts.py",
)
ROUTER_EXAMPLES = REPO / "src" / "services" / "mas" / "tasks" / "router_examples.yaml"
TESTSET = REPO / "tests" / "eval" / "testset.yaml"
WARMUP_QUESTION = "In one sentence, what kinds of documents are in the knowledge store?"
PROMPT_WINDOW = 8
SHORT_TEXT_WORDS = 6
FORBIDDEN_STRINGS = {
    "a product source path": "src/services",
    "a private registry": "ghcr.io/epitechpromo2027",
    "closed licence wording": "Proprietary",
    "a maintainer email domain": "@epitech.eu",
}
HORUS_ONLY = {
    "the candidate container of the stack": "llm-candidate",
    "the machine reference of the stack": "cpu16",
    "a stack container name": "horus_upgrade",
    "the disk of the development laptop": "SN740",
    "the CPU of the development laptop": "Ryzen AI 9",
    "the demo company": "FinCorp",
    "the demo corpus folder": "demo_assets",
}
TICKET_OR_DECISION = re.compile(r"\b(?:B-\d{2,3}|ADR-\d{1,3})\b")
PERMISSIVE = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC"}
WORD = re.compile(r"[a-z0-9]+")

spec = importlib.util.spec_from_file_location(
    "hbk_publishable", KIT / "src" / "horus_bench_kit" / "publishable.py"
)
publishable = importlib.util.module_from_spec(spec)
sys.modules["hbk_publishable"] = publishable
spec.loader.exec_module(publishable)

needs_yaml = unittest.skipUnless(
    yaml is not None, "needs PyYAML to read the Horus test set and router examples"
)


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def windows(found: list[str], size: int) -> set[tuple[str, ...]]:
    return {tuple(found[index : index + size]) for index in range(len(found) - size + 1)}


def string_literals(path: Path) -> list[str]:
    return [
        node.value
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def yaml_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in yaml_strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in yaml_strings(item)]
    return []


def horus_rules() -> tuple:
    titles = sorted(path.stem for path in (REPO / "demo_assets").glob("*.md"))
    return (
        *publishable.FORBIDDEN,
        *(publishable.forbidden_string(label, text) for label, text in HORUS_ONLY.items()),
        *(publishable.forbidden_string("a demo document title", title) for title in titles),
    )


def minimal_kit(folder: Path) -> Path:
    root = folder / "kit"
    root.mkdir()
    for name in ("LICENSE", "NOTICE", "README.md", "pyproject.toml"):
        shutil.copy2(KIT / name, root / name)
    return root


def kit_texts() -> dict[str, str]:
    return {
        relative.as_posix(): publishable.read_text(KIT, relative)
        for relative in publishable.packaged_files(KIT)
        if publishable.is_text(relative)
    }


class Publishable(unittest.TestCase):
    def test_the_kit_passes_its_own_checks(self):
        self.assertEqual(publishable.problems(KIT), [])

    def test_the_licence_files_name_the_three_authors(self):
        licence = (KIT / "LICENSE").read_text(encoding="utf-8")
        notice = (KIT / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("Apache License", licence)
        self.assertIn("Version 2.0, January 2004", licence)
        for author in ("Loup Marquez-Luttringer", "Noah Gibelli", "Matheus Lopez"):
            with self.subTest(author):
                self.assertIn(author, licence)
                self.assertIn(author, notice)
        self.assertEqual(len(notice.strip().splitlines()), 1)

    def test_the_root_licence_leaves_the_kit_out_of_the_software(self):
        text = ROOT_LICENCE.read_text(encoding="utf-8")
        definitions = text.split("\n1. DEFINITIONS\n")[1].split("\n2. ")[0]
        self.assertIn(KIT_CARVE_OUT, " ".join(definitions.split()))

    def test_the_checks_catch_each_forbidden_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = minimal_kit(Path(tmp))
            (root / "notes.md").write_text(
                "\n".join(FORBIDDEN_STRINGS.values()) + "\n", encoding="utf-8"
            )
            found = "\n".join(publishable.problems(root))
        for label in FORBIDDEN_STRINGS:
            with self.subTest(label):
                self.assertIn(f"notes.md: holds {label}", found)

    def test_the_checks_catch_an_import_from_outside_the_kit_and_a_missing_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = minimal_kit(Path(tmp))
            (root / "src").mkdir()
            (root / "src" / "leak.py").write_text("import third_party_notices\n", encoding="utf-8")
            found = "\n".join(publishable.problems(root))
        self.assertIn("src/leak.py: the first line is not", found)
        self.assertIn("src/leak.py: imports third_party_notices", found)

    def test_every_dependency_is_permissive_and_listed_with_its_licence(self):
        readme = (KIT / "README.md").read_text(encoding="utf-8")
        declared = publishable.declared_dependencies(
            (KIT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertTrue(declared)
        for requirement in declared:
            name = publishable.requirement_name(requirement)
            with self.subTest(name):
                self.assertIn(publishable.ALLOWED_DEPENDENCIES.get(name), PERMISSIVE)
                self.assertRegex(readme, rf"(?im)^.*\b{re.escape(name)}\b.*\b(MIT|BSD|Apache)")


class NoHorusContent(unittest.TestCase):
    def test_no_horus_only_string(self):
        self.assertTrue((REPO / "demo_assets").is_dir())
        self.assertEqual(publishable.problems(KIT, forbidden=horus_rules()), [])

    def test_the_horus_rules_find_what_they_look_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = minimal_kit(Path(tmp))
            (root / "notes.md").write_text("\n".join(HORUS_ONLY.values()) + "\n", encoding="utf-8")
            found = publishable.problems(root, forbidden=horus_rules())
        self.assertEqual(found, [f"notes.md: holds {label}" for label in HORUS_ONLY])

    def test_no_horus_ticket_or_decision_id(self):
        found = [
            f"{path}: {match}"
            for path, text in kit_texts().items()
            for match in TICKET_OR_DECISION.findall(text)
        ]
        self.assertEqual(found, [])

    def setUp(self) -> None:
        self.texts = kit_texts()
        self.windows = {
            path: windows(words(text), PROMPT_WINDOW) for path, text in self.texts.items()
        }

    def assert_absent(self, phrases: set[tuple[str, ...]], what: str) -> None:
        for path, found in self.windows.items():
            with self.subTest(f"{what} in {path}"):
                self.assertEqual(sorted(" ".join(phrase) for phrase in found & phrases), [])

    def test_no_sentence_of_a_horus_prompt(self):
        phrases = set()
        for path in PROMPT_SOURCES:
            for literal in string_literals(path):
                phrases |= windows(words(literal), PROMPT_WINDOW)
        self.assertTrue(phrases)
        self.assert_absent(phrases, "a Horus prompt")

    @needs_yaml
    def test_no_router_example_or_evaluation_question(self):
        router = yaml.safe_load(ROUTER_EXAMPLES.read_text(encoding="utf-8"))
        testset = yaml.safe_load(TESTSET.read_text(encoding="utf-8"))
        short = [
            text
            for text in yaml_strings(router) + yaml_strings(testset) + [WARMUP_QUESTION]
            if len(words(text)) >= SHORT_TEXT_WORDS
        ]
        self.assertTrue(short)
        for path, text in self.texts.items():
            flat = f" {' '.join(words(text))} "
            with self.subTest(path):
                self.assertEqual(
                    [item for item in short if f" {' '.join(words(item))} " in flat], []
                )


if __name__ == "__main__":
    unittest.main()
