import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { NotificationProvider } from "@/contexts/notification-context";
import TaskDetailPage from "@/app/(protected)/tasks/[id]/page";
import { chatApi, type TaskDetails } from "@/lib/chat/api";
import { agentApi } from "@/lib/agents/api";

let currentTaskId = "task-100";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: currentTaskId }),
}));

const makeRawTask = (id: string, query = "Do something"): TaskDetails => ({
  task_id: id,
  conversation_id: 1,
  agent_id: "agent-1",
  query,
  status: "running",
  created_at: "2026-10-17T01:00:00Z",
});

describe("TaskDetailPage loading on route navigation", () => {
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
  });

  beforeEach(() => {
    vi.clearAllMocks();
    currentTaskId = "task-100";
    vi.spyOn(agentApi, "getAgents").mockResolvedValue({
      ok: true,
      data: [],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const renderComponent = () =>
    render(
      <MantineProvider>
        <NotificationProvider>
          <TaskDetailPage />
        </NotificationProvider>
      </MantineProvider>
    );

  it("shows loading indicator initially and displays task once loaded", async () => {
    let resolveTask!: (val: unknown) => void;
    vi.spyOn(chatApi, "getTask").mockReturnValue(
      new Promise((resolve) => {
        resolveTask = resolve;
      }) as never
    );

    renderComponent();

    // Loading spinner is shown
    expect(screen.getByText("Loading task…")).toBeInTheDocument();

    await act(async () => {
      resolveTask({
        ok: true,
        data: makeRawTask("task-100", "Initial task"),
      });
    });

    await waitFor(() => {
      expect(screen.queryByText("Loading task…")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: "Initial task" })).toBeInTheDocument();
  });

  it("re-activates loading when navigating to a new taskId", async () => {
    vi.spyOn(chatApi, "getTask").mockResolvedValueOnce({
      ok: true,
      data: makeRawTask("task-100", "Initial task"),
    });

    const { rerender } = renderComponent();

    await waitFor(() => {
      expect(screen.queryByText("Loading task…")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: "Initial task" })).toBeInTheDocument();

    // Now navigate to a new taskId
    currentTaskId = "task-200";
    let resolveSecond!: (val: unknown) => void;
    vi.spyOn(chatApi, "getTask").mockReturnValue(
      new Promise((resolve) => {
        resolveSecond = resolve;
      }) as never
    );

    rerender(
      <MantineProvider>
        <NotificationProvider>
          <TaskDetailPage />
        </NotificationProvider>
      </MantineProvider>
    );

    // Loading spinner must be active again for the new task
    expect(screen.getByText("Loading task…")).toBeInTheDocument();

    await act(async () => {
      resolveSecond({
        ok: true,
        data: makeRawTask("task-200", "Second task"),
      });
    });

    await waitFor(() => {
      expect(screen.queryByText("Loading task…")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: "Second task" })).toBeInTheDocument();
  });
});
