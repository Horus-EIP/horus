"use client";

import { authHeaders, readApiError } from "@/lib/observability/client";

/**
 * Client for the same-origin logs BFF (`/api/logs`), which proxies to Loki and
 * enforces the admin role server-side. Mirrors how {@link apiClient} attaches the
 * bearer token, but targets `/api/logs` directly instead of `/api/orchestrator`.
 */

export interface LogEntry {
  /** Nanosecond timestamp string from Loki (used as a stable sort key / React key). */
  tsNs: string;
  /** ISO-8601 timestamp derived from {@link tsNs}. */
  ts: string;
  /** Compose service the line came from (e.g. `mas`, `agent`). */
  service: string;
  /** Container name (shown on hover; usually equals the service). */
  container: string;
  /** The raw log line. */
  line: string;
}

export interface LogQueryParams {
  /** Compose service to filter to; omit for all services. */
  service?: string;
  /** Case-insensitive substring filter. */
  search?: string;
  /** Time window: "15m" | "1h" | "6h" | "24h". */
  since?: string;
  /** Max lines (1–1000). */
  limit?: number;
}

export const logsApi = {
  /** Service names that currently have logs in Loki (for the filter dropdown). */
  async listServices(): Promise<string[]> {
    try {
      const res = await fetch("/api/logs?resource=services", {
        headers: authHeaders(),
        credentials: "include",
      });
      if (!res.ok) return [];
      const body = (await res.json().catch(() => null)) as {
        services?: string[];
      } | null;
      return body?.services ?? [];
    } catch {
      return [];
    }
  },

  /** Fetch log lines matching the given filters (newest first). */
  async query(
    params: LogQueryParams
  ): Promise<{ ok: boolean; entries: LogEntry[]; error?: string }> {
    const qs = new URLSearchParams();
    if (params.service) qs.set("service", params.service);
    if (params.search) qs.set("search", params.search);
    if (params.since) qs.set("since", params.since);
    if (params.limit) qs.set("limit", String(params.limit));

    let res: Response;
    try {
      res = await fetch(`/api/logs?${qs.toString()}`, {
        headers: authHeaders(),
        credentials: "include",
      });
    } catch {
      return {
        ok: false,
        entries: [],
        error: "Network error. Please check your connection.",
      };
    }

    if (!res.ok) {
      return { ok: false, entries: [], error: await readApiError(res) };
    }

    const body = (await res.json().catch(() => null)) as {
      entries?: LogEntry[];
    } | null;
    return { ok: true, entries: body?.entries ?? [] };
  },
};
