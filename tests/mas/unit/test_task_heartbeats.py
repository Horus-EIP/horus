from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import chat.chat_tool_functions as chat_functions
import db.models  # noqa: F401
from core.task_events import publish_task_status, read_task_events
from db.database import Base
from db.models import Task, TaskResult
from tasks import controller

STARTED_AT = datetime(2026, 10, 5, 9, 30, 0, tzinfo=UTC)


class StopLoop(BaseException):
    pass


class FakeClock:
    def __init__(self, rounds: int):
        self.now_s = 0.0
        self.rounds = rounds
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now_s

    def wall(self) -> datetime:
        return STARTED_AT + timedelta(seconds=self.now_s)

    async def sleep(self, seconds: float) -> None:
        if len(self.sleeps) == self.rounds:
            raise StopLoop
        self.sleeps.append(seconds)
        self.now_s += seconds


@pytest.fixture
def heartbeat_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.close = MagicMock()
    try:
        yield session
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def no_sockets():
    chat_functions.active_connections.clear()
    yield
    chat_functions.active_connections.clear()


def _socket(conversation_id="7"):
    ws = MagicMock()
    ws.send_json = AsyncMock()
    chat_functions.active_connections.setdefault(conversation_id, []).append(ws)
    return ws


def _add_task(db, task_id, *, status="running", conversation_id=7, parent_task_id=None):
    db.add(
        Task(
            id=task_id,
            agent_id="agent-finance",
            status=status,
            query="Summarise the Q4 report",
            conversation_id=conversation_id,
            parent_task_id=parent_task_id,
            created_at=STARTED_AT,
        )
    )
    db.add(TaskResult(task_id=task_id, history=[], future_actions=[]))
    db.commit()


def _heartbeats(task_id):
    return [event for event in read_task_events(task_id) if event["type"] == "heartbeat"]


async def _run_rounds(db, rounds):
    clock = FakeClock(rounds)
    with pytest.raises(StopLoop):
        await controller.run_task_heartbeats(
            session_factory=lambda: db,
            clock=clock.monotonic,
            now=clock.wall,
            sleep=clock.sleep,
        )
    return clock


class TestHeartbeatCadence:
    async def test_running_task_with_a_socket_gets_a_heartbeat_every_5_seconds(self, heartbeat_db):
        _add_task(heartbeat_db, "root-1")
        ws = _socket("7")

        clock = await _run_rounds(heartbeat_db, 3)

        assert clock.sleeps == [5.0, 5.0, 5.0]
        beats = _heartbeats("root-1")
        assert [beat["data"]["elapsed_s"] for beat in beats] == [5.0, 10.0, 15.0]
        frames = [call.args[0] for call in ws.send_json.await_args_list]
        assert [frame["type"] for frame in frames] == ["heartbeat"] * 3
        assert [frame["seq"] for frame in frames] == [1, 2, 3]

    async def test_heartbeat_reports_the_current_stage(self, heartbeat_db):
        _add_task(heartbeat_db, "root-1")
        _socket("7")
        await publish_task_status("root-1", 7, "running", stage="retrieval")

        await _run_rounds(heartbeat_db, 1)

        assert _heartbeats("root-1")[0]["stage"] == "retrieval"

    async def test_queued_task_without_a_stage_reports_queued(self, heartbeat_db):
        _add_task(heartbeat_db, "root-1", status="queued")
        _socket("7")

        await _run_rounds(heartbeat_db, 1)

        assert _heartbeats("root-1")[0]["stage"] == "queued"

    async def test_no_heartbeat_without_a_connected_socket(self, heartbeat_db):
        _add_task(heartbeat_db, "root-1")

        await _run_rounds(heartbeat_db, 2)

        assert _heartbeats("root-1") == []

    async def test_finished_tasks_and_subtasks_get_no_heartbeat(self, heartbeat_db):
        _add_task(heartbeat_db, "done", status="completed")
        _add_task(heartbeat_db, "root-1")
        _add_task(heartbeat_db, "step-1", parent_task_id="root-1")
        _socket("7")

        await _run_rounds(heartbeat_db, 1)

        assert _heartbeats("done") == []
        assert _heartbeats("step-1") == []
        assert len(_heartbeats("root-1")) == 1

    async def test_a_slow_round_does_not_push_the_next_heartbeat_back(
        self, heartbeat_db, monkeypatch
    ):
        clock = FakeClock(3)

        async def slow_round(_db, _now):
            clock.now_s += 2.0
            return 0

        monkeypatch.setattr(controller, "emit_task_heartbeats", slow_round)
        with pytest.raises(StopLoop):
            await controller.run_task_heartbeats(
                session_factory=lambda: heartbeat_db,
                clock=clock.monotonic,
                now=clock.wall,
                sleep=clock.sleep,
            )

        assert clock.sleeps == [5.0, 3.0, 3.0]

    async def test_a_failed_round_keeps_the_loop_alive(self, heartbeat_db, monkeypatch):
        rounds = []

        async def failing_round(_db, _now):
            rounds.append(1)
            raise RuntimeError("db down")

        monkeypatch.setattr(controller, "emit_task_heartbeats", failing_round)
        await _run_rounds(heartbeat_db, 2)

        assert len(rounds) == 2


class TestInterruptedRouting:
    async def test_tasks_still_queued_at_startup_fail_with_a_clear_message(self, heartbeat_db):
        _add_task(heartbeat_db, "stranded", status="queued")
        _add_task(heartbeat_db, "busy", status="running")

        failed = await controller.fail_interrupted_routing(lambda: heartbeat_db)

        heartbeat_db.expire_all()
        assert failed == 1
        stranded = heartbeat_db.get(Task, "stranded")
        assert stranded.status == "failed"
        assert stranded.result.result_data == controller.INTERRUPTED_ROUTING_TEXT
        assert heartbeat_db.get(Task, "busy").status == "running"
        (event,) = read_task_events("stranded")
        assert event["type"] == "error"
        assert event["data"]["status"] == "failed"

    async def test_a_database_error_does_not_block_startup(self):
        broken = MagicMock()
        broken.query.side_effect = RuntimeError("db down")

        assert await controller.fail_interrupted_routing(lambda: broken) == 0


class TestTimeoutEvents:
    async def test_timed_out_task_reports_the_timeout_as_a_stored_error_event(
        self, heartbeat_db, monkeypatch
    ):
        _add_task(heartbeat_db, "root-1")
        _add_task(heartbeat_db, "step-1", parent_task_id="root-1")
        ws = _socket("7")
        monkeypatch.setattr(controller, "SessionLocal", lambda: heartbeat_db)
        monkeypatch.setattr(controller.settings, "task_timeout", -1)
        monkeypatch.setattr("tasks.task_crud.rabbitmq_instance", MagicMock())

        async def stop(_seconds):
            raise StopLoop

        monkeypatch.setattr(controller.asyncio, "sleep", stop)
        with pytest.raises(StopLoop):
            await controller.check_task_timeout()

        heartbeat_db.expire_all()
        root = heartbeat_db.get(Task, "root-1")
        assert root.status == "canceled"
        assert "exceeded the maximum processing time" in root.result.result_data
        (event,) = read_task_events("root-1")
        assert event["type"] == "error"
        assert event["data"]["status"] == "cancelled"
        assert event["data"]["reason"] == "timeout"
        assert read_task_events("step-1") == []
        assert len(ws.send_json.await_args_list) == 1

    async def test_queued_tasks_are_watched_for_the_timeout_too(self, heartbeat_db, monkeypatch):
        _add_task(heartbeat_db, "root-1", status="queued")
        monkeypatch.setattr(controller, "SessionLocal", lambda: heartbeat_db)
        monkeypatch.setattr(controller.settings, "task_timeout", -1)
        monkeypatch.setattr("tasks.task_crud.rabbitmq_instance", MagicMock())

        async def stop(_seconds):
            raise StopLoop

        monkeypatch.setattr(controller.asyncio, "sleep", stop)
        with pytest.raises(StopLoop):
            await controller.check_task_timeout()

        heartbeat_db.expire_all()
        assert heartbeat_db.get(Task, "root-1").status == "canceled"
