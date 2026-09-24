"use client";

import { authHeaders, readApiError } from "@/lib/observability/client";

/**
 * Client for the same-origin metrics BFF (`/api/metrics`), which runs read-only
 * PromQL against Prometheus server-side and enforces the admin role.
 */

export interface MetricPoint {
  /** Epoch milliseconds. */
  t: number;
  /** Sample value, or null for a gap. */
  v: number | null;
}

export interface MetricSeries {
  name: string;
  points: MetricPoint[];
}

export interface ScrapeTarget {
  job: string;
  instance: string;
  health: string;
  lastError: string;
}

export interface MetricQuery {
  /** PromQL expression. */
  query: string;
  /** Time window: "15m" | "1h" | "6h" | "24h". */
  since?: string;
  /** Metric label to use as each series name (e.g. "status"). */
  nameLabel?: string;
}

export const metricsApi = {
  async query(
    params: MetricQuery
  ): Promise<{ ok: boolean; series: MetricSeries[]; error?: string }> {
    const qs = new URLSearchParams({ query: params.query });
    if (params.since) qs.set("since", params.since);
    if (params.nameLabel) qs.set("nameLabel", params.nameLabel);

    let res: Response;
    try {
      res = await fetch(`/api/metrics?${qs.toString()}`, {
        headers: authHeaders(),
        credentials: "include",
      });
    } catch {
      return { ok: false, series: [], error: "Network error. Please check your connection." };
    }
    if (!res.ok) {
      return { ok: false, series: [], error: await readApiError(res) };
    }
    const body = (await res.json().catch(() => null)) as {
      series?: MetricSeries[];
    } | null;
    return { ok: true, series: body?.series ?? [] };
  },

  async targets(): Promise<ScrapeTarget[]> {
    try {
      const res = await fetch("/api/metrics?resource=targets", {
        headers: authHeaders(),
        credentials: "include",
      });
      if (!res.ok) return [];
      const body = (await res.json().catch(() => null)) as {
        targets?: ScrapeTarget[];
      } | null;
      return body?.targets ?? [];
    } catch {
      return [];
    }
  },
};
