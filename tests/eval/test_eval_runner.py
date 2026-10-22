import asyncio
import importlib.util
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from eval_report import build_report, question_record
from eval_scoring import ROUTE_AGENT, ROUTE_DIRECT, ROUTE_NONE
from horus_bench_kit.target import Target

RUNNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "eval" / "run-eval.py"


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location("run_eval", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_eval"] = module
    spec.loader.exec_module(module)
    return module


class FakeSocket:
    def __init__(self, events, then="close"):
        self.events = [json.dumps(event) for event in events]
        self.then = then

    async def recv(self):
        await asyncio.sleep(0)
        if self.events:
            return self.events.pop(0)
        if self.then == "hang":
            await asyncio.Event().wait()
        raise ConnectionError("socket closed")


def fake_connect(socket, urls):
    @asynccontextmanager
    async def connect(url, **_options):
        urls.append(url)
        yield socket

    return connect


@pytest.fixture
def mas(monkeypatch):
    state = {"new_task": {"task_id": "t-1"}, "task": {"status": "running"}, "calls": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"].append((request.method, request.url.path))
        if request.url.path == "/conversations/create-conversation/":
            return httpx.Response(200, json={"conversation_id": 7})
        if request.url.path == "/tasks/new_task/":
            state["payload"] = json.loads(request.content)
            body = state["new_task"]
            return httpx.Response(body.pop("_status", 200), json=body)
        if request.url.path == "/tasks/t-1":
            return httpx.Response(200, json=state["task"])
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **kw: real_async_client(*a, transport=transport, **kw)
    )
    return state


def make_client(runner, socket, urls, event_timeout=2.0):
    client = runner.EvalClient(
        "http://mas:8000",
        "http://ks:8080",
        event_timeout=event_timeout,
        submit_timeout=5.0,
        poll_interval=0.01,
        connect=fake_connect(socket, urls),
    )
    client.token = "jwt"
    return client


def agent_events(retrieval_metadata, content="$250 per night."):
    return [
        {"type": "task_step", "step_type": "retrieval.start", "metadata": {"query": "hotel"}},
        {"type": "task_step", "step_type": "retrieval.results", "metadata": retrieval_metadata},
        {
            "type": "task_step",
            "step_type": "reasoning.start",
            "metadata": {"model": "qwen3-4b", "device": "cpu"},
        },
        {"type": "task_step", "step_type": "reasoning.delta", "metadata": {"chunk": "$250"}},
        {
            "type": "task_complete",
            "content": content,
            "agent_name": "Finance-Analyst",
            "skill_used": "research",
        },
    ]


AGENT_EVENTS = agent_events({"chunk_count": 1, "chunks": []})
TITLED_AGENT_EVENTS = agent_events(
    {"chunk_count": 2, "chunks": ["4_Expense_Policy.md", "2_Employee_Handbook.md"]}
)
WATCHDOG_EVENT = {
    "type": "agent",
    "content": "This request exceeded the maximum processing time (1800s) and was stopped. "
    "Try a shorter or simpler question, or ask an administrator to raise TASK_TIMEOUT "
    "for long-running models.",
}


class TestAsk:
    def test_agent_answer_arrives_over_the_websocket(self, runner, mas):
        urls = []
        client = make_client(runner, FakeSocket(AGENT_EVENTS), urls)
        outcome = asyncio.run(client.ask("What is the hotel limit per night in the US?", "eval-x"))
        assert urls == ["ws://mas:8000/chat/7/?token=jwt"]
        assert mas["payload"] == {
            "demand": "What is the hotel limit per night in the US?",
            "conversation_id": 7,
            "skills_required": [],
            "mode": "auto",
        }
        assert outcome["status"] == "ok"
        assert outcome["observed_route"] == ROUTE_AGENT
        assert outcome["timing_source"] == "websocket"
        assert outcome["answer"] == "$250 per night."
        assert outcome["retrieval_steps"] == 1
        assert outcome["retrieved_sources"] is None
        assert outcome["cited_sources"] is None
        assert outcome["models"] == ["qwen3-4b"]
        assert outcome["ttft_s"] is not None
        assert outcome["total_s"] >= outcome["ttft_s"]
        assert outcome["task_id"] == "t-1"

    def test_direct_answer_comes_back_in_the_http_response(self, runner, mas):
        mas["new_task"] = {"message": "Processing complete", "result": "4"}
        client = make_client(runner, FakeSocket([], then="hang"), [])
        outcome = asyncio.run(client.ask("What is 2 + 2?", "eval-x"))
        assert outcome["status"] == "ok"
        assert outcome["observed_route"] == ROUTE_DIRECT
        assert outcome["answer"] == "4"
        assert outcome["timing_source"] == "http"
        assert outcome["total_s"] == outcome["submit_http_s"]

    def test_message_without_a_task_is_recorded_as_no_route(self, runner, mas):
        mas["new_task"] = {"message": "No agents are currently registered with the orchestrator."}
        client = make_client(runner, FakeSocket([], then="hang"), [])
        outcome = asyncio.run(client.ask("What is FinCorp's CEO?", "eval-x"))
        assert outcome["observed_route"] == ROUTE_NONE
        assert outcome["answer"].startswith("No agents")

    def test_queued_task_answer_arrives_over_the_websocket(self, runner, mas):
        mas["new_task"] = {
            "_status": 202,
            "task_id": "t-1",
            "status": "queued",
            "conversation_id": 7,
        }
        events = [
            {
                "type": "task_status",
                "status": "queued",
                "task_id": "t-1",
                "seq": 1,
                "event": "progress",
            },
            {
                "type": "heartbeat",
                "elapsed_s": 5.0,
                "task_id": "t-1",
                "seq": 2,
                "event": "heartbeat",
            },
            *AGENT_EVENTS[:-1],
            {**AGENT_EVENTS[-1], "event": "result", "route": "agent"},
        ]
        client = make_client(runner, FakeSocket(events), [])
        outcome = asyncio.run(client.ask("What is the hotel limit per night in the US?", "eval-x"))
        assert outcome["status"] == "ok"
        assert outcome["task_id"] == "t-1"
        assert outcome["observed_route"] == ROUTE_AGENT
        assert outcome["answer"] == "$250 per night."
        assert outcome["timing_source"] == "websocket"

    def test_direct_answer_of_a_queued_task_comes_over_the_websocket(self, runner, mas):
        mas["new_task"] = {
            "_status": 202,
            "task_id": "t-1",
            "status": "queued",
            "conversation_id": 7,
        }
        events = [{"type": "agent", "content": "4", "event": "result", "route": "direct_answer"}]
        client = make_client(runner, FakeSocket(events), [])
        outcome = asyncio.run(client.ask("What is 2 + 2?", "eval-x"))
        assert outcome["status"] == "ok"
        assert outcome["observed_route"] == ROUTE_DIRECT
        assert outcome["answer"] == "4"

    def test_unroutable_queued_task_is_recorded_as_no_route(self, runner, mas):
        mas["new_task"] = {
            "_status": 202,
            "task_id": "t-1",
            "status": "queued",
            "conversation_id": 7,
        }
        events = [
            {
                "type": "agent",
                "content": "No agents are currently registered with the orchestrator.",
                "event": "error",
                "status": "failed",
                "route": "none",
            }
        ]
        client = make_client(runner, FakeSocket(events), [])
        outcome = asyncio.run(client.ask("What is FinCorp's CEO?", "eval-x"))
        assert outcome["observed_route"] == ROUTE_NONE
        assert outcome["answer"].startswith("No agents")

    def test_dropped_websocket_falls_back_to_polling_the_task(self, runner, mas):
        mas["task"] = {"status": "completed", "result": "$250 per night."}
        client = make_client(runner, FakeSocket(TITLED_AGENT_EVENTS[:2]), [])
        outcome = asyncio.run(client.ask("hotel?", "eval-x"))
        assert outcome["status"] == "ok"
        assert outcome["timing_source"] == "poll"
        assert outcome["answer"] == "$250 per night."
        assert outcome["retrieved_sources"] == [["4_Expense_Policy.md", "2_Employee_Handbook.md"]]
        assert ("GET", "/tasks/t-1") in mas["calls"]

    def test_task_canceled_while_polling_is_a_timeout(self, runner, mas):
        mas["task"] = {"status": "canceled", "result": None}
        client = make_client(runner, FakeSocket([]), [])
        outcome = asyncio.run(client.ask("hotel?", "eval-x"))
        assert outcome["status"] == "timeout"
        assert outcome["error"] == "task canceled"

    def test_failed_task_is_an_error(self, runner, mas):
        mas["task"] = {"status": "failed", "result": None}
        client = make_client(runner, FakeSocket([]), [])
        outcome = asyncio.run(client.ask("hotel?", "eval-x"))
        assert outcome["status"] == "error"
        assert outcome["error"] == "task failed"

    def test_no_answer_before_the_deadline_is_a_timeout(self, runner, mas):
        events = TITLED_AGENT_EVENTS[:2]
        client = make_client(runner, FakeSocket(events, then="hang"), [], event_timeout=0.2)
        outcome = asyncio.run(client.ask("hotel?", "eval-x"))
        assert outcome["status"] == "timeout"
        assert not outcome.get("answer")
        assert outcome["retrieved_sources"] == [["4_Expense_Policy.md", "2_Employee_Handbook.md"]]

    def test_rejected_submission_is_an_error(self, runner, mas):
        mas["new_task"] = {"_status": 500, "detail": "boom"}
        client = make_client(runner, FakeSocket([], then="hang"), [])
        outcome = asyncio.run(client.ask("hotel?", "eval-x"))
        assert outcome["status"] == "error"
        assert outcome["error"].startswith("new_task failed: RuntimeError: HTTP 500")

    def test_live_agent_events_give_a_correct_answer_with_an_unscored_source(
        self, runner, mas, items
    ):
        item = next(i for i in items if i["id"] == "exp-01")
        client = make_client(runner, FakeSocket(AGENT_EVENTS), [])
        record = question_record(item, asyncio.run(client.ask(item["question"], "eval-x")))
        assert record["answer_correct_auto"] is True
        assert record["source_correct_auto"] is None
        assert record["source_basis"] is None
        assert record["route_correct"] is True

    def test_titled_retrieval_events_score_the_source_by_rank(self, runner, mas, items):
        item = next(i for i in items if i["id"] == "exp-01")
        client = make_client(runner, FakeSocket(TITLED_AGENT_EVENTS), [])
        record = question_record(item, asyncio.run(client.ask(item["question"], "eval-x")))
        assert record["source_correct_auto"] is True
        assert record["source_ranks"] == [1]

    def test_direct_question_sent_to_an_agent_that_retrieved_has_a_wrong_source(
        self, runner, mas, items
    ):
        item = next(i for i in items if i["category"] == "direct")
        events = agent_events({"chunk_count": 1, "chunks": []}, content="Hi!")
        client = make_client(runner, FakeSocket(events), [])
        record = question_record(item, asyncio.run(client.ask(item["question"], "eval-x")))
        assert record["route_correct"] is False
        assert record["source_correct_auto"] is False

    def test_watchdog_message_on_the_websocket_is_recorded_as_a_timeout(self, runner, mas, items):
        item = next(i for i in items if i["id"] == "exp-01")
        client = make_client(runner, FakeSocket([AGENT_EVENTS[1], WATCHDOG_EVENT]), [])
        record = question_record(item, asyncio.run(client.ask(item["question"], "eval-x")))
        assert record["status"] == "timeout"
        assert record["fallback"] == "task_timeout"
        assert record["answer_correct_auto"] is False


class TestEnsureCorpus:
    @pytest.fixture
    def knowledge_store(self, runner, monkeypatch, testset):
        state = {"titles": list(testset["corpus"]), "scans": 0, "headers": []}

        def handler(request):
            if request.url.path == "/file":
                return httpx.Response(
                    200, json={"documents": [{"title": t} for t in state["titles"]]}
                )
            if request.url.path == "/corpus/scan":
                state["scans"] += 1
                state["headers"].append(request.headers.get("X-Corpus-Token"))
                state["titles"] = list(testset["corpus"])
                return httpx.Response(202, json={"state": "running"})
            if request.url.path == "/corpus/status":
                return httpx.Response(200, json={"state": "completed"})
            return httpx.Response(404, json={})

        transport = httpx.MockTransport(handler)
        real_async_client = httpx.AsyncClient
        monkeypatch.setattr(
            httpx, "AsyncClient", lambda *a, **kw: real_async_client(*a, transport=transport, **kw)
        )
        monkeypatch.setattr(runner, "CORPUS_POLL_INTERVAL_S", 0.0)
        return state

    def test_loaded_corpus_passes_without_a_scan(self, runner, knowledge_store, testset):
        assert asyncio.run(runner.ensure_corpus("http://ks:8080", testset, "token")) is True
        assert knowledge_store["scans"] == 0

    def test_missing_document_fails_without_a_scan_token(
        self, runner, knowledge_store, testset, capsys
    ):
        knowledge_store["titles"] = knowledge_store["titles"][1:]
        assert asyncio.run(runner.ensure_corpus("http://ks:8080", testset, None)) is False
        assert (
            "1_Q4_2025_Financial_Report.md is not in the knowledge store" in capsys.readouterr().out
        )

    def test_missing_document_triggers_a_corpus_scan_with_the_token(
        self, runner, knowledge_store, testset
    ):
        knowledge_store["titles"] = []
        assert asyncio.run(runner.ensure_corpus("http://ks:8080", testset, "s3cret")) is True
        assert knowledge_store["scans"] == 1
        assert knowledge_store["headers"] == ["s3cret"]

    def test_duplicate_uploads_fail_the_check(self, runner, knowledge_store, testset):
        knowledge_store["titles"] = knowledge_store["titles"] + ["4_Expense_Policy.md"]
        assert asyncio.run(runner.ensure_corpus("http://ks:8080", testset, None)) is False


class TestRetrieve:
    def patch_client(self, monkeypatch, handler):
        transport = httpx.MockTransport(handler)
        real_client = httpx.Client
        monkeypatch.setattr(
            httpx, "Client", lambda *a, **kw: real_client(*a, transport=transport, **kw)
        )

    def test_titles_of_the_top_results_become_the_sources(self, runner, monkeypatch):
        seen = {}

        def handler(request):
            seen.update(request.url.params)
            return httpx.Response(200, json={"metadatas": [[{"title": "4_Expense_Policy.md"}]]})

        self.patch_client(monkeypatch, handler)
        outcome = runner.retrieve("http://ks:8080", "hotel limit?", 10)
        assert seen == {"query": "hotel limit?", "n_results": "10"}
        assert outcome["status"] == "ok"
        assert outcome["retrieved_sources"] == [["4_Expense_Policy.md"]]
        assert outcome["mode"] == "retrieval"

    def test_whole_corpus_with_the_expected_document_last_is_not_correct(
        self, runner, monkeypatch, items
    ):
        item = next(i for i in items if i["id"] == "exp-01")
        ranked = [
            "1_Q4_2025_Financial_Report.md",
            "2_Employee_Handbook.md",
            "3_Compliance_Guidelines.md",
            "5_IT_Security_Policy.md",
            "4_Expense_Policy.md",
        ]
        metadatas = [[{"title": title} for title in ranked]]
        self.patch_client(
            monkeypatch, lambda request: httpx.Response(200, json={"metadatas": metadatas})
        )
        record = question_record(item, runner.retrieve("http://ks:8080", item["question"], 10))
        assert record["source_ranks"] == [5]
        assert record["source_correct_auto"] is False

    def test_passages_count_once_per_document_at_their_best_rank(self, runner, monkeypatch, items):
        item = next(i for i in items if i["id"] == "exp-01")
        passages = [
            ("doc-1:2", "doc-1", "1_Q4_2025_Financial_Report.md"),
            ("doc-1:0", "doc-1", "1_Q4_2025_Financial_Report.md"),
            ("doc-4:3", "doc-4", "4_Expense_Policy.md"),
            ("doc-1:1", "doc-1", "1_Q4_2025_Financial_Report.md"),
            ("doc-4:0", "doc-4", "4_Expense_Policy.md"),
        ]
        body = {
            "ids": [[chunk_id for chunk_id, _doc, _title in passages]],
            "metadatas": [
                [
                    {"doc_id": doc_id, "title": title, "chunk_index": int(chunk_id[-1])}
                    for chunk_id, doc_id, title in passages
                ]
            ],
        }
        self.patch_client(monkeypatch, lambda request: httpx.Response(200, json=body))
        record = question_record(item, runner.retrieve("http://ks:8080", item["question"], 50))
        assert record["retrieved_sources"] == [
            ["1_Q4_2025_Financial_Report.md", "4_Expense_Policy.md"]
        ]
        assert record["source_ranks"] == [2]

    def test_the_default_depth_reaches_every_passage_of_the_demo_corpus(self, runner):
        args = runner.build_parser().parse_args(["--label", "x", "--mode", "retrieval"])
        assert args.top_k >= 22

    def test_no_results_is_an_empty_ranking(self, runner, monkeypatch):
        self.patch_client(monkeypatch, lambda request: httpx.Response(404, json={"error": "none"}))
        outcome = runner.retrieve("http://ks:8080", "anything", 10)
        assert outcome["status"] == "ok"
        assert outcome["retrieved_sources"] == [[]]

    def test_server_error_is_recorded(self, runner, monkeypatch):
        self.patch_client(monkeypatch, lambda request: httpx.Response(500, json={}))
        outcome = runner.retrieve("http://ks:8080", "anything", 10)
        assert outcome["status"] == "error"
        assert outcome["error"] == "HTTP 500"


class TestArguments:
    def parse(self, runner, *argv):
        return runner.build_parser().parse_args(list(argv))

    def test_defaults_target_a_local_stack_and_the_shipped_testset(self, runner):
        args = self.parse(runner, "--label", "cpu16")
        assert args.mode == "chat"
        assert Path(args.testset).name == "testset.yaml"
        assert Path(args.out_dir).name == "benchmarks"
        assert runner.argument_errors(args) == []

    def test_label_is_required_unless_resummarizing(self, runner):
        assert runner.argument_errors(self.parse(runner)) == ["--label is required"]
        assert runner.argument_errors(self.parse(runner, "--resummarize", "x.json")) == []

    def test_model_hash_and_filters_are_checked(self, runner):
        args = self.parse(
            runner,
            "--label",
            "x",
            "--model-sha256",
            "abc",
            "--category",
            "lookup,trivia",
            "--limit",
            "0",
        )
        assert runner.argument_errors(args) == [
            "--model-sha256 must be 64 hexadecimal characters",
            "--category must be among lookup, numeric, multi_hop, not_in_corpus, direct",
            "--limit must be at least 1",
        ]

    def test_retrieval_mode_skips_questions_without_a_source(self, runner, testset):
        args = self.parse(runner, "--label", "x", "--mode", "retrieval")
        chosen = runner.chosen_items(args, testset)
        assert len(chosen) == 84
        assert {item["category"] for item in chosen} == {"lookup", "numeric", "multi_hop"}

    def test_id_filter_keeps_testset_order(self, runner, testset):
        args = self.parse(runner, "--label", "x", "--ids", "hr-01,fin-01")
        assert [item["id"] for item in runner.chosen_items(args, testset)] == ["fin-01", "hr-01"]


class TestWarmup:
    @pytest.fixture
    def asked(self, runner, monkeypatch):
        questions = []

        class FakeEvalClient:
            def __init__(self, *_args, **_kwargs):
                self.token = None

            async def wait_for_agent(self, timeout):
                return "agent-1"

            async def ask(self, question, conversation_name):
                questions.append(question)
                return {
                    "mode": "chat",
                    "status": "ok",
                    "answer": "$250",
                    "timing_source": "websocket",
                }

        monkeypatch.setattr(runner, "EvalClient", FakeEvalClient)
        return questions

    def run(self, runner, testset, *argv):
        args = runner.build_parser().parse_args(
            ["--label", "x", "--skip-corpus-check", "--token", "jwt", *argv]
        )
        items = runner.chosen_items(args, testset)
        records = asyncio.run(runner.run_questions(args, testset, items, lambda _records: None))
        return items, records

    def test_warmup_question_is_not_in_the_testset(self, runner, items):
        assert runner.WARMUP_QUESTION not in {item["question"] for item in items}

    def test_warmup_is_asked_before_the_scored_questions(self, runner, testset, asked):
        items, records = self.run(runner, testset, "--ids", "fin-01,exp-01")
        assert asked == [runner.WARMUP_QUESTION] + [item["question"] for item in items]
        assert [record["id"] for record in records] == ["fin-01", "exp-01"]

    def test_no_warmup_asks_only_the_scored_questions(self, runner, testset, asked):
        items, _records = self.run(runner, testset, "--ids", "fin-01", "--no-warmup")
        assert asked == [items[0]["question"]]


class TestResummarizeCommand:
    def test_filled_review_updates_the_summary_in_place(self, runner, monkeypatch, tmp_path, items):
        item = next(i for i in items if i["id"] == "exp-01")
        record = question_record(item, {"mode": "chat", "status": "ok", "answer": "$250"})
        record["review"][0].update(reviewer="ana", answer_correct=True)
        record["review"][1].update(reviewer="ben", answer_correct=True)
        path = tmp_path / "cpu16-2026-10-05.json"
        path.write_text(
            json.dumps(build_report(label="cpu16", run={}, testset={}, records=[record]))
        )
        monkeypatch.setattr(sys, "argv", ["run-eval.py", "--resummarize", str(path)])
        assert runner.main() == 0
        summary = json.loads(path.read_text(encoding="utf-8"))["summary"]["manual_review"]
        assert summary["answer_correct_pct"] == 100.0


class TestProgressLine:
    def test_line_shows_status_time_and_flags(self, runner):
        record = {
            "id": "fin-01",
            "status": "ok",
            "total_s": 12.5,
            "answer_correct_auto": True,
            "source_correct_auto": False,
            "route_correct": None,
            "error": None,
        }
        line = runner.progress_line(1, 100, record)
        assert line.startswith("[  1/100] fin-01")
        assert "12.50s" in line
        assert "answer=yes source=no route=-" in line


class TestTargets:
    def test_both_targets_follow_the_kit_target_protocol(self, runner):
        assert isinstance(runner.ChatTarget(None, "x"), Target)
        assert isinstance(runner.RetrievalTarget("http://ks:8080", 50), Target)

    def test_each_chat_question_gets_its_own_named_conversation(self, runner):
        names = []

        class Client:
            async def ask(self, question, conversation_name):
                names.append(conversation_name)
                return {"mode": "chat", "status": "ok"}

        asyncio.run(runner.ChatTarget(Client(), "cpu16 / q8").ask("Hi?", item_id="direct-01"))
        assert names == ["eval-cpu16-q8-direct-01"]

    def test_the_retrieval_target_queries_the_knowledge_store_through_retrieve(
        self, runner, monkeypatch
    ):
        asked = []

        def retrieve(ks_url, question, top_k):
            asked.append((ks_url, question, top_k))
            return {"mode": "retrieval", "status": "ok"}

        monkeypatch.setattr(runner, "retrieve", retrieve)
        outcome = asyncio.run(
            runner.RetrievalTarget("http://ks:8080", 50).ask("Hotel limit?", item_id="exp-01")
        )
        assert asked == [("http://ks:8080", "Hotel limit?", 50)]
        assert outcome == {"mode": "retrieval", "status": "ok"}


VERIFIED_SHA256 = "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
LLM_CONFIG = {
    "Image": "ghcr.io/ggml-org/llama.cpp:server-b11382",
    "Cmd": [
        "--model",
        "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf",
        "--alias",
        "qwen3-4b",
        "--port",
        "8080",
        "--ctx-size",
        "4096",
        "-ctk",
        "q8_0",
        "-ctv",
        "q8_0",
        "--metrics",
    ],
}
LLM_PROPS = {
    "build_info": "b11382-11fe0215",
    "model_path": "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf",
    "default_generation_settings": {"n_ctx": 4096},
}


def fake_docker(responses, calls=None):
    def docker_text(argv, timeout=30.0):
        if calls is not None:
            calls.append(list(argv))
        for prefix, reply in responses:
            if list(argv[: len(prefix)]) == list(prefix):
                return reply
        return None

    return docker_text


class TestLlamaServerFacts:
    def test_facts_come_from_the_container_config_props_and_verified_hash(
        self, runner, monkeypatch
    ):
        calls = []
        responses = [
            (["inspect"], json.dumps(LLM_CONFIG)),
            (["exec", "llm", "curl"], json.dumps(LLM_PROPS)),
            (["exec", "llm", "cat"], VERIFIED_SHA256 + "\n"),
        ]
        monkeypatch.setattr(runner, "docker_text", fake_docker(responses, calls))
        facts = runner.llama_server_facts("llm")
        assert facts["build"] == "b11382"
        assert facts["port"] == 8080
        assert facts["n_ctx"] == 4096
        assert facts["settings"]["cache_type_k"] == "q8_0"
        assert facts["settings"]["cache_type_v"] == "q8_0"
        assert facts["model_sha256"] == VERIFIED_SHA256
        assert ["exec", "llm", "cat", "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf.sha256"] in calls
        assert ["exec", "llm", "curl", "-fsS", "-m", "10", "http://localhost:8080/props"] in calls

    def test_build_falls_back_to_the_image_tag_when_props_are_unreadable(self, runner, monkeypatch):
        monkeypatch.setattr(
            runner, "docker_text", fake_docker([(["inspect"], json.dumps(LLM_CONFIG))])
        )
        facts = runner.llama_server_facts("llm")
        assert facts["build"] == "b11382"
        assert facts["model_sha256"] is None
        assert facts["model_path"] == "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf"

    def test_no_llm_container_means_no_facts(self, runner, monkeypatch):
        monkeypatch.setattr(runner, "docker_text", fake_docker([]))
        assert runner.llama_server_facts("llm") is None
        assert runner.llama_server_facts(None) is None


class TestModelInfo:
    def parse(self, runner, *argv):
        return runner.build_parser().parse_args(["--label", "x", *argv])

    def test_the_running_server_fills_the_model_fields(self, runner):
        server = {
            "settings": {"alias": "qwen3-4b"},
            "model_path": "/models/q4.gguf",
            "model_sha256": VERIFIED_SHA256,
        }
        model = runner.model_info(self.parse(runner), server)
        assert model["name"] == "qwen3-4b"
        assert model["file"] == "q4.gguf"
        assert model["sha256"] == VERIFIED_SHA256
        assert model["sha256_source"].startswith("llm container")

    def test_given_values_win_over_the_server(self, runner):
        args = self.parse(runner, "--model-file", "own.gguf", "--model-sha256", "AB" * 32)
        model = runner.model_info(
            args, {"model_path": "/models/q4.gguf", "model_sha256": VERIFIED_SHA256}
        )
        assert model["file"] == "own.gguf"
        assert model["sha256"] == "ab" * 32
        assert model["sha256_source"] == "given"

    def test_without_server_or_options_the_model_is_unknown(self, runner):
        model = runner.model_info(self.parse(runner), None)
        assert model == {"name": None, "file": None, "sha256": None, "sha256_source": None}

    def test_new_options_default_to_the_compose_container_names(self, runner):
        args = self.parse(runner)
        assert args.llm_container == "llm"
        assert args.swap_container == "mas"


class TestTestsetInfo:
    def test_the_shipped_testset_is_recorded_relative_to_the_repo(self, runner, testset):
        args = runner.build_parser().parse_args(["--label", "x"])
        assert (
            runner.testset_info(args, testset, testset["items"])["path"]
            == "tests/eval/testset.yaml"
        )

    def test_a_testset_outside_the_repo_keeps_no_part_of_its_folder(
        self, runner, monkeypatch, testset, host_folder, host_folder_leaks
    ):
        monkeypatch.setattr(runner, "file_sha256", lambda path: "0" * 64)
        args = runner.build_parser().parse_args(
            ["--label", "x", "--testset", f"{host_folder}/own-testset.yaml"]
        )
        info = runner.testset_info(args, testset, testset["items"])
        assert info["path"] == "own-testset.yaml"
        assert host_folder_leaks(json.dumps(info)) == []


class TestStackResources:
    def test_docker_host_swap_is_read_inside_a_container(self, runner, monkeypatch):
        meminfo = "SwapTotal: 4194304 kB\nSwapFree: 3145728 kB\n"
        monkeypatch.setattr(
            runner, "docker_text", fake_docker([(["exec", "mas", "cat", "/proc/meminfo"], meminfo)])
        )
        assert runner.docker_host_swap_used_bytes("mas") == 1024 * 1024 * 1024
        assert runner.docker_host_swap_used_bytes(None) is None

    def test_cgroup_peaks_oom_kills_and_page_cache_per_container_with_null_when_unread(
        self, runner, monkeypatch
    ):
        memory_stat = "anon 100\nfile 300\nactive_file 50\ninactive_file 250\nfile_mapped 200\n"
        responses = [
            (["exec", "llm", "cat", "/sys/fs/cgroup/memory.peak"], "5368709120\n"),
            (["exec", "llm", "cat", "/sys/fs/cgroup/memory.events"], "oom 0\noom_kill 0\n"),
            (["exec", "llm", "cat", "/sys/fs/cgroup/memory.stat"], memory_stat),
            (["exec", "agent", "cat", "/sys/fs/cgroup/memory.events"], "oom 2\noom_kill 1\n"),
        ]
        monkeypatch.setattr(runner, "docker_text", fake_docker(responses))
        assert runner.container_cgroup_facts(["llm", "agent", "web_client"]) == {
            "container_lifetime_peak_mem_bytes": {
                "agent": None,
                "llm": 5368709120,
                "web_client": None,
            },
            "container_oom_kills": {"agent": 1, "llm": 0, "web_client": None},
            "container_memory_stat": {
                "agent": None,
                "llm": {
                    "anon": 100,
                    "file": 300,
                    "active_file": 50,
                    "inactive_file": 250,
                    "file_mapped": 200,
                },
                "web_client": None,
            },
        }

    def test_restart_counts_come_from_one_docker_inspect_per_container(self, runner, monkeypatch):
        calls = []
        responses = [
            (["inspect", "--format", "{{.RestartCount}}", "llm"], "0\n"),
            (["inspect", "--format", "{{.RestartCount}}", "agent"], "3\n"),
        ]
        monkeypatch.setattr(runner, "docker_text", fake_docker(responses, calls))
        assert runner.container_restart_counts(["llm", "agent", "web_client"]) == {
            "agent": 3,
            "llm": 0,
            "web_client": None,
        }
        assert [call[-1] for call in calls] == ["agent", "llm", "web_client"]
        assert runner.container_restart_counts([]) == {}

    def test_llama_server_memory_is_read_from_pid_1_of_the_llm_container(self, runner, monkeypatch):
        status = "Name:\tllama-server\nRssAnon:\t 1835008 kB\nRssFile:\t 2490368 kB\n"
        monkeypatch.setattr(
            runner, "docker_text", fake_docker([(["exec", "llm", "cat", "/proc/1/status"], status)])
        )
        assert runner.llm_process_memory("llm") == {
            "name": "llama-server",
            "rss_file_bytes": 2490368 * 1024,
        }
        assert runner.llm_process_memory("vllm") is None
        assert runner.llm_process_memory(None) is None

    def test_sampler_windows_keep_the_peaks_of_one_question(self, runner, monkeypatch):
        usage = iter([{"llm": 100, "mas": 10}, {"llm": 300, "mas": 10}, {"llm": 200, "mas": 10}])
        monkeypatch.setattr(runner, "docker_memory_usage", lambda: next(usage))
        monkeypatch.setattr(runner, "swap_used_bytes", lambda: 0)
        monkeypatch.setattr(runner, "docker_host_swap_used_bytes", lambda container: 4096)
        sampler = runner.ResourceSampler(10.0, "mas")
        sampler.sample()
        sampler.begin_window()
        sampler.sample()
        window = sampler.end_window()
        sampler.sample()
        assert window == {
            "samples": 1,
            "containers_sum_peak_mem_bytes": 310,
            "swap_peak_used_bytes": 0,
            "docker_host_swap_peak_used_bytes": 4096,
        }
        assert sampler.peaks.samples == 3
        assert sampler.peaks.as_dict()["container_peak_mem_bytes"] == {"llm": 300, "mas": 10}
        assert sampler.end_window() is None

    def test_the_start_snapshot_covers_the_containers_seen_before_when_docker_stats_fails(
        self, runner, monkeypatch
    ):
        usage = iter([{"mas": 10, "llm": 100}, {}])
        monkeypatch.setattr(runner, "docker_memory_usage", lambda: next(usage))
        monkeypatch.setattr(runner, "swap_used_bytes", lambda: None)
        monkeypatch.setattr(runner, "docker_host_swap_used_bytes", lambda container: None)
        asked = []
        monkeypatch.setattr(
            runner, "container_cgroup_facts", lambda names: asked.append(names) or {}
        )
        monkeypatch.setattr(runner, "llm_process_memory", lambda container: None)
        monkeypatch.setattr(runner, "llm_mapped_outside_now", lambda container: None)
        sampler = runner.ResourceSampler(60.0, "mas", "llm")
        sampler.sample()
        sampler.mark_questions_start()
        assert asked == [["llm", "mas"]]

    def test_each_sample_reads_the_llm_pages_only_while_llm_runs(self, runner, monkeypatch):
        gib = 2**30
        usage = iter(
            [
                {"llm": 4 * gib, "mas": 5 * gib},
                {"llm": 2 * gib, "mas": 5 * gib + gib // 2},
                {"mas": 6 * gib},
            ]
        )
        monkeypatch.setattr(runner, "docker_memory_usage", lambda: next(usage))
        monkeypatch.setattr(runner, "swap_used_bytes", lambda: None)
        monkeypatch.setattr(runner, "docker_host_swap_used_bytes", lambda container: None)
        outside = iter([0, 2 * gib])
        read = []
        monkeypatch.setattr(
            runner,
            "llm_mapped_outside_now",
            lambda container: read.append(container) or next(outside),
        )
        sampler = runner.ResourceSampler(60.0, "mas", "llm")
        for _ in range(3):
            sampler.sample()
        resources = sampler.peaks.as_dict()
        assert read == ["llm", "llm"]
        assert resources["containers_sum_peak_mem_bytes"] == 9 * gib
        assert resources["stack_peak_mem_bytes"] == 9 * gib + gib // 2
        assert resources["llm_mapped_outside_docker_stats_bytes"] == 2 * gib
        assert resources["samples_without_llm_pages"] == 0

    def test_the_llm_pages_come_from_pid_1_status_and_the_llm_cgroup(self, runner, monkeypatch):
        status = "Name:\tllama-server\nRssFile:\t 2490368 kB\n"
        memory_stat = (
            "anon 100\nfile 300\nactive_file 1048576\ninactive_file 250\nfile_mapped 2097152\n"
        )
        responses = [
            (["exec", "llm", "cat", "/proc/1/status"], status),
            (["exec", "llm", "cat", "/sys/fs/cgroup/memory.stat"], memory_stat),
        ]
        monkeypatch.setattr(runner, "docker_text", fake_docker(responses))
        assert runner.llm_mapped_outside_now("llm") == 2490368 * 1024 - 1048576
        monkeypatch.setattr(runner, "docker_text", fake_docker(responses[:1]))
        assert runner.llm_mapped_outside_now("llm") is None

    def test_finished_sampler_adds_the_cgroup_facts(self, runner, monkeypatch):
        monkeypatch.setattr(runner, "docker_memory_usage", lambda: {"llm": 100})
        monkeypatch.setattr(runner, "swap_used_bytes", lambda: None)
        monkeypatch.setattr(runner, "docker_host_swap_used_bytes", lambda container: None)
        monkeypatch.setattr(
            runner,
            "container_cgroup_facts",
            lambda names: {
                "container_lifetime_peak_mem_bytes": dict.fromkeys(names, 7),
                "container_oom_kills": {},
            },
        )
        monkeypatch.setattr(
            runner, "container_restart_counts", lambda names: dict.fromkeys(names, 0)
        )
        monkeypatch.setattr(runner, "llm_process_memory", lambda container: None)
        sampler = runner.ResourceSampler(60.0)
        sampler.start()
        resources = sampler.finish()
        assert resources["container_peak_mem_bytes"] == {"llm": 100}
        assert resources["container_lifetime_peak_mem_bytes"] == {"llm": 7}
        assert resources["container_oom_kills"] == {}
        assert resources["container_restarts"] == {"llm": 0}
        assert resources["llm_process"] is None
        assert resources["stack_peak_mem_bytes"] is None
        assert resources["at_questions_start"] is None
        assert resources["unsampled_peak_excess_bytes"] is None

    def test_questions_are_checked_against_the_samples_and_p_adds_the_model_pages(
        self, runner, monkeypatch
    ):
        gib = 2**30
        monkeypatch.setattr(
            runner, "docker_memory_usage", lambda: {"knowledge_store": 2 * gib, "llm": 3 * gib}
        )
        monkeypatch.setattr(runner, "swap_used_bytes", lambda: None)
        swaps = iter([gib, gib // 4])
        monkeypatch.setattr(
            runner, "docker_host_swap_used_bytes", lambda container: next(swaps, gib // 2)
        )
        llm_stat = {
            "anon": gib,
            "file": 4 * gib,
            "active_file": 2 * gib,
            "inactive_file": 2 * gib,
            "file_mapped": 2 * gib,
        }
        facts = iter(
            [
                {
                    "container_lifetime_peak_mem_bytes": {
                        "knowledge_store": 5 * gib,
                        "llm": 3 * gib,
                    },
                    "container_oom_kills": {"knowledge_store": 0, "llm": 0},
                    "container_memory_stat": {"knowledge_store": None, "llm": llm_stat},
                },
                {
                    "container_lifetime_peak_mem_bytes": {
                        "knowledge_store": 5 * gib,
                        "llm": 6 * gib,
                    },
                    "container_oom_kills": {"knowledge_store": 0, "llm": 0},
                    "container_memory_stat": {"knowledge_store": None, "llm": llm_stat},
                },
            ]
        )
        asked = []

        def cgroup_facts(names):
            asked.append(names)
            return next(facts)

        processes = []

        def llm_process(container):
            processes.append(container)
            return {"name": "llama-server", "rss_file_bytes": 2 * gib + gib // 8}

        monkeypatch.setattr(runner, "container_cgroup_facts", cgroup_facts)
        monkeypatch.setattr(
            runner, "container_restart_counts", lambda names: dict.fromkeys(names, 0)
        )
        monkeypatch.setattr(runner, "llm_process_memory", llm_process)
        outside = iter([2 * gib])
        monkeypatch.setattr(runner, "llm_mapped_outside_now", lambda container: next(outside, 0))
        sampler = runner.ResourceSampler(60.0, "mas", "llm")
        sampler.sample()
        sampler.mark_questions_start()
        sampler.sample()
        sampler.start()
        resources = sampler.finish()
        assert asked == [["knowledge_store", "llm"], ["knowledge_store", "llm"]]
        assert processes == ["llm", "llm"]
        assert (
            resources["at_questions_start"]["container_lifetime_peak_mem_bytes"]["llm"] == 3 * gib
        )
        assert resources["at_questions_start"]["docker_host_swap_used_bytes"] == gib // 4
        assert (
            resources["at_questions_start"]["llm_process"]["rss_file_bytes"] == 2 * gib + gib // 8
        )
        assert resources["unsampled_peak_excess_bytes"] == {"llm": gib}
        assert resources["docker_host_swap_peak_used_bytes"] == gib
        assert resources["docker_host_swap_growth_bytes"] == gib // 4
        assert resources["containers_sum_peak_mem_bytes"] == 5 * gib
        assert resources["llm_mapped_outside_docker_stats_bytes"] == 2 * gib
        assert resources["stack_peak_mem_bytes"] == 7 * gib


class FakeSampler:
    def __init__(self):
        self.windows = 0
        self.starts = 0

    def mark_questions_start(self):
        self.starts += 1

    def begin_window(self):
        self.windows += 1

    def end_window(self):
        return {"samples": 2, "containers_sum_peak_mem_bytes": 8 * 2**30}


class TestQuestionProbes:
    def test_probes_record_server_usage_and_question_resources(self, runner, monkeypatch):
        scrapes = iter(
            [
                {"llamacpp:prompt_tokens_total": 100.0, "llamacpp:prompt_seconds_total": 2.0},
                {"llamacpp:prompt_tokens_total": 1100.0, "llamacpp:prompt_seconds_total": 22.0},
            ]
        )
        monkeypatch.setattr(runner, "read_llm_counters", lambda container, port: next(scrapes))
        sampler = FakeSampler()
        probes = runner.QuestionProbes(sampler, {"container": "llm", "port": 8080})
        outcome = {}
        asyncio.run(probes.before())
        asyncio.run(probes.after(outcome))
        assert outcome["llm"]["prompt_tokens"] == 1000
        assert outcome["llm"]["prompt_s"] == 20.0
        assert outcome["llm"]["prompt_tps"] == 50.0
        assert outcome["resources"]["samples"] == 2
        assert sampler.windows == 1

    def test_probes_without_a_server_or_sampler_add_nothing(self, runner):
        probes = runner.QuestionProbes(None, None)
        outcome = {}
        asyncio.run(probes.start())
        asyncio.run(probes.before())
        asyncio.run(probes.after(outcome))
        assert outcome == {}

    def test_start_takes_the_snapshot_before_the_first_question(self, runner):
        sampler = FakeSampler()
        asyncio.run(runner.QuestionProbes(sampler, None).start())
        assert sampler.starts == 1
        assert sampler.windows == 0

    def test_probes_record_the_router_decision_of_the_question(self, runner, monkeypatch):
        scrapes = iter(
            [
                {"embedding": {"count": 4.0, "seconds": 0.05}},
                {"embedding": {"count": 5.0, "seconds": 0.062}},
            ]
        )
        urls = []

        def read(mas_url):
            urls.append(mas_url)
            return next(scrapes)

        monkeypatch.setattr(runner, "read_routing_decisions", read)
        probes = runner.QuestionProbes(None, None, "http://localhost:8000")
        outcome = {}
        asyncio.run(probes.before())
        asyncio.run(probes.after(outcome))
        assert outcome == {
            "routing_decision": {"decisions": 1, "methods": {"embedding": 1}, "seconds": 0.012}
        }
        assert urls == ["http://localhost:8000", "http://localhost:8000"]

    def test_router_metrics_are_read_from_the_mas_metrics_endpoint(self, runner, monkeypatch):
        text = 'mas_routing_decision_seconds_count{method="rules"} 2.0\n'
        replies = {
            "http://mas:8000/metrics": httpx.Response(
                200, text="# TYPE mas_routing_decision_seconds histogram\n" + text
            ),
            "http://old-mas:8000/metrics": httpx.Response(404),
        }

        def get(url, timeout):
            if url not in replies:
                raise httpx.ConnectError("refused")
            return replies[url]

        monkeypatch.setattr(runner.httpx, "get", get)
        assert runner.read_routing_decisions("http://mas:8000/") == {
            "rules": {"count": 2.0, "seconds": 0.0}
        }
        assert runner.read_routing_decisions("http://old-mas:8000") is None
        assert runner.read_routing_decisions("http://down:8000") is None

    def test_every_scored_question_goes_through_the_probes(self, runner, testset, monkeypatch):
        class FakeEvalClient:
            def __init__(self, *_args, **_kwargs):
                self.token = None

            async def wait_for_agent(self, timeout):
                return "agent-1"

            async def ask(self, question, conversation_name):
                return {
                    "mode": "chat",
                    "status": "ok",
                    "answer": "$250",
                    "timing_source": "websocket",
                }

        class CountingProbes:
            def __init__(self):
                self.calls = []

            async def start(self):
                self.calls.append("start")

            async def before(self):
                self.calls.append("before")

            async def after(self, outcome):
                self.calls.append("after")
                outcome["llm"] = {"prompt_s": 1.0}

        monkeypatch.setattr(runner, "EvalClient", FakeEvalClient)
        args = runner.build_parser().parse_args(
            [
                "--label",
                "x",
                "--skip-corpus-check",
                "--token",
                "jwt",
                "--ids",
                "fin-01,exp-01",
                "--no-warmup",
            ]
        )
        probes = CountingProbes()
        items = runner.chosen_items(args, testset)
        records = asyncio.run(
            runner.run_questions(args, testset, items, lambda _records: None, probes)
        )
        assert probes.calls == ["start", "before", "after", "before", "after"]
        assert [record["llm"] for record in records] == [{"prompt_s": 1.0}, {"prompt_s": 1.0}]


class TestMachineInfo:
    def test_host_facts_overrides_docker_and_gpu(self, runner, monkeypatch):
        collected = {
            "cpu_model": ("AMD Ryzen 5 5600U", "/proc/cpuinfo"),
            "physical_cores": (6, "/proc/cpuinfo"),
            "ram_total_bytes": (16 * 2**30, "/proc/meminfo"),
            "disk_type": ("NVMe SSD", "lsblk"),
        }
        monkeypatch.setattr(runner.host, "collect_host", lambda path: collected)
        monkeypatch.setattr(runner.pipeline, "gpu_info", lambda: {"error": "nvidia-smi not found"})
        args = runner.build_parser().parse_args(
            ["--label", "x", "--reference", "cpu16", "--ram-speed", "3200 MT/s"]
        )
        machine = runner.machine_info(args, {"mem_total_bytes": 16 * 2**30})
        assert machine["reference"] == "cpu16"
        assert machine["cpu_model"] == "AMD Ryzen 5 5600U"
        assert machine["ram_speed"] == "3200 MT/s"
        assert machine["sources"]["ram_speed"] == "given"
        assert machine["docker"] == {"mem_total_bytes": 16 * 2**30}
        assert machine["gpu"] is None


class TestMainAgainstAStack:
    def test_chat_run_records_server_facts_usage_and_machine(self, runner, monkeypatch, tmp_path):
        facts = {
            "container": "llm",
            "port": 8080,
            "build": "b11382",
            "settings": {"alias": "qwen3-4b", "cache_type_k": "f16", "cache_type_v": "f16"},
            "model_path": "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf",
            "model_sha256": VERIFIED_SHA256,
        }
        scrapes = iter(
            [
                {"llamacpp:prompt_tokens_total": 0.0, "llamacpp:prompt_seconds_total": 0.0},
                {"llamacpp:prompt_tokens_total": 900.0, "llamacpp:prompt_seconds_total": 18.0},
                {"llamacpp:prompt_tokens_total": 900.0, "llamacpp:prompt_seconds_total": 18.0},
                {"llamacpp:prompt_tokens_total": 2100.0, "llamacpp:prompt_seconds_total": 42.0},
            ]
        )

        class FakeEvalClient:
            def __init__(self, *_args, **_kwargs):
                self.token = None

            async def wait_for_agent(self, timeout):
                return "agent-1"

            async def ask(self, question, conversation_name):
                return {
                    "mode": "chat",
                    "status": "ok",
                    "answer": "$250",
                    "timing_source": "websocket",
                    "total_s": 30.0,
                    "dispatch_s": 0.3,
                }

        collected = {
            "cpu_model": ("AMD Ryzen 5 5600U", "/proc/cpuinfo"),
            "ram_total_bytes": (16 * 2**30, "/proc/meminfo"),
        }
        monkeypatch.setattr(runner, "EvalClient", FakeEvalClient)
        monkeypatch.setattr(
            runner, "llama_server_facts", lambda container: facts if container == "llm" else None
        )
        routing = iter(
            [
                {},
                {"embedding": {"count": 1.0, "seconds": 0.01}},
                {"embedding": {"count": 1.0, "seconds": 0.01}},
                {
                    "embedding": {"count": 1.0, "seconds": 0.01},
                    "llm": {"count": 1.0, "seconds": 2.0},
                },
            ]
        )
        monkeypatch.setattr(runner, "read_llm_counters", lambda container, port: next(scrapes))
        monkeypatch.setattr(runner, "read_routing_decisions", lambda mas_url: next(routing))
        monkeypatch.setattr(runner.host, "docker_facts", lambda: {"mem_total_bytes": 15 * 2**30})
        monkeypatch.setattr(runner.host, "collect_host", lambda path: collected)
        monkeypatch.setattr(runner.pipeline, "gpu_info", lambda: {"error": "nvidia-smi not found"})
        monkeypatch.setattr(runner.pipeline, "git_commit", lambda: "abc1234")
        monkeypatch.setattr(runner.pipeline, "websockets", object())
        samplers = []

        class RecordingSampler(FakeSampler):
            def __init__(self, interval, swap_container=None, llm_container=None):
                super().__init__()
                self.args = (interval, swap_container, llm_container)
                samplers.append(self)

            def start(self):
                pass

            def finish(self):
                return {"stack_peak_mem_bytes": 7 * 2**30}

        monkeypatch.setattr(runner, "ResourceSampler", RecordingSampler)
        argv = [
            "run-eval.py",
            "--label",
            "eval-cpu16",
            "--reference",
            "cpu16",
            "--skip-corpus-check",
            "--token",
            "jwt",
            "--ids",
            "fin-01,exp-01",
            "--no-warmup",
            "--out-dir",
            str(tmp_path),
            "--sample-resources",
        ]
        monkeypatch.setattr(sys, "argv", argv)
        assert runner.main() == 0
        [saved] = list(tmp_path.iterdir())
        report = json.loads(saved.read_text(encoding="utf-8"))
        [sampler] = samplers
        assert sampler.args == (10.0, "mas", "llm")
        assert (sampler.starts, sampler.windows) == (1, 2)
        assert report["resources"] == {"stack_peak_mem_bytes": 7 * 2**30}
        assert report["schema_version"] == 2
        assert report["llama_cpp"]["build"] == "b11382"
        assert report["llama_cpp"]["server"]["settings"]["cache_type_v"] == "f16"
        assert report["model"]["file"] == "qwen3-4b-instruct-2507-Q4_K_M.gguf"
        assert report["model"]["sha256"] == VERIFIED_SHA256
        assert report["machine"]["reference"] == "cpu16"
        assert report["machine"]["docker"] == {"mem_total_bytes": 15 * 2**30}
        assert [question["llm"]["prompt_tokens"] for question in report["questions"]] == [900, 1200]
        assert [question["dispatch_s"] for question in report["questions"]] == [0.3, 0.3]
        assert [question["routing_decision"]["methods"] for question in report["questions"]] == [
            {"embedding": 1},
            {"llm": 1},
        ]
        assert report["summary"]["llm"]["prompt_tps"] == 50.0
        assert report["summary"]["dispatch_s"]["median"] == 0.3
        assert report["summary"]["routing"]["llm_pct"] == 50.0
        assert report["run"]["completed"] is True


class TestTokenRenewal:
    def signed_in_client(self, runner, urls):
        client = make_client(runner, FakeSocket(AGENT_EVENTS), urls)
        logins = []

        async def authenticate(username, password):
            logins.append((username, password))
            client.token = f"jwt-{len(logins)}"
            return True

        client.authenticate = authenticate
        clock = [1000.0]
        client.clock = lambda: clock[0]
        assert asyncio.run(client.sign_in("admin", "admin"))
        return client, logins, clock

    def test_a_token_older_than_the_refresh_age_is_renewed_before_the_next_question(
        self, runner, mas
    ):
        urls = []
        client, logins, clock = self.signed_in_client(runner, urls)
        clock[0] += runner.TOKEN_REFRESH_S + 1

        outcome = asyncio.run(client.ask("What is the hotel limit per night in the US?", "eval-x"))

        assert outcome["status"] == "ok"
        assert logins == [("admin", "admin"), ("admin", "admin")]
        assert urls == ["ws://mas:8000/chat/7/?token=jwt-2"]

    def test_a_fresh_token_is_kept(self, runner, mas):
        urls = []
        client, logins, clock = self.signed_in_client(runner, urls)
        clock[0] += 60

        asyncio.run(client.ask("What is the hotel limit per night in the US?", "eval-x"))

        assert logins == [("admin", "admin")]
        assert urls == ["ws://mas:8000/chat/7/?token=jwt-1"]

    def polling_mas(self, monkeypatch, task_status):
        polled_with = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/conversations/create-conversation/":
                return httpx.Response(200, json={"conversation_id": 7})
            if request.url.path == "/tasks/new_task/":
                return httpx.Response(200, json={"task_id": "t-1"})
            if request.url.path == "/tasks/t-1":
                token = request.headers.get("Authorization", "")
                polled_with.append(token)
                return task_status(token)
            return httpx.Response(404, json={})

        transport = httpx.MockTransport(handler)
        real_async_client = httpx.AsyncClient
        monkeypatch.setattr(
            httpx, "AsyncClient", lambda *a, **kw: real_async_client(*a, transport=transport, **kw)
        )
        return polled_with

    def test_polling_renews_a_refused_token_and_reports_the_real_final_status(
        self, runner, monkeypatch
    ):
        def task_status(token):
            if token != "Bearer jwt-2":
                return httpx.Response(401, json={"detail": "Could not validate credentials"})
            return httpx.Response(200, json={"status": "completed", "result": "$250 per night."})

        polled_with = self.polling_mas(monkeypatch, task_status)
        client, logins, _clock = self.signed_in_client(runner, [])
        client.connect = fake_connect(FakeSocket(TITLED_AGENT_EVENTS[:2]), [])

        outcome = asyncio.run(client.ask("What is the hotel limit per night in the US?", "eval-x"))

        assert outcome["status"] == "ok"
        assert outcome["timing_source"] == "poll"
        assert outcome["answer"] == "$250 per night."
        assert logins == [("admin", "admin"), ("admin", "admin")]
        assert polled_with == ["Bearer jwt-1", "Bearer jwt-2"]

    def test_a_long_poll_renews_the_token_once_it_is_old(self, runner, monkeypatch):
        client, logins, clock = self.signed_in_client(runner, [])
        client.connect = fake_connect(FakeSocket(TITLED_AGENT_EVENTS[:2]), [])

        def task_status(token):
            if token == "Bearer jwt-2":
                return httpx.Response(
                    200, json={"status": "completed", "result": "$250 per night."}
                )
            clock[0] += runner.TOKEN_REFRESH_S / 2
            return httpx.Response(200, json={"status": "running"})

        polled_with = self.polling_mas(monkeypatch, task_status)

        outcome = asyncio.run(client.ask("What is the hotel limit per night in the US?", "eval-x"))

        assert outcome["status"] == "ok"
        assert outcome["answer"] == "$250 per night."
        assert logins == [("admin", "admin"), ("admin", "admin")]
        assert polled_with == ["Bearer jwt-1", "Bearer jwt-1", "Bearer jwt-2"]

    def test_a_token_given_on_the_command_line_is_never_renewed(self, runner, mas):
        urls = []
        client = make_client(runner, FakeSocket(AGENT_EVENTS), urls)
        client.clock = lambda: 10_000_000.0

        outcome = asyncio.run(client.ask("What is the hotel limit per night in the US?", "eval-x"))

        assert outcome["status"] == "ok"
        assert urls == ["ws://mas:8000/chat/7/?token=jwt"]
