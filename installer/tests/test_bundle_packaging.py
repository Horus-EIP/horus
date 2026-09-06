from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
BUNDLER = REPO / "packaging" / "build_bundle.py"
sys.path.insert(0, str(REPO / "packaging"))
import build_bundle  # noqa: E402

posix_only = unittest.skipUnless(
    os.name == "posix", "needs a POSIX kernel for modes and symlinks"
)

def make_app(root: Path) -> Path:
    app = root / "Horus.app"
    macos = app / "Contents" / "MacOS"
    versions = app / "Contents" / "Frameworks" / "A" / "Versions" / "1"
    macos.mkdir(parents=True)
    versions.mkdir(parents=True)

    (macos / "Horus").write_text("macho", encoding="utf-8")
    os.chmod(macos / "Horus", 0o755)
    (app / "Contents" / "Info.plist").write_text("<plist/>", encoding="utf-8")
    (versions / "A").write_text("FRAMEWORK", encoding="utf-8")
    os.symlink("1", versions.parent / "Current")
    os.symlink("Versions/Current/A", versions.parent.parent / "A")
    return app

def build(app_dir: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BUNDLER), "--out", str(out), "--app-dir", str(app_dir)],
        capture_output=True, text=True, cwd=str(REPO), timeout=300,
    )

def entries(zip_path: Path) -> dict:
    out = {}
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if not info.filename.startswith("app/"):
                continue
            mode = info.external_attr >> 16
            payload = zf.read(info.filename)
            out[info.filename] = (mode & 0o777, stat.S_ISLNK(mode), payload)
    return out

@posix_only
class AppBundleIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.app_dir = tmp / "app"
        cls.app_dir.mkdir()
        make_app(cls.app_dir)
        os.symlink("/etc/passwd", cls.app_dir / "Horus.app" / "Contents" / "escape.txt")

        cls.result = build(cls.app_dir, tmp / "dist")
        cls.zip_path = next((tmp / "dist").glob("*.zip"), None)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def setUp(self) -> None:
        if self.zip_path is None:
            self.fail(f"no archive was produced:\n{self.result.stdout}\n{self.result.stderr}")
        self.entries = entries(self.zip_path)

    def test_the_build_succeeded(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout)

    def test_the_macos_binary_keeps_its_executable_bit(self):
        mode, is_link, _ = self.entries["app/Horus.app/Contents/MacOS/Horus"]
        self.assertFalse(is_link)
        self.assertTrue(mode & 0o111, f"shipped {oct(mode)}; macOS will not open it")

    def test_ordinary_files_are_not_made_executable(self):
        mode, _, _ = self.entries["app/Horus.app/Contents/Info.plist"]
        self.assertFalse(mode & 0o111)

    def test_framework_symlinks_are_stored_as_symlinks(self):
        for name, target in (
            ("app/Horus.app/Contents/Frameworks/A/Versions/Current", "1"),
            ("app/Horus.app/Contents/Frameworks/A/A", "Versions/Current/A"),
        ):
            with self.subTest(name):
                _, is_link, payload = self.entries[name]
                self.assertTrue(is_link, f"{name} was flattened into a file")
                self.assertEqual(payload.decode(), target)

    def test_the_link_target_is_stored_once_not_twice(self):
        copies = [n for n, (_, is_link, payload) in self.entries.items()
                  if not is_link and payload == b"FRAMEWORK"]
        self.assertEqual(len(copies), 1, f"duplicated as {copies}")

    def test_a_symlink_out_of_the_tree_is_refused(self):
        self.assertNotIn("app/Horus.app/Contents/escape.txt", self.entries)
        for name, (_, _, payload) in self.entries.items():
            self.assertNotIn(b"root:", payload, f"{name} absorbed /etc/passwd")

    def test_the_refusal_is_reported_not_silent(self):
        self.assertIn("escape.txt", self.result.stdout)

    def test_the_bundle_still_resolves_after_extraction(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with zipfile.ZipFile(self.zip_path) as zf:
                for info in zf.infolist():
                    if not info.filename.startswith("app/"):
                        continue
                    dest = root / info.filename
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        os.symlink(zf.read(info.filename).decode(), dest)
                    else:
                        dest.write_bytes(zf.read(info.filename))
                        os.chmod(dest, mode & 0o777)

            through_links = root / "app/Horus.app/Contents/Frameworks/A/A"
            self.assertEqual(through_links.read_text(encoding="utf-8"), "FRAMEWORK")
            binary = root / "app/Horus.app/Contents/MacOS/Horus"
            self.assertTrue(os.access(binary, os.X_OK))

class LineEndingGuard(unittest.TestCase):

    def setUp(self):
        build_bundle.NORMALISED.clear()

    def roundtrip(self, name: str, payload: bytes) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / name
            src.write_bytes(payload)
            zip_path = Path(tmp) / "t.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                build_bundle.add(zf, src, "horus/" + name)
            with zipfile.ZipFile(zip_path) as zf:
                return zf.read("horus/" + name)

    def test_a_crlf_shell_script_is_stored_as_lf(self):
        out = self.roundtrip("stack-up.sh", b"#!/bin/sh\r\necho hi\r\n")
        self.assertEqual(out, b"#!/bin/sh\necho hi\n")
        self.assertEqual(build_bundle.NORMALISED, ["horus/stack-up.sh  (CRLF -> LF)"])

    def test_command_files_and_dockerfiles_are_stored_as_lf(self):
        self.assertEqual(self.roundtrip("START-HERE-macOS.command", b"a\r\nb\r\n"), b"a\nb\n")
        self.assertEqual(self.roundtrip("Dockerfile", b"FROM x\r\nRUN y \\\r\n  z\r\n"),
                         b"FROM x\nRUN y \\\n  z\n")
        self.assertEqual(len(build_bundle.NORMALISED), 2)

    def test_an_lf_batch_file_is_stored_as_crlf(self):
        out = self.roundtrip("START-HERE-Windows.bat", b"@echo off\ngoto :x\n:x\n")
        self.assertEqual(out, b"@echo off\r\ngoto :x\r\n:x\r\n")
        self.assertEqual(build_bundle.NORMALISED, ["horus/START-HERE-Windows.bat  (LF -> CRLF)"])

    def test_already_correct_files_are_not_reported(self):
        self.roundtrip("ok.sh", b"#!/bin/sh\n")
        self.roundtrip("ok.bat", b"@echo off\r\n")
        self.assertEqual(build_bundle.NORMALISED, [])

    def test_other_files_are_left_byte_for_byte(self):
        self.assertEqual(self.roundtrip("notes.py", b"a\r\nb\n"), b"a\r\nb\n")
        self.assertEqual(self.roundtrip("README.md", b"a\r\n"), b"a\r\n")
        self.assertEqual(build_bundle.NORMALISED, [])

@posix_only
class ExecutableBitGuard(unittest.TestCase):

    def test_a_non_executable_app_binary_fails_the_build(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            app_dir = tmp / "app"
            app_dir.mkdir()
            app = make_app(app_dir)
            os.chmod(app / "Contents" / "MacOS" / "Horus", 0o644)

            result = build(app_dir, tmp / "dist")
            self.assertEqual(result.returncode, 1)
            self.assertIn("not executable", result.stdout)
            self.assertFalse(list((tmp / "dist").glob("*.zip")),
                             "a broken archive was written anyway")

if __name__ == "__main__":
    unittest.main()
