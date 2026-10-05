import { vi, describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useWebSocket } from "@/hooks/use-web-socket";
import { useTaskResync, type TaskResync } from "@/hooks/use-task-resync";
import {
  MockWebSocket,
  installMockWebSocket,
  latestSocket,
  waitForOpenSockets,
} from "./support/mock-web-socket";

const { notification, chatApiMock } = vi.hoisted(() => ({
  notification: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
  chatApiMock: {
    getRunningTasksForConversation: vi.fn(),
    getTask: vi.fn(),
  },
}));

vi.mock("@/contexts/notification-context", () => ({
  useNotification: () => notification,
}));

vi.mock("@/lib/chat/api", () => ({
  chatApi: chatApiMock,
}));

describe("useWebSocket", () => {
  beforeEach(() => {
    installMockWebSocket();
  });

  it("sets status to connected when WebSocket opens", async () => {
    const { result } = renderHook(() =>
      useWebSocket({
        url: "ws://example.com",
        autoReconnect: false,
      })
    );

    expect(result.current.status).toBe("connecting");

    await waitFor(() => {
      expect(result.current.status).toBe("connected");
    }, { timeout: 1000 });
  });

  it("does not report the first open as a reconnect", async () => {
    const onReconnect = vi.fn();
    renderHook(() =>
      useWebSocket({ url: "ws://example.com", backoffBaseMs: 1, onReconnect })
    );

    await waitForOpenSockets(1);

    expect(onReconnect).not.toHaveBeenCalled();
  });

  it("reports a reconnect when the socket reopens after the server dropped it", async () => {
    const onReconnect = vi.fn();
    const { result } = renderHook(() =>
      useWebSocket({ url: "ws://example.com", backoffBaseMs: 1, onReconnect })
    );
    await waitForOpenSockets(1);

    latestSocket().dropFromServer();

    await waitFor(() => expect(onReconnect).toHaveBeenCalledTimes(1));
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(result.current.status).toBe("connected");
  });

  it("does not report a reconnect when the url changes to another conversation", async () => {
    const onReconnect = vi.fn();
    const { rerender } = renderHook(
      ({ url }) => useWebSocket({ url, backoffBaseMs: 1, onReconnect }),
      { initialProps: { url: "ws://example.com/chat/1/" } }
    );
    await waitForOpenSockets(1);

    rerender({ url: "ws://example.com/chat/2/" });

    await waitForOpenSockets(2);
    expect(onReconnect).not.toHaveBeenCalled();
  });
});

describe("task re-fetch on reconnect", () => {
  const runningTask = {
    id: "root-7",
    status: "running",
    agent_id: "manager",
    conversation_id: 42,
    query: "compare the Q4 reports",
    created_at: "2026-10-05T09:30:12",
  };
  const finishedTask = {
    task_id: "root-7",
    status: "completed",
    agent_id: "manager",
    conversation_id: 42,
    query: "compare the Q4 reports",
    created_at: "2026-10-05T09:30:12",
    result: "Revenue grew 12%.",
  };

  beforeEach(() => {
    installMockWebSocket();
    chatApiMock.getRunningTasksForConversation.mockReset();
    chatApiMock.getTask.mockReset();
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({
      ok: true,
      data: [runningTask],
    });
    chatApiMock.getTask.mockResolvedValue({ ok: true, data: finishedTask });
  });

  function renderChatSocket(
    openTaskId: string | null,
    onResync: (resync: TaskResync) => void
  ) {
    return renderHook(() => {
      const resyncTasks = useTaskResync({ conversationId: "42", openTaskId, onResync });
      return useWebSocket({
        url: "ws://example.com/chat/42/",
        backoffBaseMs: 1,
        onReconnect: resyncTasks,
      });
    });
  }

  it("re-fetches the running tasks and the open task after a reconnect", async () => {
    const onResync = vi.fn();
    renderChatSocket("root-7", onResync);
    await waitForOpenSockets(1);
    expect(chatApiMock.getRunningTasksForConversation).not.toHaveBeenCalled();
    expect(chatApiMock.getTask).not.toHaveBeenCalled();

    latestSocket().dropFromServer();

    await waitFor(() => expect(onResync).toHaveBeenCalledTimes(1));
    expect(chatApiMock.getRunningTasksForConversation).toHaveBeenCalledWith("42");
    expect(chatApiMock.getTask).toHaveBeenCalledWith("root-7");
    expect(onResync).toHaveBeenCalledWith({
      runningTasks: [runningTask],
      openTask: finishedTask,
    });
  });

  it("only lists the running tasks when no task is open", async () => {
    const onResync = vi.fn();
    renderChatSocket(null, onResync);
    await waitForOpenSockets(1);

    latestSocket().dropFromServer();

    await waitFor(() => expect(onResync).toHaveBeenCalledTimes(1));
    expect(chatApiMock.getTask).not.toHaveBeenCalled();
    expect(onResync).toHaveBeenCalledWith({
      runningTasks: [runningTask],
      openTask: null,
    });
  });

  it("reports no open task when its re-fetch fails", async () => {
    chatApiMock.getTask.mockResolvedValue({ ok: false, error: "Request aborted" });
    const onResync = vi.fn();
    renderChatSocket("root-7", onResync);
    await waitForOpenSockets(1);

    latestSocket().dropFromServer();

    await waitFor(() => expect(onResync).toHaveBeenCalledTimes(1));
    expect(onResync).toHaveBeenCalledWith({
      runningTasks: [runningTask],
      openTask: null,
    });
  });
});
