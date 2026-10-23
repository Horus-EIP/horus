from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import smoke  # noqa: E402

QUEUED = {"task_id": "3f6c", "status": "queued", "conversation_id": 7}


class FakeSocket:
    def __init__(self, frames):
        self.frames = [(1, json.dumps(frame).encode("utf-8")) for frame in frames]
        self.closed = False

    def connect(self):
        return None

    def recv_message(self, _timeout):
        return self.frames.pop(0) if self.frames else None

    def close(self):
        self.closed = True


class TestSmokeAgainstTheQueuedTaskApi(unittest.TestCase):
    def ask(self, status, body, frames):
        socket = FakeSocket(frames)
        response = smoke.Response(status, json.dumps(body).encode("utf-8"))
        with (
            mock.patch.object(smoke, "_create_conversation", return_value=7),
            mock.patch.object(smoke, "WSClient", return_value=socket),
            mock.patch.object(smoke, "_json_post", return_value=response),
            mock.patch.object(smoke, "_poll_task", return_value=""),
        ):
            return smoke.ask(mock.Mock(), "http://mas", "jwt", "What was Q4 revenue?", "smoke", 5.0)

    def test_a_202_queued_task_waits_for_the_answer_on_the_socket(self):
        frames = [
            {
                "type": "task_status",
                "status": "queued",
                "task_id": "3f6c",
                "seq": 1,
                "event": "progress",
            },
            {
                "type": "heartbeat",
                "elapsed_s": 5.0,
                "task_id": "3f6c",
                "seq": 2,
                "event": "heartbeat",
            },
            {
                "type": "task_complete",
                "content": "Q4 2025 revenue was $4.2M.",
                "agent_name": "Finance-Analyst",
                "skill_used": "analysis",
                "task_id": "3f6c",
                "seq": 3,
                "event": "result",
            },
        ]

        answer, note = self.ask(202, QUEUED, frames)

        self.assertEqual(answer, "Q4 2025 revenue was $4.2M.")
        self.assertEqual(note, "answered over the chat socket")

    def test_a_routing_failure_is_reported_instead_of_taken_as_the_answer(self):
        frames = [
            {
                "type": "agent",
                "content": "No agents are currently registered with the orchestrator.",
                "status": "failed",
                "task_id": "3f6c",
                "seq": 3,
                "event": "error",
            }
        ]

        answer, note = self.ask(202, QUEUED, frames)

        self.assertEqual(answer, "")
        self.assertIn("No agents are currently registered", note)

    def test_a_rejected_submission_is_reported(self):
        answer, note = self.ask(500, {"detail": "Failed to create task"}, [])

        self.assertEqual(answer, "")
        self.assertIn("HTTP 500", note)


class TestFailedTaskNote(unittest.TestCase):
    def test_only_error_events_are_failures(self):
        self.assertIsNone(
            smoke._failed_task_note({"type": "agent", "content": "Hi", "event": "result"})
        )
        self.assertIsNone(smoke._failed_task_note({"type": "agent", "content": "Hi"}))

    def test_the_reason_is_kept(self):
        note = smoke._failed_task_note(
            {"type": "agent", "content": " Request cancelled. ", "event": "error"}
        )

        self.assertEqual(note, "the task ended without an answer: Request cancelled.")

    def test_an_error_without_text_still_fails(self):
        self.assertEqual(
            smoke._failed_task_note({"event": "error"}), "the task ended without an answer"
        )


if __name__ == "__main__":
    unittest.main()
