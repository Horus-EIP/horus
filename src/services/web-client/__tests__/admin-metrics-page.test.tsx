import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { NotificationProvider } from "@/contexts/notification-context";
import { AdminMetricsPage } from "@/app/(protected)/admin/metrics/page";
import { metricsApi } from "@/lib/metrics/api";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/metrics",
}));

vi.mock("@mantine/charts", () => ({
  LineChart: () => <div data-testid="line-chart" />,
}));

vi.mock("@/components/admin/observability-tabs", () => ({
  ObservabilityTabs: () => <div data-testid="observability-tabs" />,
}));

describe("AdminMetricsPage loading and query triggers", () => {
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
    vi.spyOn(metricsApi, "targets").mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const renderComponent = () =>
    render(
      <MantineProvider>
        <NotificationProvider>
          <AdminMetricsPage />
        </NotificationProvider>
      </MantineProvider>
    );

  it("shows loading indicator on initial render until metrics resolve", async () => {
    const resolvers: ((val: unknown) => void)[] = [];
    vi.spyOn(metricsApi, "query").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvers.push(resolve);
        }) as never
    );

    renderComponent();

    const loadingIndicators = screen.getAllByText("Loading…");
    expect(loadingIndicators.length).toBeGreaterThan(0);

    await act(async () => {
      resolvers.forEach((res) =>
        res({
          ok: true,
          series: [{ name: "series-1", points: [{ t: 1000, v: 5 }] }],
        })
      );
    });

    await waitFor(() => {
      expect(screen.queryAllByText("Loading…")).toHaveLength(0);
    });
  });

  it("activates loading indicator on manual refresh", async () => {
    vi.spyOn(metricsApi, "query").mockResolvedValue({
      ok: true,
      series: [{ name: "series-1", points: [{ t: 1000, v: 5 }] }],
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.queryAllByText("Loading…")).toHaveLength(0);
    });

    const refreshResolvers: ((val: unknown) => void)[] = [];
    vi.spyOn(metricsApi, "query").mockImplementation(
      () =>
        new Promise((resolve) => {
          refreshResolvers.push(resolve);
        }) as never
    );

    const refreshBtn = screen.getByRole("button", { name: /Refresh/i });
    fireEvent.click(refreshBtn);

    expect(screen.getAllByText("Loading…").length).toBeGreaterThan(0);

    await act(async () => {
      refreshResolvers.forEach((res) =>
        res({
          ok: true,
          series: [{ name: "series-1", points: [{ t: 2000, v: 10 }] }],
        })
      );
    });

    await waitFor(() => {
      expect(screen.queryAllByText("Loading…")).toHaveLength(0);
    });
  });

  it("activates loading on time range change and handles rapid flips without collision", async () => {
    vi.spyOn(metricsApi, "query").mockResolvedValue({
      ok: true,
      series: [{ name: "series-1", points: [{ t: 1000, v: 5 }] }],
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.queryAllByText("Loading…")).toHaveLength(0);
    });

    const resolvers: ((val: unknown) => void)[] = [];
    vi.spyOn(metricsApi, "query").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvers.push(resolve);
        }) as never
    );

    // Open Select dropdown
    const selectTrigger = screen.getByDisplayValue("Last 1 hour");
    fireEvent.click(selectTrigger);

    // Select 24h
    const option24h = screen.getByText("Last 24 hours");
    fireEvent.click(option24h);

    expect(screen.getAllByText("Loading…").length).toBeGreaterThan(0);

    // Rapid flip back to 1h
    fireEvent.click(screen.getByDisplayValue("Last 24 hours"));
    const option1h = screen.getByText("Last 1 hour");
    fireEvent.click(option1h);

    expect(screen.getAllByText("Loading…").length).toBeGreaterThan(0);

    // Resolve latest queries
    await act(async () => {
      resolvers.forEach((res) =>
        res({
          ok: true,
          series: [{ name: "series-1", points: [{ t: 3000, v: 15 }] }],
        })
      );
    });

    await waitFor(() => {
      expect(screen.queryAllByText("Loading…")).toHaveLength(0);
    });
  });

  it("running a custom query only queries the custom panel and does not trigger fixed panels", async () => {
    const queriedQueries: string[] = [];
    vi.spyOn(metricsApi, "query").mockImplementation(({ query }) => {
      queriedQueries.push(query);
      return Promise.resolve({
        ok: true,
        series: [{ name: "series-1", points: [{ t: 1000, v: 5 }] }],
      });
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.queryAllByText("Loading…")).toHaveLength(0);
    });

    const initialQueryCount = queriedQueries.length;
    expect(initialQueryCount).toBeGreaterThan(0);

    const customInput = screen.getByPlaceholderText(/PromQL, e.g./i);
    fireEvent.change(customInput, { target: { value: "up{job='custom'}" } });

    const runBtn = screen.getByRole("button", { name: "Run" });
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(queriedQueries).toContain("up{job='custom'}");
    });

    const fixedPanelQueriesAfterRun = queriedQueries.filter(
      (q) => q !== "up{job='custom'}"
    ).length;
    expect(fixedPanelQueriesAfterRun).toBe(initialQueryCount);
  });
});
