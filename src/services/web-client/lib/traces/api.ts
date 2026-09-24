"use client";

import { authHeaders, readApiError } from "@/lib/observability/client";

/**
 * Client for the same-origin traces BFF (`/api/traces`), which talks to Tempo
 * server-side (admin-gated) and returns normalized traces / spans.
 */

export interface TraceSummary {
  traceID: string;
  rootService: string;
  rootName: string;
  startMs: number;
  durationMs: number;
}

export interface TraceSpan {
  spanId: string;
  parentId: string;
  name: string;
  service: string;
  /** Offset from the trace start, in milliseconds. */
  offsetMs: number;
  durationMs: number;
  /** Nesting depth (0 = root) for waterfall indentation. */
  depth: number;
}

export interface TraceDetail {
  spans: TraceSpan[];
  durationMs: number;
}

export interface TraceSearchParams {
  service?: string;
  since?: string;
  limit?: number;
}

export const tracesApi = {
  async search(
    params: TraceSearchParams
  ): Promise<{ ok: boolean; traces: TraceSummary[]; error?: string }> {
    const qs = new URLSearchParams({ resource: "search" });
    if (params.service) qs.set("service", params.service);
    if (params.since) qs.set("since", params.since);
    if (params.limit) qs.set("limit", String(params.limit));

    let res: Response;
    try {
      res = await fetch(`/api/traces?${qs.toString()}`, {
        headers: authHeaders(),
        credentials: "include",
      });
    } catch {
      return { ok: false, traces: [], error: "Network error. Please check your connection." };
    }
    if (!res.ok) {
      return { ok: false, traces: [], error: await readApiError(res) };
    }
    const body = (await res.json().catch(() => null)) as {
      traces?: TraceSummary[];
    } | null;
    return { ok: true, traces: body?.traces ?? [] };
  },

  async detail(
    traceID: string
  ): Promise<{ ok: boolean; detail?: TraceDetail; error?: string }> {
    const qs = new URLSearchParams({ resource: "trace", id: traceID });
    let res: Response;
    try {
      res = await fetch(`/api/traces?${qs.toString()}`, {
        headers: authHeaders(),
        credentials: "include",
      });
    } catch {
      return { ok: false, error: "Network error. Please check your connection." };
    }
    if (!res.ok) {
      return { ok: false, error: await readApiError(res) };
    }
    const body = (await res.json().catch(() => null)) as TraceDetail | null;
    return { ok: true, detail: body ?? { spans: [], durationMs: 0 } };
  },
};
