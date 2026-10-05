import React from "react";
import { vi, describe, it, expect, beforeAll, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import ChatPage from "@/app/(protected)/chat/page";
import {
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
});
