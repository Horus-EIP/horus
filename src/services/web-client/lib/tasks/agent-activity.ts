import type { TaskDetail, TaskStatus } from "./types";

const IN_PROGRESS_STATUSES: readonly string[] = ["queued", "pending", "running"];

export function isTaskInProgress(status: TaskStatus | string | undefined): boolean {
  return status !== undefined && IN_PROGRESS_STATUSES.includes(status);
}

export function taskStatusByAgentId(
  task: Pick<TaskDetail, "agentId" | "status" | "subtasks">
): Record<string, TaskStatus> {
  const statuses: Record<string, TaskStatus> = {};
  const record = (agentId: string, status: TaskStatus) => {
    if (!isTaskInProgress(statuses[agentId])) statuses[agentId] = status;
  };
  const chainIsOpen = isTaskInProgress(task.status);
  task.subtasks.forEach((step) =>
    record(step.assignedAgent, chainIsOpen ? step.status : task.status)
  );
  record(task.agentId, task.status);
  return statuses;
}
