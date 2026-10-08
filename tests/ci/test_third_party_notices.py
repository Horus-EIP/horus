from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
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
files = notices.licence_files

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
        self.assertIn("python:3.11.17-slim", used)


class WebClient(unittest.TestCase):
    def test_only_production_dependencies_are_listed_with_their_licence(self):
        entries = notices.web_entries()
        names = {entry.name for entry in entries}
        self.assertIn("next", names)
        self.assertNotIn("vitest", names)
        self.assertTrue(all(entry.licence != "UNKNOWN" for entry in entries))

    def test_optional_peers_and_other_platforms_are_left_out(self):
        names = {entry.name for entry in notices.web_entries()}
        self.assertNotIn("@playwright/test", names)
        self.assertNotIn("@img/sharp-win32-x64", names)
        self.assertNotIn("@next/swc-darwin-arm64", names)
        self.assertIn("@img/sharp-libvips-linuxmusl-x64", names)
        self.assertNotIn("@img/sharp-libvips-linux-x64", names)
        self.assertNotIn("@next/swc-linux-x64-gnu", names)

    def test_a_package_for_another_platform_does_not_run_in_the_image(self):
        linux = {"os": ["linux"], "cpu": ["x64"]}
        packages = {"node_modules/@x/bin-linux-x64-gnu": linux, "node_modules/@x/bin-linux-x64-musl": linux}
        self.assertTrue(notices.runs_in_web_image({}))
        self.assertTrue(notices.runs_in_web_image(linux))
        self.assertFalse(notices.runs_in_web_image({"os": ["darwin"], "cpu": ["arm64"]}))
        self.assertFalse(notices.runs_in_web_image({"cpu": ["wasm32"]}))
        self.assertFalse(notices.runs_in_web_image(linux, "node_modules/@x/bin-linux-x64-gnu", packages))
        self.assertTrue(notices.runs_in_web_image(linux, "node_modules/@x/bin-linux-x64-musl", packages))


class LicenceFiles(unittest.TestCase):
    def test_licence_and_notice_files_are_found_by_name(self):
        classify = files.classify
        self.assertEqual(classify("fastembed-0.8.1.dist-info/licenses/NOTICE"), "notice")
        self.assertEqual(classify("onnxruntime/ThirdPartyNotices.txt"), "notice")
        self.assertEqual(classify("torch-2.14.1.dist-info/licenses/third_party/fmt/LICENSE"), "licence")
        self.assertEqual(classify("pypdfium2-5.14.0.dist-info/licenses/data/linux_x64/BUILD_LICENSES/icu.txt"),
                         "licence")
        self.assertEqual(classify("package/LICENSE-MIT"), "licence")
        self.assertEqual(classify("package/license.md"), "licence")
        self.assertEqual(classify("package/dist/compiled/react/LICENSE"), "licence")
        self.assertIsNone(classify("package/lib/license.js"))
        self.assertIsNone(classify("package/test/fixtures/LICENSE"))

    def test_the_licence_is_recognised_from_its_text(self):
        bsd3 = ("Redistribution and use in source and binary forms, with or without modification ... "
                "Neither the name of the copyright holder nor the names of its contributors")
        self.assertEqual(files.identify(bsd3), "BSD-3-Clause")
        self.assertEqual(files.identify("Redistribution and use in source and binary forms"), "BSD-2-Clause")
        self.assertEqual(files.identify("Permission is hereby granted, free of charge, to any person"), "MIT")
        self.assertEqual(files.identify("Apache License\nVersion 2.0, January 2004"), "Apache-2.0")
        self.assertIsNone(files.identify("All rights reserved."))

    def test_expressions_are_split_into_licences_and_exceptions(self):
        self.assertEqual(files.split_expression("(MIT OR Apache-2.0) AND Unicode-3.0"),
                         (["MIT", "Apache-2.0", "Unicode-3.0"], []))
        self.assertEqual(files.split_expression("GPL-3.0-or-later WITH GCC-exception-3.1"),
                         (["GPL-3.0-or-later"], ["GCC-exception-3.1"]))

    def test_licences_with_a_copyright_line_keep_the_component_copy(self):
        self.assertTrue(files.needs_own_copy("MIT"))
        self.assertTrue(files.needs_own_copy("Apache-2.0 OR MIT"))
        self.assertTrue(files.needs_own_copy("BSD-3-Clause"))
        self.assertTrue(files.needs_own_copy("LicenseRef-NVIDIA-Proprietary"))
        self.assertFalse(files.needs_own_copy("Apache-2.0"))
        self.assertFalse(files.needs_own_copy("LGPL-3.0-or-later"))

    def test_a_generic_apache_text_is_not_copied_but_a_combined_file_is(self):
        apache = b"Apache License\nVersion 2.0, January 2004\nTERMS AND CONDITIONS"
        self.assertTrue(files.generic_licence(apache))
        self.assertFalse(files.generic_licence(apache + b"\nPermission is hereby granted, free of charge"))
        self.assertFalse(files.generic_licence(b"Copyright (c) 2024 Someone\nPermission is hereby granted"))

    def test_an_expression_is_valid_only_with_known_ids(self):
        ids = ({"MIT", "Apache-2.0", "GPL-3.0-or-later"}, {"GCC-exception-3.1"})
        self.assertTrue(files.valid_expression("MIT OR Apache-2.0", *ids))
        self.assertTrue(files.valid_expression("GPL-3.0-or-later WITH GCC-exception-3.1", *ids))
        self.assertTrue(files.valid_expression("LicenseRef-NVIDIA-Proprietary", *ids))
        self.assertFalse(files.valid_expression("MIT License", *ids))
        self.assertFalse(files.valid_expression("BSD", *ids))

    def test_file_names_are_safe_and_distinct(self):
        self.assertEqual(files.safe_name("@img/sharp-libvips-linuxmusl-x64"), "img+sharp-libvips-linuxmusl-x64")
        named = files.target_names("crate-1.0", [("crate-1.0/LICENSE-MIT", b"a"), ("crate-1.0/LICENSE-APACHE", b"b")])
        self.assertEqual([name for name, _ in named], ["crate-1.0.LICENSE-MIT.txt", "crate-1.0.LICENSE-APACHE.txt"])
        self.assertEqual(files.target_names("pkg-2", [("pkg-2/LICENSE", b"a")]), [("pkg-2.txt", b"a")])

    def test_identical_files_are_kept_once(self):
        kept = files.distinct({"a/LICENSE": b"same\r\n", "a/sub/LICENSE": b"same\n", "a/COPYING": b"other"})
        self.assertEqual([source for source, _ in kept], ["a/COPYING", "a/LICENSE"])

    def test_a_licence_page_becomes_plain_text(self):
        page = b"<!DOCTYPE html><html><head><style>x{}</style></head><body><p>Terms &amp; conditions</p></body></html>"
        self.assertEqual(files.text_of(page), b"Terms & conditions\n")
        self.assertEqual(files.text_of(b"plain text"), b"plain text")


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

    def test_every_entry_names_its_licence_text(self):
        text = (REPO / "THIRD_PARTY_NOTICES").read_text(encoding="utf-8")
        self.assertIn("NOTICE: NOTICES/python/fastembed-0.8.1", text)
        self.assertIn("NOTICE: NOTICES/python/onnxruntime-1.30.0", text)
        entries = text.count("\n- ")
        self.assertEqual(text.count("  Licence text ("), entries)

    def test_a_missing_licence_text_or_notice_fails_the_check(self):
        records = json.loads(notices.FILES_DATA.read_text(encoding="utf-8"))
        components = notices.read_components()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patched = {"REPO": root, "LICENSES_DIR": root / "LICENSES",
                       "COMPONENT_LICENCES": root / "LICENSES" / "components", "NOTICES_DIR": root / "NOTICES"}
            saved = {name: getattr(notices, name) for name in patched}
            try:
                for name, value in patched.items():
                    setattr(notices, name, value)
                report = notices.Report()
                notices.check_licence_files(components, records, report)
            finally:
                for name, value in saved.items():
                    setattr(notices, name, value)
        problems = "\n".join(report.stale)
        self.assertIn("LICENSES/MIT.txt is missing", problems)
        self.assertIn("NOTICES/python/fastembed-0.8.1", problems)


if __name__ == "__main__":
    unittest.main()
