from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "licences" / "report_image_copyleft.py"
spec = importlib.util.spec_from_file_location("report_image_copyleft", SCRIPT)
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


class NoticePackages(unittest.TestCase):
    def setUp(self) -> None:
        self.notices = """\
7. Source code of GPL and LGPL components

7.1 Debian packages

- adduser 3.152
  Licence: GPL-2+. Images: agent, knowledge-store,
  llm-mock, mas.
- poppler-utils 25.03
  Licence: GPL-2.0-only. Images: knowledge-store.

7.2 Alpine packages

- busybox 1.37.0-r19
  Licence: GPL-2.0-only. Images: web-client.

7.3 LGPL libraries among our dependencies

- psycopg2-binary 2.9.10
  Licence: LGPL-3.0-or-later. Images: mas.
"""

    def test_reads_real_section_7_format_and_wrapped_image_lists(self):
        found = reporter.notice_packages(self.notices, "knowledge_store")
        self.assertEqual(found, {
            "adduser": ("3.152", "GPL-2+"),
            "poppler-utils": ("25.03", "GPL-2.0-only"),
        })

    def test_reads_alpine_entries_for_web_client(self):
        self.assertEqual(
            reporter.notice_packages(self.notices, "web-client"),
            {"busybox": ("1.37.0-r19", "GPL-2.0-only")},
        )

    def test_does_not_match_package_names_as_substrings(self):
        text = self.notices.replace("- adduser 3.152", "- adduser-extra 3.152")
        found = reporter.notice_packages(text, "agent")
        self.assertNotIn("adduser", found)
        self.assertIn("adduser-extra", found)

    def test_missing_notice_entry_fails_the_report(self):
        text, complete = reporter.markdown_report(
            "mas",
            self.notices,
            [{"name": "unlisted", "version": "1.0", "licence": "GPL-3+"}],
        )
        self.assertFalse(complete)
        self.assertIn("Missing from Section 7", text)

    def test_version_mismatch_fails_the_report(self):
        text, complete = reporter.markdown_report(
            "mas",
            self.notices,
            [{"name": "adduser", "version": "3.153", "licence": "GPL-2+"}],
        )
        self.assertFalse(complete)
        self.assertIn("Version mismatch", text)
        self.assertIn("3.152", text)

    def test_listed_package_is_reported_as_matched(self):
        text, complete = reporter.markdown_report(
            "mas",
            self.notices,
            [{"name": "adduser", "version": "3.152", "licence": "GPL-2+"}],
        )
        self.assertTrue(complete)
        self.assertIn("Listed in Section 7 (GPL-2+)", text)


if __name__ == "__main__":
    unittest.main()
