from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from tasks.routes import router
from tasks.status import TaskStatus


def running_task(created_at):
    return SimpleNamespace(
        id="t1",
        status=TaskStatus.RUNNING.value,
        agent_id="agent-1",
        conversation_id=None,
        query="What is the hotel limit?",
        parent_task_id=None,
        order=0,
        created_at=created_at,
        result=SimpleNamespace(result_data=None, history=[], future_actions=[]),
    )


@patch("tasks.routes.agent_may_submit_task_result", return_value=True)
@patch("tasks.routes.validating_task_results")
def test_a_completed_task_records_its_processing_time(_validate, _allowed, make_client, mock_db):
    created_at = datetime.now(UTC) - timedelta(minutes=3)
    mock_db.query.return_value.filter.return_value.first.return_value = running_task(created_at)
    client = make_client(router, agent_api_auth=("agent-1", "k"))

    with patch("tasks.routes.observe_task_processing_time") as observe:
        response = client.post(
            "/tasks/task-result/",
            json={"task_id": "t1", "agent_id": "agent-1", "result": "$250 per night"},
        )

    assert response.status_code == 200
    observe.assert_called_once_with(created_at)
