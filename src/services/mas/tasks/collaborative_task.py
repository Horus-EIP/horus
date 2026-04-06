import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class SubTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    agent_type: str
    status: TaskStatus = TaskStatus.PENDING
    depends_on: List[str] = []
    result: Optional[str] = None
    agent_id: Optional[str] = None


class CollaborativeTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_demand: Optional[str] = ""
    sub_tasks: List[SubTask]
    context: Dict[str, Any] = {}

    def get_ready_subtasks(self) -> List[SubTask]:
        """
        Returns a list of subtasks that are pending and have all their dependencies met.
        """
        ready = []
        # Get IDs of completed tasks
        completed_ids = {
            t.id for t in self.sub_tasks if t.status == TaskStatus.COMPLETED
        }

        for task in self.sub_tasks:
            if task.status == TaskStatus.PENDING:
                # Check dependencies
                dependencies_met = True
                for dep_id in task.depends_on:
                    if dep_id not in completed_ids:
                        dependencies_met = False
                        break

                if dependencies_met:
                    ready.append(task)
        return ready

    def update_subtask_status(
        self, subtask_id: str, status: TaskStatus, result: Optional[str] = None
    ):
        """
        Updates the status and result of a specific subtask.
        """
        for task in self.sub_tasks:
            if task.id == subtask_id:
                task.status = status
                if result:
                    task.result = result
                break

    def is_complete(self) -> bool:
        """
        Checks if the entire collaborative task is complete.
        """
        return all(task.status == TaskStatus.COMPLETED for task in self.sub_tasks)

    def aggregate_results(self) -> str:
        """
        Aggregates results from all completed subtasks.
        """
        results = []
        for task in self.sub_tasks:
            if task.status == TaskStatus.COMPLETED:
                results.append(f"Task ({task.agent_type}): {task.result}")
        return "\n\n".join(results)
