from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ci" / "check-versions.py"

spec = importlib.util.spec_from_file_location("check_versions", SCRIPT)
check_versions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_versions)


def package_json(version: str) -> str:
    return json.dumps({"name": "app", "version": version})


def package_lock(version: str) -> str:
    return json.dumps(
        {
            "name": "app",
            "version": version,
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "app", "version": version},
                "node_modules/next": {"version": "16.1.1"},
            },
        }
    )


def write_tree(root: Path, version: str = "1.2.3") -> None:
    files = {
        "VERSION": f"{version}\n",
        "src/services/web-client/package.json": package_json(version),
        "src/services/web-client/package-lock.json": package_lock(version),
        "desktop/package.json": package_json(version),
        "desktop/package-lock.json": package_lock(version),
        "desktop/src-tauri/tauri.conf.json": json.dumps({"version": version}),
        "desktop/src-tauri/Cargo.toml": (
            f'[package]\nname = "horus-desktop"\nversion = "{version}"\n\n'
            '[dependencies]\nserde = { version = "1" }\n'
        ),
        "desktop/src-tauri/Cargo.lock": (
            'version = 4\n\n[[package]]\nname = "serde"\nversion = "1.0.228"\n\n'
            f'[[package]]\nname = "horus-desktop"\nversion = "{version}"\n'
        ),
        "desktop/ui/index.html": (
            f'<input placeholder="C:\\Users\\you\\Downloads\\Horus-Beta-{version}" />\n'
        ),
        "src/infra/.env.example": f"# HORUS_VERSION=0.0.1\nHORUS_VERSION={version}\nOTHER=1\n",
        "CHANGELOG.md": f"# Changelog\n\n## {version} (unreleased)\n\n## 0.0.9 - 2026-01-01\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def replace_nth(text: str, old: str, new: str, index: int) -> str:
    start = -1
    for _ in range(index + 1):
        start = text.index(old, start + 1)
    return text[:start] + new + text[start + len(old) :]


def run(root: Path, *extra: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = check_versions.main(["--root", str(root), *extra])
    return code, out.getvalue()


class CheckVersions(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        write_tree(self.root)

    def test_a_tree_where_every_version_agrees_passes(self):
        code, out = run(self.root)
        self.assertEqual(code, 0, out)
        self.assertIn(f"All {len(check_versions.CHECKS)} version numbers match", out)

    def test_every_listed_field_is_compared(self):
        for rel, field, _ in check_versions.CHECKS:
            with self.subTest(f"{rel} {field}"):
                self.assertTrue(
                    self.an_edit_is_reported(rel, field), f"changing {rel} never reported {field}"
                )

    def an_edit_is_reported(self, rel: str, field: str) -> bool:
        path = self.root / rel
        original = path.read_text(encoding="utf-8")
        try:
            for index in range(original.count("1.2.3")):
                path.write_text(replace_nth(original, "1.2.3", "9.9.9", index), encoding="utf-8")
                code, out = run(self.root)
                if code == 1 and f"{rel}: {field} is '9.9.9'" in out:
                    return True
            return False
        finally:
            path.write_text(original, encoding="utf-8")

    def test_only_the_root_package_entry_of_a_lockfile_counts(self):
        lock = self.root / "src/services/web-client/package-lock.json"
        data = json.loads(lock.read_text(encoding="utf-8"))
        data["packages"]["node_modules/next"]["version"] = "0.0.1"
        lock.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(run(self.root)[0], 0)

    def test_a_mismatch_names_the_file_the_field_and_both_values(self):
        tauri = self.root / "desktop/src-tauri/tauri.conf.json"
        tauri.write_text(json.dumps({"version": "1.2.2"}), encoding="utf-8")
        code, out = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn(
            "desktop/src-tauri/tauri.conf.json: version is '1.2.2', VERSION says '1.2.3'", out
        )

    def test_a_missing_file_fails_instead_of_passing_silently(self):
        (self.root / "desktop/src-tauri/Cargo.lock").unlink()
        code, out = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("desktop/src-tauri/Cargo.lock: cannot read", out)

    def test_a_missing_field_fails(self):
        (self.root / "src/infra/.env.example").write_text("OTHER=1\n", encoding="utf-8")
        code, out = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("src/infra/.env.example: cannot read HORUS_VERSION", out)

    def test_a_missing_version_file_fails(self):
        (self.root / "VERSION").unlink()
        code, out = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("VERSION: cannot read", out)

    def test_a_version_file_that_is_not_a_release_number_fails(self):
        (self.root / "VERSION").write_text("v1.2\n", encoding="utf-8")
        code, out = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("is not MAJOR.MINOR.PATCH", out)

    def test_windows_line_endings_are_accepted(self):
        for rel in ("VERSION", "src/infra/.env.example", "CHANGELOG.md"):
            path = self.root / rel
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(run(self.root)[0], 0)

    def test_the_changelog_must_open_with_the_current_release(self):
        (self.root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## 1.2.2 - 2026-01-01\n", encoding="utf-8"
        )
        code, out = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("CHANGELOG.md: newest release heading is '1.2.2'", out)

    def test_a_release_tag_naming_the_version_passes(self):
        self.assertEqual(run(self.root, "--tag", "v1.2.3")[0], 0)
        self.assertEqual(run(self.root, "--tag", "1.2.3")[0], 0)

    def test_a_release_tag_naming_another_version_fails(self):
        code, out = run(self.root, "--tag", "v1.2.4")
        self.assertEqual(code, 1)
        self.assertIn("git tag 'v1.2.4' does not name VERSION '1.2.3'", out)


class RepositoryVersions(unittest.TestCase):
    def test_the_repository_itself_agrees_with_its_version_file(self):
        code, out = run(REPO)
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
