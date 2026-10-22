from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "reindex-knowledge-store.py"
spec = importlib.util.spec_from_file_location("reindex_knowledge_store", SCRIPT)
reindex_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reindex_script)

KS = "http://ks:8080"


def _status(state: str, **totals) -> dict:
    return {
        "job_id": "job-1",
        "state": state,
        "embed_model": "sentence-transformers:BAAI/bge-base-en-v1.5",
        "totals": {
            "pending": 2,
            "migrated": 0,
            "reembedded": 0,
            "unchanged": 0,
            "failed": 0,
            **totals,
        },
        "failures": [],
    }


class FakeKnowledgeStore:
    def __init__(self, post_status: int = 202, states: list[dict] | None = None):
        self.post_status = post_status
        self.states = list(states or [_status("completed", migrated=2)])
        self.requests: list[tuple[str, str, str | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(
            (request.method, request.url.path, request.headers.get("X-Corpus-Token"))
        )
        if request.method == "POST":
            if self.post_status == 202:
                return httpx.Response(202, json={"job_id": "job-1", "state": "running"})
            return httpx.Response(self.post_status, json={"error": "busy"})
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return httpx.Response(200, json=state)


@pytest.fixture
def knowledge_store(monkeypatch):
    def install(fake: FakeKnowledgeStore) -> FakeKnowledgeStore:
        real_client = httpx.Client
        monkeypatch.setattr(
            reindex_script.httpx,
            "Client",
            lambda *a, **kw: real_client(*a, transport=httpx.MockTransport(fake), **kw),
        )
        monkeypatch.setattr(reindex_script.time, "sleep", lambda _seconds: None)
        return fake

    return install


def test_it_starts_the_re_index_with_the_token_and_waits_for_it(knowledge_store, capsys):
    fake = knowledge_store(
        FakeKnowledgeStore(
            states=[
                _status("running", migrated=1),
                _status("completed", migrated=2),
            ]
        )
    )

    code = reindex_script.main(["--ks-url", KS, "--token", "s3cret"])

    assert code == 0
    assert fake.requests[0] == ("POST", "/corpus/reindex", "s3cret")
    assert {path for _m, path, _t in fake.requests} == {"/corpus/reindex"}
    assert "2/2 documents" in capsys.readouterr().out


def test_a_re_index_already_running_is_followed_instead_of_failing(knowledge_store):
    fake = knowledge_store(
        FakeKnowledgeStore(
            post_status=409,
            states=[
                _status("running"),
                _status("completed", unchanged=2),
            ],
        )
    )

    assert reindex_script.main(["--ks-url", KS, "--token", "s3cret"]) == 0
    assert [method for method, _p, _t in fake.requests].count("POST") == 1


def test_a_running_corpus_scan_refuses_the_re_index(knowledge_store, capsys):
    knowledge_store(FakeKnowledgeStore(post_status=409, states=[{"state": "idle"}]))

    assert reindex_script.main(["--ks-url", KS, "--token", "s3cret"]) == 2
    assert "refused" in capsys.readouterr().err


def test_failed_documents_make_the_run_fail(knowledge_store, capsys):
    final = _status("completed", migrated=1, failed=1)
    final["failures"] = [{"doc_id": "doc-9", "reason": "RuntimeError: boom"}]
    knowledge_store(FakeKnowledgeStore(states=[final]))

    assert reindex_script.main(["--ks-url", KS, "--token", "s3cret"]) == 1
    assert "doc-9" in capsys.readouterr().err


def test_without_a_token_nothing_is_sent(knowledge_store, monkeypatch):
    monkeypatch.delenv("CORPUS_SCAN_TOKEN", raising=False)
    fake = knowledge_store(FakeKnowledgeStore())

    assert reindex_script.main(["--ks-url", KS, "--token", ""]) == 2
    assert fake.requests == []


def test_a_re_index_that_outlives_the_timeout_is_reported(knowledge_store):
    knowledge_store(FakeKnowledgeStore(states=[_status("running")]))

    assert reindex_script.main(["--ks-url", KS, "--token", "s3cret", "--timeout", "0"]) == 1
