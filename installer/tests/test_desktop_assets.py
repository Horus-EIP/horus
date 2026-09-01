from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
DESKTOP = REPO / "desktop"
TAURI = DESKTOP / "src-tauri"
UI = DESKTOP / "ui"

HAS_DESKTOP = TAURI.is_dir()
skip_without_desktop = unittest.skipUnless(HAS_DESKTOP, "desktop/ is not present")

def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def rust_sources() -> str:
    return "\n".join(read(p) for p in sorted((TAURI / "src").glob("*.rs")))

@skip_without_desktop
class Layout(unittest.TestCase):
    def test_every_file_the_build_needs_is_present(self):
        for rel in (
            "src-tauri/Cargo.toml",
            "src-tauri/build.rs",
            "src-tauri/tauri.conf.json",
            "src-tauri/capabilities/default.json",
            "src-tauri/src/main.rs",
            "ui/index.html",
            "ui/app.js",
            "ui/styles.css",
            "package.json",
            "package-lock.json",
        ):
            with self.subTest(rel):
                self.assertTrue((DESKTOP / rel).is_file(), f"missing {rel}")

    def test_every_declared_module_exists(self):
        main = read(TAURI / "src" / "main.rs")
        for name in re.findall(r"^mod\s+([a-z_]+);", main, re.MULTILINE):
            with self.subTest(name):
                self.assertTrue(
                    (TAURI / "src" / f"{name}.rs").is_file(),
                    f"main.rs declares `mod {name};` but src/{name}.rs is missing",
                )

    def test_no_module_is_orphaned(self):
        main = read(TAURI / "src" / "main.rs")
        declared = set(re.findall(r"^mod\s+([a-z_]+);", main, re.MULTILINE))
        on_disk = {p.stem for p in (TAURI / "src").glob("*.rs")} - {"main"}
        self.assertEqual(
            on_disk - declared,
            set(),
            "these .rs files are never compiled because main.rs does not "
            "declare them",
        )

@skip_without_desktop
class TauriConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads(read(TAURI / "tauri.conf.json"))

    def test_identity_fields_are_set(self):
        self.assertEqual(self.config["productName"], "Horus")
        self.assertTrue(self.config["identifier"])
        self.assertTrue(self.config["version"])

    def test_frontend_dist_points_at_the_ui(self):
        dist = self.config["build"]["frontendDist"]
        resolved = (TAURI / dist).resolve()
        self.assertTrue(resolved.is_dir(), f"frontendDist {dist} is not a directory")
        self.assertTrue((resolved / "index.html").is_file())

    def test_no_before_build_command(self):
        self.assertNotIn("beforeBuildCommand", self.config.get("build", {}))

    def test_every_icon_exists_and_is_not_empty(self):
        for rel in self.config["bundle"]["icon"]:
            with self.subTest(rel):
                icon = TAURI / rel
                self.assertTrue(icon.is_file(), f"tauri.conf.json names {rel}")
                self.assertGreater(icon.stat().st_size, 0)

    def test_windows_and_macos_icons_are_the_right_formats(self):
        ico = (TAURI / "icons" / "icon.ico").read_bytes()
        self.assertEqual(ico[:4], b"\x00\x00\x01\x00", "icon.ico is not an ICO")
        icns = (TAURI / "icons" / "icon.icns").read_bytes()
        self.assertEqual(icns[:4], b"icns", "icon.icns is not an ICNS")

    def test_declared_icns_length_matches_the_file(self):
        icns = (TAURI / "icons" / "icon.icns").read_bytes()
        declared = int.from_bytes(icns[4:8], "big")
        self.assertEqual(declared, len(icns))

    def test_version_agrees_across_the_three_files(self):
        cargo = read(TAURI / "Cargo.toml")
        cargo_version = re.search(r'^version\s*=\s*"([^"]+)"', cargo, re.MULTILINE)
        self.assertIsNotNone(cargo_version)
        package = json.loads(read(DESKTOP / "package.json"))
        self.assertEqual(self.config["version"], cargo_version.group(1))
        self.assertEqual(self.config["version"], package["version"])

@skip_without_desktop
class Capabilities(unittest.TestCase):
    def setUp(self) -> None:
        self.capability = json.loads(read(TAURI / "capabilities" / "default.json"))

    def test_scoped_to_the_status_window_only(self):
        self.assertEqual(self.capability.get("windows"), ["status"])

    def test_no_remote_urls_are_granted(self):
        self.assertNotIn("remote", self.capability)

@skip_without_desktop
class IpcContract(unittest.TestCase):

    def setUp(self) -> None:
        self.app_js = read(UI / "app.js")
        self.rust = rust_sources()

    def registered_commands(self) -> set[str]:
        block = re.search(
            r"generate_handler!\[(.*?)\]", self.rust, re.DOTALL
        )
        self.assertIsNotNone(block, "no generate_handler! in the Rust sources")
        return {
            name.strip()
            for name in block.group(1).replace("\n", " ").split(",")
            if name.strip()
        }

    def invoked_commands(self) -> set[str]:
        return set(re.findall(r'\b(?:invoke|run)\(\s*"([a-z_]+)"', self.app_js))

    def test_every_invoked_command_is_registered(self):
        missing = self.invoked_commands() - self.registered_commands()
        self.assertEqual(
            missing, set(),
            "app.js calls these, and they are not in generate_handler!: "
            "the button does nothing and the error only appears in a console "
            "the tester cannot open",
        )

    def test_every_registered_command_is_defined(self):
        for name in self.registered_commands():
            with self.subTest(name):
                self.assertRegex(
                    self.rust,
                    rf"#\[tauri::command\][^#]*?fn {re.escape(name)}\b",
                    f"{name} is registered but has no #[tauri::command] fn",
                )

    def test_no_command_is_registered_and_never_used(self):
        unused = self.registered_commands() - self.invoked_commands()
        self.assertEqual(unused, set(), "registered but never invoked")

    def test_the_event_channel_name_matches(self):
        channel = re.search(r'EVENT_CHANNEL:\s*&str\s*=\s*"([^"]+)"', self.rust)
        self.assertIsNotNone(channel)
        self.assertIn(f'listen("{channel.group(1)}"', self.app_js)

    def test_the_event_prefix_matches_the_installer(self):
        prefix = re.search(r'EVENT_PREFIX:\s*&str\s*=\s*"([^"]+)"', self.rust)
        self.assertIsNotNone(prefix)
        self.assertEqual(prefix.group(1), common.EVENT_PREFIX)

@skip_without_desktop
class UiWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.html = read(UI / "index.html")
        self.app_js = read(UI / "app.js")

    def test_every_referenced_element_id_exists(self):
        html_ids = set(re.findall(r'id="([a-z0-9-]+)"', self.html))
        used = set(re.findall(r'getElementById\("([a-z0-9-]+)"\)', self.app_js))
        used |= set(re.findall(r'\bon\("([a-z0-9-]+)"', self.app_js))
        self.assertEqual(used - html_ids, set(), "referenced but not in the HTML")

    def test_every_view_shown_exists_in_the_html(self):
        views = set(re.findall(r'data-view="([a-z-]+)"', self.html))
        shown = set(re.findall(r'show\("([a-z-]+)"\)', self.app_js))
        shown |= set(re.findall(r'"view":\s*"([a-z-]+)"', rust_sources()))
        self.assertEqual(
            shown - views, set(),
            "show() names a view with no matching section, which renders a "
            "blank window",
        )

    def test_every_view_in_the_html_is_reachable(self):
        views = set(re.findall(r'data-view="([a-z-]+)"', self.html))
        self.assertEqual(views - self.reachable_views(), set(),
                         "dead view sections in the HTML")

    def reachable_views(self) -> set:
        reachable = set(re.findall(r'show\("([a-z-]+)"\)', self.app_js))
        for name in ("EXIT_VIEWS", "PHASES"):
            table = re.search(rf"const {name} = \{{(.*?)\}};", self.app_js, re.DOTALL)
            if table:
                reachable |= set(re.findall(r'"([a-z-]+)"\s*\]?,?\s*$',
                                            table.group(1), re.MULTILINE))
                reachable |= set(re.findall(r':\s*"([a-z-]+)"', table.group(1)))
        return reachable

    def test_stylesheet_and_script_are_the_files_that_exist(self):
        for rel in re.findall(r'(?:href|src)="([^"]+)"', self.html):
            if rel.startswith("http"):
                continue
            with self.subTest(rel):
                self.assertTrue((UI / rel).is_file(), f"index.html references {rel}")

    def test_no_external_resources(self):
        self.assertNotIn("http://", self.html.replace("http://localhost", ""))
        self.assertNotIn("https://fonts.", self.html)

@skip_without_desktop
class ExitCodeMapping(unittest.TestCase):

    def setUp(self) -> None:
        self.app_js = read(UI / "app.js")

    def mapping(self) -> dict:
        block = re.search(r"const EXIT_VIEWS = \{(.*?)\};", self.app_js, re.DOTALL)
        self.assertIsNotNone(block)
        return {
            int(code): view
            for code, view in re.findall(r'(\d+):\s*"([a-z-]+)"', block.group(1))
        }

    def test_codes_match_the_installer(self):
        expected = {
            common.EXIT_DOCKER_NOT_FOUND: "docker-down",
            common.EXIT_DOCKER_DAEMON_DOWN: "docker-down",
            common.EXIT_REPO_NOT_FOUND: "not-found",
            common.EXIT_NOT_INSTALLED: "not-installed",
        }
        self.assertEqual(self.mapping(), expected)

@skip_without_desktop
class IconMaster(unittest.TestCase):

    def test_icon_source_is_reproducible(self):
        tool = DESKTOP / "tools" / "make_icon_source.py"
        committed = DESKTOP / "icon-source.png"
        self.assertTrue(tool.is_file())
        self.assertTrue(committed.is_file())

        with tempfile.TemporaryDirectory() as name:
            out = Path(name) / "regenerated.png"
            result = subprocess.run(
                [sys.executable, str(tool), "--out", str(out)],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                out.read_bytes(), committed.read_bytes(),
                "desktop/icon-source.png is not what make_icon_source.py "
                "produces from the current logo.png. Re-run the tool and "
                "regenerate the icon set.",
            )

@skip_without_desktop
class ReleaseWorkflow(unittest.TestCase):

    def setUp(self) -> None:
        workflow = REPO / ".github" / "workflows" / "desktop-release.yml"
        if not workflow.is_file():
            self.skipTest("desktop-release.yml is not present")
        self.text = read(workflow)
        self.scripts = json.loads(read(DESKTOP / "package.json"))["scripts"]

    def test_every_npm_script_it_runs_is_defined(self):
        for name in re.findall(r"npm run ([a-z:]+)", self.text):
            with self.subTest(name):
                self.assertIn(name, self.scripts)

    def test_it_builds_all_three_platforms(self):
        for os_name in ("windows-latest", "macos-latest", "ubuntu-22.04"):
            self.assertIn(os_name, self.text)

    def test_no_appimage_is_built(self):
        commands = [
            line for line in self.text.splitlines()
            if not line.lstrip().startswith("#")
        ]
        offenders = [line for line in commands if "appimage" in line.lower()]
        self.assertEqual(offenders, [], "an AppImage target crept back in")

    def test_the_bundler_is_called_with_an_app_dir(self):
        self.assertIn("build_bundle.py --out dist --app-dir app", self.text)

if __name__ == "__main__":
    unittest.main()
