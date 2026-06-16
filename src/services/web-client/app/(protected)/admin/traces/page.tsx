'use client';

import { useCallback, useEffect, useState } from "react";
import { Select, Switch } from "@mantine/core";
import { IconChevronDown, IconRefresh } from "@tabler/icons-react";
import {
  tracesApi,
  type TraceSummary,
  type TraceDetail,
} from "@/lib/traces/api";
import { useNotification } from "@/contexts/notification-context";
import { ObservabilityTabs } from "@/components/admin/observability-tabs";

const SERVICE_OPTIONS = [
  { value: "all", label: "All services" },
  { value: "mas", label: "mas" },
  { value: "agent", label: "agent" },
  { value: "knowledge-store", label: "knowledge-store" },
];

const SINCE_OPTIONS = [
  { value: "15m", label: "Last 15 min" },
  { value: "1h", label: "Last 1 hour" },
  { value: "6h", label: "Last 6 hours" },
  { value: "24h", label: "Last 24 hours" },
];

const selectClassNames = {
  input: "!bg-[var(--bg)] !text-[var(--text)] rounded-xl !border-white/10",
  dropdown:
    "!bg-[var(--bgSoft)] !backdrop-blur-xl !border-white/10 !rounded-xl !shadow-2xl p-1",
  option:
    "!rounded-lg !text-[var(--textSoft)] !hover:bg-white/10 !hover:text-white !data-[checked]:bg-blue-600 !data-[checked]:text-white mb-1",
};

const SERVICE_COLORS: Record<string, string> = {
  mas: "bg-blue-500",
  agent: "bg-teal-500",
  "knowledge-store": "bg-fuchsia-500",
};
const FALLBACK_COLORS = [
  "bg-orange-500",
  "bg-lime-500",
  "bg-pink-500",
  "bg-cyan-500",
];

function colorForService(service: string): string {
  if (SERVICE_COLORS[service]) return SERVICE_COLORS[service];
  let hash = 0;
  for (let i = 0; i < service.length; i++) hash = (hash * 31 + service.charCodeAt(i)) | 0;
  return FALLBACK_COLORS[Math.abs(hash) % FALLBACK_COLORS.length];
}

function fmtDuration(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  if (ms >= 1) return `${ms.toFixed(1)} ms`;
  return `${(ms * 1000).toFixed(0)} µs`;
}

function fmtClock(ms: number): string {
  if (!ms) return "";
  return new Date(ms).toLocaleString([], { hour12: false });
}

const AdminTracesPage = () => {
  const { error: notifyError } = useNotification();

  const [service, setService] = useState("all");
  const [since, setSince] = useState("1h");
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);

  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const loadList = useCallback(async () => {
    setLoadingList(true);
    const res = await tracesApi.search({
      service: service === "all" ? undefined : service,
      since,
      limit: 50,
    });
    if (!res.ok) {
      notifyError(res.error || "Failed to search traces.");
    } else {
      setTraces(res.traces);
    }
    setLoadingList(false);
  }, [service, since, notifyError]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => void loadList(), 10000);
    return () => clearInterval(id);
  }, [autoRefresh, loadList]);

  const openTrace = useCallback(
    async (traceID: string) => {
      setSelected(traceID);
      setDetail(null);
      setLoadingDetail(true);
      const res = await tracesApi.detail(traceID);
      if (!res.ok) {
        notifyError(res.error || "Failed to load trace.");
      } else {
        setDetail(res.detail ?? null);
      }
      setLoadingDetail(false);
    },
    [notifyError]
  );

  const totalMs = detail?.durationMs || 1;

  return (
    <div className="space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text)]">Traces</h1>
          <p className="text-sm text-[var(--textSoft)]">
            Distributed traces from Tempo (replaces Grafana trace search).
          </p>
        </div>
        <ObservabilityTabs />
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-end gap-3 rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-3">
        <div className="flex flex-col gap-1 min-w-[160px]">
          <label className="text-xs font-medium text-[var(--textSoft)]">Service</label>
          <Select
            value={service}
            data={SERVICE_OPTIONS}
            onChange={(v) => v && setService(v)}
            rightSection={<IconChevronDown size={14} className="text-[var(--textSoft)]" />}
            classNames={selectClassNames}
            comboboxProps={{ transitionProps: { transition: "pop", duration: 150 }, offset: 8 }}
          />
        </div>
        <div className="flex flex-col gap-1 min-w-[140px]">
          <label className="text-xs font-medium text-[var(--textSoft)]">Time range</label>
          <Select
            value={since}
            data={SINCE_OPTIONS}
            onChange={(v) => v && setSince(v)}
            rightSection={<IconChevronDown size={14} className="text-[var(--textSoft)]" />}
            classNames={selectClassNames}
            comboboxProps={{ transitionProps: { transition: "pop", duration: 150 }, offset: 8 }}
          />
        </div>
        <button
          onClick={() => void loadList()}
          disabled={loadingList}
          className="rounded-xl bg-blue-600 px-3 py-2 text-sm text-white shadow hover:bg-blue-700 cursor-pointer flex items-center gap-2 disabled:opacity-60"
        >
          <IconRefresh size={16} className={loadingList ? "animate-spin" : ""} />
          Search
        </button>
        <div className="flex items-center px-1 pb-2">
          <Switch
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.currentTarget.checked)}
            size="sm"
            label="Auto (10s)"
            classNames={{ label: "text-xs text-[var(--textSoft)]" }}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,360px)_1fr]">
        {/* Trace list */}
        <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 overflow-hidden">
          <div className="border-b border-white/10 px-3 py-2 text-xs text-[var(--textSoft)]">
            {traces.length} trace{traces.length === 1 ? "" : "s"}
          </div>
          <div className="max-h-[65vh] overflow-auto">
            {traces.length === 0 && !loadingList ? (
              <div className="px-3 py-8 text-center text-sm text-[var(--textSoft)]">
                No traces in this range.
              </div>
            ) : (
              traces.map((t) => (
                <button
                  key={t.traceID}
                  onClick={() => void openTrace(t.traceID)}
                  className={`w-full border-b border-white/5 px-3 py-2 text-left hover:bg-white/5 cursor-pointer ${
                    selected === t.traceID ? "bg-blue-600/15" : ""
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm text-[var(--text)]">
                      {t.rootName || "(root)"}
                    </span>
                    <span className="shrink-0 text-xs text-[var(--textSoft)]">
                      {fmtDuration(t.durationMs)}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-center justify-between gap-2">
                    <span className="text-xs text-blue-300/80">{t.rootService}</span>
                    <span className="text-[10px] text-[var(--textSoft)]">{fmtClock(t.startMs)}</span>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Waterfall */}
        <div className="rounded-2xl border border-white/10 bg-black/40 overflow-hidden">
          <div className="flex items-center justify-between border-b border-white/10 px-3 py-2 text-xs text-[var(--textSoft)]">
            <span className="truncate font-mono">{selected ?? "Select a trace"}</span>
            {detail && <span>total {fmtDuration(detail.durationMs)}</span>}
          </div>
          <div className="max-h-[65vh] overflow-auto p-3">
            {!selected ? (
              <div className="py-12 text-center text-sm text-[var(--textSoft)]">
                Pick a trace on the left to see its span waterfall.
              </div>
            ) : loadingDetail ? (
              <div className="py-12 text-center text-sm text-[var(--textSoft)]">Loading trace…</div>
            ) : !detail || detail.spans.length === 0 ? (
              <div className="py-12 text-center text-sm text-[var(--textSoft)]">No spans in this trace.</div>
            ) : (
              <div className="space-y-1">
                {detail.spans.map((s, i) => {
                  const leftPct = Math.min((s.offsetMs / totalMs) * 100, 100);
                  const widthPct = Math.max((s.durationMs / totalMs) * 100, 0.5);
                  return (
                    <div
                      key={`${s.spanId}-${i}`}
                      className="grid grid-cols-[minmax(0,40%)_1fr] items-center gap-2"
                    >
                      <div
                        className="truncate text-xs"
                        style={{ paddingLeft: `${Math.min(s.depth, 8) * 12}px` }}
                        title={`${s.service} · ${s.name}`}
                      >
                        <span className="text-[var(--text)]">{s.name}</span>{" "}
                        <span className="text-[var(--textSoft)]">· {s.service}</span>
                      </div>
                      <div className="relative h-4 rounded bg-white/5">
                        <div
                          className={`absolute top-0 h-4 rounded ${colorForService(s.service)}`}
                          style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                          title={`${s.name} — ${fmtDuration(s.durationMs)}`}
                        />
                        <span className="absolute right-1 top-0 text-[10px] leading-4 text-[var(--textSoft)]">
                          {fmtDuration(s.durationMs)}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminTracesPage;
