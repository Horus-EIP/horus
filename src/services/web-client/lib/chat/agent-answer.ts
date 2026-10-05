import type { Message } from "@/components/message-list";
import type { TaskDetails } from "@/lib/chat/api";

export type AgentAnswer = {
  content: string;
  timestamp: Date;
  agentId?: string;
  agentName?: string;
  skillUsed?: string;
};

const FINISHED_TASK_STATUSES = ["completed", "failed", "cancelled"];

export function isFinishedTask(task: TaskDetails | null): task is TaskDetails {
  return task !== null && FINISHED_TASK_STATUSES.includes(task.status);
}

export function finishedTaskAnswer(task: TaskDetails): { content: string; agentId: string } {
  const subtasks = task.subtasks ?? [];
  const answeringAgentId = subtasks[subtasks.length - 1]?.assignedAgent || task.agent_id;
  return {
    content: task.status === "completed" ? task.result ?? "" : "",
    agentId: answeringAgentId,
  };
}

export function appendAgentAnswer(messages: Message[], answer: AgentAnswer): Message[] {
  const text = answer.content.trim();
  const last = messages[messages.length - 1];
  if (!text || (last?.sender === "agent" && last.text.trim() === text)) {
    return messages;
  }
  return [
    ...messages,
    {
      id: Date.now().toString(),
      text: answer.content,
      sender: "agent",
      timestamp: answer.timestamp,
      status: "sent",
      agentId: answer.agentId,
      agentName: answer.agentName,
      skillUsed: answer.skillUsed,
    },
  ];
}
