from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Query, Session

from auth.permissions import Role
from db.models import Conversations, Task

ROLES_THAT_READ_EVERY_TASK = frozenset({Role.ADMIN.value, Role.MANAGER.value})

TASK_READ_REFUSED = "Only the task's owner, a manager or an admin can read this task"
TASK_EVENTS_REFUSED = "Only the task's owner, a manager or an admin can read its events"
RUNNING_TASKS_REFUSED = (
    "Only the conversation's owner, a manager or an admin can list its running tasks"
)


def role_of(user: dict) -> str:
    role = user.get("role")
    return str(getattr(role, "value", role) or "").lower()


def reads_every_task(user: dict) -> bool:
    return role_of(user) in ROLES_THAT_READ_EVERY_TASK


def owns_conversation(user: dict, conversation: Conversations) -> bool:
    owner = conversation.owner_username
    return bool(owner) and owner == user.get("username")


def _root_of(task: Task, db: Session) -> Task:
    seen = {task.id}
    while task.parent_task_id and task.parent_task_id not in seen:
        parent = db.query(Task).filter(Task.id == task.parent_task_id).first()
        if parent is None:
            break
        seen.add(parent.id)
        task = parent
    return task


def _conversation_owner(conversation_id: int | None, db: Session) -> str | None:
    if conversation_id is None:
        return None
    conversation = db.query(Conversations).filter(Conversations.id == conversation_id).first()
    return conversation.owner_username if conversation is not None else None


def task_owner(task: Task, db: Session) -> str | None:
    if task.owner_username:
        return task.owner_username
    root = _root_of(task, db)
    if root.owner_username:
        return root.owner_username
    conversation_id = (
        task.conversation_id if task.conversation_id is not None else root.conversation_id
    )
    return _conversation_owner(conversation_id, db)


def may_read_task(user: dict, task: Task, db: Session) -> bool:
    if reads_every_task(user):
        return True
    owner = task_owner(task, db)
    return bool(owner) and owner == user.get("username")


def may_read_conversation_tasks(user: dict, conversation: Conversations) -> bool:
    return reads_every_task(user) or owns_conversation(user, conversation)


def root_tasks_visible_to(user: dict, query: Query) -> Query:
    if reads_every_task(user):
        return query
    username = user.get("username")
    owned_conversations = select(Conversations.id).where(Conversations.owner_username == username)
    unowned = or_(Task.owner_username.is_(None), Task.owner_username == "")
    return query.filter(
        or_(
            Task.owner_username == username,
            and_(unowned, Task.conversation_id.in_(owned_conversations)),
        )
    )
