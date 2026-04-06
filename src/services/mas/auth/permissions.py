from enum import Enum
from typing import Dict, List, Set


class Role(str, Enum):
    ADMIN = "admin"
    USER = "user"
    MANAGER = "manager"
    SYSTEM = "system"


class Permission(str, Enum):
    USER_CREATE = "user:create"
    USER_READ = "user:read"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"

    TASK_CREATE = "task:create"
    TASK_READ = "task:read"
    TASK_EXECUTE = "task:execute"
    TASK_DELETE = "task:delete"
    TASK_APPROVE = "task:approve"

    VIEW_ANALYTICS = "analytics:view"
    EXPORT_DATA = "data:export"

    SYSTEM_CONFIG = "system:config"

    AGENT_CREATE = "agent:create"
    AGENT_UPDATE = "agent:update"
    AGENT_DELETE = "agent:delete"
    AGENT_EXECUTE = "agent:execute"
    AGENT_READ = "agent:read"


ROLE_PERMISSION: Dict[Role, Set[Permission]] = {
    Role.ADMIN: {
        Permission.EXPORT_DATA,
        Permission.SYSTEM_CONFIG,
        Permission.TASK_APPROVE,
        Permission.TASK_CREATE,
        Permission.TASK_DELETE,
        Permission.TASK_EXECUTE,
        Permission.TASK_READ,
        Permission.USER_CREATE,
        Permission.USER_DELETE,
        Permission.USER_READ,
        Permission.USER_UPDATE,
        Permission.VIEW_ANALYTICS,
        Permission.AGENT_CREATE,
        Permission.AGENT_DELETE,
        Permission.AGENT_EXECUTE,
        Permission.AGENT_UPDATE,
        Permission.AGENT_READ,
    },
    Role.MANAGER: {
        Permission.USER_READ,
        Permission.TASK_CREATE,
        Permission.TASK_APPROVE,
        Permission.TASK_DELETE,
        Permission.TASK_EXECUTE,
        Permission.VIEW_ANALYTICS,
        Permission.EXPORT_DATA,
        Permission.AGENT_READ,
        Permission.AGENT_EXECUTE,
    },
    Role.USER: {
        Permission.USER_READ,
        Permission.TASK_READ,
        Permission.TASK_CREATE,
        Permission.TASK_DELETE,
        Permission.AGENT_READ,
        Permission.AGENT_EXECUTE,
        Permission.VIEW_ANALYTICS,
    },
    Role.SYSTEM: {
        Permission.TASK_EXECUTE,
        Permission.TASK_READ,
        Permission.AGENT_READ,
        Permission.AGENT_EXECUTE,
    },
}


def check_permission(user_role: str, required_permission: Permission) -> bool:
    try:
        role = Role(user_role.lower())
    except ValueError:
        return False

    return required_permission in ROLE_PERMISSION.get(role, set())
