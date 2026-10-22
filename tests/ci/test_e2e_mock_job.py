from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ci" / "smoke-steps.py"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
MOCK_FILES = "docker-compose.yml:docker-compose.cpu.yml:docker-compose.mock.yml"
MONITORING_OFF = "docker-compose.monitoring-off.yml"
NO_MODEL_FILES = f"{MOCK_FILES}:{MONITORING_OFF}"

spec = importlib.util.spec_from_file_location("smoke_steps", SCRIPT)
smoke_steps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke_steps)

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the workflow")


def step(number: int, ok: bool = True, **extra) -> dict:
    return {"name": f"{number}/9  step", "ok": ok, "detail": "d", "seconds": 0.1, **extra}


class SmokeSteps(unittest.TestCase):
    def check(self, steps: list[dict] | None, before: str = "") -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "smoke-log.txt"
            text = before + ("" if steps is None else f"x INFO smoke steps: {json.dumps(steps)}\n")
            log.write_text(text, encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = smoke_steps.main([str(log)])
        return code, out.getvalue()

    def test_nine_passed_steps_pass(self):
        older = f"x INFO smoke steps: {json.dumps([step(1, ok=False)])}\n"
        code, out = self.check([step(n) for n in range(1, 10)], before=older)
        self.assertEqual(code, 0)
        self.assertEqual(out.count("ok    "), 9)

    def test_a_failed_step_a_warning_or_a_missing_step_fails(self):
        cases = {
            "failed": [*[step(n) for n in range(1, 9)], step(9, ok=False)],
            "warned": [*[step(n) for n in range(1, 9)], step(9, warning="it said lima")],
            "short": [step(n) for n in range(1, 8)],
        }
        for name, steps in cases.items():
            with self.subTest(name):
                code, out = self.check(steps)
                self.assertEqual(code, 1)
                self.assertIn("::error::", out)

    def test_a_log_without_the_steps_fails(self):
        self.assertEqual(self.check(None, before="nothing\n")[0], 1)
        self.assertEqual(smoke_steps.main([]), 2)


@needs_yaml
class EndToEndJob(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["e2e-mock"]
        cls.runs = "\n".join(step.get("run", "") for step in cls.job["steps"])

    def step(self, name: str) -> dict:
        return next(s for s in self.job["steps"] if s.get("name") == name)

    def test_it_builds_and_starts_the_whole_stack_and_needs_no_artifact(self):
        build = " ".join(self.step("Build every image of the stack")["run"].split())
        start = " ".join(
            self.step("Start the whole stack with no model and monitoring off")["run"].split()
        )
        self.assertIn("docker compose --progress plain build echo", build)
        self.assertIn("up -d --wait --wait-timeout 900 echo", start)
        uses = [step.get("uses", "") for step in self.job["steps"]]
        self.assertFalse([use for use in uses if "artifact" in use])
        self.assertNotIn("needs", self.job)

    def test_it_runs_the_cpu_stack_with_the_mock_and_monitoring_off_overlays(self):
        self.assertIn(f'echo "COMPOSE_FILE={NO_MODEL_FILES}"', self.runs)
        for setting in (
            "OTEL_SDK_DISABLED",
            "KNOWLEDGE_STORE_REINDEX_ON_STARTUP",
            "EMBED_URL",
            "HORUS_SPACY",
        ):
            with self.subTest(setting):
                self.assertNotIn(setting, self.runs)
        write = next(
            s for s in self.job["steps"] if s.get("name") == "Write src/infra/.env for mock mode"
        )
        appended = write["run"].split("{", 1)[1].splitlines()
        self.assertEqual(appended[1].strip(), "echo", ".env.example has no final newline")
        self.assertIn("HORUS_AI_MODE=mock", self.runs)

    def test_the_workflow_credentials_never_reach_compose(self):
        for line in self.runs.splitlines():
            if "docker compose" in line and not line.strip().startswith(("for ", "echo")):
                with self.subTest(line.strip()):
                    self.assertIn('env -i PATH="$PATH" HOME="$HOME"', line)

    def test_it_uploads_the_corpus_runs_smoke_and_checks_every_step(self):
        self.assertIn("demo_assets/*.md", self.runs)
        self.assertIn("http://127.0.0.1:8080/file", self.runs)
        self.assertIn("python installer/smoke.py", self.runs)
        self.assertIn("python scripts/ci/smoke-steps.py", self.runs)
        self.assertIn("http://127.0.0.1:8000/system/ai", self.runs)

    def test_mas_must_report_no_model_at_all(self):
        check = self.step(
            "MAS reports mock mode, mock embeddings, spaCy off and monitoring off at /system/ai"
        )
        self.assertIn('("mock", True, "mock", "off", "off")', check["run"])
        self.assertIn('mode["embeddings"], mode["spacy"], mode["monitoring"]', check["run"])

    def test_every_service_log_goes_through_the_model_load_check(self):
        check = self.step("No service loaded a model")
        self.assertIn("docker compose config --services", check["run"])
        self.assertIn('--no-log-prefix "$service"', check["run"])
        self.assertIn('scripts/ci/no-model-loads.py "$RUNNER_TEMP/service-logs"', check["run"])
        names = [s.get("name") for s in self.job["steps"]]
        self.assertLess(names.index("Smoke test"), names.index("No service loaded a model"))

    def test_it_checks_the_compose_files_with_and_without_the_overlay(self):
        for files in (
            "docker-compose.yml docker-compose.yml:docker-compose.cpu.yml",
            MOCK_FILES,
            f"docker-compose.yml:{MONITORING_OFF}",
            f"docker-compose.yml:docker-compose.cpu.yml:{MONITORING_OFF}",
            f"{MOCK_FILES}:{MONITORING_OFF}",
        ):
            self.assertIn(files, self.runs)
        self.assertIn("config -q", self.runs)

    def test_it_reports_its_duration_and_always_stops_the_stack(self):
        report = next(s for s in self.job["steps"] if s.get("name") == "Report the duration")
        stop = next(s for s in self.job["steps"] if s.get("name") == "Stop the stack")
        self.assertEqual(report["if"], "always()")
        self.assertIn("GITHUB_STEP_SUMMARY", report["run"])
        self.assertEqual(stop["if"], "always()")
        self.assertIn("down -v", stop["run"])
        self.assertLessEqual(self.job["timeout-minutes"], 40)


if __name__ == "__main__":
    unittest.main()
