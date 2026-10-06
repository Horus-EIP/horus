from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import smoke  # noqa: E402
from common import InstallError  # noqa: E402


def response(status: int, body) -> smoke.Response:
    return smoke.Response(status, json.dumps(body).encode("utf-8"))


class FakeKnowledgeStore:
    def __init__(self, already_indexed: bool = False):
        self.titles = [smoke.DEMO_DOC] if already_indexed else []
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, url, **_kwargs):
        self.calls.append((method, url))
        if method == "GET" and url.endswith("/file"):
            return response(200, {"documents": [{"title": title} for title in self.titles]})
        if method == "POST" and url.endswith("/file"):
            self.titles.append(smoke.DEMO_DOC)
            return response(200, [{"filename": smoke.DEMO_DOC, "doc_id": "smoke-doc"}])
        if method == "DELETE":
            self.titles.remove(smoke.DEMO_DOC)
            return response(200, {"deleted_ids": ["smoke-doc:0"]})
        return response(404, {})


def demo_repo() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "demo_assets").mkdir()
    (root / "demo_assets" / smoke.DEMO_DOC).write_text("Q4 revenue was $4.2M.", encoding="utf-8")
    return root


class TestTheSmokeTestLeavesNoDocumentBehind(unittest.TestCase):
    def run_smoke(self, store: FakeKnowledgeStore, failing_step: str | None = None):
        steps_to_patch = {
            "admin_credentials": ("admin", "admin"),
            "step_knowledge_health": None,
            "step_unauthenticated_ping": None,
            "step_login": "jwt",
            "step_authenticated_ping": None,
            "step_wait_for_agents": ["Finance-Analyst"],
            "step_chat": "Q4 2025 revenue was $4.2M.",
            "step_check_answer": None,
            "step_negative_control": None,
        }
        patches = [mock.patch.object(smoke, "http", side_effect=store)]
        for name, value in steps_to_patch.items():
            effect = InstallError(50, "failed", "", "") if name == failing_step else None
            patches.append(mock.patch.object(smoke, name, return_value=value, side_effect=effect))
        with tempfile.TemporaryDirectory() as logs:
            log = smoke.Log(Path(logs) / "install-log.txt")
            for patch in patches:
                patch.start()
            try:
                return smoke.run(log, demo_repo(), timeout=60, model_server="llm")
            finally:
                for patch in patches:
                    patch.stop()
                log.close(0)

    def test_the_demo_document_it_uploaded_is_deleted_after_a_passing_run(self):
        store = FakeKnowledgeStore()

        self.run_smoke(store)

        self.assertIn(("DELETE", "http://localhost:8080/smoke-doc"), store.calls)
        self.assertEqual(store.titles, [])

    def test_the_demo_document_it_uploaded_is_deleted_when_a_later_step_fails(self):
        store = FakeKnowledgeStore()

        with self.assertRaises(InstallError):
            self.run_smoke(store, failing_step="step_chat")

        self.assertIn(("DELETE", "http://localhost:8080/smoke-doc"), store.calls)

    def test_a_document_that_was_already_indexed_is_left_alone(self):
        store = FakeKnowledgeStore(already_indexed=True)

        self.run_smoke(store)

        self.assertNotIn("DELETE", [method for method, _ in store.calls])
        self.assertEqual(store.titles, [smoke.DEMO_DOC])

    def test_a_failed_clean_up_never_fails_the_verification(self):
        result = self.run_smoke(UnreachableOnDelete())

        self.assertTrue(result["passed"])


class UnreachableOnDelete(FakeKnowledgeStore):
    def __call__(self, method, url, **kwargs):
        if method == "DELETE":
            self.calls.append((method, url))
            raise smoke.Unreachable("knowledge store went away")
        return super().__call__(method, url, **kwargs)


if __name__ == "__main__":
    unittest.main()
