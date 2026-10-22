from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reindex  # noqa: E402
import smoke  # noqa: E402
from common import EVENT_PREFIX, Events, Log  # noqa: E402

KS = "http://127.0.0.1:8080"
UNREACHABLE = object()


def response(status: int, body) -> smoke.Response:
    return smoke.Response(status, json.dumps(body).encode("utf-8"))


def job(
    state: str,
    pending: int = 0,
    done: int = 0,
    failed: int = 0,
    failures: tuple[str, ...] = (),
    error: str | None = None,
) -> dict:
    return {
        "job_id": "j1",
        "state": state,
        "trigger": "startup",
        "embed_model": "http:horus-mock:768",
        "error": error,
        "totals": {
            "pending": pending,
            "migrated": 0,
            "reembedded": done - failed,
            "unchanged": 0,
            "failed": failed,
        },
        "failures": [{"doc_id": doc, "reason": "EmbeddingsRefused: 500"} for doc in failures],
    }


class FakeReindex:
    def __init__(self, gets: list, post: int = 202):
        self.gets = list(gets)
        self.post = post
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs.get("headers") or {}))
        if method == "POST":
            return response(self.post, {"job_id": "j1", "state": "running"})
        answer = self.gets.pop(0) if len(self.gets) > 1 else self.gets[0]
        if answer is UNREACHABLE:
            raise smoke.Unreachable("connection refused")
        status, body = answer
        return response(status, body)

    @property
    def methods(self) -> list[str]:
        return [method for method, _url, _headers in self.calls]


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class LogCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.events = io.StringIO()
        self.out = io.StringIO()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contextlib.redirect_stdout(self.out))
        self.log = Log(Path(tmp.name) / "log.txt", events=Events(True, self.events))
        self.addCleanup(self.log.close, 0)

    def text(self) -> str:
        return " ".join(self.out.getvalue().split())

    def emitted(self, kind: str) -> list[dict]:
        rows = [
            json.loads(line[len(EVENT_PREFIX) :])
            for line in self.events.getvalue().splitlines()
            if line.startswith(EVENT_PREFIX)
        ]
        return [row for row in rows if row["event"] == kind]


class Counting(unittest.TestCase):
    def corpus(self, answer) -> reindex.Corpus | None:
        def http(method, url, **kwargs):
            if answer is UNREACHABLE:
                raise smoke.Unreachable("refused")
            return response(*answer)

        with mock.patch.object(smoke, "http", side_effect=http) as call:
            corpus = reindex.stored_corpus(KS)
        if answer is not UNREACHABLE:
            self.assertEqual(call.call_args.args, ("GET", f"{KS}/file"))
        return corpus

    def test_the_documents_are_counted_with_the_passages_the_store_keeps(self):
        documents = [
            {"chunk_count": 12, "size": 2_000_000},
            {"chunk_count": 1},
            {"size": 3400},
            {"size": 0},
            {},
            {"chunk_count": True, "size": 900},
            "odd",
        ]
        self.assertEqual(
            self.corpus((200, {"documents": documents})),
            reindex.Corpus(7, 12 + 1 + 4 + 1 + 1 + 1 + 1),
        )

    def test_a_knowledge_store_that_cannot_say_gives_no_count(self):
        for answer in (UNREACHABLE, (404, {"error": "x"}), (200, {"documents": "x"}), (200, [])):
            with self.subTest(answer=answer):
                self.assertIsNone(self.corpus(answer))

    def test_a_passage_is_about_800_new_characters(self):
        self.assertEqual(
            [reindex.passages_in(size) for size in (1, 1000, 1001, 1800, 1801, True, -5)],
            [1, 1, 2, 2, 3, 1, 1],
        )

    def test_a_large_or_unknown_corpus_asks_first(self):
        self.assertTrue(reindex.needs_confirmation(None))
        self.assertFalse(reindex.needs_confirmation(reindex.Corpus(reindex.ASK_ABOVE_DOCUMENTS, 1)))
        self.assertTrue(
            reindex.needs_confirmation(reindex.Corpus(reindex.ASK_ABOVE_DOCUMENTS + 1, 1))
        )

    def test_the_wait_grows_with_the_corpus(self):
        self.assertEqual(reindex.patience(None), reindex.UNKNOWN_CORPUS_WAIT_SECONDS)
        self.assertEqual(reindex.patience(reindex.Corpus(5, 22)), reindex.SHORTEST_WAIT_SECONDS)
        large = reindex.Corpus(400, 60_000)
        self.assertEqual(reindex.patience(large), reindex.WAIT_MARGIN * large.cpu_seconds)

    def test_the_startup_reindex_is_on_unless_turned_off(self):
        for setting, expected in (
            (None, True),
            ("", True),
            ("1", True),
            ("0", False),
            ("off", False),
            (" False ", False),
            ("no", False),
        ):
            with self.subTest(setting=setting):
                self.assertEqual(reindex.runs_at_start(setting), expected)


class Announcing(LogCase):
    def test_towards_local_the_count_comes_with_the_cpu_time(self):
        reindex.announce(self.log, reindex.Corpus(40, 480), towards_local=True)
        self.assertIn("holds 40 documents (480 passages)", self.text())
        self.assertIn("On the processor that takes about 2m 00s", self.text())
        self.assertEqual(
            self.emitted("reembed")[-1],
            {"event": "reembed", "documents": 40, "passages": 480, "cpu_seconds": 120},
        )

    def test_towards_mock_it_says_the_way_back_costs_the_cpu_time(self):
        reindex.announce(self.log, reindex.Corpus(5, 22), towards_local=False)
        self.assertIn("llm-mock does it in seconds", self.text())
        self.assertIn(
            "Switching back to local later re-embeds them on the processor again: under a minute",
            self.text(),
        )

    def test_an_empty_or_silent_knowledge_store_is_said_plainly(self):
        reindex.announce(self.log, reindex.Corpus(0, 0), towards_local=True)
        self.assertIn("holds no document, so nothing needs re-embedding", self.text())
        reindex.announce(self.log, None, towards_local=True)
        self.assertIn("how many documents it holds is unknown", self.text())


class Following(LogCase):
    def follow(
        self,
        store: FakeReindex,
        start_now: bool = False,
        may_start: bool = True,
        startup: bool = True,
        wait_seconds: float = reindex.SHORTEST_WAIT_SECONDS,
    ):
        clock = Clock()
        with mock.patch.object(smoke, "http", side_effect=store):
            result = reindex.follow(
                self.log,
                KS,
                "secret",
                start_now,
                may_start,
                startup,
                wait_seconds,
                sleep=clock.sleep,
                clock=clock,
            )
        return result, clock

    def test_the_startup_reindex_is_followed_to_the_end(self):
        store = FakeReindex(
            [
                (200, job("running")),
                (200, job("running", 5, 2)),
                (200, job("running", 5, 2)),
                (200, job("completed", 5, 5)),
            ]
        )
        result, clock = self.follow(store)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(store.methods, ["GET"] * 4)
        self.assertTrue(
            all(headers == {reindex.TOKEN_HEADER: "secret"} for _m, _u, headers in store.calls)
        )
        self.assertEqual(store.calls[0][1], f"{KS}/corpus/reindex")
        self.assertEqual(clock.slept, [reindex.POLL_SECONDS] * 3)
        self.assertIn("re-embedding the stored documents: 2/5", self.text())
        self.assertIn("Re-embedded 5 documents with http:horus-mock:768", self.text())
        self.assertEqual(
            [row["state"] for row in self.emitted("reindex")], ["running", "running", "completed"]
        )

    def test_an_idle_knowledge_store_is_asked_to_reindex(self):
        store = FakeReindex([(200, {"state": "idle"}), (200, job("completed"))])
        self.follow(store)
        self.assertEqual(store.methods, ["GET", "POST", "GET"])
        self.assertIn("nothing to re-embed", self.text())

    def test_an_install_only_watches_and_never_starts_one(self):
        store = FakeReindex([(200, {"state": "idle"})])
        result, _clock = self.follow(store, may_start=False)
        self.assertIsNone(result)
        self.assertEqual(store.methods, ["GET"])

    def test_with_the_startup_reindex_off_the_installer_starts_it(self):
        store = FakeReindex([(200, job("running", 3, 0)), (200, job("completed", 3, 3))])
        self.follow(store, start_now=True, startup=False)
        self.assertEqual(store.methods, ["POST", "GET", "GET"])

    def test_a_restarted_knowledge_store_is_asked_again(self):
        store = FakeReindex(
            [(200, job("running", 3, 1)), (200, {"state": "idle"}), (200, job("completed", 3, 3))]
        )
        self.follow(store)
        self.assertEqual(store.methods, ["GET", "GET", "POST", "GET"])

    def test_a_busy_store_is_asked_again_every_half_minute_only(self):
        store = FakeReindex(
            [(200, {"state": "idle"})] * 25 + [(200, job("completed", 2, 2))], post=409
        )
        result, clock = self.follow(store)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(store.methods.count("POST"), 3)
        self.assertEqual(self.text().count("busy with a corpus scan or another re-index"), 1)

    def test_a_knowledge_store_that_does_not_answer_yet_is_polled_again(self):
        store = FakeReindex([UNREACHABLE, (500, {"error": "x"}), (200, job("completed", 1, 1))])
        result, _clock = self.follow(store)
        self.assertEqual(result["state"], "completed")

    def test_without_the_token_the_installer_says_it_cannot_follow(self):
        for status in (403, 503):
            with self.subTest(status=status):
                store = FakeReindex(
                    [(status, {"error": "Missing or invalid X-Corpus-Token header."})]
                )
                result, _clock = self.follow(store)
                self.assertIsNone(result)
                self.assertIn(
                    f"cannot follow the knowledge store's re-index (HTTP {status}", self.text()
                )

    def test_a_refused_start_is_said_too(self):
        store = FakeReindex([(200, job("completed"))], post=503)
        result, _clock = self.follow(store, start_now=True, startup=False)
        self.assertIsNone(result)
        self.assertEqual(store.methods, ["POST"])

    def test_documents_that_failed_are_named_with_how_to_finish(self):
        store = FakeReindex([(200, job("completed", 7, 7, failed=2, failures=("a", "b")))])
        self.follow(store)
        self.assertIn("2 of 7 documents could not be re-embedded (a, b)", self.text())
        self.assertIn("the next start of Horus tries them again", self.text())
        self.assertEqual(self.emitted("reindex")[-1]["failed"], 2)
        self.follow(
            FakeReindex([(200, job("completed", 7, 7, failed=1, failures=("c",)))]), startup=False
        )
        self.assertIn("run scripts/reindex-knowledge-store.py or this switch again", self.text())

    def test_a_failed_job_says_why(self):
        store = FakeReindex([(200, job("failed", 7, 3, error="RuntimeError: disk full"))])
        self.follow(store)
        self.assertIn("stopped after 0s: RuntimeError: disk full", self.text())

    def test_a_long_document_is_waited_for_as_long_as_the_corpus_needs(self):
        store = FakeReindex([(200, job("running", 9, 4))] * 400 + [(200, job("completed", 9, 9))])
        result, clock = self.follow(store, wait_seconds=1800.0)
        self.assertEqual(result["state"], "completed")
        self.assertGreater(clock.now, reindex.SHORTEST_WAIT_SECONDS)

    def test_a_reindex_that_never_ends_is_left_behind_at_the_end_of_the_wait(self):
        restarts = [(200, {**job("running", 9, 0), "job_id": f"j{n}"}) for n in range(1000)]
        result, clock = self.follow(FakeReindex(restarts), wait_seconds=900.0)
        self.assertEqual(result["state"], "running")
        self.assertGreaterEqual(clock.now, 900.0)
        self.assertLess(clock.now, 900.0 + 2 * reindex.POLL_SECONDS)
        self.assertIn("did not end within 15m 00s", self.text())


if __name__ == "__main__":
    unittest.main()
