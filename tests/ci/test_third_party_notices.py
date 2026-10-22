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
system = notices.system_packages

fetch_spec = importlib.util.spec_from_file_location("fetch_gpl_sources", SCRIPT.with_name("fetch-gpl-sources.py"))
fetch = importlib.util.module_from_spec(fetch_spec)
fetch_spec.loader.exec_module(fetch)

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
        components = text.split("\n7. Source code of GPL and LGPL components")[0]
        self.assertEqual(components.count("  Licence text ("), components.count("\n- "))

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


DEP5_HEADER = "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n"


class SystemPackages(unittest.TestCase):
    def test_the_gpl_files_of_a_machine_readable_copyright_are_listed(self):
        text = DEP5_HEADER + ("Files: *\nLicense: GPL-2+\n\nFiles: lib/*\nLicense: LGPL-2.1+ and MIT\n\n"
                              "Files: debian/*\nLicense: GPL-3+\n")
        self.assertEqual(system.debian_licences(text), ["GPL-2+", "LGPL-2.1+"])

    def test_packaging_files_and_permissive_choices_are_left_out(self):
        text = DEP5_HEADER + ("Files: *\nLicense: BSD-3-clause\n\nFiles: debian/*\nLicense: GPL-2+\n\n"
                              "Files: lib/cap_text.c\nLicense: BSD-3-clause or GPL-2\n")
        self.assertEqual(system.debian_licences(text), [])

    def test_build_files_under_an_exception_are_left_out_but_not_the_main_licence(self):
        build = DEP5_HEADER + "Files: *\nLicense: MIT\n\nFiles: m4/libtool.m4\nLicense: GPL-2+ with Libtool exception\n"
        runtime = DEP5_HEADER + "Files: *\nLicense: GPL-3+ with GCC-exception-3.1\n"
        self.assertEqual(system.debian_licences(build), [])
        self.assertEqual(system.debian_licences(runtime), ["GPL-3+ with GCC-exception-3.1"])

    def test_a_free_text_copyright_is_classified_by_its_words(self):
        lgpl = "It is distributed under the GNU Lesser General Public License, version 2.1 or later."
        self.assertEqual(system.debian_licences(lgpl), ["LGPL"])
        self.assertEqual(system.debian_licences("Permission is hereby granted, free of charge"), [])

    def test_alpine_expressions_are_split_and_choices_left_out(self):
        self.assertEqual(system.alpine_licences("MIT AND BSD-2-Clause AND GPL-2.0-or-later"), ["GPL-2.0-or-later"])
        self.assertEqual(system.alpine_licences("Apache-2.0 OR GPL-2.0-only"), [])
        self.assertEqual(system.alpine_licences("MIT"), [])

    def test_licence_names_map_to_the_spdx_texts(self):
        names = ["GPL-2+", "LGPL-2.1+-with-link-exception", "GPL-3+ with Bison exception", "GPL-2", "LGPL-3.0+",
                 "GPL-2.0-only", "GPL", "SMAIL-GPL"]
        self.assertEqual(system.spdx_texts(names), ["GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-or-later",
                                                    "LGPL-2.1-or-later", "LGPL-3.0-or-later"])

    def test_the_final_stage_of_a_dockerfile_gives_the_recipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            dockerfile = Path(tmp) / "Dockerfile"
            dockerfile.write_text(
                "FROM python:3.11.17-slim AS builder\nRUN apt-get install -y build-essential\n\n"
                "FROM python:3.11.17-slim\n# runtime\nRUN apt-get update && apt-get install -y \\\n"
                "    --no-install-recommends \\\n    # PDF\n    poppler-utils \\\n\n    tesseract-ocr \\\n"
                "    && rm -rf /var/lib/apt/lists/*\nRUN chmod +x entrypoint.sh\n", encoding="utf-8")
            self.assertEqual(system.recipe(dockerfile),
                             {"from": "python:3.11.17-slim", "installs": ["poppler-utils", "tesseract-ocr"]})

    @needs_yaml
    def test_a_changed_final_stage_makes_the_list_stale(self):
        data = json.loads(notices.SYSTEM_DATA.read_text(encoding="utf-8"))
        data["images"]["knowledge-store"]["recipe"]["installs"] = ["poppler-utils"]
        del data["images"]["web-client"]
        report = notices.Report()
        notices.check_system(data, report)
        problems = "\n".join(report.stale)
        self.assertIn("knowledge-store: the final stage of its Dockerfile changed", problems)
        self.assertIn("has no web-client image", problems)

    def test_the_committed_list_matches_the_dockerfiles(self):
        report = notices.Report()
        notices.check_system(notices.system_data(), report)
        self.assertEqual(report.stale, [])

    def test_the_offer_uses_the_contact_addresses_of_the_licence(self):
        self.assertEqual(notices.offer_addresses(notices.Report()),
                         ["loup.marquez@epitech.eu", "noah.gibelli@epitech.eu", "matheus.lopez@epitech.eu"])

    def test_the_committed_notices_carry_the_written_offer(self):
        text = (REPO / "THIRD_PARTY_NOTICES").read_text(encoding="utf-8")
        offer = text.split("\n7. Source code of GPL and LGPL components\n")[1]
        flat = " ".join(offer.split())
        for expected in ("For three years from our last distribution", "no more than our cost of sending it",
                         "https://snapshot.debian.org/", "scripts/licences/fetch-gpl-sources.py",
                         "loup.marquez@epitech.eu, noah.gibelli@epitech.eu and matheus.lopez@epitech.eu",
                         "- poppler-utils ", "- busybox ", "- psycopg2-binary ", "- @img/sharp-libvips-linuxmusl-x64 ",
                         "https://pypi.org/project/psycopg2-binary/"):
            self.assertIn(expected, flat)
        for identifier in ("GPL-2.0-only", "GPL-3.0-or-later", "LGPL-2.1-or-later"):
            self.assertTrue((notices.LICENSES_DIR / f"{identifier}.txt").is_file(), identifier)


class FetchGplSources(unittest.TestCase):
    def test_debian_files_come_from_the_main_archives(self):
        listing = {"fileinfo": {
            "aa11": [{"archive_name": "debian-debug", "name": "x.dsc", "size": 1},
                     {"archive_name": "debian", "name": "bash_5.2.37-2.dsc", "size": 2162}],
            "bb22": [{"archive_name": "debian-security", "name": "bash_5.2.37.orig.tar.xz", "size": 5600932}],
        }}
        self.assertEqual(fetch.choose_debian_files(listing), [
            {"name": "bash_5.2.37-2.dsc", "size": 2162, "sha1": "aa11", "url": "https://snapshot.debian.org/file/aa11"},
            {"name": "bash_5.2.37.orig.tar.xz", "size": 5600932, "sha1": "bb22",
             "url": "https://snapshot.debian.org/file/bb22"},
        ])

    def test_remote_alpine_sources_keep_their_sha512_and_local_patches_stay_in_aports(self):
        out = ("busybox-1.37.0.tar.bz2::https://busybox.net/downloads/busybox-1.37.0.tar.bz2\n"
               "https://example.org/extra-1.0.tar.gz\nfix-mount.patch\n--\n"
               "aaa  busybox-1.37.0.tar.bz2\nbbb  extra-1.0.tar.gz\nccc  fix-mount.patch\n")
        self.assertEqual(fetch.parse_apkbuild_sources(out), [
            {"name": "busybox-1.37.0.tar.bz2", "url": "https://busybox.net/downloads/busybox-1.37.0.tar.bz2",
             "sha512": "aaa"},
            {"name": "extra-1.0.tar.gz", "url": "https://example.org/extra-1.0.tar.gz", "sha512": "bbb"},
            {"name": "fix-mount.patch", "path": "fix-mount.patch", "sha512": "ccc"},
        ])

    def test_alpine_recipe_falls_back_to_the_github_mirror(self):
        original = fetch.fetch
        urls = []

        def get(url, **kwargs):
            urls.append(url)
            if "gitlab.alpinelinux.org" in url:
                raise fetch.urllib.error.HTTPError(url, 404, "not found", None, None)
            return b"pkgname=busybox\n"

        fetch.fetch = get
        try:
            repository, apkbuild = fetch.alpine_recipe("busybox", "a" * 40)
        finally:
            fetch.fetch = original

        self.assertEqual(repository, "main")
        self.assertEqual(apkbuild, b"pkgname=busybox\n")
        self.assertIn("https://raw.githubusercontent.com/alpinelinux/aports/" + "a" * 40
                      + "/main/busybox/APKBUILD", urls)

    def test_alpine_recipe_falls_back_when_gitlab_is_unreachable(self):
        original = fetch.fetch
        urls = []

        def get(url, **kwargs):
            urls.append(url)
            if "gitlab.alpinelinux.org" in url:
                raise OSError("Network is unreachable")
            return b"pkgname=busybox\n"

        fetch.fetch = get
        try:
            repository, apkbuild = fetch.alpine_recipe("busybox", "a" * 40)
        finally:
            fetch.fetch = original

        self.assertEqual(repository, "main")
        self.assertEqual(apkbuild, b"pkgname=busybox\n")
        self.assertIn("https://raw.githubusercontent.com/alpinelinux/aports/" + "a" * 40
                      + "/main/busybox/APKBUILD", urls)

    def test_alpine_recipe_uses_a_bounded_request_for_each_mirror(self):
        original = fetch.fetch
        requests = []

        def get(url, **kwargs):
            requests.append((url, kwargs))
            if "gitlab.alpinelinux.org" in url:
                raise OSError("timed out")
            return b"pkgname=busybox\n"

        fetch.fetch = get
        try:
            repository, _ = fetch.alpine_recipe("busybox", "a" * 40)
        finally:
            fetch.fetch = original

        self.assertEqual(repository, "main")
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(kwargs == {"attempts": 1, "timeout": 30} for _, kwargs in requests))


if __name__ == "__main__":
    unittest.main()
