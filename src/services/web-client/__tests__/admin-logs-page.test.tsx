import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { NotificationProvider } from "@/contexts/notification-context";
import { AdminLogsPage } from "@/app/(protected)/admin/logs/page";
import { logsApi, type LogEntry } from "@/lib/logs/api";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/logs",
}));

const makeLog = (line: string, ts = "2026-10-17T01:00:00Z", service = "mas", tsNs = "1"): LogEntry => ({
  ts,
  tsNs,
  service,
  container: `${service}-1`,
  line,
});

describe("AdminLogsPage loading indicator and query triggers", () => {
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
    window.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(logsApi, "listServices").mockResolvedValue(["mas", "agent", "knowledge-store"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const renderComponent = () =>
    render(
      <MantineProvider>
        <NotificationProvider>
          <AdminLogsPage />
        </NotificationProvider>
      </MantineProvider>
    );

  it("shows loading on initial mount and hides it once query completes", async () => {
    let resolveQuery!: (val: unknown) => void;
    const queryPromise = new Promise((resolve) => {
      resolveQuery = resolve;
    });
    vi.spyOn(logsApi, "query").mockReturnValue(queryPromise as never);

    renderComponent();

    // Initial render: loading indicator is active and Refresh is disabled
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    const refreshBtn = screen.getByRole("button", { name: /Refresh/i });
    expect(refreshBtn).toBeDisabled();

    // Resolve initial query
    await act(async () => {
      resolveQuery({
        ok: true,
        entries: [makeLog("Started mas service")],
      });
    });

    await waitFor(() => {
      expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    });
    expect(refreshBtn).not.toBeDisabled();
    expect(screen.getByText("Started mas service")).toBeInTheDocument();
  });

  it("shows loading indicator and disables Refresh button during manual refresh", async () => {
    vi.spyOn(logsApi, "query").mockResolvedValueOnce({
      ok: true,
      entries: [makeLog("Initial log")],
    });

    renderComponent();

    // Wait for initial load to finish
    await waitFor(() => {
      expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    });
    const refreshBtn = screen.getByRole("button", { name: /Refresh/i });
    expect(refreshBtn).not.toBeDisabled();

    // Set up a pending second query
    let resolveSecondQuery!: (val: unknown) => void;
    const secondPromise = new Promise((resolve) => {
      resolveSecondQuery = resolve;
    });
    vi.spyOn(logsApi, "query").mockReturnValue(secondPromise as never);

    // Click Refresh
    fireEvent.click(refreshBtn);

    // Loading should be active again during refresh
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(refreshBtn).toBeDisabled();

    // Resolve second query
    await act(async () => {
      resolveSecondQuery({
        ok: true,
        entries: [makeLog("Refreshed log", "2026-10-17T01:05:00Z", "mas", "2")],
      });
    });

    await waitFor(() => {
      expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    });
    expect(refreshBtn).not.toBeDisabled();
    expect(screen.getByText("Refreshed log")).toBeInTheDocument();
  });

  it("triggers query with loading indicator on Enter key in search input", async () => {
    vi.spyOn(logsApi, "query").mockResolvedValueOnce({
      ok: true,
      entries: [makeLog("Initial log")],
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText("Filter lines (case-insensitive)…");

    // Typing in the input does NOT trigger a query
    const initialCallCount = vi.mocked(logsApi.query).mock.calls.length;
    fireEvent.change(searchInput, { target: { value: "error" } });
    expect(vi.mocked(logsApi.query).mock.calls.length).toBe(initialCallCount);

    // Set up pending query for Enter
    let resolveSearchQuery!: (val: unknown) => void;
    vi.spyOn(logsApi, "query").mockReturnValue(
      new Promise((resolve) => {
        resolveSearchQuery = resolve;
      }) as never
    );

    // Press Enter
    fireEvent.keyDown(searchInput, { key: "Enter", code: "Enter" });

    // Should trigger query with the search term and show loading
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(logsApi.query).toHaveBeenCalledWith(
      expect.objectContaining({ search: "error" })
    );

    // Resolve query
    await act(async () => {
      resolveSearchQuery({
        ok: true,
        entries: [makeLog("Fatal error log", "2026-10-17T01:06:00Z", "mas", "3")],
      });
    });

    await waitFor(() => {
      expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Fatal error log")).toBeInTheDocument();
  });

  it("triggers periodic queries when auto-refresh is enabled", async () => {
    vi.useFakeTimers();
    try {
      vi.spyOn(logsApi, "query").mockResolvedValue({
        ok: true,
        entries: [makeLog("Initial log")],
      });

      renderComponent();

      // Initial query was called
      expect(logsApi.query).toHaveBeenCalledTimes(1);

      // Toggle auto-refresh on
      const autoSwitch = screen.getByRole("switch", { name: /Auto/i });
      fireEvent.click(autoSwitch);

      // Fast forward 5 seconds
      await act(async () => {
        vi.advanceTimersByTime(5000);
      });

      // Second query should have been triggered
      expect(logsApi.query).toHaveBeenCalledTimes(2);

      // Fast forward another 5 seconds
      await act(async () => {
        vi.advanceTimersByTime(5000);
      });

      expect(logsApi.query).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("ignores older out-of-order responses when multiple refreshes occur", async () => {
    const pendingResolvers: ((val: unknown) => void)[] = [];
    vi.spyOn(logsApi, "query").mockImplementation(() =>
      new Promise((resolve) => {
        pendingResolvers.push(resolve);
      }) as never
    );

    renderComponent();

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(pendingResolvers.length).toBe(1);

    // Trigger another refresh
    const refreshBtn = screen.getByRole("button", { name: /Refresh/i });
    // Simulate query 2
    await act(async () => {
      // First query resolves with older data
      pendingResolvers[0]({
        ok: true,
        entries: [makeLog("Older log", "2026-10-17T01:00:00Z", "mas", "1")],
      });
    });

    await waitFor(() => {
      expect(screen.getByText("Older log")).toBeInTheDocument();
      expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    });

    // Click refresh to start query 2
    fireEvent.click(refreshBtn);
    expect(pendingResolvers.length).toBe(2);
    expect(screen.getByText("Loading…")).toBeInTheDocument();

    // Trigger query 3 before query 2 finishes (via enter or state update)
    const searchInput = screen.getByPlaceholderText("Filter lines (case-insensitive)…");
    fireEvent.change(searchInput, { target: { value: "newer" } });
    fireEvent.keyDown(searchInput, { key: "Enter", code: "Enter" });
    expect(pendingResolvers.length).toBe(3);

    // Now resolve query 3 first
    await act(async () => {
      pendingResolvers[2]({
        ok: true,
        entries: [makeLog("Query 3 latest", "2026-10-17T01:02:00Z", "mas", "3")],
      });
    });

    await waitFor(() => {
      expect(screen.getByText("Query 3 latest")).toBeInTheDocument();
      expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    });

    // Now resolve the older query 2 late
    await act(async () => {
      pendingResolvers[1]({
        ok: true,
        entries: [makeLog("Query 2 stale", "2026-10-17T01:01:00Z", "mas", "2")],
      });
    });

    // Stale response from query 2 must NOT overwrite query 3 results
    expect(screen.getByText("Query 3 latest")).toBeInTheDocument();
    expect(screen.queryByText("Query 2 stale")).not.toBeInTheDocument();
  });
});
