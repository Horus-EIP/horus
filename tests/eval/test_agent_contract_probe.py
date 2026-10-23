import asyncio
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from eval_contract import check_reply

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "scripts" / "eval" / "agent-contract-probe.py"
AGENT_APP = REPO_ROOT / "src" / "services" / "agent" / "app"


@pytest.fixture(scope="module")
def probe():
    spec = importlib.util.spec_from_file_location("agent_contract_probe", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_contract_probe"] = module
    spec.loader.exec_module(module)
    return module


PASSAGES = [
    {
        "chunk_id": "d4:2",
        "doc_id": "d4",
        "title": "4_Expense_Policy.md",
        "page": None,
        "text": "Hotels: $250 per night in the US.",
    },
    {
        "chunk_id": "d2:7",
        "doc_id": "d2",
        "title": "2_Employee_Handbook.md",
        "page": 3,
        "text": "Travel is booked through the portal.",
    },
    {
        "chunk_id": "d4:3",
        "doc_id": "d4",
        "title": "4_Expense_Policy.md",
        "page": None,
        "text": "Meals: $75 per day.",
    },
]


class FakeCatalog:
    def __init__(self):
        self.labels = []
        self.records = {}

    def format_passages(self, passages, budget):
        blocks = []
        for passage in passages:
            label = f"S{len(self.labels) + 1}"
            self.labels.append(label)
            self.records[label] = {
                "doc_id": passage["doc_id"],
                "chunk_id": passage["chunk_id"],
                "title": passage["title"],
                "page": passage["page"],
            }
            blocks.append(f"[{label}] {passage['title']}\n{passage['text']}")
        return "\n\n".join(blocks)[:budget]

    def cite(self, labels):
        return [dict(self.records[label]) for label in labels]


class FakeContractModule:
    SourceCatalog = FakeCatalog

    @staticmethod
    def answer_prompt(request, context, labels):
        return (
            f"rules for {len(labels)} labels",
            f"Request: {request}\n\nPassages:\n{context or '(no passages)'}",
        )

    @staticmethod
    def answer_response_format(labels):
        properties = {
            "status": {"type": "string", "enum": ["ok", "not_found"]},
            "answer": {"type": "string"},
        }
        required = ["status", "answer"]
        if labels:
            properties["sources"] = {
                "type": "array",
                "items": {"type": "string", "enum": list(labels)},
            }
            required.append("sources")
        schema = {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
        return {
            "type": "json_schema",
            "json_schema": {"name": "agent_answer", "strict": True, "schema": schema},
        }


class FakeAgentModule:
    calls = []

    @staticmethod
    def _max_context_chars():
        return 6000

    @staticmethod
    def _fit_vllm_prompt(system, user):
        FakeAgentModule.calls.append((system, user))
        return user, 1536

    @staticmethod
    def _vllm_model_name():
        return "qwen3-4b"

    @staticmethod
    def _vllm_base_url():
        return "http://llm:8080/v1/"

    @staticmethod
    def _vllm_timeout():
        return 900.0


class FakeStore:
    def __init__(self, results):
        self.results = results
        self.queries = []

    async def __call__(self, question):
        self.queries.append(question)
        result = self.results.get(question)
        if isinstance(result, Exception):
            raise result
        return result


def contract(probe, results):
    return probe.AgentContract(FakeContractModule, FakeAgentModule, FakeStore(results))


def llama_response(content, **extra):
    return {
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content, **extra},
            }
        ],
        "usage": {"prompt_tokens": 812, "completion_tokens": 31, "total_tokens": 843},
        "timings": {
            "prompt_n": 812,
            "prompt_ms": 15000.0,
            "predicted_n": 31,
            "predicted_ms": 3100.0,
            "predicted_per_second": 10.0,
        },
    }


class TestPrepare:
    def test_builds_the_agents_request_from_its_own_contract_functions(self, probe):
        glue = contract(probe, {})
        prepared = glue.prepare("What is the hotel limit?", {"passages": PASSAGES})
        assert prepared.url == "http://llm:8080/v1/chat/completions"
        assert prepared.timeout == 900.0
        assert prepared.labels == ["S1", "S2", "S3"]
        assert prepared.sources_by_label["S2"] == {
            "doc_id": "d2",
            "chunk_id": "d2:7",
            "title": "2_Employee_Handbook.md",
            "page": 3,
        }
        assert prepared.retrieved_titles == ["4_Expense_Policy.md", "2_Employee_Handbook.md"]
        assert prepared.schema["properties"]["sources"]["items"]["enum"] == ["S1", "S2", "S3"]
        payload = prepared.payload
        assert set(payload) == {
            "model",
            "messages",
            "max_tokens",
            "temperature",
            "stream",
            "response_format",
        }
        assert payload["model"] == "qwen3-4b"
        assert payload["max_tokens"] == 1536
        assert payload["temperature"] == 0.0
        assert payload["stream"] is False
        assert payload["messages"][0] == {"role": "system", "content": "rules for 3 labels"}
        assert "[S1] 4_Expense_Policy.md" in payload["messages"][1]["content"]

    def test_without_passages_the_store_text_is_the_context_and_nothing_can_be_cited(self, probe):
        prepared = contract(probe, {}).prepare(
            "hello", {"query": "hello", "data": "Documents in the store: ..."}
        )
        assert prepared.labels == []
        assert prepared.sources_by_label == {}
        assert "sources" not in prepared.schema["properties"]
        assert "Documents in the store" in prepared.payload["messages"][1]["content"]

    def test_a_failed_search_is_a_retrieval_error_like_the_rag_pipeline(self, probe):
        glue = contract(probe, {})
        assert (
            glue.retrieval_error({"data": "Error", "error": "Failed to query knowledge store"})
            == "Failed to query knowledge store"
        )
        assert glue.retrieval_error({"passages": PASSAGES, "error": "ignored"}) is None
        assert glue.retrieval_error({"data": ""}) is None


class TestProbeItem:
    def test_records_the_raw_reply_with_its_timings(self, probe):
        glue = contract(probe, {"What is the hotel limit?": {"passages": PASSAGES}})
        sent = []
        content = json.dumps({"status": "ok", "answer": "$250 per night.", "sources": ["S1"]})

        def post(url, payload, timeout):
            sent.append((url, payload, timeout))
            return llama_response(content, reasoning_content="")

        ticks = iter([10.0, 22.5])
        record = asyncio.run(
            probe.probe_item(
                {"id": "exp-01", "question": "What is the hotel limit?"},
                glue,
                post,
                clock=lambda: next(ticks),
            )
        )
        assert sent[0][0] == "http://llm:8080/v1/chat/completions"
        assert record["id"] == "exp-01"
        assert record["content"] == content
        assert record["finish_reason"] == "stop"
        assert record["wall_s"] == 12.5
        assert record["max_tokens"] == 1536
        assert record["usage"]["completion_tokens"] == 31
        assert record["timings"]["predicted_per_second"] == 10.0
        assert check_reply(record)[1] is None

    def test_a_retrieval_failure_never_reaches_the_model(self, probe):
        glue = contract(
            probe, {"q": RuntimeError("store down"), "r": {"data": "", "error": "Invalid request"}}
        )
        posted = []
        first = asyncio.run(
            probe.probe_item({"id": "a", "question": "q"}, glue, lambda *a: posted.append(a))
        )
        second = asyncio.run(
            probe.probe_item({"id": "b", "question": "r"}, glue, lambda *a: posted.append(a))
        )
        assert first == {"id": "a", "error_stage": "retrieval", "error": "RuntimeError: store down"}
        assert second == {"id": "b", "error_stage": "retrieval", "error": "Invalid request"}
        assert posted == []

    def test_a_server_error_is_recorded_as_an_llm_failure(self, probe):
        glue = contract(probe, {"q": {"passages": PASSAGES}})

        def post(url, payload, timeout):
            raise RuntimeError("HTTP 400: the request exceeds the available context size")

        record = asyncio.run(probe.probe_item({"id": "a", "question": "q"}, glue, post))
        assert record["error_stage"] == "llm"
        assert (
            record["error"]
            == "RuntimeError: HTTP 400: the request exceeds the available context size"
        )
        assert record["labels"] == ["S1", "S2", "S3"]


def test_reply_from_response_tolerates_a_missing_choice(probe):
    assert probe.reply_from_response({"error": {"message": "x"}}, 1.23456) == {
        "content": None,
        "reasoning_content": None,
        "finish_reason": None,
        "usage": None,
        "timings": None,
        "wall_s": 1.235,
    }


def test_run_probe_warms_up_unscored_and_emits_one_line_per_question(probe):
    results = {
        "warm": {"passages": PASSAGES},
        "q1": {"passages": PASSAGES},
        "q2": {"passages": PASSAGES[:1]},
    }
    glue = contract(probe, results)
    emitted = []

    def post(url, payload, timeout):
        return llama_response(json.dumps({"status": "ok", "answer": "x", "sources": []}))

    job = {
        "warmup": "warm",
        "items": [{"id": "i1", "question": "q1"}, {"id": "i2", "question": "q2"}],
    }
    count = asyncio.run(probe.run_probe(job, glue, emitted.append, post))
    assert count == 2
    assert [record["id"] for record in emitted] == ["i1", "i2"]
    assert glue.store_client.queries == ["warm", "q1", "q2"]


def test_main_reads_the_job_from_stdin_and_writes_json_lines(probe, monkeypatch, capsys):
    glue = contract(probe, {"q1": {"passages": PASSAGES}})
    monkeypatch.setattr(probe, "load_agent_contract", lambda app_dir: glue)
    monkeypatch.setattr(probe, "post_json", lambda url, payload, timeout: llama_response("{}"))
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"items": [{"id": "i1", "question": "q1"}]}))
    )
    assert probe.main() == 0
    captured = capsys.readouterr()
    assert [json.loads(line)["id"] for line in captured.out.splitlines()] == ["i1"]
    assert "[  1/1] i1 stop" in captured.err


AGENT_CHECK = """
import importlib, importlib.util, json, sys
sys.path.insert(0, sys.argv[1])
spec = importlib.util.spec_from_file_location("agent_contract_probe", sys.argv[2])
probe = importlib.util.module_from_spec(spec)
sys.modules["agent_contract_probe"] = probe
spec.loader.exec_module(probe)
contract = importlib.import_module("ai_agents.answer_contract")
agent = importlib.import_module("ai_agents.decision_making_agent")
glue = probe.AgentContract(contract, agent, None)
passages = json.loads(sys.argv[3])
with_passages = glue.prepare("What is the US hotel limit per night?", {"passages": passages})
without = glue.prepare("hello", {"data": ""})
print(json.dumps({
    "labels": with_passages.labels,
    "sources": with_passages.sources_by_label,
    "schema": with_passages.schema,
    "schema_without_passages": without.schema,
    "payload": with_passages.payload,
    "url": with_passages.url,
}))
"""


def test_the_probe_drives_the_real_agent_contract_and_the_checker_accepts_its_schema():
    env = {**os.environ, "LLM_VLLM_URL": "http://llm:8080/v1", "LLM_VLLM_MODEL": "qwen3-4b"}
    completed = subprocess.run(
        [sys.executable, "-c", AGENT_CHECK, str(AGENT_APP), str(PROBE_PATH), json.dumps(PASSAGES)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        env=env,
    )
    if completed.returncode != 0 and "ModuleNotFoundError" in completed.stderr:
        pytest.skip(
            f"the agent's modules do not import here: {completed.stderr.strip().splitlines()[-1]}"
        )
    assert completed.returncode == 0, completed.stderr
    found = json.loads(completed.stdout.strip().splitlines()[-1])
    assert found["labels"] == ["S1", "S2", "S3"]
    assert found["sources"]["S1"]["chunk_id"] == "d4:2"
    assert found["url"] == "http://llm:8080/v1/chat/completions"
    assert found["payload"]["response_format"]["json_schema"]["schema"] == found["schema"]
    schema = found["schema"]
    good = {"status": "ok", "answer": "$250 per night.", "sources": ["S1"]}
    assert check_reply({"content": json.dumps(good), "schema": schema})[1] is None
    assert (
        check_reply({"content": json.dumps({**good, "sources": ["S7"]}), "schema": schema})[1]
        == "schema"
    )
    refusal = {"status": "not_found", "answer": "The documents do not say."}
    assert (
        check_reply({"content": json.dumps(refusal), "schema": found["schema_without_passages"]})[1]
        is None
    )
