import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/server/require-admin";

/**
 * BFF for distributed traces. Talks to Tempo server-side (admin-gated) and
 * normalizes its OTLP/JSON into a flat span list the UI can render as a
 * waterfall, so Grafana is no longer needed to inspect traces.
 *
 *   ?resource=search&service=<svc>&since=<key>&limit=<n>  → recent traces
 *   ?resource=trace&id=<traceID>                          → one trace's spans
 */
export const dynamic = "force-dynamic";

const tempoBase = (process.env.TEMPO_URL ?? "http://127.0.0.1:3200").replace(
  /\/$/,
  ""
);

const SERVICE_RE = /^[a-zA-Z0-9_.\-/]+$/;
const TRACE_ID_RE = /^[0-9a-fA-F]{1,32}$/;

const SINCE_PRESETS: Record<string, number> = {
  "15m": 15 * 60,
  "1h": 60 * 60,
  "6h": 6 * 60 * 60,
  "24h": 24 * 60 * 60,
};

const NS_PER_MS = 1_000_000;

// ---- OTLP/JSON shapes (only the fields we use) ----
interface OtlpKeyValue {
  key?: string;
  value?: { stringValue?: string };
}
interface OtlpSpan {
  spanId?: string;
  parentSpanId?: string;
  name?: string;
  startTimeUnixNano?: string;
  endTimeUnixNano?: string;
}
interface OtlpScopeSpans {
  spans?: OtlpSpan[];
}
interface OtlpBatch {
  resource?: { attributes?: OtlpKeyValue[] };
  scopeSpans?: OtlpScopeSpans[];
  instrumentationLibrarySpans?: OtlpScopeSpans[];
}

function serviceNameOf(batch: OtlpBatch): string {
  const attr = batch.resource?.attributes?.find((a) => a.key === "service.name");
  return attr?.value?.stringValue ?? "unknown";
}

// ---- Search: recent traces ----
async function searchTraces(searchParams: URLSearchParams): Promise<Response> {
  const service = (searchParams.get("service") ?? "").trim();
  if (service && !SERVICE_RE.test(service)) {
    return NextResponse.json({ error: "Invalid service filter." }, { status: 400 });
  }
  const since = SINCE_PRESETS[searchParams.get("since") ?? "1h"] ?? SINCE_PRESETS["1h"];
  const limitRaw = Number.parseInt(searchParams.get("limit") ?? "20", 10);
  const limit = Number.isFinite(limitRaw) ? Math.min(Math.max(limitRaw, 1), 100) : 20;

  const traceql = service ? `{ resource.service.name = "${service}" }` : "{}";
  const end = Math.floor(Date.now() / 1000);
  const start = end - since;

  const url = new URL(`${tempoBase}/api/search`);
  url.searchParams.set("q", traceql);
  url.searchParams.set("start", String(start));
  url.searchParams.set("end", String(end));
  url.searchParams.set("limit", String(limit));

  let res: Response;
  try {
    res = await fetch(url.toString(), { redirect: "follow" });
  } catch {
    return NextResponse.json({ error: "Trace store unreachable." }, { status: 502 });
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    return NextResponse.json(
      { error: text.slice(0, 300) || `Trace search failed (${res.status}).` },
      { status: res.status === 400 ? 400 : 502 }
    );
  }

  const body = (await res.json().catch(() => null)) as {
    traces?: Array<{
      traceID?: string;
      rootServiceName?: string;
      rootTraceName?: string;
      startTimeUnixNano?: string;
      durationMs?: number;
    }>;
  } | null;

  const traces = (body?.traces ?? []).map((t) => ({
    traceID: t.traceID ?? "",
    rootService: t.rootServiceName ?? "unknown",
    rootName: t.rootTraceName ?? "",
    startMs: t.startTimeUnixNano
      ? Number(BigInt(t.startTimeUnixNano) / BigInt(NS_PER_MS))
      : 0,
    durationMs: t.durationMs ?? 0,
  }));
  // Newest first.
  traces.sort((a, b) => b.startMs - a.startMs);

  return NextResponse.json({ traces });
}

// ---- Detail: one trace's spans, normalized for a waterfall ----
async function getTrace(id: string): Promise<Response> {
  if (!TRACE_ID_RE.test(id)) {
    return NextResponse.json({ error: "Invalid trace id." }, { status: 400 });
  }

  let res: Response;
  try {
    res = await fetch(`${tempoBase}/api/traces/${id}`, {
      headers: { Accept: "application/json" },
      redirect: "follow",
    });
  } catch {
    return NextResponse.json({ error: "Trace store unreachable." }, { status: 502 });
  }
  if (res.status === 404) {
    return NextResponse.json({ error: "Trace not found." }, { status: 404 });
  }
  if (!res.ok) {
    return NextResponse.json({ error: `Trace fetch failed (${res.status}).` }, { status: 502 });
  }

  const body = (await res.json().catch(() => null)) as { batches?: OtlpBatch[] } | null;
  const batches = body?.batches ?? [];

  type Raw = {
    spanId: string;
    parentId: string;
    name: string;
    service: string;
    startNs: bigint;
    endNs: bigint;
  };
  const raw: Raw[] = [];
  for (const batch of batches) {
    const service = serviceNameOf(batch);
    const scopes = batch.scopeSpans ?? batch.instrumentationLibrarySpans ?? [];
    for (const scope of scopes) {
      for (const span of scope.spans ?? []) {
        if (!span.startTimeUnixNano || !span.endTimeUnixNano) continue;
        raw.push({
          spanId: span.spanId ?? "",
          parentId: span.parentSpanId ?? "",
          name: span.name ?? "(unnamed)",
          service,
          startNs: BigInt(span.startTimeUnixNano),
          endNs: BigInt(span.endTimeUnixNano),
        });
      }
    }
  }

  if (raw.length === 0) {
    return NextResponse.json({ spans: [], durationMs: 0 });
  }

  let traceStart = raw[0].startNs;
  let traceEnd = raw[0].endNs;
  for (const s of raw) {
    if (s.startNs < traceStart) traceStart = s.startNs;
    if (s.endNs > traceEnd) traceEnd = s.endNs;
  }

  const byId = new Map(raw.map((s) => [s.spanId, s]));
  const depthOf = (s: Raw): number => {
    let depth = 0;
    let cur = s.parentId;
    const seen = new Set<string>();
    while (cur && byId.has(cur) && !seen.has(cur)) {
      seen.add(cur);
      depth += 1;
      cur = byId.get(cur)!.parentId;
    }
    return depth;
  };

  // Relative offsets/durations are small (a trace spans ms–s), so Number() is safe.
  const spans = raw
    .map((s) => ({
      spanId: s.spanId,
      parentId: s.parentId,
      name: s.name,
      service: s.service,
      offsetMs: Number(s.startNs - traceStart) / NS_PER_MS,
      durationMs: Number(s.endNs - s.startNs) / NS_PER_MS,
      depth: depthOf(s),
    }))
    .sort((a, b) => a.offsetMs - b.offsetMs);

  return NextResponse.json({
    spans,
    durationMs: Number(traceEnd - traceStart) / NS_PER_MS,
  });
}

export async function GET(request: NextRequest): Promise<Response> {
  const guard = await requireAdmin(request);
  if (!guard.ok) return guard.response;

  const { searchParams } = new URL(request.url);
  const resource = searchParams.get("resource") ?? "search";

  if (resource === "trace") {
    const id = (searchParams.get("id") ?? "").trim();
    if (!id) return NextResponse.json({ error: "Missing trace id." }, { status: 400 });
    return getTrace(id);
  }

  return searchTraces(searchParams);
}
