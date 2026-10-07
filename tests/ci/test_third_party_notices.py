from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "licences" / "third_party_notices.py"

spec = importlib.util.spec_from_file_location("third_party_notices", SCRIPT)
notices = importlib.util.module_from_spec(spec)
sys.modules["third_party_notices"] = notices
spec.loader.exec_module(notices)

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read scripts/licences/*.yaml")


class LicenceFromMetadata(unittest.TestCase):
    def test_a_licence_expression_wins(self):
        self.assertEqual(notices.licence_from_metadata("MIT OR Apache-2.0", "BSD", []), "MIT OR Apache-2.0")

    def test_a_short_license_field_is_used_as_it_is(self):
        self.assertEqual(notices.licence_from_metadata("", "BSD-3-Clause", []), "BSD-3-Clause")

    def test_a_full_licence_text_falls_back_to_the_classifiers(self):
        text = "Copyright (c) 2005, NumPy Developers.\nAll rights reserved.\n" + "x" * 200
        classifiers = ["License :: OSI Approved :: BSD License"]
        self.assertEqual(notices.licence_from_metadata("", text, classifiers), "BSD License")

    def test_classifiers_drop_their_prefix_and_are_joined(self):
        classifiers = [
            "License :: OSI Approved :: MIT License",
            "License :: OSI Approved :: Apache Software License",
        ]
        self.assertEqual(notices.licence_from_metadata("", "UNKNOWN", classifiers),
                         "Apache Software License OR MIT License")

    def test_no_licence_anywhere_gives_an_empty_string(self):
        self.assertEqual(notices.licence_from_metadata("", "", []), "")


class LockedRequirements(unittest.TestCase):
    def test_pins_extras_hashes_and_direct_urls_are_read(self):
        text = "\n".join([
            "# generated",
            "fastapi[all]==0.128.0 \\",
            "    --hash=sha256:abc",
            "Pika==1.3.2",
            "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/"
            "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
            "--extra-index-url https://download.pytorch.org/whl/cpu",
        ])
        self.assertEqual(notices.parse_locked(text), {
            "fastapi": "0.128.0",
            "pika": "1.3.2",
            "en-core-web-sm": "3.8.0",
        })


class Images(unittest.TestCase):
    def test_our_own_images_are_not_listed(self):
        raw = "${HORUS_REGISTRY:+${HORUS_REGISTRY}/horus-mas:${HORUS_VERSION:?x}-gpu}"
        self.assertIsNone(notices.resolve_image(raw))

    def test_a_variable_default_is_the_image_used(self):
        self.assertEqual(notices.resolve_image("${VLLM_IMAGE:-vllm/vllm-openai:v0.23.0}"),
                         "vllm/vllm-openai:v0.23.0")

    def test_repository_and_tag_are_split_after_the_registry(self):
        image = "ghcr.io/ggml-org/llama.cpp:server-b11382"
        self.assertEqual(notices.repository_of(image), "ghcr.io/ggml-org/llama.cpp")
        self.assertEqual(notices.tag_of(image), "server-b11382")
        self.assertEqual(notices.repository_of("localhost:5000/team/app:1.2"), "localhost:5000/team/app")
        self.assertEqual(notices.tag_of("postgres"), "latest")

    def test_build_stages_are_not_images(self):
        used = notices.used_images()
        self.assertNotIn("builder", used)
        self.assertIn("python:3.11-slim", used)


class WebClient(unittest.TestCase):
    def test_only_production_dependencies_are_listed_with_their_licence(self):
        entries = notices.web_entries()
        names = {entry.name for entry in entries}
        self.assertIn("next", names)
        self.assertNotIn("vitest", names)
        self.assertTrue(all(entry.licence != "UNKNOWN" for entry in entries))


@needs_yaml
class CommittedNotices(unittest.TestCase):
    def test_the_committed_file_is_up_to_date(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = notices.main(["--check"])
        self.assertEqual(status, 0, out.getvalue())

    def test_every_image_and_model_has_a_licence(self):
        report = notices.Report()
        notices.render(report)
        self.assertEqual(report.stale, [])


if __name__ == "__main__":
    unittest.main()
