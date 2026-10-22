from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts" / "licences"

sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("check_licences", SCRIPTS / "check_licences.py")
check_licences = importlib.util.module_from_spec(spec)
sys.modules["check_licences"] = check_licences
spec.loader.exec_module(check_licences)

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read scripts/licences/*.yaml")


class LicenceKind(unittest.TestCase):
    def kind(self, licence: str) -> str:
        return check_licences.licence_kind(licence)

    def test_permissive_licences_pass(self):
        for licence in ("MIT", "Apache-2.0", "BSD-3-Clause", "MIT/Apache-2.0", "MPL-2.0", ""):
            with self.subTest(licence):
                self.assertEqual(self.kind(licence), check_licences.FREE)

    def test_gpl_agpl_and_sspl_are_strong(self):
        for licence in (
            "GPL-3.0-only",
            "AGPL-3.0-or-later",
            "SSPL-1.0",
            "GPLv2",
            "GNU General Public License v2 (GPLv2)",
        ):
            with self.subTest(licence):
                self.assertEqual(self.kind(licence), check_licences.STRONG)

    def test_lgpl_is_weak(self):
        for licence in (
            "LGPL-3.0-or-later",
            "LGPL with exceptions",
            "GNU Lesser General Public License v3 (LGPLv3)",
        ):
            with self.subTest(licence):
                self.assertEqual(self.kind(licence), check_licences.WEAK)

    def test_a_permissive_alternative_is_enough(self):
        self.assertEqual(self.kind("MIT OR Apache-2.0 OR LGPL-2.1-or-later"), check_licences.FREE)
        self.assertEqual(self.kind("(GPL-2.0-only OR MIT)"), check_licences.FREE)

    def test_every_licence_of_a_conjunction_applies(self):
        self.assertEqual(self.kind("Apache-2.0 AND LGPL-3.0-or-later"), check_licences.WEAK)
        self.assertEqual(self.kind("MIT AND GPL-3.0-only"), check_licences.STRONG)


@needs_yaml
class Allowlist(unittest.TestCase):
    def write(self, text: str) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "allowlist.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_an_entry_without_a_reason_is_refused(self):
        path = self.write("allow:\n  - ecosystem: python\n    name: psycopg2-binary\n")
        with self.assertRaises(SystemExit):
            check_licences.read_allowlist(path)

    def test_a_pattern_matches_package_names(self):
        allowed = {("web", "@img/sharp-*"): "reviewed"}
        self.assertEqual(
            check_licences.allowed_by(allowed, "web", "@img/sharp-libvips-linux-x64"),
            ("web", "@img/sharp-*"),
        )
        self.assertIsNone(
            check_licences.allowed_by(allowed, "rust", "@img/sharp-libvips-linux-x64")
        )

    def test_the_repository_passes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = check_licences.main([])
        self.assertEqual(status, 0, out.getvalue())


if __name__ == "__main__":
    unittest.main()
