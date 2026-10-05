from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
import horus_install  # noqa: E402
from common import Log  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent

class InstallerVersion(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_the_installer_reports_the_repository_version_file(self):
        expected = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(common.VERSION, expected)

    def test_the_version_file_sits_next_to_the_installer_folder(self):
        self.assertEqual(common.VERSION_FILE, common.BUNDLE_DIR / "VERSION")

    def test_surrounding_whitespace_and_crlf_are_ignored(self):
        path = self.tmp / "VERSION"
        path.write_bytes(b"  1.2.3\r\n")
        self.assertEqual(common.read_version(path), "1.2.3")

    def test_a_missing_version_file_reads_as_unknown(self):
        self.assertEqual(common.read_version(self.tmp / "VERSION"), common.UNKNOWN_VERSION)

    def test_an_empty_version_file_reads_as_unknown(self):
        path = self.tmp / "VERSION"
        path.write_text("\n", encoding="utf-8")
        self.assertEqual(common.read_version(path), common.UNKNOWN_VERSION)

    def test_the_version_flag_prints_it(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            horus_install.build_parser().parse_args(["--version"])
        self.assertIn(common.VERSION, out.getvalue())

class InstallWritesTheVersion(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        (self.repo / "src" / "infra").mkdir(parents=True)
        self.log = Log(self.repo / "install-log.txt")
        self.addCleanup(self.log.close, 0)

    def written_env(self) -> dict[str, str]:
        args = horus_install.build_parser().parse_args(
            ["--profile", "gpu-8g", "--non-interactive", "--skip-smoke"]
        )
        probe = dict(horus_install.SIMULATIONS["nvidia-8gb"])
        with contextlib.ExitStack() as stack:
            patch = stack.enter_context
            patch(mock.patch.object(horus_install, "find_repo", return_value=self.repo))
            patch(mock.patch.object(horus_install, "banner"))
            patch(mock.patch.object(horus_install, "preflight"))
            consent = patch(mock.patch.object(horus_install, "consent"))
            consent.choose.return_value = {"corpus_dir": "../../demo_assets"}
            hardware = patch(mock.patch.object(horus_install, "hardware"))
            hardware.probe.return_value = probe
            apply_env = patch(mock.patch.object(horus_install, "apply_env"))
            patch(mock.patch.object(horus_install, "pull_and_build"))
            patch(mock.patch.object(horus_install, "wait_for_health"))
            patch(mock.patch.object(horus_install, "_success"))
            patch(contextlib.redirect_stdout(io.StringIO()))
            code = horus_install._dispatch(self.log, args)
        self.assertEqual(code, common.EXIT_OK)
        return apply_env.call_args.args[2]

    def test_a_full_install_writes_the_release_version_into_the_env(self):
        self.assertEqual(self.written_env()["HORUS_VERSION"], common.VERSION)

if __name__ == "__main__":
    unittest.main()
