import { vi, describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
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
    getTaskEvents: vi.fn(),
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

  it("reports every open, the first one too, and says which ones are reconnects", async () => {
    const onOpen = vi.fn();
    renderHook(() => useWebSocket({ url: "ws://example.com", backoffBaseMs: 1, onOpen }));
    await waitForOpenSockets(1);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenLastCalledWith({ reconnect: false });

    latestSocket().dropFromServer();

    await waitFor(() => expect(onOpen).toHaveBeenCalledTimes(2));
    expect(onOpen).toHaveBeenLastCalledWith({ reconnect: true });
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

  it("gives up after maxRetries failed attempts when no task is running", async () => {
    notification.error.mockClear();
    MockWebSocket.refuseConnections = true;
    const { result } = renderHook(() =>
      useWebSocket({ url: "ws://example.com", backoffBaseMs: 1, maxRetries: 2 })
    );

    await waitFor(() =>
      expect(notification.error).toHaveBeenCalledWith("Connection lost. Please refresh the page.")
    );
    expect(MockWebSocket.instances).toHaveLength(3);
    expect(result.current.status).toBe("disconnected");
  });

  it("keeps reconnecting with a capped backoff while a task runs", async () => {
    notification.error.mockClear();
    MockWebSocket.refuseConnections = true;
    const onReconnect = vi.fn();
    const { result } = renderHook(() =>
      useWebSocket({
        url: "ws://example.com",
        backoffBaseMs: 1,
        maxBackoffMs: 4,
        maxRetries: 2,
        keepReconnecting: true,
        onReconnect,
      })
    );
    await waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(8));

    expect(result.current.status).toBe("reconnecting");
    expect(notification.error).not.toHaveBeenCalled();

    MockWebSocket.refuseConnections = false;
    await waitFor(() => expect(result.current.status).toBe("connected"));
  });

  it("resumes reconnecting when a task starts after it gave up", async () => {
    MockWebSocket.refuseConnections = true;
    const { result, rerender } = renderHook(
      ({ keepReconnecting }) =>
        useWebSocket({
          url: "ws://example.com",
          backoffBaseMs: 1,
          maxRetries: 1,
          keepReconnecting,
        }),
      { initialProps: { keepReconnecting: false } }
    );
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(2));
    await waitFor(() => expect(result.current.status).toBe("disconnected"));

    MockWebSocket.refuseConnections = false;
    rerender({ keepReconnecting: true });

    await waitFor(() => expect(result.current.status).toBe("connected"));
    expect(MockWebSocket.instances).toHaveLength(3);
  });

  it("sets error on socket error and clears it on url change", async () => {
    const { result, rerender } = renderHook(
      ({ url }) =>
        useWebSocket({
          url,
          autoReconnect: false,
        }),
      { initialProps: { url: "ws://example.com/a" as string | null } }
    );

    await waitFor(() => expect(result.current.status).toBe("connected"));

    act(() => {
      latestSocket()?.onerror?.();
    });

    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("Connection error. The assistant may not respond.");

    rerender({ url: "ws://example.com/b" });

    expect(result.current.error).toBeNull();
    await waitFor(() => expect(result.current.status).toBe("connected"));
  });

  it("transitions to disconnected when url becomes null", async () => {
    const { result, rerender } = renderHook(
      ({ url }) =>
        useWebSocket({
          url,
          autoReconnect: false,
        }),
      { initialProps: { url: "ws://example.com/a" as string | null } }
    );

    await waitFor(() => expect(result.current.status).toBe("connected"));

    act(() => {
      latestSocket()?.onerror?.();
    });

    expect(result.current.status).toBe("error");
    expect(result.current.error).not.toBeNull();

    rerender({ url: null });

    expect(result.current.status).toBe("disconnected");
  });

  it("disconnect() transitions status to disconnected", async () => {
    const { result } = renderHook(() =>
      useWebSocket({
        url: "ws://example.com",
        autoReconnect: false,
      })
    );

    await waitFor(() => expect(result.current.status).toBe("connected"));

    act(() => {
      result.current.disconnect();
    });

    expect(result.current.status).toBe("disconnected");
  });

  it("reconnects and resets connection when options change", async () => {
    const { rerender } = renderHook(
      ({ maxRetries }) =>
        useWebSocket({
          url: "ws://example.com",
          maxRetries,
        }),
      { initialProps: { maxRetries: 3 } }
    );

    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));
    const firstSocket = MockWebSocket.instances[0];

    rerender({ maxRetries: 5 });

    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(2));
    expect(firstSocket.readyState).toBe(3);
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
    chatApiMock.getTaskEvents.mockReset();
    chatApiMock.getTaskEvents.mockResolvedValue({
      ok: true,
      data: { task_id: "root-7", status: "completed", since: 0, events: [], last_seq: 0, has_more: false },
    });
    chatApiMock.getRunningTasksForConversation.mockResolvedValue({
      ok: true,
      data: [runningTask],
    });
    chatApiMock.getTask.mockResolvedValue({ ok: true, data: finishedTask });
  });

  function renderChatSocket(
    openTaskId: string | null,
    onResync: (resync: TaskResync) => void,
    sinceFor?: (taskId: string) => number
  ) {
    return renderHook(() => {
      const resyncTasks = useTaskResync({ conversationId: "42", openTaskId, sinceFor, onResync });
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
      missedFrames: [],
    });
  });

  it("fetches the open task's events missed since the last seq it saw", async () => {
    chatApiMock.getTaskEvents.mockResolvedValue({
      ok: true,
      data: {
        task_id: "root-7",
        status: "completed",
        since: 3,
        events: [
          {
            task_id: "root-7",
            seq: 4,
            type: "result",
            stage: "generation",
            data: { type: "task_complete", content: "Revenue grew 12%." },
            ts: "2026-10-05T09:33:00Z",
          },
        ],
        last_seq: 4,
        has_more: false,
      },
    });
    const onResync = vi.fn();
    renderChatSocket("root-7", onResync, () => 3);
    await waitForOpenSockets(1);

    latestSocket().dropFromServer();

    await waitFor(() => expect(onResync).toHaveBeenCalledTimes(1));
    expect(chatApiMock.getTaskEvents).toHaveBeenCalledWith("root-7", 3);
    expect(onResync.mock.calls[0][0].missedFrames).toEqual([
      {
        type: "task_complete",
        content: "Revenue grew 12%.",
        task_id: "root-7",
        seq: 4,
        event: "result",
        stage: "generation",
        ts: "2026-10-05T09:33:00Z",
      },
    ]);
  });

  it("only lists the running tasks when no task is open", async () => {
    const onResync = vi.fn();
    renderChatSocket(null, onResync);
    await waitForOpenSockets(1);

    latestSocket().dropFromServer();

    await waitFor(() => expect(onResync).toHaveBeenCalledTimes(1));
    expect(chatApiMock.getTask).not.toHaveBeenCalled();
    expect(chatApiMock.getTaskEvents).not.toHaveBeenCalled();
    expect(onResync).toHaveBeenCalledWith({
      runningTasks: [runningTask],
      openTask: null,
      missedFrames: [],
    });
  });

  it("reports no open task when its re-fetch fails", async () => {
    chatApiMock.getTask.mockResolvedValue({ ok: false, error: "Request aborted" });
    chatApiMock.getTaskEvents.mockResolvedValue({ ok: false, error: "Request aborted" });
    const onResync = vi.fn();
    renderChatSocket("root-7", onResync);
    await waitForOpenSockets(1);

    latestSocket().dropFromServer();

    await waitFor(() => expect(onResync).toHaveBeenCalledTimes(1));
    expect(onResync).toHaveBeenCalledWith({
      runningTasks: [runningTask],
      openTask: null,
      missedFrames: [],
    });
  });
});
