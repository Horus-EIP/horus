import React from "react";
import { vi, describe, it, expect, beforeAll, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import ChatPage from "@/app/(protected)/chat/page";
import {
  MockWebSocket,
  installMockWebSocket,
  latestSocket,
  waitForOpenSockets,
} from "./support/mock-web-socket";

const { notification, chatApiMock, agentApiMock } = vi.hoisted(() => ({
  notification: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
  chatApiMock: {
    getConversations: vi.fn(),
    getHistory: vi.fn(),
    getRunningTasksForConversation: vi.fn(),
    getTask: vi.fn(),
    getTaskEvents: vi.fn(),
    createTask: vi.fn(),
    cancelTask: vi.fn(),
    createConversation: vi.fn(),
    deleteConversation: vi.fn(),
  },
  agentApiMock: {
    getAgents: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({
    get: (key: string) => (key === "conversation" ? "42" : null),
  }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@/contexts/notification-context", () => ({
  useNotification: () => notification,
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({ user: { username: "alice", role: "user" } }),
}));

vi.mock("@/components/tasks/file-attachments", () => ({
  FileAttachments: () => null,
}));

vi.mock("@/lib/chat/api", () => ({
  chatApi: chatApiMock,
}));

vi.mock("@/lib/agents/api", () => ({
  agentApi: agentApiMock,
}));

const ANSWER = "Q4 revenue grew 12% year on year.";
const TIMEOUT_NOTICE =
  "This request exceeded the maximum processing time (1800s) and was stopped.";

function storedEvents(events: Array<Record<string, unknown>>, taskId = "root-7") {
  return {
    ok: true,
    data: {
      task_id: taskId,
      status: "running",
      since: 0,
      events: events.map((data, index) => ({
        task_id: taskId,
        seq: index + 1,
        type: data.event_type ?? "progress",
        stage: "generation",
        data,
        ts: "2026-10-05T09:31:00Z",
      })),
      last_seq: events.length,
      has_more: false,
    },
  };
}

const runningRoot = {
  id: "root-7",
  status: "running",
  agent_id: "manager",
  conversation_id: 42,
  query: "Summarise the Q4 report",
  created_at: "2026-10-05T09:30:00",
};

function rootDetail(status: string, result?: string) {
  return {
    task_id: "root-7",
    status,
    agent_id: "manager",
    conversation_id: 42,
    query: "Summarise the Q4 report",
    created_at: "2026-10-05T09:30:00",
    result,
    subtasks: [
      { id: "sub-1", title: "summarise", status, assignedAgent: "agent-finance" },
    ],
  };
}

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  window.ResizeObserver = ResizeObserverStub;
  window.HTMLElement.prototype.scrollIntoView = () => {};
});

describe("chat page after a WebSocket reconnect", () => {
  beforeEach(() => {
    installMockWebSocket();
    localStorage.setItem("auth_token", "token");
    Object.values(chatApiMock).forEach((fn) => fn.mockReset());
    chatApiMock.getConversations.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getHistory.mockResolvedValue({
      ok: true,
      data: {
        items: [
          {
            role: "user",
            message: "Summarise the Q4 report",
            timestamp: "2026-10-05T09:30:00",
          },
        ],
        nextCursor: null,
      },
    });
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({
      ok: true,
      data: [runningRoot],
    });
    chatApiMock.getTask.mockResolvedValue({ ok: true, data: rootDetail("running") });
    chatApiMock.getTaskEvents.mockResolvedValue(storedEvents([]));
    agentApiMock.getAgents.mockResolvedValue({
      ok: true,
      data: [{ id: "agent-finance", name: "Finance-Analyst" }],
    });
  });

  async function renderWaitingChat() {
    render(
      <MantineProvider>
        <ChatPage />
      </MantineProvider>
    );
    await waitForOpenSockets(1);
    await screen.findByLabelText("Stop generating");
  }

  it("shows a result that finished while the socket was down, once", async () => {
    await renderWaitingChat();
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getTask.mockResolvedValue({
      ok: true,
      data: rootDetail("completed", ANSWER),
    });

    latestSocket().dropFromServer();

    await screen.findByText(ANSWER, {}, { timeout: 3000 });
    expect(screen.getByLabelText("Send message")).toBeInTheDocument();
    expect(screen.queryByLabelText("Stop generating")).not.toBeInTheDocument();
    expect(screen.getByTitle("Agent ID: agent-finance")).toHaveTextContent("Finance-Analyst");

    latestSocket().deliver({
      type: "task_complete",
      content: ANSWER,
      timestamp: "2026-10-05T09:33:00",
      agent_id: "agent-finance",
      agent_name: "Finance-Analyst",
      skill_used: "analysis",
    });

    expect(screen.getAllByText(ANSWER)).toHaveLength(1);
  });

  it("keeps waiting when the task is still running after the reconnect", async () => {
    await renderWaitingChat();
    expect(chatApiMock.getRunningTasksForConversation).toHaveBeenCalledTimes(1);

    latestSocket().dropFromServer();

    await waitForOpenSockets(2, 3000);
    await waitFor(() =>
      expect(chatApiMock.getRunningTasksForConversation).toHaveBeenCalledTimes(2)
    );
    expect(screen.getByLabelText("Stop generating")).toBeInTheDocument();
    expect(screen.queryByText(ANSWER)).not.toBeInTheDocument();
  });

  it("replays the events missed while the socket was down and shows the answer once", async () => {
    await renderWaitingChat();
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getTask.mockResolvedValue({ ok: true, data: rootDetail("completed", ANSWER) });
    chatApiMock.getTaskEvents.mockResolvedValue(
      storedEvents([
        { type: "task_status", status: "running", stage: "retrieval" },
        {
          type: "task_complete",
          event_type: "result",
          content: ANSWER,
          timestamp: "2026-10-05T09:33:00",
          agent_id: "agent-finance",
          agent_name: "Finance-Analyst",
          skill_used: "analysis",
          message_id: 90,
        },
      ])
    );

    latestSocket().dropFromServer();

    await screen.findByText(ANSWER, {}, { timeout: 3000 });
    expect(chatApiMock.getTaskEvents).toHaveBeenLastCalledWith("root-7", 0);
    expect(screen.queryByLabelText("Stop generating")).not.toBeInTheDocument();

    latestSocket().deliver({
      type: "task_complete",
      content: ANSWER,
      timestamp: "2026-10-05T09:33:00",
      agent_id: "agent-finance",
      agent_name: "Finance-Analyst",
      task_id: "root-7",
      seq: 2,
      event: "result",
    });

    expect(screen.getAllByText(ANSWER)).toHaveLength(1);
  });

  it("explains a task that was cancelled while the socket was down", async () => {
    await renderWaitingChat();
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getTask.mockResolvedValue({ ok: true, data: rootDetail("cancelled") });

    latestSocket().dropFromServer();

    await screen.findByText(
      "This request was cancelled before it finished.",
      {},
      { timeout: 3000 }
    );
    expect(screen.getByLabelText("Send message")).toBeInTheDocument();
  });

  it("explains a failed task found on reconnect", async () => {
    await renderWaitingChat();
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getTask.mockResolvedValue({ ok: true, data: rootDetail("failed", "Traceback") });

    latestSocket().dropFromServer();

    await screen.findByText(
      "This request failed before an answer was produced.",
      {},
      { timeout: 3000 }
    );
    expect(screen.queryByText("Traceback")).not.toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("shows the timeout notice replayed from the task's events, once", async () => {
    await renderWaitingChat();
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getTask.mockResolvedValue({
      ok: true,
      data: rootDetail("cancelled", TIMEOUT_NOTICE),
    });
    chatApiMock.getTaskEvents.mockResolvedValue(
      storedEvents([
        {
          type: "agent",
          event_type: "error",
          content: TIMEOUT_NOTICE,
          status: "cancelled",
          reason: "timeout",
          timestamp: "2026-10-05T10:00:00",
        },
      ])
    );

    latestSocket().dropFromServer();

    await screen.findByText(TIMEOUT_NOTICE, {}, { timeout: 3000 });
    expect(screen.getAllByText(TIMEOUT_NOTICE)).toHaveLength(1);
    expect(screen.getByLabelText("Send message")).toBeInTheDocument();
  });

  it("shows a calm reconnecting state instead of giving up while the task runs", async () => {
    await renderWaitingChat();
    MockWebSocket.refuseConnections = true;

    latestSocket().dropFromServer();

    await screen.findByText(
      "Connection lost. Reconnecting… your request keeps running on the server."
    );
    expect(screen.getByLabelText("Stop generating")).toBeInTheDocument();
    expect(notification.error).not.toHaveBeenCalledWith("Connection lost. Please refresh the page.");
  });
});

describe("chat page sending a question", () => {
  beforeEach(() => {
    installMockWebSocket();
    localStorage.setItem("auth_token", "token");
    Object.values(chatApiMock).forEach((fn) => fn.mockReset());
    chatApiMock.getConversations.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getHistory.mockResolvedValue({ ok: true, data: { items: [], nextCursor: null } });
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getTask.mockResolvedValue({ ok: false, error: "not yet" });
    chatApiMock.getTaskEvents.mockResolvedValue(storedEvents([], "root-9"));
    chatApiMock.createTask.mockResolvedValue({
      ok: true,
      data: { task_id: "root-9", status: "queued", conversation_id: 42 },
    });
    agentApiMock.getAgents.mockResolvedValue({ ok: true, data: [] });
  });

  async function ask(question: string) {
    render(
      <MantineProvider>
        <ChatPage />
      </MantineProvider>
    );
    await waitForOpenSockets(1);
    fireEvent.change(screen.getByPlaceholderText("Type a message..."), {
      target: { value: question },
    });
    fireEvent.click(screen.getByLabelText("Send message"));
    await screen.findByLabelText("Stop generating");
  }

  it("follows the queued task's progress and answer over the socket", async () => {
    await ask("What was Q4 2025 revenue?");

    expect(chatApiMock.createTask).toHaveBeenCalledTimes(1);
    expect(chatApiMock.createTask.mock.calls[0][0]).toMatchObject({
      demand: "What was Q4 2025 revenue?",
      conversation_id: "42",
    });

    latestSocket().deliver({
      type: "task_status",
      status: "queued",
      task_id: "root-9",
      seq: 1,
      event: "progress",
      stage: "queued",
    });
    await screen.findByText("Queued, waiting for the orchestrator");

    latestSocket().deliver({
      type: "heartbeat",
      elapsed_s: 65,
      task_id: "root-9",
      seq: 2,
      event: "heartbeat",
      stage: "routing",
    });
    await screen.findByText("Choosing the right agents · 1m 05s");

    latestSocket().deliver({
      type: "task_complete",
      content: ANSWER,
      timestamp: "2026-10-05T09:33:00",
      agent_id: "agent-finance",
      agent_name: "Finance-Analyst",
      task_id: "root-9",
      seq: 3,
      event: "result",
      stage: "generation",
    });

    await screen.findByText(ANSWER);
    expect(screen.getByLabelText("Send message")).toBeInTheDocument();
    expect(screen.queryByText("Choosing the right agents · 1m 05s")).not.toBeInTheDocument();
  });

  it("shows the place in line, then marks a timed-out answer as failed", async () => {
    await ask("Summarise every 2025 report");

    latestSocket().deliver({
      type: "task_status",
      status: "busy",
      detail: "Busy, position 11",
      position: 11,
      task_id: "root-9",
      seq: 2,
      event: "progress",
      stage: "queued",
    });
    await screen.findByText("Busy, position 11");

    latestSocket().deliver({
      type: "task_complete",
      content: "The model did not finish its answer within 900s, so this request was stopped.",
      agent_id: "agent-finance",
      agent_name: "Finance-Analyst",
      status: "failed",
      reason: "timeout",
      task_id: "root-9",
      seq: 3,
      event: "error",
      stage: "generation",
    });

    await screen.findByText(
      "The model did not finish its answer within 900s, so this request was stopped."
    );
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.queryByText("Busy, position 11")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Send message")).toBeInTheDocument();
  });

  it("explains why a question could not be routed", async () => {
    await ask("What is FinCorp's CEO?");

    latestSocket().deliver({
      type: "agent",
      content: "No agents are currently registered with the orchestrator.",
      status: "failed",
      route: "none",
      task_id: "root-9",
      seq: 2,
      event: "error",
    });

    await screen.findByText("No agents are currently registered with the orchestrator.");
    expect(screen.getByLabelText("Send message")).toBeInTheDocument();
  });

  it("marks the question unsent when the task cannot be queued", async () => {
    chatApiMock.createTask.mockResolvedValue({ ok: false, error: "Failed to create task" });
    render(
      <MantineProvider>
        <ChatPage />
      </MantineProvider>
    );
    await waitForOpenSockets(1);
    fireEvent.change(screen.getByPlaceholderText("Type a message..."), {
      target: { value: "hello" },
    });
    fireEvent.click(screen.getByLabelText("Send message"));

    await waitFor(() =>
      expect(notification.error).toHaveBeenCalledWith(
        "Your message could not be sent. Please try again."
      )
    );
    expect(screen.getByLabelText("Send message")).toBeInTheDocument();
  });
});
