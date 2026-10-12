import React from "react";
import { vi, describe, it, expect, beforeAll, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import ChatPage from "@/app/(protected)/chat/page";
import {
  MockWebSocket,
  installMockWebSocket,
  latestSocket,
  waitForOpenSockets,
} from "./support/mock-web-socket";

const { notification, chatApiMock, agentApiMock, navigation } = vi.hoisted(() => ({
  navigation: { conversation: "42" },
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
    get: (key: string) => (key === "conversation" ? navigation.conversation : null),
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
  FileAttachments: ({
    value,
    onChange,
  }: {
    value: { attached: Array<{ filename: string; doc_id?: string }>; inline: unknown[] };
    onChange: (next: { attached: Array<{ filename: string; doc_id?: string }>; inline: unknown[] }) => void;
  }) => (
    <div>
      <span data-testid="attachment-count">{value.attached.length + value.inline.length}</span>
      <button
        type="button"
        onClick={() =>
          onChange({ attached: [...value.attached, { filename: "q4.pdf", doc_id: "doc-q4" }], inline: value.inline })
        }
      >
        Attach the Q4 report
      </button>
    </div>
  ),
}));

vi.mock("@/lib/chat/api", () => ({
  chatApi: chatApiMock,
}));

vi.mock("@/lib/agents/api", () => ({
  agentApi: agentApiMock,
}));

const ANSWER = "Q4 revenue grew 12% year on year.";
const Q4_SOURCE = {
  doc_id: "doc-q4",
  chunk_id: "doc-q4:3",
  title: "1_Q4_2025_Financial_Report.md",
  page: 2,
};
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
    const beforeTheDrop = chatApiMock.getRunningTasksForConversation.mock.calls.length;
    expect([1, 2]).toContain(beforeTheDrop);

    latestSocket().dropFromServer();

    await waitForOpenSockets(2, 3000);
    await waitFor(() =>
      expect(chatApiMock.getRunningTasksForConversation).toHaveBeenCalledTimes(beforeTheDrop + 1)
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

  it("shows the sources of a live answer under it", async () => {
    await renderWaitingChat();

    latestSocket().deliver({
      type: "task_complete",
      content: ANSWER,
      timestamp: "2026-10-05T09:33:00",
      agent_id: "agent-finance",
      agent_name: "Finance-Analyst",
      task_id: "root-7",
      seq: 5,
      event: "result",
      sources: [Q4_SOURCE],
    });

    await screen.findByText(ANSWER);
    expect(
      screen.getByRole("link", { name: /1_Q4_2025_Financial_Report\.md, page 2/ })
    ).toHaveAttribute("href", "/knowledge-store?doc=doc-q4");
  });

  it("shows the sources of an answer found on reconnect", async () => {
    await renderWaitingChat();
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getTask.mockResolvedValue({
      ok: true,
      data: { ...rootDetail("completed", ANSWER), sources: [Q4_SOURCE] },
    });

    latestSocket().dropFromServer();

    await screen.findByText(ANSWER, {}, { timeout: 3000 });
    expect(
      screen.getByRole("link", { name: /1_Q4_2025_Financial_Report\.md, page 2/ })
    ).toBeInTheDocument();
  });

  it("clears the live preview when the orchestrator asks the agent once more", async () => {
    await renderWaitingChat();
    const delta = (chunk: string, index: number, seq: number) => ({
      type: "task_step",
      step_type: "reasoning.delta",
      task_id: "root-7",
      subtask_id: "root-7",
      metadata: { chunk, index },
      seq,
      event: "token",
    });

    latestSocket().deliver(delta("The documents do not say.", 0, 3));
    await screen.findByText("The documents do not say.");

    latestSocket().deliver({
      type: "task_status",
      status: "retrying",
      detail: "The documents found did not answer it; searching again with another query.",
      attempt: 2,
      task_id: "root-7",
      seq: 4,
      event: "progress",
      stage: "retrieval",
    });

    await waitFor(() =>
      expect(screen.queryByText("The documents do not say.")).not.toBeInTheDocument()
    );
    expect(
      screen.getByText(
        "The documents found did not answer it; searching again with another query."
      )
    ).toBeInTheDocument();

    latestSocket().deliver(delta("Revenue grew 12%.", 0, 5));
    await screen.findByText("Revenue grew 12%.");
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

describe("chat page following a task it adopted on load", () => {
  const finalAnswerEvent = {
    type: "task_complete",
    event_type: "result",
    content: ANSWER,
    timestamp: "2026-10-05T09:33:00",
    agent_id: "agent-finance",
    agent_name: "Finance-Analyst",
    skill_used: "analysis",
    message_id: 90,
  };

  function renderChat() {
    return render(
      <MantineProvider>
        <ChatPage />
      </MantineProvider>
    );
  }

  beforeEach(() => {
    installMockWebSocket();
    navigation.conversation = "42";
    localStorage.setItem("auth_token", "token");
    Object.values(chatApiMock).forEach((fn) => fn.mockReset());
    chatApiMock.getConversations.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getHistory.mockResolvedValue({
      ok: true,
      data: {
        items: [
          { role: "user", message: "Summarise the Q4 report", timestamp: "2026-10-05T09:30:00" },
        ],
        nextCursor: null,
      },
    });
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [runningRoot] });
    chatApiMock.getTask.mockResolvedValue({ ok: true, data: rootDetail("running") });
    chatApiMock.getTaskEvents.mockResolvedValue(storedEvents([]));
    agentApiMock.getAgents.mockResolvedValue({
      ok: true,
      data: [{ id: "agent-finance", name: "Finance-Analyst" }],
    });
  });

  afterEach(() => {
    navigation.conversation = "42";
  });

  it("replays the missed events when the socket first opens after the task was adopted", async () => {
    MockWebSocket.holdOpen = true;
    renderChat();
    await screen.findByLabelText("Stop generating");
    await waitFor(() => expect(chatApiMock.getTaskEvents).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(0));
    chatApiMock.getTaskEvents.mockResolvedValue(storedEvents([finalAnswerEvent]));

    latestSocket().openFromServer();

    await screen.findByText(ANSWER, {}, { timeout: 3000 });
    expect(chatApiMock.getTaskEvents).toHaveBeenLastCalledWith("root-7", 0);
    expect(screen.getAllByText(ANSWER)).toHaveLength(1);
    expect(screen.queryByLabelText("Stop generating")).not.toBeInTheDocument();
  });

  it("ends the turn once when the task poll sees the task finished", async () => {
    renderChat();
    await waitForOpenSockets(1);
    await screen.findByLabelText("Stop generating");
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getTask.mockResolvedValue({ ok: true, data: rootDetail("completed", ANSWER) });

    await screen.findByText(ANSWER, {}, { timeout: 4000 });
    expect(screen.queryByLabelText("Stop generating")).not.toBeInTheDocument();
    expect(screen.getByTitle("Agent ID: agent-finance")).toHaveTextContent("Finance-Analyst");

    latestSocket().deliver({ ...finalAnswerEvent, type: "task_complete", task_id: "root-7", seq: 4, event: "result" });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1800));
    });
    expect(screen.getAllByText(ANSWER)).toHaveLength(1);
  });

  it("drops a replay that arrives after the user switched to another conversation", async () => {
    MockWebSocket.holdOpen = true;
    let finishReplay: (page: unknown) => void = () => {};
    chatApiMock.getTaskEvents.mockImplementationOnce(
      () => new Promise((resolve) => {
        finishReplay = resolve;
      })
    );
    const view = renderChat();
    await screen.findByLabelText("Stop generating");
    await waitFor(() => expect(chatApiMock.getTaskEvents).toHaveBeenCalledTimes(1));

    chatApiMock.getHistory.mockResolvedValue({
      ok: true,
      data: {
        items: [{ role: "user", message: "What is the travel policy?", timestamp: "2026-10-05T10:00:00" }],
        nextCursor: null,
      },
    });
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [] });
    navigation.conversation = "43";
    view.rerender(
      <MantineProvider>
        <ChatPage />
      </MantineProvider>
    );
    await screen.findByText("What is the travel policy?");

    await act(async () => {
      finishReplay(storedEvents([finalAnswerEvent]));
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    expect(screen.queryByText(ANSWER)).not.toBeInTheDocument();
    expect(screen.getByText("What is the travel policy?")).toBeInTheDocument();
  });
});

describe("chat page switching conversation while a task runs", () => {
  const otherHistory = {
    ok: true,
    data: {
      items: [{ role: "user", message: "What is the travel policy?", timestamp: "2026-10-05T10:00:00" }],
      nextCursor: null,
    },
  };

  function renderChat() {
    return render(
      <MantineProvider>
        <ChatPage />
      </MantineProvider>
    );
  }

  async function switchTo(view: ReturnType<typeof renderChat>, conversation: string) {
    navigation.conversation = conversation;
    view.rerender(
      <MantineProvider>
        <ChatPage />
      </MantineProvider>
    );
  }

  function pollsOf(taskId: string) {
    return chatApiMock.getTask.mock.calls.filter(([id]) => id === taskId).length;
  }

  beforeEach(() => {
    installMockWebSocket();
    navigation.conversation = "42";
    localStorage.setItem("auth_token", "token");
    Object.values(chatApiMock).forEach((fn) => fn.mockReset());
    chatApiMock.getConversations.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getHistory.mockImplementation(async (conversationId: string) =>
      conversationId === "43"
        ? otherHistory
        : {
            ok: true,
            data: {
              items: [
                { role: "user", message: "Summarise the Q4 report", timestamp: "2026-10-05T09:30:00" },
              ],
              nextCursor: null,
            },
          }
    );
    chatApiMock.getRunningTasksForConversation.mockImplementation(async (conversationId: string) => ({
      ok: true,
      data: conversationId === "42" ? [runningRoot] : [],
    }));
    chatApiMock.getTask.mockResolvedValue({ ok: true, data: rootDetail("running") });
    chatApiMock.getTaskEvents.mockResolvedValue(storedEvents([]));
    agentApiMock.getAgents.mockResolvedValue({
      ok: true,
      data: [{ id: "agent-finance", name: "Finance-Analyst" }],
    });
  });

  afterEach(() => {
    navigation.conversation = "42";
  });

  it("leaves no spinner and stops the old task's poll after switching away", async () => {
    const view = renderChat();
    await screen.findByLabelText("Stop generating");
    await waitFor(() => expect(pollsOf("root-7")).toBeGreaterThan(0));

    await switchTo(view, "43");
    await screen.findByText("What is the travel policy?");

    await waitFor(() => expect(screen.queryByLabelText("Stop generating")).not.toBeInTheDocument());
    expect(screen.getByLabelText("Send message")).toBeInTheDocument();
    const pollsAfterSwitch = pollsOf("root-7");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1800));
    });
    expect(pollsOf("root-7")).toBe(pollsAfterSwitch);
  });

  it("adopts the task again when switching back while it still runs", async () => {
    const view = renderChat();
    await screen.findByLabelText("Stop generating");
    await switchTo(view, "43");
    await screen.findByText("What is the travel policy?");
    await waitFor(() => expect(screen.queryByLabelText("Stop generating")).not.toBeInTheDocument());
    const replaysBefore = chatApiMock.getTaskEvents.mock.calls.length;

    await switchTo(view, "42");

    await screen.findByLabelText("Stop generating");
    await waitFor(() => expect(chatApiMock.getTaskEvents.mock.calls.length).toBeGreaterThan(replaysBefore));
    expect(chatApiMock.getTaskEvents).toHaveBeenLastCalledWith("root-7", 0);
  });

  it("shows the answer once when the task finished while the user was away", async () => {
    const view = renderChat();
    await screen.findByLabelText("Stop generating");
    await switchTo(view, "43");
    await screen.findByText("What is the travel policy?");

    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getTask.mockResolvedValue({ ok: true, data: rootDetail("completed", ANSWER) });
    chatApiMock.getHistory.mockImplementation(async (conversationId: string) =>
      conversationId === "43"
        ? otherHistory
        : {
            ok: true,
            data: {
              items: [
                { role: "user", message: "Summarise the Q4 report", timestamp: "2026-10-05T09:30:00" },
                {
                  role: "agent",
                  message: ANSWER,
                  timestamp: "2026-10-05T09:33:00",
                  agentId: "agent-finance",
                  agentName: "Finance-Analyst",
                  messageId: 90,
                },
              ],
              nextCursor: null,
            },
          }
    );

    await switchTo(view, "42");

    await screen.findByText(ANSWER);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1800));
    });
    expect(screen.getAllByText(ANSWER)).toHaveLength(1);
    expect(screen.queryByLabelText("Stop generating")).not.toBeInTheDocument();
  });

  it("does not follow a task sent from the conversation the user has left", async () => {
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getTaskEvents.mockImplementation(async (taskId: string) =>
      storedEvents(
        taskId === "root-9"
          ? [{ type: "task_complete", event_type: "result", content: ANSWER, agent_id: "agent-finance" }]
          : [],
        taskId
      )
    );
    let answerCreate: (value: unknown) => void = () => {};
    chatApiMock.createTask.mockImplementation(
      () => new Promise((resolve) => {
        answerCreate = resolve;
      })
    );
    const view = renderChat();
    await waitForOpenSockets(1);
    fireEvent.change(screen.getByPlaceholderText("Type a message..."), {
      target: { value: "What was Q4 2025 revenue?" },
    });
    fireEvent.click(screen.getByLabelText("Send message"));
    await screen.findByLabelText("Stop generating");

    await switchTo(view, "43");
    await screen.findByText("What is the travel policy?");
    await act(async () => {
      answerCreate({ ok: true, data: { task_id: "root-9", status: "queued", conversation_id: 42 } });
    });
    latestSocket().dropFromServer();
    await waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(1));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
    });

    expect(screen.queryByText(ANSWER)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Stop generating")).not.toBeInTheDocument();
  });
});

describe("chat page attachments", () => {
  const travelHistory = {
    ok: true,
    data: {
      items: [{ role: "user", message: "What is the travel policy?", timestamp: "2026-10-05T10:00:00" }],
      nextCursor: null,
    },
  };

  function renderChat() {
    return render(
      <MantineProvider>
        <ChatPage />
      </MantineProvider>
    );
  }

  async function switchTo(view: ReturnType<typeof renderChat>, conversation: string) {
    navigation.conversation = conversation;
    view.rerender(
      <MantineProvider>
        <ChatPage />
      </MantineProvider>
    );
    if (conversation === "43") await screen.findByText("What is the travel policy?");
  }

  function attachmentCount() {
    return screen.getByTestId("attachment-count").textContent;
  }

  function typeAndSend(text: string) {
    fireEvent.change(screen.getByPlaceholderText("Type a message..."), { target: { value: text } });
    fireEvent.click(screen.getByLabelText("Send message"));
  }

  function heldCreate() {
    let answer: (value: unknown) => void = () => {};
    chatApiMock.createTask.mockImplementationOnce(
      () => new Promise((resolve) => {
        answer = resolve;
      })
    );
    return (value: unknown) => answer(value);
  }

  beforeEach(() => {
    installMockWebSocket();
    navigation.conversation = "42";
    localStorage.setItem("auth_token", "token");
    Object.values(chatApiMock).forEach((fn) => fn.mockReset());
    notification.error.mockReset();
    chatApiMock.getConversations.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getHistory.mockImplementation(async (conversationId: string) =>
      conversationId === "43" ? travelHistory : { ok: true, data: { items: [], nextCursor: null } }
    );
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getTask.mockResolvedValue({ ok: false, error: "not yet" });
    chatApiMock.getTaskEvents.mockResolvedValue(storedEvents([], "root-9"));
    chatApiMock.createTask.mockResolvedValue({
      ok: true,
      data: { task_id: "root-9", status: "queued", conversation_id: 43 },
    });
    agentApiMock.getAgents.mockResolvedValue({ ok: true, data: [] });
  });

  afterEach(() => {
    navigation.conversation = "42";
  });

  it("does not carry the files of a message sent before switching into the next conversation", async () => {
    const view = renderChat();
    await waitForOpenSockets(1);
    fireEvent.click(screen.getByText("Attach the Q4 report"));
    const answerFirst = heldCreate();
    typeAndSend("Summarise this report");
    await screen.findByLabelText("Stop generating");

    await switchTo(view, "43");
    expect(attachmentCount()).toBe("0");
    await act(async () => {
      answerFirst({ ok: true, data: { task_id: "root-8", status: "queued", conversation_id: 42 } });
    });
    typeAndSend("What is the hotel limit?");

    await waitFor(() => expect(chatApiMock.createTask).toHaveBeenCalledTimes(2));
    expect(chatApiMock.createTask.mock.calls[0][0].attached_files).toEqual([
      { filename: "q4.pdf", doc_id: "doc-q4" },
    ]);
    expect(chatApiMock.createTask.mock.calls[1][0]).toMatchObject({
      conversation_id: "43",
      attached_files: [],
      inline_files: [],
    });
  });

  it("empties the picker while a message is sent and gives the files back when the send fails", async () => {
    renderChat();
    await waitForOpenSockets(1);
    fireEvent.click(screen.getByText("Attach the Q4 report"));
    const answer = heldCreate();
    typeAndSend("Summarise this report");

    await waitFor(() => expect(attachmentCount()).toBe("0"));
    await act(async () => {
      answer({ ok: false, error: "Failed to create task" });
    });

    expect(attachmentCount()).toBe("1");
    expect(notification.error).toHaveBeenCalledWith("Your message could not be sent. Please try again.");
  });

  it("empties the picker when the user switches conversation", async () => {
    const view = renderChat();
    await waitForOpenSockets(1);
    fireEvent.click(screen.getByText("Attach the Q4 report"));
    expect(attachmentCount()).toBe("1");

    await switchTo(view, "43");

    expect(attachmentCount()).toBe("0");
  });

  it("stays quiet in the new conversation when a send from the old one fails", async () => {
    const view = renderChat();
    await waitForOpenSockets(1);
    fireEvent.click(screen.getByText("Attach the Q4 report"));
    const answer = heldCreate();
    typeAndSend("Summarise this report");
    await screen.findByLabelText("Stop generating");

    await switchTo(view, "43");
    await act(async () => {
      answer({ ok: false, error: "Failed to create task" });
    });

    expect(notification.error).not.toHaveBeenCalled();
    expect(attachmentCount()).toBe("0");
  });
});

describe("chat page polling a task the server refuses", () => {
  function pollsOf(taskId: string) {
    return chatApiMock.getTask.mock.calls.filter(([id]) => id === taskId).length;
  }

  async function renderWaitingChat() {
    render(
      <MantineProvider>
        <ChatPage />
      </MantineProvider>
    );
    await waitForOpenSockets(1);
    await screen.findByLabelText("Stop generating");
    await waitFor(() => expect(pollsOf("root-7")).toBeGreaterThan(0));
  }

  async function waitPolls(count: number) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1700 * count));
    });
  }

  beforeEach(() => {
    installMockWebSocket();
    navigation.conversation = "42";
    localStorage.setItem("auth_token", "token");
    Object.values(chatApiMock).forEach((fn) => fn.mockReset());
    notification.info.mockReset();
    chatApiMock.getConversations.mockResolvedValue({ ok: true, data: [] });
    chatApiMock.getHistory.mockResolvedValue({
      ok: true,
      data: {
        items: [{ role: "user", message: "Summarise the Q4 report", timestamp: "2026-10-05T09:30:00" }],
        nextCursor: null,
      },
    });
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({ ok: true, data: [runningRoot] });
    chatApiMock.getTask.mockResolvedValue({ ok: true, data: rootDetail("running") });
    chatApiMock.getTaskEvents.mockResolvedValue(storedEvents([]));
    agentApiMock.getAgents.mockResolvedValue({ ok: true, data: [] });
  });

  it.each([403, 404])("stops polling and drops the spinner when the poll answers %i", async (status) => {
    await renderWaitingChat();
    chatApiMock.getTask.mockResolvedValue({ ok: false, error: "refused", status });

    await waitFor(() => expect(screen.queryByLabelText("Stop generating")).not.toBeInTheDocument(), {
      timeout: 3000,
    });
    const pollsWhenDropped = pollsOf("root-7");
    await waitPolls(1);

    expect(pollsOf("root-7")).toBe(pollsWhenDropped);
    expect(notification.info).toHaveBeenCalledTimes(1);
    expect(notification.info).toHaveBeenCalledWith("This task is no longer available.");
  });

  it("keeps polling through a network error", async () => {
    await renderWaitingChat();
    chatApiMock.getTask.mockResolvedValue({ ok: false, error: "Network error" });
    const pollsBefore = pollsOf("root-7");

    await waitPolls(2);

    expect(pollsOf("root-7")).toBeGreaterThanOrEqual(pollsBefore + 2);
    expect(screen.getByLabelText("Stop generating")).toBeInTheDocument();
    expect(notification.info).not.toHaveBeenCalled();
  });
});
