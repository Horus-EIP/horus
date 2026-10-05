import type { Message } from "@/components/message-list";
import type { TaskDetails } from "@/lib/chat/api";

export type AgentAnswer = {
  content: string;
  timestamp: Date;
  agentId?: string;
  agentName?: string;
  skillUsed?: string;
  messageId?: number;
  failed?: boolean;
};

const FINISHED_TASK_STATUSES = ["completed", "failed", "cancelled"];

export const FAILED_TASK_TEXT = "This request failed before an answer was produced.";
export const CANCELLED_TASK_TEXT = "This request was cancelled before it finished.";

let answersAppended = 0;

export function isFinishedTask(task: TaskDetails | null): task is TaskDetails {
  return task !== null && FINISHED_TASK_STATUSES.includes(task.status);
}

function finishedTaskText(task: TaskDetails): string {
  if (task.status === "completed") return task.result ?? "";
  if (task.status === "cancelled") return task.result?.trim() || CANCELLED_TASK_TEXT;
  return FAILED_TASK_TEXT;
}

export function finishedTaskAnswer(task: TaskDetails): {
  content: string;
  agentId: string;
  failed: boolean;
} {
  const subtasks = task.subtasks ?? [];
  const answeringAgentId = subtasks[subtasks.length - 1]?.assignedAgent || task.agent_id;
  return {
    content: finishedTaskText(task),
    agentId: answeringAgentId,
    failed: task.status === "failed",
  };
}

function isAlreadyShown(messages: Message[], answer: AgentAnswer, text: string): boolean {
  if (
    answer.messageId !== undefined &&
    messages.some((message) => message.messageId === answer.messageId)
  ) {
    return true;
  }
  const last = messages[messages.length - 1];
  return last?.sender === "agent" && last.text.trim() === text;
}

export function appendAgentAnswer(messages: Message[], answer: AgentAnswer): Message[] {
  const text = answer.content.trim();
  if (!text || isAlreadyShown(messages, answer, text)) {
    return messages;
  }
  answersAppended += 1;
  return [
    ...messages,
    {
      id: `${Date.now()}-${answersAppended}`,
      text: answer.content,
      sender: "agent",
      timestamp: answer.timestamp,
      status: answer.failed ? "error" : "sent",
      agentId: answer.agentId,
      agentName: answer.agentName,
      skillUsed: answer.skillUsed,
      messageId: answer.messageId,
    },
  ];
}
