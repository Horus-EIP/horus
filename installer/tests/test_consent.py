from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import consent  # noqa: E402
from common import EXIT_CONSENT_CANCELLED, EXIT_USAGE, InstallError, Log  # noqa: E402

POSIX_REJECTED = [
    "/", "/etc", "/usr", "/bin", "/sbin", "/lib", "/var", "/boot", "/dev",
    "/proc", "/sys", "/System", "/Library", "/Applications", "/private",
    "/opt/homebrew",
]
WINDOWS_REJECTED = [
    "C:\\", "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
    "C:\\ProgramData", "C:\\Users",
]

POSIX_MOUNT_EQUIVALENT_REJECTED = ["/run", "/srv", "/snap", "/home", "/Users"]

WINDOWS_PREFIXED_REJECTED = [
    "\\\\?\\C:\\Windows",
    "\\\\?\\C:\\Users",
    "\\\\?\\C:\\Program Files",
    "\\\\?\\C:\\Windows\\System32",
    "\\\\.\\C:\\Windows",
]

WINDOWS_UNC_REJECTED = [
    "\\\\localhost\\C$\\Windows",
    "\\\\127.0.0.1\\C$\\Windows",
]

IS_WINDOWS = os.name == "nt"

class Script:

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.calls = 0

    def __call__(self, prompt: str = "") -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError("script exhausted")
        return self.answers.pop(0)

class ConsentTestCase(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        (self.repo / "demo_assets").mkdir(parents=True)
        self.log = Log(self.tmp / "install-log.txt")

    def tearDown(self) -> None:
        self.log.close(0)
        self._tmp.cleanup()

    def choose(self, *answers: str, **kwargs):
        script = kwargs.pop("script", None) or Script(*answers)
        kwargs.setdefault("interactive", True)
        kwargs.setdefault("input_fn", script)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = consent.choose(self.log, self.repo, **kwargs)
        return result, script, buf.getvalue()

    def choose_expecting(self, exc, *answers: str, **kwargs):
        buf = io.StringIO()
        script = Script(*answers)
        kwargs.setdefault("interactive", True)
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(exc) as caught:
                consent.choose(self.log, self.repo, input_fn=script, **kwargs)
        return caught.exception

class TestSystemPathsRejected(ConsentTestCase):

    @unittest.skipIf(IS_WINDOWS, "POSIX system paths")
    def test_every_posix_system_path_is_rejected(self):
        for raw in POSIX_REJECTED:
            with self.subTest(path=raw):
                reason = consent.system_location_reason(Path(raw).resolve())
                self.assertIsNotNone(reason, f"{raw} was NOT rejected")
                self.assertTrue(reason.strip())

    @unittest.skipUnless(IS_WINDOWS, "Windows system paths")
    def test_every_windows_system_path_is_rejected(self):
        for raw in WINDOWS_REJECTED:
            with self.subTest(path=raw):
                reason = consent.system_location_reason(Path(raw).resolve())
                self.assertIsNotNone(reason, f"{raw} was NOT rejected")
                self.assertTrue(reason.strip())

    @unittest.skipUnless(IS_WINDOWS, "Windows system paths")
    def test_the_reason_names_the_path_itself_not_a_child_of_it(self):
        reason = consent.system_location_reason(Path(r"C:\Users").resolve())
        self.assertIn(r"C:\Users is a system location", reason)

    @unittest.skipUnless(IS_WINDOWS, "Windows system paths")
    def test_windows_system_paths_are_rejected_case_insensitively(self):
        for raw in WINDOWS_REJECTED:
            with self.subTest(path=raw):
                self.assertIsNotNone(consent.system_location_reason(Path(raw.lower()).resolve()))

    def test_validate_folder_rejects_the_system_paths_that_exist(self):
        checked = 0
        for raw in (WINDOWS_REJECTED if IS_WINDOWS else POSIX_REJECTED):
            if not Path(raw).is_dir():
                continue
            checked += 1
            with self.subTest(path=raw):
                with self.assertRaises(consent.PathRejected):
                    consent.validate_folder(raw)
        self.assertGreater(checked, 0, "no system path existed to test against")

    def test_a_parent_of_a_system_location_is_rejected(self):
        target = "C:\\" if IS_WINDOWS else "/opt"
        self.assertIsNotNone(consent.system_location_reason(Path(target).resolve()))

    def test_child_of_a_system_location_is_rejected(self):
        child = Path("C:\\Windows\\System32") if IS_WINDOWS else Path("/etc/ssh")
        self.assertIsNotNone(consent.system_location_reason(child.resolve()))

    def test_drive_or_filesystem_root_is_rejected(self):
        root = Path(Path.home().anchor)
        reason = consent.system_location_reason(root.resolve())
        self.assertIsNotNone(reason)

    def test_rule_shapes_against_a_synthetic_table(self):
        base = self.tmp / "fake"
        tree_root = base / "system"
        self_root = base / "home"
        (tree_root / "deep").mkdir(parents=True)
        (self_root / "docs").mkdir(parents=True)

        def fake_table():
            return [(tree_root, consent.TREE), (self_root, consent.SELF)]

        real_table, real_home = consent.forbidden_roots, consent._home
        consent.forbidden_roots = fake_table
        consent._home = lambda: self_root
        try:
            self.assertIsNotNone(consent.system_location_reason(tree_root))
            self.assertIsNotNone(consent.system_location_reason(tree_root / "deep"))
            self.assertIsNotNone(consent.system_location_reason(base))
            self.assertIsNotNone(consent.system_location_reason(self_root))
            self.assertIsNone(consent.system_location_reason(self_root / "docs"))
        finally:
            consent.forbidden_roots = real_table
            consent._home = real_home

class TestSymlinkResolution(ConsentTestCase):

    def setUp(self) -> None:
        super().setUp()
        self._links: list[Path] = []

    def tearDown(self) -> None:
        for link in self._links:
            try:
                os.rmdir(link)
            except OSError:
                try:
                    os.unlink(link)
                except OSError:
                    pass
        super().tearDown()

    def _symlink(self, link: Path, target: Path) -> None:
        try:
            os.symlink(str(target), str(link), target_is_directory=True)
            self._links.append(link)
            return
        except (OSError, NotImplementedError, AttributeError) as exc:
            first_error = exc

        if IS_WINDOWS:
            rc = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True, text=True,
            )
            if rc.returncode == 0 and link.exists():
                self._links.append(link)
                return
            first_error = RuntimeError(f"{first_error}; mklink /J: {rc.stderr.strip()}")
        self.skipTest(f"cannot create links here: {first_error}")

    def test_symlink_into_a_system_location_is_rejected_after_resolution(self):
        target = Path("C:\\Windows") if IS_WINDOWS else Path("/etc")
        if not target.is_dir():
            self.skipTest(f"{target} does not exist on this host")
        link = self.tmp / "innocent-looking-docs"
        self._symlink(link, target)

        self.assertNotEqual(link.resolve(), link)
        with self.assertRaises(consent.PathRejected) as caught:
            consent.validate_folder(str(link))
        self.assertIn("system location", caught.exception.reason)

    def test_symlink_to_a_harmless_folder_is_accepted_and_resolved(self):
        real = self.tmp / "real-docs"
        real.mkdir()
        (real / "note.md").write_text("hello", encoding="utf-8")
        link = self.tmp / "link-to-docs"
        self._symlink(link, real)

        got = consent.validate_folder(str(link))
        self.assertEqual(got, real.resolve())

class TestHomeDirectory(ConsentTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.home = Path.home().resolve()
        self.sub = Path(tempfile.mkdtemp(prefix="horus-consent-test-", dir=str(self.home)))
        (self.sub / "doc.md").write_text("x", encoding="utf-8")

    def tearDown(self) -> None:
        for child in self.sub.iterdir():
            child.unlink()
        self.sub.rmdir()
        super().tearDown()

    def test_home_itself_is_rejected(self):
        with self.assertRaises(consent.PathRejected) as caught:
            consent.validate_folder(str(self.home))
        self.assertIn("home directory", caught.exception.reason)

    def test_home_via_tilde_is_rejected(self):
        with self.assertRaises(consent.PathRejected):
            consent.validate_folder("~")

    def test_a_subdirectory_of_home_is_accepted(self):
        got = consent.validate_folder(str(self.sub))
        self.assertEqual(got, self.sub.resolve())
        self.assertIsNone(consent.system_location_reason(self.sub.resolve()))

    @unittest.skipUnless(IS_WINDOWS, "the C:\\Users carve-out is Windows-specific")
    def test_users_tree_is_rejected_even_though_home_lives_in_it(self):
        self.assertIsNotNone(consent.system_location_reason(self.home.parent))
        self.assertIsNone(consent.system_location_reason(self.sub.resolve()))

class TestValidateFolder(ConsentTestCase):

    def test_relative_path_is_rejected(self):
        with self.assertRaises(consent.PathRejected) as caught:
            consent.validate_folder("documents")
        self.assertIn("absolute", caught.exception.reason)

    def test_missing_path_is_rejected(self):
        with self.assertRaises(consent.PathRejected) as caught:
            consent.validate_folder(str(self.tmp / "nope" / "nowhere"))
        self.assertIn("nothing at that path", caught.exception.reason)

    def test_a_file_is_rejected(self):
        target = self.tmp / "report.md"
        target.write_text("x", encoding="utf-8")
        with self.assertRaises(consent.PathRejected) as caught:
            consent.validate_folder(str(target))
        self.assertIn("file, not a folder", caught.exception.reason)

    def test_empty_input_is_rejected(self):
        with self.assertRaises(consent.PathRejected):
            consent.validate_folder("   ")

    def test_quoted_paths_from_explorer_are_accepted(self):
        folder = self.tmp / "my docs"
        folder.mkdir()
        self.assertEqual(consent.validate_folder(f'"{folder}"'), folder.resolve())

    def test_duplicate_and_nested_paths_are_rejected(self):
        outer = self.tmp / "outer"
        inner = outer / "inner"
        inner.mkdir(parents=True)
        accepted: list[Path] = []

        consent.add_folder(accepted, outer.resolve())
        with self.assertRaises(consent.PathRejected):
            consent.add_folder(accepted, outer.resolve())
        with self.assertRaises(consent.PathRejected):
            consent.add_folder(accepted, inner.resolve())
        self.assertEqual(accepted, [outer.resolve()])

        accepted = [inner.resolve()]
        with self.assertRaises(consent.PathRejected):
            consent.add_folder(accepted, outer.resolve())

class TestWholeDevicePhrase(ConsentTestCase):

    NEAR_MISSES = [
        "i accept full disk access",
        "I Accept Full Disk Access",
        "I ACCEPT FULL DISK ACCESS.",
        "yes I ACCEPT FULL DISK ACCESS",
        "I ACCEPT FULL DISK ACCESS please",
        "I ACCEPT FULL DISK ACCES",
        "I  ACCEPT  FULL  DISK  ACCESS",
        "y",
        "yes",
        "",
    ]

    def test_near_misses_do_not_grant_whole_device(self):
        for attempt in self.NEAR_MISSES:
            with self.subTest(typed=attempt):
                result, _, _ = self.choose("3", attempt, "1")
                self.assertEqual(result["mode"], consent.CONSENT_DEMO)

    def test_exact_phrase_grants_whole_device(self):
        result, _, _ = self.choose("3", consent.WHOLE_DEVICE_PHRASE)
        self.assertEqual(result["mode"], consent.CONSENT_WHOLE_DEVICE)
        self.assertEqual(result["corpus_dir"], consent.to_compose_path(consent.whole_device_root()))

    def test_surrounding_whitespace_only_is_forgiven(self):
        result, _, _ = self.choose("3", f"  {consent.WHOLE_DEVICE_PHRASE}\t")
        self.assertEqual(result["mode"], consent.CONSENT_WHOLE_DEVICE)

    def test_the_warning_names_what_is_exposed(self):
        _, _, printed = self.choose("3", "no", "1")
        for phrase in ("SSH private key", "browser profile", "password", "tax",
                       "medical", "index", "quote it back"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), printed.lower())

    def test_preselect_whole_device_still_requires_the_phrase(self):
        result, script, _ = self.choose("", "nope", "1", preselect=consent.CONSENT_WHOLE_DEVICE)
        self.assertEqual(result["mode"], consent.CONSENT_DEMO)
        self.assertTrue(any("phrase" in p for p in script.prompts))

class TestNonInteractive(ConsentTestCase):

    def test_non_interactive_cannot_reach_whole_device(self):
        for preselect in (None, consent.CONSENT_DEMO, consent.CONSENT_FOLDERS,
                          consent.CONSENT_WHOLE_DEVICE):
            with self.subTest(preselect=preselect):
                script = Script(consent.WHOLE_DEVICE_PHRASE, "3", "y")
                result, _, _ = self.choose(
                    script=script, non_interactive=True, preselect=preselect, interactive=True
                )
                self.assertEqual(result["mode"], consent.CONSENT_DEMO)
                self.assertEqual(result["corpus_dir"], consent.DEMO_CORPUS_DIR)
                self.assertEqual(script.calls, 0, "a non-interactive run must not prompt")

    def test_closed_stdin_falls_back_to_demo(self):
        script = Script(consent.WHOLE_DEVICE_PHRASE)
        result, _, _ = self.choose(
            script=script, interactive=False, preselect=consent.CONSENT_WHOLE_DEVICE
        )
        self.assertEqual(result["mode"], consent.CONSENT_DEMO)
        self.assertEqual(script.calls, 0)

    def test_eof_at_the_menu_cancels_the_install(self):
        exc = self.choose_expecting(InstallError)
        self.assertEqual(exc.code, EXIT_CONSENT_CANCELLED)

    def test_typing_q_cancels_the_install(self):
        exc = self.choose_expecting(InstallError, "q")
        self.assertEqual(exc.code, EXIT_CONSENT_CANCELLED)

    def test_unknown_preselect_is_a_usage_error(self):
        exc = self.choose_expecting(InstallError, "1", preselect="everything")
        self.assertEqual(exc.code, EXIT_USAGE)

class TestChoiceShape(ConsentTestCase):

    def test_demo_is_the_default_answer(self):
        result, _, _ = self.choose("")
        self.assertEqual(result["mode"], consent.CONSENT_DEMO)
        self.assertEqual(result["corpus_dir"], "../../demo_assets")
        self.assertIn("accepted_at", result)
        self.assertIn("T", result["accepted_at"])

    def test_folder_choice_returns_a_forward_slash_absolute_path(self):
        folder = Path(tempfile.mkdtemp(prefix="horus-consent-", dir=str(Path.home())))
        try:
            result, _, _ = self.choose("2", str(folder), "")
            self.assertEqual(result["mode"], consent.CONSENT_FOLDERS)
            self.assertEqual(result["paths"], [str(folder.resolve())])
            self.assertNotIn("\\", result["corpus_dir"])
            self.assertEqual(result["corpus_dir"], str(folder.resolve()).replace("\\", "/"))
        finally:
            folder.rmdir()

    def test_a_bad_folder_reprompts_instead_of_failing(self):
        folder = Path(tempfile.mkdtemp(prefix="horus-consent-", dir=str(Path.home())))
        try:
            result, _, printed = self.choose("2", "relative/path", str(folder), "")
            self.assertEqual(result["paths"], [str(folder.resolve())])
            self.assertIn("absolute", printed)
        finally:
            folder.rmdir()

    def test_several_folders_narrow_to_one_mount(self):
        a = Path(tempfile.mkdtemp(prefix="horus-consent-a-", dir=str(Path.home())))
        b = Path(tempfile.mkdtemp(prefix="horus-consent-b-", dir=str(Path.home())))
        try:
            result, _, printed = self.choose("2", str(a), str(b), "", "2")
            self.assertEqual(result["paths"], [str(b.resolve())])
            self.assertIn("one folder per install", printed)
        finally:
            a.rmdir()
            b.rmdir()

    def test_describe_says_read_only_and_names_the_mount(self):
        text = consent.describe(consent.demo_choice(self.repo))
        self.assertIn("read-only", text)
        self.assertIn(consent.CONTAINER_CORPUS_PATH, text)
        self.assertIn(consent.HORUS_CORPUS_ENV_KEY, text)

class TestDevicePrefixesAndUNC(ConsentTestCase):

    @unittest.skipUnless(IS_WINDOWS, "NT device prefixes are Windows-only")
    def test_device_prefixed_system_paths_are_rejected(self):
        checked = 0
        for raw in WINDOWS_PREFIXED_REJECTED:
            plain = consent.strip_device_prefix(Path(raw))
            if not plain.is_dir():
                continue
            checked += 1
            with self.subTest(path=raw):
                with self.assertRaises(consent.PathRejected) as caught:
                    consent.validate_folder(raw)
                self.assertIn("system location", caught.exception.reason)
        self.assertGreater(checked, 0, "no prefixed system path existed to test")

    @unittest.skipUnless(IS_WINDOWS, "NT device prefixes are Windows-only")
    def test_device_prefixed_home_is_rejected(self):
        raw = "\\\\?\\" + str(Path.home().resolve())
        with self.assertRaises(consent.PathRejected) as caught:
            consent.validate_folder(raw)
        self.assertIn("home directory", caught.exception.reason)

    @unittest.skipUnless(IS_WINDOWS, "UNC spellings are Windows-only")
    def test_unc_admin_shares_are_rejected(self):
        for raw in WINDOWS_UNC_REJECTED:
            with self.subTest(path=raw):
                with self.assertRaises(consent.PathRejected) as caught:
                    consent.validate_folder(raw)
                self.assertIn("network", caught.exception.reason)

    @unittest.skipUnless(IS_WINDOWS, "NT device prefixes are Windows-only")
    def test_a_harmless_folder_keeps_working_when_prefixed(self):
        folder = Path(tempfile.mkdtemp(prefix="horus-consent-pfx-", dir=str(Path.home())))
        try:
            got = consent.validate_folder("\\\\?\\" + str(folder))
            self.assertEqual(got, folder.resolve())
        finally:
            folder.rmdir()

    @unittest.skipUnless(IS_WINDOWS, "NT device prefixes are Windows-only")
    def test_strip_device_prefix_rewrites_both_prefix_forms(self):
        cases = {
            "\\\\?\\C:\\Windows": "C:\\Windows",
            "\\\\.\\C:\\Windows": "C:\\Windows",
            "\\\\?\\UNC\\srv\\share": "\\\\srv\\share",
            "\\\\?\\unc\\srv\\share": "\\\\srv\\share",
            "C:\\Windows": "C:\\Windows",
            "\\\\srv\\share": "\\\\srv\\share",
        }
        for raw, want in cases.items():
            with self.subTest(path=raw):
                self.assertEqual(consent.strip_device_prefix(Path(raw)), Path(want))

    @unittest.skipIf(IS_WINDOWS, "a backslash is an ordinary character here")
    def test_strip_device_prefix_leaves_posix_names_alone(self):
        weird = Path("/tmp/\\\\?\\C:\\Windows")
        self.assertEqual(consent.strip_device_prefix(weird), weird)

class TestPosixWholeDeviceEquivalents(ConsentTestCase):

    @unittest.skipIf(IS_WINDOWS, "POSIX system paths")
    def test_the_mount_equivalent_roots_are_rejected(self):
        for raw in POSIX_MOUNT_EQUIVALENT_REJECTED:
            with self.subTest(path=raw):
                reason = consent.system_location_reason(Path(raw).resolve())
                self.assertIsNotNone(reason, f"{raw} was NOT rejected")

    @unittest.skipIf(IS_WINDOWS, "POSIX system paths")
    def test_var_run_is_rejected_after_it_resolves_into_run(self):
        if not Path("/var/run").exists() or Path("/var/run").resolve() != Path("/run"):
            self.skipTest("/var/run is not a symlink to /run on this host")
        self.assertIsNotNone(consent.system_location_reason(Path("/var/run").resolve()))

    @unittest.skipIf(IS_WINDOWS, "POSIX system paths")
    def test_home_tree_is_rejected_even_when_home_is_not_inside_it(self):
        real_home = consent._home
        consent._home = lambda: Path("/root")
        try:
            self.assertIsNotNone(consent.system_location_reason(Path("/home")))
        finally:
            consent._home = real_home

    @unittest.skipIf(IS_WINDOWS, "mount roots are drive letters on Windows")
    def test_the_top_of_a_mount_is_rejected_but_a_folder_inside_it_is_not(self):
        base = Path(tempfile.mkdtemp(prefix="horus-consent-mnt-", dir=str(Path.home())))
        inside = base / "reports"
        inside.mkdir()
        real_ismount = os.path.ismount
        os.path.ismount = lambda p: str(p) == str(base)
        try:
            reason = consent.system_location_reason(base.resolve())
            self.assertIsNotNone(reason)
            self.assertIn("mounted filesystem", reason)
            with self.assertRaises(consent.PathRejected):
                consent.validate_folder(str(base))
            self.assertEqual(consent.validate_folder(str(inside)), inside.resolve())
        finally:
            os.path.ismount = real_ismount
            inside.rmdir()
            base.rmdir()

    @unittest.skipIf(IS_WINDOWS, "mount roots are drive letters on Windows")
    def test_a_real_mount_point_is_rejected(self):
        candidates = ["/mnt/c", "/run", "/tmp", "/boot", "/media"]
        found = [c for c in candidates
                 if Path(c).is_dir() and os.path.ismount(c) and Path(c).parent != Path(c)]
        if not found:
            self.skipTest("no non-root mount point on this host")
        for raw in found:
            with self.subTest(path=raw):
                self.assertIsNotNone(consent.system_location_reason(Path(raw)))

    @unittest.skipIf(IS_WINDOWS, "mount roots are drive letters on Windows")
    def test_a_directory_that_contains_a_mount_root_is_rejected(self):
        base = Path(tempfile.mkdtemp(prefix="horus-consent-parent-",
                                     dir=str(Path.home())))
        child = base / "c"
        child.mkdir()
        real_ismount = os.path.ismount
        os.path.ismount = lambda p: str(p) == str(child)
        try:
            reason = consent.system_location_reason(base.resolve())
            self.assertIsNotNone(reason, "a directory containing a mount root "
                                         "must be rejected")
            self.assertIn("mounted filesystem", reason)
            with self.assertRaises(consent.PathRejected):
                consent.validate_folder(str(base))
        finally:
            os.path.ismount = real_ismount
            child.rmdir()
            base.rmdir()

    @unittest.skipIf(IS_WINDOWS, "reaching Windows through a mount is a POSIX view")
    def test_a_windows_system_dir_reached_through_a_mount_is_rejected(self):
        base = Path(tempfile.mkdtemp(prefix="horus-consent-wsl-",
                                     dir=str(Path.home())))
        users = base / "Users"
        deep = users / "someone" / "reports"
        deep.mkdir(parents=True)
        windows = base / "Windows"
        (windows / "System32").mkdir(parents=True)
        real_ismount = os.path.ismount
        os.path.ismount = lambda p: str(p) == str(base)
        try:
            for path in (users, windows, windows / "System32"):
                with self.subTest(path=str(path)):
                    self.assertIsNotNone(
                        consent.system_location_reason(path.resolve()),
                        f"{path} should be refused as a Windows system location")
            self.assertEqual(consent.validate_folder(str(deep)), deep.resolve())
        finally:
            os.path.ismount = real_ismount
            shutil.rmtree(base, ignore_errors=True)

    def test_is_mount_point_never_raises(self):
        real_ismount = os.path.ismount

        def boom(_path):
            raise OSError(5, "Input/output error")

        os.path.ismount = boom
        try:
            self.assertFalse(consent._is_mount_point(Path("/anything")))
        finally:
            os.path.ismount = real_ismount

    @unittest.skipIf(IS_WINDOWS, "the /home carve-out is POSIX-specific")
    def test_your_own_folder_inside_home_still_works(self):
        folder = Path(tempfile.mkdtemp(prefix="horus-consent-own-", dir=str(Path.home())))
        try:
            self.assertIsNone(consent.system_location_reason(folder.resolve()))
            self.assertEqual(consent.validate_folder(str(folder)), folder.resolve())
        finally:
            folder.rmdir()

class TestComposeUnsafeNames(ConsentTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.base = Path(tempfile.mkdtemp(prefix="horus-consent-env-", dir=str(Path.home())))
        self.made: list[Path] = []

    def tearDown(self) -> None:
        for folder in self.made:
            try:
                folder.rmdir()
            except OSError:
                pass
        self.base.rmdir()
        super().tearDown()

    def _folder(self, name: str) -> Path | None:
        folder = self.base / name
        try:
            folder.mkdir()
        except OSError:
            return None
        self.made.append(folder)
        return folder

    def test_whitespace_then_hash_is_rejected(self):
        folder = self._folder("Q4 #final")
        self.assertIsNotNone(folder, "this OS refused to create 'Q4 #final'")
        with self.assertRaises(consent.PathRejected) as caught:
            consent.validate_folder(str(folder))
        self.assertIn("#", caught.exception.reason)

    def test_every_compose_metacharacter_is_rejected(self):
        names = {"cost $sheet": "$", "it's mine": "'", 'say "hi"': '"'}
        if not IS_WINDOWS:
            names["source:target"] = ":"
            names["two\nlines"] = "line"
        checked = 0
        for name, expected in names.items():
            folder = self._folder(name)
            if folder is None:
                continue
            checked += 1
            with self.subTest(name=name):
                with self.assertRaises(consent.PathRejected) as caught:
                    consent.validate_folder(str(folder))
                self.assertIn(expected, caught.exception.reason)
        self.assertGreater(checked, 0, "no unsafe name could be created here")

    def test_a_component_padded_with_a_space_is_rejected(self):
        folder = self._folder(" padded")
        self.assertIsNotNone(folder, "this OS refused to create ' padded'")
        with self.assertRaises(consent.PathRejected) as caught:
            consent.validate_folder(str(folder))
        self.assertIn("space", caught.exception.reason)

    def test_an_ordinary_name_is_still_accepted(self):
        folder = self._folder("Q4 reports (final)")
        self.assertIsNotNone(folder)
        got = consent.validate_folder(str(folder))
        self.assertEqual(got, folder.resolve())
        for char in "#$\"'\n\r":
            self.assertNotIn(char, consent.to_compose_path(got))

if __name__ == "__main__":
    unittest.main(verbosity=2)
