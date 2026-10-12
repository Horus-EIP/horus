import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/server/require-admin";
import { monitoringIsOff, monitoringOff } from "@/lib/server/monitoring";

/**
 * BFF for metrics. Runs read-only PromQL against Prometheus server-side (so the
 * browser never reaches the Docker-internal `prometheus` host) and enforces the
 * admin role first. Mirrors the logs BFF; the Prometheus query API is read-only.
 */
export const dynamic = "force-dynamic";

const promBase = (process.env.PROMETHEUS_URL ?? "http://127.0.0.1:9090").replace(
  /\/$/,
  ""
);

/** Time window (seconds) → resolution step (seconds), keeping ~90–290 points. */
const RANGE_PRESETS: Record<string, { window: number; step: number }> = {
  "15m": { window: 15 * 60, step: 10 },
  "1h": { window: 60 * 60, step: 30 },
  "6h": { window: 6 * 60 * 60, step: 120 },
  "24h": { window: 24 * 60 * 60, step: 300 },
};

const MAX_QUERY_LEN = 2000;
const LABEL_NAME_RE = /^[a-zA-Z_][a-zA-Z0-9_]*$/;

interface PromSeries {
  metric?: Record<string, string>;
  values?: [number, string][];
}

/** Pick a human series name from a metric's labels. */
function seriesName(
  metric: Record<string, string>,
  nameLabel: string | null
): string {
  if (nameLabel && metric[nameLabel]) return metric[nameLabel];
  const labels = Object.entries(metric).filter(([k]) => k !== "__name__");
  if (labels.length) return labels.map(([k, v]) => `${k}="${v}"`).join(", ");
  return metric.__name__ ?? "value";
}

async function listTargets(): Promise<Response> {
  try {
    const res = await fetch(`${promBase}/api/v1/targets?state=active`, {
      redirect: "follow",
    });
    const body = (await res.json().catch(() => null)) as {
      data?: { activeTargets?: Array<Record<string, unknown>> };
    } | null;
    const targets = (body?.data?.activeTargets ?? []).map((t) => ({
      job: String((t.labels as Record<string, string> | undefined)?.job ?? ""),
      instance: String(t.scrapeUrl ?? ""),
      health: String(t.health ?? "unknown"),
      lastError: String(t.lastError ?? ""),
    }));
    return NextResponse.json({ targets });
  } catch {
    return NextResponse.json({ targets: [] });
  }
}

export async function GET(request: NextRequest): Promise<Response> {
  const guard = await requireAdmin(request);
  if (!guard.ok) return guard.response;
  if (monitoringIsOff()) return monitoringOff();

  const { searchParams } = new URL(request.url);

  if (searchParams.get("resource") === "targets") {
    return listTargets();
  }

  const query = (searchParams.get("query") ?? "").trim();
  if (!query) {
    return NextResponse.json({ error: "Missing query." }, { status: 400 });
  }
  if (query.length > MAX_QUERY_LEN) {
    return NextResponse.json({ error: "Query too long." }, { status: 400 });
  }

  const nameLabel = searchParams.get("nameLabel");
  if (nameLabel && !LABEL_NAME_RE.test(nameLabel)) {
    return NextResponse.json({ error: "Invalid nameLabel." }, { status: 400 });
  }

  const preset = RANGE_PRESETS[searchParams.get("since") ?? "1h"] ?? RANGE_PRESETS["1h"];
  const end = Math.floor(Date.now() / 1000);
  const start = end - preset.window;

  const url = new URL(`${promBase}/api/v1/query_range`);
  url.searchParams.set("query", query);
  url.searchParams.set("start", String(start));
  url.searchParams.set("end", String(end));
  url.searchParams.set("step", String(preset.step));

  let res: Response;
  try {
    res = await fetch(url.toString(), { redirect: "follow" });
  } catch {
    return NextResponse.json({ error: "Metrics store unreachable." }, { status: 502 });
  }

  const body = (await res.json().catch(() => null)) as {
    status?: string;
    error?: string;
    data?: { result?: PromSeries[] };
  } | null;

  if (!res.ok || body?.status === "error") {
    return NextResponse.json(
      { error: body?.error?.slice(0, 300) || `Metrics query failed (${res.status}).` },
      { status: res.status === 400 || body?.status === "error" ? 400 : 502 }
    );
  }

  const series = (body?.data?.result ?? []).map((s) => ({
    name: seriesName(s.metric ?? {}, nameLabel),
    points: (s.values ?? []).map(([t, v]) => {
      const num = Number(v);
      return { t: t * 1000, v: Number.isFinite(num) ? num : null };
    }),
  }));

  return NextResponse.json({ series, step: preset.step });
}
