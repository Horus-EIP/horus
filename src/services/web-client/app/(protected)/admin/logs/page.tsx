'use client';

import { useCallback, useEffect, useRef, useState } from "react";
import { Select, Switch, TextInput } from "@mantine/core";
import {
  IconChevronDown,
  IconDownload,
  IconRefresh,
  IconSearch,
} from "@tabler/icons-react";
import { logsApi, type LogEntry } from "@/lib/logs/api";
import { useNotification } from "@/contexts/notification-context";
import { ObservabilityTabs } from "@/components/admin/observability-tabs";
import { MonitoringGate } from "@/components/admin/monitoring-gate";

const SINCE_OPTIONS = [
  { value: "15m", label: "Last 15 min" },
  { value: "1h", label: "Last 1 hour" },
  { value: "6h", label: "Last 6 hours" },
  { value: "24h", label: "Last 24 hours" },
];

const LIMIT_OPTIONS = [
  { value: "100", label: "100 lines" },
  { value: "300", label: "300 lines" },
  { value: "500", label: "500 lines" },
  { value: "1000", label: "1000 lines" },
];

const selectClassNames = {
  input: "!bg-[var(--bg)] !text-[var(--text)] rounded-xl !border-white/10",
  dropdown:
    "!bg-[var(--bgSoft)] !backdrop-blur-xl !border-white/10 !rounded-xl !shadow-2xl p-1",
  option:
    "!rounded-lg !text-[var(--textSoft)] !hover:bg-white/10 !hover:text-white !data-[checked]:bg-blue-600 !data-[checked]:text-white mb-1",
};

/** Colour a line by the level keyword it contains (best-effort heuristic). */
function levelClass(line: string): string {
  const l = line.toLowerCase();
  if (/\b(error|err|fatal|critical|exception|traceback)\b/.test(l))
    return "text-red-400";
  if (/\b(warn|warning)\b/.test(l)) return "text-amber-400";
  if (/\b(debug|trace)\b/.test(l)) return "text-[var(--textSoft)]";
  return "text-[var(--text)]";
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour12: false });
}

const AdminLogsPage = () => {
  const { error: notifyError } = useNotification();

  const [services, setServices] = useState<string[]>([]);
  const [service, setService] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [since, setSince] = useState("1h");
  const [limit, setLimit] = useState("300");
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);

  // Read search lazily so auto-refresh/Enter use the latest value without
  // re-creating loadLogs (which would restart the interval) on each keystroke.
  const searchRef = useRef(search);
  searchRef.current = search;

  const loadServices = useCallback(async () => {
    setServices(await logsApi.listServices());
  }, []);

  const loadLogs = useCallback(async () => {
    setIsLoading(true);
    const res = await logsApi.query({
      service: service === "all" ? undefined : service,
      search: searchRef.current.trim() || undefined,
      since,
      limit: Number(limit),
    });
    if (!res.ok) {
      notifyError(res.error || "Failed to load logs.");
    } else {
      setEntries(res.entries);
    }
    setIsLoading(false);
  }, [service, since, limit, notifyError]);

  useEffect(() => {
    void loadServices();
  }, [loadServices]);

  useEffect(() => {
    void loadLogs();
  }, [loadLogs]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => void loadLogs(), 5000);
    return () => clearInterval(id);
  }, [autoRefresh, loadLogs]);

  const serviceOptions = [
    { value: "all", label: "All services" },
    ...services.map((s) => ({ value: s, label: s })),
  ];

  const handleDownload = () => {
    const text = entries
      .slice()
      .reverse()
      .map((e) => `${e.ts} [${e.service}] ${e.line}`)
      .join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "horus-logs.txt";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text)]">System Logs</h1>
          <p className="text-sm text-[var(--textSoft)]">
            Live container logs from the Horus stack (via Loki).
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
            data={serviceOptions}
            onChange={(v) => v && setService(v)}
            rightSection={<IconChevronDown size={14} className="text-[var(--textSoft)]" />}
            classNames={selectClassNames}
            comboboxProps={{ transitionProps: { transition: "pop", duration: 150 }, offset: 8 }}
          />
        </div>

        <div className="flex flex-1 flex-col gap-1 min-w-[200px]">
          <label className="text-xs font-medium text-[var(--textSoft)]">Search</label>
          <TextInput
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void loadLogs();
            }}
            placeholder="Filter lines (case-insensitive)…"
            leftSection={<IconSearch size={14} className="text-[var(--textSoft)]" />}
            classNames={{ input: "!bg-[var(--bg)] !text-[var(--text)] rounded-xl !border-white/10" }}
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

        <div className="flex flex-col gap-1 min-w-[120px]">
          <label className="text-xs font-medium text-[var(--textSoft)]">Lines</label>
          <Select
            value={limit}
            data={LIMIT_OPTIONS}
            onChange={(v) => v && setLimit(v)}
            rightSection={<IconChevronDown size={14} className="text-[var(--textSoft)]" />}
            classNames={selectClassNames}
            comboboxProps={{ transitionProps: { transition: "pop", duration: 150 }, offset: 8 }}
          />
        </div>

        <button
          onClick={() => void loadLogs()}
          disabled={isLoading}
          className="rounded-xl bg-blue-600 px-3 py-2 text-sm text-white shadow hover:bg-blue-700 cursor-pointer flex items-center gap-2 disabled:opacity-60"
        >
          <IconRefresh size={16} className={isLoading ? "animate-spin" : ""} />
          Refresh
        </button>

        <div className="flex items-center px-1 pb-2">
          <Switch
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.currentTarget.checked)}
            size="sm"
            label="Auto (5s)"
            classNames={{ label: "text-xs text-[var(--textSoft)]" }}
          />
        </div>

        <button
          onClick={handleDownload}
          disabled={!entries.length}
          className="rounded-xl bg-white/5 px-3 py-2 text-sm text-[var(--text)] shadow hover:bg-white/10 cursor-pointer flex items-center gap-2 disabled:opacity-40"
        >
          <IconDownload size={16} />
          Export
        </button>
      </div>

      {/* Log panel */}
      <div className="rounded-2xl border border-white/10 bg-black/40 overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-white/10 text-xs text-[var(--textSoft)]">
          <span>
            {entries.length} line{entries.length === 1 ? "" : "s"}
            {service !== "all" ? ` · ${service}` : ""}
          </span>
          {isLoading && <span>Loading…</span>}
        </div>
        <div className="max-h-[60vh] overflow-auto font-mono text-xs leading-relaxed p-3 space-y-0.5">
          {entries.length === 0 && !isLoading ? (
            <div className="text-[var(--textSoft)] py-8 text-center">
              No log lines for this filter.
            </div>
          ) : (
            entries.map((e, i) => (
              <div
                key={`${e.tsNs}-${i}`}
                className="flex gap-3 hover:bg-white/5 rounded px-1"
              >
                <span className="shrink-0 text-[var(--textSoft)] tabular-nums">
                  {fmtTime(e.ts)}
                </span>
                <span
                  className="shrink-0 w-32 truncate text-blue-300/80"
                  title={e.container}
                >
                  {e.service}
                </span>
                <span className={`whitespace-pre-wrap break-all ${levelClass(e.line)}`}>
                  {e.line}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

const GatedAdminLogsPage = () => (
  <MonitoringGate title="System Logs">
    <AdminLogsPage />
  </MonitoringGate>
);

export default GatedAdminLogsPage;
