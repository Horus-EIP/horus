import pytest

import tasks.task_tool_functions as tasks


class DummyQueue:
    def __init__(self, message_count):
        self.method = type("M", (), {"message_count": message_count})()


@pytest.fixture(autouse=True)
def clean_mocks(monkeypatch):
    monkeypatch.setattr(tasks, "get_all_agents", lambda: {})
    monkeypatch.setattr(tasks.channel, "queue_declare", lambda **kwargs: DummyQueue(0))
    yield


# ---------- Tests: aucun agent dispo ----------


def test_no_agents_registered_returns_empty_string(capsys):
    result = tasks.select_agent_for_task(["nlp"])
    out = capsys.readouterr().out
    assert result == ""
    assert "No available agent" in out


def test_no_agent_with_required_skill_returns_empty_string():
    def fake_get_all_agents():
        return {
            "id1": {"skills": ["vision"], "status": "active"},
            "id2": {"skills": ["ocr"], "status": "active"},
        }

    tasks.get_all_agents = fake_get_all_agents
    assert tasks.select_agent_for_task(["nlp"]) == ""


def test_agent_inactive_not_selected():
    def fake_get_all_agents():
        return {
            "id1": {"skills": ["nlp"], "status": "inactive"},
        }

    tasks.get_all_agents = fake_get_all_agents
    assert tasks.select_agent_for_task(["nlp"]) == ""


# ---------- Tests: sélection de l’agent ----------


def test_single_agent_with_skill_selected(monkeypatch):
    tasks.get_all_agents = lambda: {
        "id1": {"skills": ["nlp", "ocr"], "status": "active"},
    }
    result = tasks.select_agent_for_task(["nlp"])
    assert result == "id1"


def test_selects_agent_with_smallest_queue(monkeypatch):
    tasks.get_all_agents = lambda: {
        "id1": {"skills": ["nlp"], "status": "active"},
        "id2": {"skills": ["nlp"], "status": "active"},
    }

    def fake_queue_declare(queue, passive):
        if queue == "id1":
            return DummyQueue(5)
        elif queue == "id2":
            return DummyQueue(2)

    monkeypatch.setattr(tasks.channel, "queue_declare", fake_queue_declare)

    result = tasks.select_agent_for_task(["nlp"])
    assert result == "id2"


def test_tie_breaker_uses_sorted_order(monkeypatch):
    tasks.get_all_agents = lambda: {
        "b-agent": {"skills": ["nlp"], "status": "active"},
        "a-agent": {"skills": ["nlp"], "status": "active"},
    }

    monkeypatch.setattr(tasks.channel, "queue_declare", lambda **kwargs: DummyQueue(1))

    result = tasks.select_agent_for_task(["nlp"])
    assert result == "b-agent"


# ---------- Tests: compute_best_agent_for_task ----------


def test_compute_best_agent_for_task_calls_queue_declare(monkeypatch):
    called = {}

    def fake_queue_declare(queue, passive):
        called["queue"] = queue
        return DummyQueue(7)

    monkeypatch.setattr(tasks.channel, "queue_declare", fake_queue_declare)
    agent = ("some-id", {"skills": ["nlp"], "status": "active"})
    count = tasks.compute_best_agent_for_task(agent)
    assert count == 7
    assert called["queue"] == "some-id"
