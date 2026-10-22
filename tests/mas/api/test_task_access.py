from __future__ import annotations

from unittest.mock import patch

import pytest

from db.models import Conversations, Messages, Task
from tasks import routes
from tasks.task_jobs import task_jobs


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
    routing_db.add(Conversations(id=9, owner_username="manager", name="Team review"))
    routing_db.add_all(
        [
            Task(
                id="mine",
                agent_id="manager",
                status="running",
                query="Q4 revenue?",
                conversation_id=7,
                owner_username="user",
            ),
            Task(
                id="via-conversation",
                agent_id="manager",
                status="completed",
                query="Hotel limit?",
                conversation_id=7,
                owner_username=None,
            ),
            Task(
                id="theirs",
                agent_id="manager",
                status="running",
                query="Travel policy?",
                conversation_id=8,
                owner_username="other",
            ),
            Task(
                id="standalone",
                agent_id="manager",
                status="running",
                query="Sent from /tasks/new",
                conversation_id=None,
                owner_username="user",
            ),
            Task(
                id="my-step",
                agent_id="agent-finance",
                status="running",
                query="Step 1",
                conversation_id=None,
                owner_username=None,
                parent_task_id="standalone",
            ),
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
            "Only the task's owner, the owner of its conversation, a manager or an admin "
            "can read this task"
        )

    async def test_a_task_owned_through_its_conversation_is_read_by_that_owner(
        self, tasks, mas_client
    ):
        assert (await _get(mas_client, OWNER, "/tasks/via-conversation")).status_code == 200
        assert (await _get(mas_client, OTHER, "/tasks/via-conversation")).status_code == 403

    async def test_the_owner_reads_a_subtask_that_has_no_owner_of_its_own(self, tasks, mas_client):
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
            "mine",
            "via-conversation",
            "theirs",
            "standalone",
        }


@pytest.fixture
def stays_queued(monkeypatch):
    async def no_routing(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(routes, "run_routing_job", no_routing)


async def _post(mas_client, user: dict, conversation_id: int | None, headers: dict | None = None):
    body = {
        "demand": "What was Q4 2025 revenue?",
        "conversation_id": conversation_id,
        "skills_required": [],
    }
    async with mas_client(user) as client:
        response = await client.post("/tasks/new_task/", json=body, headers=headers or {})
    await task_jobs.drain()
    return response


WHO_POSTS = [
    (OWNER, 7, 202),
    (OTHER, 7, 403),
    (MANAGER, 7, 403),
    (MANAGER, 9, 202),
    (ADMIN, 8, 202),
    (SYSTEM, 7, 403),
]
WHO_POSTS_IDS = [
    "owner",
    "another-user",
    "manager-elsewhere",
    "manager-own",
    "admin-anywhere",
    "system",
]


class TestCreatingATask:
    @pytest.mark.parametrize(("user", "conversation_id", "expected"), WHO_POSTS, ids=WHO_POSTS_IDS)
    async def test_only_the_conversation_owner_or_an_admin_posts_into_it(
        self, tasks, mas_client, stays_queued, user, conversation_id, expected
    ):
        tasks_before = tasks.query(Task).count()

        response = await _post(mas_client, user, conversation_id)

        assert response.status_code == expected
        tasks.expire_all()
        assert tasks.query(Task).count() == tasks_before + (1 if expected == 202 else 0)

    async def test_a_refused_post_adds_no_message_and_says_why(
        self, tasks, mas_client, stays_queued
    ):
        response = await _post(mas_client, OTHER, 7)

        assert response.json()["detail"] == (
            "Only the conversation's owner or an admin can add a task to it"
        )
        assert tasks.query(Messages).filter(Messages.conversation_id == 7).count() == 0

    async def test_a_task_without_a_conversation_is_still_accepted(
        self, tasks, mas_client, stays_queued
    ):
        assert (await _post(mas_client, OTHER, None)).status_code == 202

    async def test_a_replayed_idempotency_key_does_not_get_around_the_check(
        self, tasks, mas_client, stays_queued
    ):
        headers = {"Idempotency-Key": "same-key"}

        own = await _post(mas_client, OTHER, 8, headers)
        replayed = await _post(mas_client, OTHER, 7, headers)

        assert own.status_code == 202
        assert replayed.status_code == 403
        assert "task_id" not in replayed.json()

    async def test_an_unknown_conversation_is_404_and_does_not_use_up_the_key(
        self, tasks, mas_client, stays_queued
    ):
        headers = {"Idempotency-Key": "first-try"}
        tasks_before = tasks.query(Task).count()

        missing = await _post(mas_client, OWNER, 999, headers)

        assert missing.status_code == 404
        assert missing.json()["detail"] == "Conversation not found"
        tasks.expire_all()
        assert tasks.query(Task).count() == tasks_before

        retried = await _post(mas_client, OWNER, 7, headers)

        assert retried.status_code == 202
        assert retried.headers.get("Idempotent-Replayed") is None
        tasks.expire_all()
        assert tasks.query(Task).count() == tasks_before + 1


WHO_CANCELS = [(OWNER, 200), (OTHER, 403), (MANAGER, 200), (ADMIN, 200), (SYSTEM, 403)]


class TestCancellingATask:
    async def _cancel(self, mas_client, user: dict, path: str):
        with patch("tasks.task_crud.rabbitmq_instance"):
            async with mas_client(user) as client:
                return await client.patch(path)

    @pytest.mark.parametrize(("user", "expected"), WHO_CANCELS, ids=WHO_READS_IDS)
    async def test_only_the_owner_a_manager_or_an_admin_cancels(
        self, tasks, mas_client, user, expected
    ):
        response = await self._cancel(mas_client, user, "/tasks/task-cancel/mine")

        assert response.status_code == expected
        tasks.expire_all()
        assert tasks.get(Task, "mine").status == ("canceled" if expected == 200 else "running")

    async def test_the_alternate_path_checks_the_same_way(self, tasks, mas_client):
        response = await self._cancel(mas_client, OTHER, "/tasks/mine/cancel")

        assert response.status_code == 403
        assert response.json()["detail"] == (
            "Only the task's owner, the owner of its conversation, a manager or an admin "
            "can cancel this task"
        )

    async def test_the_owner_cancels_a_subtask_that_has_no_owner_of_its_own(
        self, tasks, mas_client
    ):
        assert (
            await self._cancel(mas_client, OWNER, "/tasks/task-cancel/my-step")
        ).status_code == 200

    async def test_an_unknown_task_is_404_before_any_ownership_check(self, tasks, mas_client):
        assert (
            await self._cancel(mas_client, OTHER, "/tasks/task-cancel/missing")
        ).status_code == 404


@pytest.fixture
def admin_posted(tasks):
    tasks.add_all(
        [
            Task(
                id="admin-in-mine",
                agent_id="manager",
                status="running",
                query="Posted by an admin",
                conversation_id=7,
                owner_username="admin",
            ),
            Task(
                id="admin-step",
                agent_id="agent-finance",
                status="running",
                query="Step 1",
                conversation_id=None,
                owner_username=None,
                parent_task_id="admin-in-mine",
            ),
            Task(
                id="loop-a",
                agent_id="agent-finance",
                status="running",
                query="Loop A",
                conversation_id=None,
                owner_username=None,
                parent_task_id="loop-b",
            ),
            Task(
                id="loop-b",
                agent_id="agent-finance",
                status="running",
                query="Loop B",
                conversation_id=None,
                owner_username="user",
                parent_task_id="loop-a",
            ),
        ]
    )
    tasks.commit()
    return tasks


class TestTheConversationOwnersTasks:
    @pytest.mark.parametrize(
        "path", ["/tasks/admin-in-mine", "/tasks/admin-in-mine/events", "/tasks/admin-step"]
    )
    async def test_the_owner_of_the_conversation_reads_a_task_an_admin_posted_in_it(
        self, admin_posted, mas_client, path
    ):
        assert (await _get(mas_client, OWNER, path)).status_code == 200
        assert (await _get(mas_client, OTHER, path)).status_code == 403

    async def test_the_owner_of_the_conversation_cancels_it(self, admin_posted, mas_client):
        with patch("tasks.task_crud.rabbitmq_instance"):
            async with mas_client(OTHER) as client:
                refused = await client.patch("/tasks/task-cancel/admin-in-mine")
            async with mas_client(OWNER) as client:
                cancelled = await client.patch("/tasks/task-cancel/admin-in-mine")

        assert refused.status_code == 403
        assert cancelled.status_code == 200

    async def test_it_is_in_the_conversation_owners_task_list_only(self, admin_posted, mas_client):
        async with mas_client(OWNER) as client:
            mine = {task["id"] for task in (await client.get("/tasks/list")).json()}
        async with mas_client(OTHER) as client:
            theirs = {task["id"] for task in (await client.get("/tasks/list")).json()}

        assert "admin-in-mine" in mine
        assert "admin-in-mine" not in theirs

    async def test_a_cycle_in_the_parent_chain_ends_with_the_right_answer(
        self, admin_posted, mas_client
    ):
        assert (await _get(mas_client, OWNER, "/tasks/loop-a")).status_code == 200
        assert (await _get(mas_client, OTHER, "/tasks/loop-a")).status_code == 403
