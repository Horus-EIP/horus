from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ci" / "coverage-line.py"
WORKFLOWS = REPO / ".github" / "workflows"
TEST_JOBS = {
    "test-mas": ("MAS", "coverage-mas.xml", "junit-mas.xml"),
    "test-agent": ("Agent", "coverage-agent.xml", "junit-agent.xml"),
    "test-knowledge-store": ("Knowledge store", "coverage-ks.xml", "junit-ks.xml"),
    "test-installer": ("Installer", "coverage-installer.xml", "junit-installer.xml"),
    "test-llm-mock": ("LLM mock", "coverage-llm-mock.xml", "junit-llm-mock.xml"),
}
RETENTION = {"coverage-": 3, "app-": 7, "Horus-Beta-zip": 14}
RELEASE_UPLOADS = {("desktop-release.yml", "build"), ("desktop-release.yml", "bundle")}
REPORT_UPLOADS = {
    "test-mas": ("coverage-mas", ("coverage-mas.xml", "junit-mas.xml", "htmlcov-mas/")),
    "test-agent": ("coverage-agent", ("coverage-agent.xml", "junit-agent.xml", "htmlcov-agent/")),
    "test-knowledge-store": (
        "coverage-knowledge-store",
        ("coverage-ks.xml", "junit-ks.xml", "htmlcov-ks/"),
    ),
}

spec = importlib.util.spec_from_file_location("coverage_line", SCRIPT)
coverage_line = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage_line)

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the workflows")
needs_pytest_cov = unittest.skipUnless(
    importlib.util.find_spec("pytest_cov") is not None,
    "needs pytest-cov, which the versions job installs",
)

GATES = {"test-mas": 85, "test-agent": 90, "test-knowledge-store": 85, "test-llm-mock": 90}
COVERAGE = (
    '<?xml version="1.0" ?><coverage line-rate="0.924" branch-rate="0.81" lines-valid="1000" '
    'lines-covered="924" branches-valid="300" branches-covered="243"></coverage>'
)
SAMPLE = textwrap.dedent("""
    def grade(score):
        if score > 50:
            return "pass"
        return "fail"


    def kind(value):
        if isinstance(value, int):
            return "int"
        if isinstance(value, str):
            return "str"
        return "other"
""")
SAMPLE_TESTS = textwrap.dedent("""
    from sample import grade, kind


    def test_grade():
        assert grade(80) == "pass"


    def test_kind():
        assert kind(1) == "int"
""")
JUNIT = (
    '<?xml version="1.0"?><testsuites><testsuite tests="40" failures="1" errors="1" skipped="2">'
    + '<testcase classname="t" name="ok"/>' * 6
    + '<testcase classname="t" name="bad"><failure message="no"/></testcase>'
    + '<testcase classname="t" name="broken"><error message="no"/></testcase>'
    + '<testcase classname="t" name="later"><skipped message="no"/></testcase>' * 2
    + "</testsuite></testsuites>"
)


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def upload_steps():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job_name, job in workflow(path.name)["jobs"].items():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                    yield path.name, job_name, step


class CoverageLine(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.summary = self.tmp / "summary.md"
        self.output = self.tmp / "output.txt"
        patcher = mock.patch.dict(
            os.environ,
            {"GITHUB_STEP_SUMMARY": str(self.summary), "GITHUB_OUTPUT": str(self.output)},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_script(self, *args: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(coverage_line.main(list(args)), 0)
        return out.getvalue()

    def reports(
        self, coverage: str | None = COVERAGE, junit: str | None = JUNIT
    ) -> tuple[str, str]:
        paths = (self.tmp / "coverage.xml", self.tmp / "junit.xml")
        for path, text in zip(paths, (coverage, junit)):
            if text is not None:
                path.write_text(text, encoding="utf-8")
        return str(paths[0]), str(paths[1])

    def test_a_suite_line_gives_lines_covered_and_the_test_counts(self):
        self.run_script("line", "MAS", *self.reports())
        row = "| MAS | 92.4 % | 89.77 % | 6 passed, 2 failed, 2 skipped |"
        self.assertEqual(
            self.summary.read_text(encoding="utf-8"), f"{coverage_line.HEADER}\n{row}\n"
        )
        self.assertEqual(self.output.read_text(encoding="utf-8"), f"row={row}\n")

    def test_a_single_testsuite_root_is_read_too(self):
        junit = '<testsuite tests="3">' + '<testcase classname="t" name="ok"/>' * 3 + "</testsuite>"
        self.assertIn(
            "3 passed, 0 failed, 0 skipped",
            self.run_script("line", "Agent", *self.reports(junit=junit)),
        )

    def test_a_test_with_a_skipped_and_a_failed_part_counts_once_as_failed(self):
        junit = (
            "<testsuite>"
            + '<testcase classname="t" name="ok"/>' * 2
            + '<testcase classname="t" name="mixed"><skipped message="a"/><failure message="b"/></testcase>'
            + '<testcase classname="t" name="teardown"><skipped message="a"/><error message="b"/></testcase>'
            + "</testsuite>"
        )
        printed = self.run_script("line", "Installer", *self.reports(junit=junit))
        self.assertIn("2 passed, 2 failed, 0 skipped", printed)

    def test_subtests_do_not_count_as_tests(self):
        printed = self.run_script("line", "MAS", *self.reports())
        self.assertIn("6 passed, 2 failed, 2 skipped", printed)
        self.assertNotIn("36 passed", printed)

    def test_reports_a_crashed_run_never_wrote_say_so(self):
        printed = self.run_script("line", "Installer", *self.reports(coverage=None, junit=None))
        self.assertEqual(printed.strip(), "| Installer | no report | no report | no report |")

    def test_lines_and_branches_together_is_covered_over_valid_of_both(self):
        coverage = (
            '<coverage line-rate="0.5" lines-valid="10" lines-covered="5" '
            'branches-valid="10" branches-covered="9"/>'
        )
        self.assertIn(
            "| 50.0 % | 70.00 % |", self.run_script("line", "MAS", *self.reports(coverage=coverage))
        )

    def test_without_branches_both_figures_count_lines(self):
        coverage = (
            '<coverage line-rate="0.875" lines-valid="8" lines-covered="7" '
            'branches-valid="0" branches-covered="0"/>'
        )
        self.assertIn(
            "| 87.5 % | 87.50 % |", self.run_script("line", "MAS", *self.reports(coverage=coverage))
        )

    def test_a_report_without_the_totals_still_gives_its_lines(self):
        coverage = '<coverage line-rate="0.924" branch-rate="0.81"></coverage>'
        self.assertIn(
            "| 92.4 % | no report |",
            self.run_script("line", "MAS", *self.reports(coverage=coverage)),
        )

    def test_the_summary_job_adds_what_arrived_and_names_what_did_not(self):
        printed = self.run_script(
            "collect", "MAS=| MAS | 92.4 % | 89.77 % | 6 passed, 2 failed, 2 skipped |", "Agent="
        )
        self.assertIn(coverage_line.HEADER, printed)
        self.assertIn("| MAS | 92.4 % | 89.77 % |", printed)
        self.assertIn("| Agent | nothing arrived | nothing arrived | nothing arrived |", printed)
        self.assertNotIn("No test job sent", printed)

    def test_the_summary_job_says_so_when_nothing_arrived(self):
        printed = self.run_script("collect", "MAS=", "Agent=")
        self.assertIn("No test job sent its coverage line.", printed)


@needs_yaml
class Workflows(unittest.TestCase):
    def test_no_upload_can_fail_a_job(self):
        for name, job, step in upload_steps():
            with self.subTest(f"{name} {job}"):
                self.assertIs(step.get("continue-on-error"), True)

    def test_no_test_job_uploads_artifacts_on_a_green_run(self):
        for name, job, step in upload_steps():
            if (name, job) in RELEASE_UPLOADS:
                continue
            with self.subTest(f"{name} {job}"):
                self.assertEqual(step.get("if"), "failure()")

    def test_a_failed_test_job_still_uploads_its_reports(self):
        jobs = workflow("ci.yml")["jobs"]
        for job, (artifact, paths) in REPORT_UPLOADS.items():
            uploads = [
                step
                for step in jobs[job]["steps"]
                if str(step.get("uses", "")).startswith("actions/upload-artifact@")
            ]
            with self.subTest(job):
                self.assertEqual(len(uploads), 1)
                self.assertEqual(uploads[0]["with"]["name"], artifact)
                self.assertEqual(uploads[0]["with"]["path"].split(), list(paths))
                self.assertEqual(uploads[0]["if"], "failure()")

    def test_only_the_release_workflow_uploads_on_success(self):
        always = {
            (name, job) for name, job, step in upload_steps() if step.get("if") != "failure()"
        }
        self.assertEqual(always, RELEASE_UPLOADS)

    def test_uploads_are_kept_only_as_long_as_needed(self):
        for name, job, step in upload_steps():
            artifact = step["with"]["name"]
            days = next(days for prefix, days in RETENTION.items() if artifact.startswith(prefix))
            with self.subTest(artifact):
                self.assertEqual(step["with"]["retention-days"], days)

    def test_a_release_missing_an_app_stops_before_the_zip_is_built(self):
        steps = workflow("desktop-release.yml")["jobs"]["bundle"]["steps"]
        names = [step.get("name") or step.get("uses", "") for step in steps]
        check = names.index("Every platform's app arrived")
        download = next(i for i, name in enumerate(names) if "download-artifact" in name)
        build = names.index("Build the archive")
        self.assertLess(download, check)
        self.assertLess(check, build)
        for artifact in ("app-windows-latest", "app-macos-latest", "app-ubuntu-22.04"):
            with self.subTest(artifact):
                self.assertIn(artifact, steps[check]["run"])
        matrix = workflow("desktop-release.yml")["jobs"]["build"]["strategy"]["matrix"]["include"]
        self.assertEqual(
            {f"app-{row['os']}" for row in matrix},
            {"app-windows-latest", "app-macos-latest", "app-ubuntu-22.04"},
        )

    def test_each_test_job_writes_its_line_even_when_its_tests_fail(self):
        jobs = workflow("ci.yml")["jobs"]
        for job, (suite, coverage, junit) in TEST_JOBS.items():
            step = next(step for step in jobs[job]["steps"] if step.get("id") == "coverage-line")
            with self.subTest(job):
                self.assertEqual(step["if"], "always()")
                self.assertIn(f'coverage-line.py line "{suite}" {coverage} {junit}', step["run"])
                self.assertEqual(
                    jobs[job]["outputs"]["coverage-row"], "${{ steps.coverage-line.outputs.row }}"
                )

    def test_the_summary_job_reads_job_outputs_not_artifacts(self):
        job = workflow("ci.yml")["jobs"]["coverage-summary"]
        self.assertEqual(sorted(job["needs"]), sorted(TEST_JOBS))
        self.assertFalse(
            any("download-artifact" in str(step.get("uses", "")) for step in job["steps"])
        )
        self.assertFalse(
            any("upload-artifact" in str(step.get("uses", "")) for step in job["steps"])
        )

    def test_the_summary_job_runs_when_a_test_job_fails_not_when_the_run_is_cancelled(self):
        job = workflow("ci.yml")["jobs"]["coverage-summary"]
        self.assertEqual(job["if"], "${{ !cancelled() }}")
        collect = next(
            step for step in job["steps"] if "coverage-line.py collect" in str(step.get("run", ""))
        )
        sources = {value for value in collect["env"].values()}
        self.assertEqual(
            sources, {f"${{{{ needs.{name}.outputs.coverage-row }}}}" for name in TEST_JOBS}
        )
        for variable, value in collect["env"].items():
            suite = next(
                suite for name, (suite, _, _) in TEST_JOBS.items() if f"needs.{name}." in value
            )
            with self.subTest(suite):
                self.assertIn(f'"{suite}=${variable}"', collect["run"])


@needs_pytest_cov
class GateFigure(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        (self.tmp / "sample.py").write_text(SAMPLE, encoding="utf-8")
        (self.tmp / "test_sample.py").write_text(SAMPLE_TESTS, encoding="utf-8")

    def gate(self, fail_under: int) -> tuple[int, str]:
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--cov=sample",
                "--cov-branch",
                f"--cov-fail-under={fail_under}",
                "--cov-report=xml:coverage.xml",
                "test_sample.py",
            ],
            cwd=self.tmp,
            env={**os.environ, "PYTHONPATH": str(self.tmp)},
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return done.returncode, done.stdout + done.stderr

    def summary_figures(self) -> list[str]:
        row = coverage_line.suite_row("Sample", self.tmp / "coverage.xml", self.tmp / "junit.xml")
        return [cell.strip() for cell in row.strip("|").split("|")][1:3]

    def test_the_lines_and_branches_figure_is_the_total_the_gate_compares_with_its_minimum(self):
        code, log = self.gate(1)
        self.assertEqual(code, 0, log)
        total = re.search(r"Total coverage: (\d+\.\d\d)%", log).group(1)
        lines, lines_and_branches = self.summary_figures()
        self.assertEqual(lines_and_branches, f"{total} %")
        self.assertLess(float(total), float(lines.removesuffix(" %")))
        reached = round(float(total))
        self.assertEqual(self.gate(reached)[0], 0)
        self.assertNotEqual(self.gate(reached + 1)[0], 0)


@needs_yaml
class GateReports(unittest.TestCase):
    def test_each_summary_reads_the_report_of_the_run_its_gate_checked(self):
        jobs = workflow("ci.yml")["jobs"]
        for job, (suite, coverage, junit) in TEST_JOBS.items():
            run = next(
                step["run"]
                for step in jobs[job]["steps"]
                if f"--cov-report=xml:{coverage}" in str(step.get("run", ""))
            )
            with self.subTest(job):
                self.assertIn("--cov-branch", run)
                self.assertIn(f"--junitxml={junit}", run)
                gates = re.findall(r"--cov-fail-under=(\d+)", run)
                self.assertEqual(gates, [str(GATES[job])] if job in GATES else [])

    def test_the_versions_job_installs_pytest_cov_so_the_gate_check_runs_in_ci(self):
        steps = workflow("ci.yml")["jobs"]["versions"]["steps"]
        installs = " ".join(
            str(step.get("run", "")) for step in steps if "pip install" in str(step.get("run", ""))
        )
        self.assertIn("pytest-cov", installs.split())
        names = [str(step.get("run", "")) for step in steps]
        install = next(i for i, run in enumerate(names) if "pytest-cov" in run)
        tests = next(i for i, run in enumerate(names) if "unittest discover -s tests/ci" in run)
        self.assertLess(install, tests)


if __name__ == "__main__":
    unittest.main()
