import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/server/require-admin";

/**
 * BFF for container logs. Queries Loki (the log store fed by Promtail) server-side
 * so the browser never needs to reach the Docker-internal `loki` host, and so the
 * caller's admin role can be enforced before any log line is returned.
 */
export const dynamic = "force-dynamic";

const lokiBase = (process.env.LOKI_URL ?? "http://127.0.0.1:3100").replace(
  /\/$/,
  ""
);

/** Compose service / container label values are restricted to a safe charset. */
const LABEL_VALUE_RE = /^[a-zA-Z0-9_.-]+$/;

/** Allowed time windows (seconds). Keyed by the value the UI sends. */
const SINCE_PRESETS: Record<string, number> = {
  "15m": 15 * 60,
  "1h": 60 * 60,
  "6h": 6 * 60 * 60,
  "24h": 24 * 60 * 60,
};

const NS_PER_MS = 1_000_000n;
const NS_PER_S = 1_000_000_000n;

/** Turn free text into a literal, case-insensitive LogQL line filter (no regex injection). */
function buildLineFilter(search: string): string {
  const cleaned = search.replace(/`/g, ""); // backtick can't appear in a LogQL raw string
  const literal = cleaned.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return ` |~ \`(?i)${literal}\``;
}

async function listServices(): Promise<string[]> {
  try {
    const res = await fetch(
      `${lokiBase}/loki/api/v1/label/compose_service/values`,
      { redirect: "follow" }
    );
    if (!res.ok) return [];
    const body = (await res.json().catch(() => null)) as {
      data?: string[];
    } | null;
    const values = Array.isArray(body?.data) ? body.data : [];
    return values.filter((s) => LABEL_VALUE_RE.test(s)).sort();
  } catch {
    return [];
  }
}

interface LokiStream {
  stream?: Record<string, string>;
  values?: [string, string][];
}

export async function GET(request: NextRequest): Promise<Response> {
  const guard = await requireAdmin(request);
  if (!guard.ok) return guard.response;

  const { searchParams } = new URL(request.url);

  // --- List the services that have logs (for the UI dropdown) ---
  if (searchParams.get("resource") === "services") {
    return NextResponse.json({ services: await listServices() });
  }

  // --- Query log lines ---
  const service = (searchParams.get("service") ?? "").trim();
  const search = (searchParams.get("search") ?? "").trim();
  const since = SINCE_PRESETS[searchParams.get("since") ?? "1h"] ?? SINCE_PRESETS["1h"];
  const limitRaw = Number.parseInt(searchParams.get("limit") ?? "300", 10);
  const limit = Number.isFinite(limitRaw)
    ? Math.min(Math.max(limitRaw, 1), 1000)
    : 300;

  if (service && !LABEL_VALUE_RE.test(service)) {
    return NextResponse.json({ error: "Invalid service filter." }, { status: 400 });
  }

  const selector = service
    ? `{compose_service="${service}"}`
    : `{compose_service=~".+"}`;
  const query = search ? `${selector}${buildLineFilter(search)}` : selector;

  const nowNs = BigInt(Date.now()) * NS_PER_MS;
  const startNs = nowNs - BigInt(since) * NS_PER_S;

  const url = new URL(`${lokiBase}/loki/api/v1/query_range`);
  url.searchParams.set("query", query);
  url.searchParams.set("start", startNs.toString());
  url.searchParams.set("end", nowNs.toString());
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("direction", "backward");

  let res: Response;
  try {
    res = await fetch(url.toString(), { redirect: "follow" });
  } catch {
    return NextResponse.json({ error: "Log store unreachable." }, { status: 502 });
  }

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    return NextResponse.json(
      { error: text.slice(0, 300) || `Log query failed (${res.status}).` },
      { status: res.status === 400 ? 400 : 502 }
    );
  }

  const body = (await res.json().catch(() => null)) as {
    data?: { result?: LokiStream[] };
  } | null;

  const streams = body?.data?.result ?? [];
  const entries: {
    tsNs: string;
    ts: string;
    service: string;
    container: string;
    line: string;
  }[] = [];

  for (const s of streams) {
    const svc = s.stream?.compose_service ?? s.stream?.container ?? "unknown";
    const container = s.stream?.container ?? svc;
    for (const [tsNs, line] of s.values ?? []) {
      entries.push({
        tsNs,
        ts: new Date(Number(BigInt(tsNs) / NS_PER_MS)).toISOString(),
        service: svc,
        container,
        line,
      });
    }
  }

  // Loki returns newest-first per stream; merge-sort across streams (desc by ns).
  entries.sort((a, b) => (a.tsNs < b.tsNs ? 1 : a.tsNs > b.tsNs ? -1 : 0));

  return NextResponse.json({ entries: entries.slice(0, limit) });
}
