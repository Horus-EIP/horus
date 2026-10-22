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
SCRIPT = REPO / "scripts" / "ci" / "no-model-loads.py"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
REAL_SEARCH_TEST = "tests/knowledge_store/unit/test_real_fastembed.py"

spec = importlib.util.spec_from_file_location("no_model_loads", SCRIPT)
no_model_loads = importlib.util.module_from_spec(spec)
sys.modules["no_model_loads"] = no_model_loads
spec.loader.exec_module(no_model_loads)

CLEAN = {
    "mas": "[bootstrap_llm] LLM_BACKEND=vllm -> no local model needed; skipping download.\n"
    "[info     ] Background thread: preloading orchestrator LLM...\n"
    "[info     ] Background thread: orchestrator LLM preload finished.\n"
    "[info     ] Background thread: preloading sentence-embedding model...\n"
    "mas  | INFO Embeddings come from http://llm-mock:8080/v1 with the model horus-mock, 384 values "
    "per vector: no embedding model is loaded in MAS\n",
    "knowledge_store": 'knowledge_store  | {"message": "Embeddings come from http://llm-mock:8080/v1: '
    'no embedding model is loaded in this service"}\n'
    'knowledge_store  | {"message": "spaCy is off (HORUS_SPACY=off): entities"}\n',
    "agent": "agent  | INFO spaCy is off (HORUS_SPACY=off): payments are extracted with regular expressions\n",
    "llm-mock": "llm-mock  | INFO embeddings: inputs=1 dimensions=384 status=200\n",
}


class NoModelLoads(unittest.TestCase):
    def check(self, logs: dict[str, str]) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as folder:
            for service, text in logs.items():
                (Path(folder) / f"{service}.log").write_text(text, encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = no_model_loads.main([folder])
        return code, out.getvalue()

    def test_a_stack_that_loads_no_model_passes(self):
        code, out = self.check(CLEAN)
        self.assertEqual(code, 0, out)
        self.assertIn("No service loaded a model", out)

    def test_every_model_load_line_fails_the_check(self):
        loads = {
            "mas": "Loading sentence-embedding model sentence-transformers/all-MiniLM-L6-v2 with FastEmbed",
            "knowledge_store": "BGE embedder BAAI/bge-base-en-v1.5 loaded with fastembed 0.8.1 on cpu",
            "agent": "AGENT_SPACY_PREFER_SM: loading en_core_web_sm (lighter).",
            "llm-mock": "Fetching 5 files: 100%",
        }
        for service, line in loads.items():
            with self.subTest(service):
                code, out = self.check({**CLEAN, service: CLEAN[service] + line + "\n"})
                self.assertEqual(code, 1)
                self.assertEqual(out.count(f"::error::{service} loaded a model"), 1)

    def test_a_line_two_patterns_match_is_reported_once(self):
        line = "[bootstrap_llm] downloading Qwen/Qwen3-4B into /models"
        code, out = self.check({**CLEAN, "agent": CLEAN["agent"] + line + "\n"})
        self.assertEqual(code, 1)
        self.assertEqual(out.count("::error::"), 1)

    def test_a_service_that_never_says_it_runs_without_a_model_fails(self):
        code, out = self.check({**CLEAN, "agent": "agent  | INFO started\n"})
        self.assertEqual(code, 1)
        self.assertIn("agent never logged 'spaCy is off'", out)

    def test_a_missing_log_fails(self):
        code, out = self.check({key: value for key, value in CLEAN.items() if key != "mas"})
        self.assertEqual(code, 1)
        self.assertIn("mas.log is missing", out)

    def test_usage(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(no_model_loads.main([]), 2)

    def test_every_line_it_watches_is_still_written_by_its_service(self):
        lines = [
            *no_model_loads.LOADS,
            *(line for found in no_model_loads.NO_MODEL.values() for line in found),
        ]
        for line in lines:
            if not line.source:
                continue
            with self.subTest(line.literal):
                self.assertIn(line.literal, (REPO / line.source).read_text(encoding="utf-8"))
                self.assertRegex(line.literal.replace("%s", "x").replace("%d", "1"), line.pattern)


@unittest.skipUnless(yaml is not None, "needs PyYAML to read the workflow")
class RealSearchStillRunsInCi(unittest.TestCase):
    def test_the_knowledge_store_job_downloads_bge_and_requires_the_real_search_test(self):
        job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["test-knowledge-store"]
        names = [step.get("name") for step in job["steps"]]
        tests = next(
            step
            for step in job["steps"]
            if step.get("name") == "Run Knowledge Store unit tests with coverage"
        )
        download = next(
            step
            for step in job["steps"]
            if step.get("name") == "Download the BGE model for the real-search test"
        )
        self.assertLess(names.index(download["name"]), names.index(tests["name"]))
        self.assertIn("TextEmbedding('BAAI/bge-base-en-v1.5')", download["run"])
        self.assertEqual(tests["env"]["HORUS_REQUIRE_MODEL_TESTS"], "1")
        self.assertEqual(
            tests["env"]["FASTEMBED_CACHE_PATH"], download["env"]["FASTEMBED_CACHE_PATH"]
        )
        self.assertIn("tests/knowledge_store", tests["run"])
        self.assertTrue((REPO / REAL_SEARCH_TEST).is_file())


if __name__ == "__main__":
    unittest.main()
