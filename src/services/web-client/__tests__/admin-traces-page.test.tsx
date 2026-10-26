import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { NotificationProvider } from "@/contexts/notification-context";
import { AdminTracesPage } from "@/app/(protected)/admin/traces/page";
import { tracesApi, type TraceSummary } from "@/lib/traces/api";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/traces",
}));

vi.mock("@/components/admin/observability-tabs", () => ({
  ObservabilityTabs: () => <div data-testid="observability-tabs" />,
}));

const makeTrace = (id: string, rootService = "mas", durationMs = 120): TraceSummary => ({
  traceID: id,
  rootName: id,
  rootService,
  startMs: 1000000,
  durationMs,
});

describe("AdminTracesPage loading and query triggers", () => {
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
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const renderComponent = () =>
    render(
      <MantineProvider>
        <NotificationProvider>
          <AdminTracesPage />
        </NotificationProvider>
      </MantineProvider>
    );

  it("shows loading indicator and disables search button on initial mount", async () => {
    let resolveQuery!: (val: unknown) => void;
    vi.spyOn(tracesApi, "search").mockReturnValue(
      new Promise((resolve) => {
        resolveQuery = resolve;
      }) as never
    );

    renderComponent();

    const searchBtn = screen.getByRole("button", { name: /Search/i });
    expect(searchBtn).toBeDisabled();

    await act(async () => {
      resolveQuery({
        ok: true,
        traces: [makeTrace("trace-1")],
      });
    });

    await waitFor(() => {
      expect(searchBtn).not.toBeDisabled();
    });
    expect(screen.getByText("trace-1")).toBeInTheDocument();
  });

  it("activates loading indicator and disables search button when filter changes", async () => {
    vi.spyOn(tracesApi, "search").mockResolvedValue({
      ok: true,
      traces: [makeTrace("initial-trace")],
    });

    renderComponent();

    const searchBtn = screen.getByRole("button", { name: /Search/i });
    await waitFor(() => {
      expect(searchBtn).not.toBeDisabled();
    });

    let resolveSecond!: (val: unknown) => void;
    vi.spyOn(tracesApi, "search").mockReturnValue(
      new Promise((resolve) => {
        resolveSecond = resolve;
      }) as never
    );

    // Open Service select dropdown
    const serviceInput = screen.getByDisplayValue("All services");
    fireEvent.click(serviceInput);

    // Select MAS option specifically
    const masOption = screen.getByRole("option", { name: "mas", hidden: true });
    fireEvent.click(masOption);

    // Search button should now be disabled while fetching new filter
    expect(searchBtn).toBeDisabled();

    await act(async () => {
      resolveSecond({
        ok: true,
        traces: [makeTrace("mas-trace", "mas")],
      });
    });

    await waitFor(() => {
      expect(searchBtn).not.toBeDisabled();
    });
    expect(screen.getByText("mas-trace")).toBeInTheDocument();
  });

  it("keeps loading indicator active when flipping filters all -> mas -> all with second query pending", async () => {
    vi.spyOn(tracesApi, "search").mockResolvedValue({
      ok: true,
      traces: [makeTrace("initial-all-trace")],
    });

    renderComponent();

    const searchBtn = screen.getByRole("button", { name: /Search/i });
    await waitFor(() => {
      expect(searchBtn).not.toBeDisabled();
    });
    expect(screen.getByText("initial-all-trace")).toBeInTheDocument();

    let resolveSecond!: (val: Awaited<ReturnType<typeof tracesApi.search>>) => void;
    let resolveThird!: (val: Awaited<ReturnType<typeof tracesApi.search>>) => void;

    let callCount = 1;
    vi.spyOn(tracesApi, "search").mockImplementation(() => {
      callCount++;
      if (callCount === 2) {
        return new Promise((resolve) => {
          resolveSecond = resolve;
        });
      }
      return new Promise((resolve) => {
        resolveThird = resolve;
      });
    });

    // 1. Switch to 'mas'
    const serviceInput = screen.getAllByRole("textbox")[0];
    fireEvent.click(serviceInput);
    const masOption = screen.getByRole("option", { name: "mas", hidden: true });
    fireEvent.click(masOption);

    // Indicator is active, button is disabled
    expect(searchBtn).toBeDisabled();

    // 2. While 'mas' is still pending, switch quickly back to 'All services'
    fireEvent.click(serviceInput);
    const allOption = screen.getByRole("option", { name: "All services", hidden: true });
    fireEvent.click(allOption);

    // Indicator must remain active and button disabled
    expect(searchBtn).toBeDisabled();

    // 3. Resolve the second query ('mas') - loading should still remain active because 'all' is pending
    await act(async () => {
      resolveSecond({
        ok: true,
        traces: [makeTrace("mas-trace", "mas")],
      });
    });
    expect(searchBtn).toBeDisabled();

    // 4. Resolve the third query ('all')
    await act(async () => {
      resolveThird({
        ok: true,
        traces: [makeTrace("final-all-trace")],
      });
    });

    await waitFor(() => {
      expect(searchBtn).not.toBeDisabled();
    });
    expect(screen.getByText("final-all-trace")).toBeInTheDocument();
  });

  it("activates loading indicator when Search button is clicked", async () => {
    vi.spyOn(tracesApi, "search").mockResolvedValue({
      ok: true,
      traces: [makeTrace("initial-trace")],
    });

    renderComponent();

    const searchBtn = screen.getByRole("button", { name: /Search/i });
    await waitFor(() => {
      expect(searchBtn).not.toBeDisabled();
    });

    let resolveManual!: (val: unknown) => void;
    vi.spyOn(tracesApi, "search").mockReturnValue(
      new Promise((resolve) => {
        resolveManual = resolve;
      }) as never
    );

    fireEvent.click(searchBtn);
    expect(searchBtn).toBeDisabled();

    await act(async () => {
      resolveManual({
        ok: true,
        traces: [makeTrace("refreshed-trace")],
      });
    });

    await waitFor(() => {
      expect(searchBtn).not.toBeDisabled();
    });
    expect(screen.getByText("refreshed-trace")).toBeInTheDocument();
  });

  it("resets auto-refresh interval when filter changes", async () => {
    vi.useFakeTimers();
    const searchSpy = vi.spyOn(tracesApi, "search").mockResolvedValue({
      ok: true,
      traces: [makeTrace("t1")],
    });

    renderComponent();
    await waitFor(() => expect(searchSpy).toHaveBeenCalledTimes(1));

    // Turn on auto-refresh
    const autoSwitch = screen.getByLabelText(/Auto \(10s\)/i);
    fireEvent.click(autoSwitch);

    // Advance 6 seconds (not yet reached 10s)
    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    expect(searchSpy).toHaveBeenCalledTimes(1);

    // Change service filter
    const serviceInput = screen.getByDisplayValue("All services");
    fireEvent.click(serviceInput);
    const masOption = screen.getByRole("option", { name: "mas", hidden: true });
    fireEvent.click(masOption);

    // Filter change triggered 2nd call
    await waitFor(() => expect(searchSpy).toHaveBeenCalledTimes(2));

    // Advance another 6 seconds; interval was reset, so 6s < 10s, no 3rd call yet
    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    expect(searchSpy).toHaveBeenCalledTimes(2);

    // Advance remaining 4 seconds (reaches 10s since filter change)
    await act(async () => {
      vi.advanceTimersByTime(4000);
    });
    expect(searchSpy).toHaveBeenCalledTimes(3);

    vi.useRealTimers();
  });
});
