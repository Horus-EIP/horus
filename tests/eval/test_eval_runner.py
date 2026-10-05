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
        {"type": "task_step", "step_type": "reasoning.start", "metadata": {"model": "qwen3-4b", "device": "cpu"}},
        {"type": "task_step", "step_type": "reasoning.delta", "metadata": {"chunk": "$250"}},
        {"type": "task_complete", "content": content, "agent_name": "Finance-Analyst", "skill_used": "research"},
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

    def test_live_agent_events_give_a_correct_answer_with_an_unscored_source(self, runner, mas, items):
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
                return httpx.Response(200, json={"documents": [{"title": t} for t in state["titles"]]})
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

    def test_missing_document_fails_without_a_scan_token(self, runner, knowledge_store, testset, capsys):
        knowledge_store["titles"] = knowledge_store["titles"][1:]
        assert asyncio.run(runner.ensure_corpus("http://ks:8080", testset, None)) is False
        assert "1_Q4_2025_Financial_Report.md is not in the knowledge store" in capsys.readouterr().out

    def test_missing_document_triggers_a_corpus_scan_with_the_token(self, runner, knowledge_store, testset):
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
        monkeypatch.setattr(httpx, "Client", lambda *a, **kw: real_client(*a, transport=transport, **kw))

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
        self.patch_client(monkeypatch, lambda request: httpx.Response(200, json={"metadatas": metadatas}))
        record = question_record(item, runner.retrieve("http://ks:8080", item["question"], 10))
        assert record["source_ranks"] == [5]
        assert record["source_correct_auto"] is False

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
            runner, "--label", "x", "--model-sha256", "abc", "--category", "lookup,trivia", "--limit", "0"
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
                return {"mode": "chat", "status": "ok", "answer": "$250", "timing_source": "websocket"}

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
        path.write_text(json.dumps(build_report(label="cpu16", run={}, testset={}, records=[record])))
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
