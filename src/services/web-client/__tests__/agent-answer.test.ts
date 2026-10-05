import { describe, it, expect } from "vitest";
import type { Message } from "@/components/message-list";
import type { TaskDetails } from "@/lib/chat/api";
import {
  appendAgentAnswer,
  finishedTaskAnswer,
  isFinishedTask,
} from "@/lib/chat/agent-answer";

const question: Message = {
  id: "1",
  text: "Summarise the Q4 report",
  sender: "user",
  timestamp: new Date("2026-10-05T09:30:00Z"),
  status: "sent",
  taskId: "task-7",
};

function task(overrides: Partial<TaskDetails>): TaskDetails {
  return {
    task_id: "task-7",
    status: "running",
    agent_id: "agent-finance",
    conversation_id: 42,
    query: "Summarise the Q4 report",
    created_at: "2026-10-05T09:30:00",
    subtasks: [],
    ...overrides,
  };
}

describe("appendAgentAnswer", () => {
  const answer = {
    content: "Revenue grew 12%.",
    timestamp: new Date("2026-10-05T09:33:00Z"),
    agentId: "agent-finance",
    agentName: "Finance-Analyst",
  };

  it("appends the answer as an attributed agent message", () => {
    const messages = appendAgentAnswer([question], answer);

    expect(messages).toHaveLength(2);
    expect(messages[1]).toMatchObject({
      text: "Revenue grew 12%.",
      sender: "agent",
      status: "sent",
      agentId: "agent-finance",
      agentName: "Finance-Analyst",
    });
  });

  it("does not duplicate an answer the socket already delivered", () => {
    const delivered = appendAgentAnswer([question], answer);

    const resynced = appendAgentAnswer(delivered, {
      ...answer,
      content: "Revenue grew 12%.\n",
    });

    expect(resynced).toBe(delivered);
  });

  it("does not duplicate a resynced answer when the socket delivers it too", () => {
    const resynced = appendAgentAnswer([question], { ...answer, content: "  Revenue grew 12%." });

    const delivered = appendAgentAnswer(resynced, answer);

    expect(delivered).toBe(resynced);
  });

  it("ignores an empty answer", () => {
    const messages = [question];

    expect(appendAgentAnswer(messages, { ...answer, content: "   " })).toBe(messages);
  });
});

describe("finishedTaskAnswer", () => {
  it("treats only completed, failed and cancelled tasks as finished", () => {
    expect(isFinishedTask(task({ status: "running" }))).toBe(false);
    expect(isFinishedTask(task({ status: "pending" }))).toBe(false);
    expect(isFinishedTask(null)).toBe(false);
    expect(isFinishedTask(task({ status: "completed" }))).toBe(true);
    expect(isFinishedTask(task({ status: "failed" }))).toBe(true);
    expect(isFinishedTask(task({ status: "cancelled" }))).toBe(true);
  });

  it("gives a single-agent task's result to its agent", () => {
    expect(finishedTaskAnswer(task({ status: "completed", result: "Revenue grew 12%." }))).toEqual({
      content: "Revenue grew 12%.",
      agentId: "agent-finance",
    });
  });

  it("gives a chain's final answer to the specialist that ran the last step", () => {
    const chain = task({
      status: "completed",
      agent_id: "manager",
      result: "Combined briefing",
      subtasks: [
        { id: "s1", title: "research", status: "completed", assignedAgent: "agent-research" },
        { id: "s2", title: "write", status: "completed", assignedAgent: "agent-writer" },
      ],
    });

    expect(finishedTaskAnswer(chain)).toEqual({
      content: "Combined briefing",
      agentId: "agent-writer",
    });
  });

  it("has no answer text for a failed or cancelled task", () => {
    expect(finishedTaskAnswer(task({ status: "failed", result: "Traceback" })).content).toBe("");
    expect(finishedTaskAnswer(task({ status: "cancelled" })).content).toBe("");
  });
});
