from __future__ import annotations

import pytest

from db.models import Conversations, Task


def _user(user_id: int, username: str, role: str) -> dict:
    return {"id": user_id, "user_id": str(user_id), "username": username, "role": role}


ADMIN = _user(1, "admin", "admin")
MANAGER = _user(2, "manager", "manager")
OWNER = _user(3, "user", "user")
OTHER = _user(4, "other", "user")
SYSTEM = _user(5, "robot", "system")

WHO_READS = [(OWNER, 200), (OTHER, 403), (MANAGER, 200), (ADMIN, 200), (SYSTEM, 403)]
WHO_READS_IDS = ["owner", "another-user", "manager", "admin", "system"]


@pytest.fixture
def tasks(routing_db):
    routing_db.add(Conversations(id=8, owner_username="other", name="Travel"))
    routing_db.add_all(
        [
            Task(id="mine", agent_id="manager", status="running", query="Q4 revenue?",
                 conversation_id=7, owner_username="user"),
            Task(id="via-conversation", agent_id="manager", status="completed",
                 query="Hotel limit?", conversation_id=7, owner_username=None),
            Task(id="theirs", agent_id="manager", status="running", query="Travel policy?",
                 conversation_id=8, owner_username="other"),
            Task(id="standalone", agent_id="manager", status="running",
                 query="Sent from /tasks/new", conversation_id=None, owner_username="user"),
            Task(id="my-step", agent_id="agent-finance", status="running", query="Step 1",
                 conversation_id=None, owner_username=None, parent_task_id="standalone"),
        ]
    )
    routing_db.commit()
    return routing_db


async def _get(mas_client, user: dict, path: str):
    async with mas_client(user) as client:
        return await client.get(path)


class TestReadingOneTask:
    @pytest.mark.parametrize(("user", "expected"), WHO_READS, ids=WHO_READS_IDS)
    async def test_the_task_detail_is_for_its_owner_managers_and_admins(
        self, tasks, mas_client, user, expected
    ):
        response = await _get(mas_client, user, "/tasks/mine")

        assert response.status_code == expected
        if expected == 200:
            assert response.json()["task_id"] == "mine"

    @pytest.mark.parametrize(("user", "expected"), WHO_READS, ids=WHO_READS_IDS)
    async def test_the_task_events_are_for_its_owner_managers_and_admins(
        self, tasks, mas_client, user, expected
    ):
        response = await _get(mas_client, user, "/tasks/mine/events")

        assert response.status_code == expected

    async def test_a_refused_read_says_who_may_read_it(self, tasks, mas_client):
        response = await _get(mas_client, OTHER, "/tasks/mine")

        assert response.json()["detail"] == (
            "Only the task's owner, a manager or an admin can read this task"
        )

    async def test_a_task_owned_through_its_conversation_is_read_by_that_owner(
        self, tasks, mas_client
    ):
        assert (await _get(mas_client, OWNER, "/tasks/via-conversation")).status_code == 200
        assert (await _get(mas_client, OTHER, "/tasks/via-conversation")).status_code == 403

    async def test_the_owner_reads_a_subtask_that_has_no_owner_of_its_own(
        self, tasks, mas_client
    ):
        mine = await _get(mas_client, OWNER, "/tasks/my-step")
        theirs = await _get(mas_client, OTHER, "/tasks/my-step")
        root = await _get(mas_client, OWNER, "/tasks/standalone")

        assert mine.status_code == 200
        assert theirs.status_code == 403
        assert [subtask["id"] for subtask in root.json()["subtasks"]] == ["my-step"]

    @pytest.mark.parametrize(
        "path", ["/tasks/missing", "/tasks/missing/events", "/tasks/conversation/999/running"]
    )
    @pytest.mark.parametrize("user", [OTHER, ADMIN], ids=["user", "admin"])
    async def test_an_unknown_id_is_404_before_any_ownership_check(
        self, tasks, mas_client, path, user
    ):
        assert (await _get(mas_client, user, path)).status_code == 404


class TestRunningTasksOfAConversation:
    @pytest.mark.parametrize(("user", "expected"), WHO_READS, ids=WHO_READS_IDS)
    async def test_they_are_for_the_conversation_owner_managers_and_admins(
        self, tasks, mas_client, user, expected
    ):
        response = await _get(mas_client, user, "/tasks/conversation/7/running")

        assert response.status_code == expected
        if expected == 200:
            assert [task["id"] for task in response.json()] == ["mine"]
        else:
            assert response.json()["detail"] == (
                "Only the conversation's owner, a manager or an admin can list its running tasks"
            )


class TestTaskList:
    async def _listed(self, mas_client, user: dict) -> set[str]:
        response = await _get(mas_client, user, "/tasks/list")
        assert response.status_code == 200
        return {task["id"] for task in response.json()}

    async def test_a_user_lists_only_the_root_tasks_they_own(self, tasks, mas_client):
        assert await self._listed(mas_client, OWNER) == {"mine", "via-conversation", "standalone"}
        assert await self._listed(mas_client, OTHER) == {"theirs"}

    async def test_the_system_role_lists_like_a_user(self, tasks, mas_client):
        assert await self._listed(mas_client, SYSTEM) == set()

    @pytest.mark.parametrize("user", [MANAGER, ADMIN], ids=["manager", "admin"])
    async def test_managers_and_admins_list_every_root_task(self, tasks, mas_client, user):
        assert await self._listed(mas_client, user) == {
            "mine", "via-conversation", "theirs", "standalone",
        }
