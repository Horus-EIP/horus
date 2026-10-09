import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextRequest, NextResponse } from "next/server";

import { GET as monitoringRoute } from "@/app/api/monitoring/route";
import { GET as logsRoute } from "@/app/api/logs/route";
import { GET as metricsRoute } from "@/app/api/metrics/route";
import { GET as tracesRoute } from "@/app/api/traces/route";
import LogsPage from "@/app/(protected)/admin/logs/page";
import MetricsPage from "@/app/(protected)/admin/metrics/page";
import TracesPage from "@/app/(protected)/admin/traces/page";
import { MonitoringGate } from "@/components/admin/monitoring-gate";
import { readMonitoringState } from "@/lib/observability/client";
import { requireAdmin } from "@/lib/server/require-admin";
import {
  MONITORING_CHECKING,
  MONITORING_OFF_HELP,
  MONITORING_OFF_TITLE,
} from "@/lib/observability/monitoring";

vi.mock("@/lib/server/require-admin", () => ({
  requireAdmin: vi.fn(async () => ({ ok: true })),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/logs",
}));

function reply(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function request(path: string): NextRequest {
  return new NextRequest(`http://localhost${path}`, {
    headers: { authorization: "Bearer admin-token" },
  });
}

const ROUTES = [
  ["logs", logsRoute, "/api/logs?since=1h"],
  ["metrics", metricsRoute, "/api/metrics?query=up"],
  ["traces", tracesRoute, "/api/traces?resource=search"],
] as const;

const PAGES = [
  ["System Logs", LogsPage],
  ["Metrics", MetricsPage],
  ["Traces", TracesPage],
] as const;

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("GET /api/monitoring", () => {
  it.each([["off"], ["OFF"], [" 0 "], ["false"], ["no"]])(
    "says off when HORUS_MONITORING=%s",
    async (value) => {
      vi.stubEnv("HORUS_MONITORING", value);

      const res = await monitoringRoute(request("/api/monitoring"));

      expect(await res.json()).toEqual({ monitoring: "off" });
    }
  );

  it.each([["on"], [""], ["yes"]])("says on when HORUS_MONITORING=%s", async (value) => {
    vi.stubEnv("HORUS_MONITORING", value);

    const res = await monitoringRoute(request("/api/monitoring"));

    expect(await res.json()).toEqual({ monitoring: "on" });
  });

  it("says on when the setting is absent, as on a local install", async () => {
    vi.stubEnv("HORUS_MONITORING", undefined);

    const res = await monitoringRoute(request("/api/monitoring"));

    expect(await res.json()).toEqual({ monitoring: "on" });
  });
});

describe("the logs, metrics and traces routes with monitoring off", () => {
  it.each(ROUTES)("%s says monitoring is off and how to turn it on", async (_name, route, path) => {
    vi.stubEnv("HORUS_MONITORING", "off");

    const res = await route(request(path));
    const body = await res.json();

    expect(res.status).toBe(503);
    expect(body.monitoring).toBe("off");
    expect(body.error).toContain(MONITORING_OFF_TITLE);
    expect(body.error).toContain("HORUS_MONITORING=on");
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it.each(ROUTES)("%s still checks the admin role first", async (_name, route, path) => {
    vi.stubEnv("HORUS_MONITORING", "off");
    vi.mocked(requireAdmin).mockResolvedValueOnce({
      ok: false,
      response: NextResponse.json({ error: "Admin role required." }, { status: 403 }),
    });

    const res = await route(request(path));

    expect(res.status).toBe(403);
  });

  it("queries Loki as before when monitoring is on", async () => {
    vi.stubEnv("HORUS_MONITORING", "on");
    vi.mocked(global.fetch).mockResolvedValueOnce(reply({ data: { result: [] } }));

    const res = await logsRoute(request("/api/logs?since=1h"));

    expect(res.status).toBe(200);
    expect(String(vi.mocked(global.fetch).mock.calls[0][0])).toContain("/loki/api/v1/query_range");
  });
});

describe("the admin pages", () => {
  it.each(PAGES)("%s shows that monitoring is off and queries nothing else", async (title, Page) => {
    vi.mocked(global.fetch).mockResolvedValue(reply({ monitoring: "off" }));

    render(<Page />);

    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent(MONITORING_OFF_TITLE);
    expect(notice).toHaveTextContent(MONITORING_OFF_HELP);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(title);
    expect(vi.mocked(global.fetch).mock.calls.map(([url]) => String(url))).toEqual(["/api/monitoring"]);
  });

  it("shows the page itself when monitoring is on", async () => {
    vi.mocked(global.fetch).mockResolvedValue(reply({ monitoring: "on" }));

    render(<MonitoringGate title="System Logs"><p>log controls</p></MonitoringGate>);

    expect(await screen.findByText("log controls")).toBeInTheDocument();
    expect(screen.queryByText(MONITORING_OFF_TITLE)).not.toBeInTheDocument();
  });

  it("keeps the title and the tabs while it checks, and shows nothing of the page yet", () => {
    vi.mocked(global.fetch).mockImplementation(() => new Promise(() => {}));

    render(<MonitoringGate title="Traces"><p>trace search</p></MonitoringGate>);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Traces");
    expect(screen.getByText(MONITORING_CHECKING)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Logs/ })).toBeInTheDocument();
    expect(screen.queryByText("trace search")).not.toBeInTheDocument();
  });

  it("gives up on a check that does not answer and shows the page", async () => {
    vi.mocked(global.fetch).mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));

    expect(await readMonitoringState(20)).toBe("on");
  });

  it.each([
    ["the route is missing", () => Promise.resolve(reply({ error: "Not found" }, 404))],
    ["the web client is unreachable", () => Promise.reject(new TypeError("fetch failed"))],
  ])("shows the page itself when %s", async (_case, answer) => {
    vi.mocked(global.fetch).mockImplementation(answer);

    render(<MonitoringGate title="Metrics"><p>metric panels</p></MonitoringGate>);

    expect(await screen.findByText("metric panels")).toBeInTheDocument();
  });
});
