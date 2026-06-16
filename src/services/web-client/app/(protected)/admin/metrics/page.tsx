'use client';

import { useCallback, useEffect, useState } from "react";
import { LineChart } from "@mantine/charts";
import { Select, Switch, TextInput } from "@mantine/core";
import { IconChevronDown, IconRefresh, IconSearch } from "@tabler/icons-react";
import {
  metricsApi,
  type MetricSeries,
  type ScrapeTarget,
} from "@/lib/metrics/api";
import { useNotification } from "@/contexts/notification-context";
import { ObservabilityTabs } from "@/components/admin/observability-tabs";

const SINCE_OPTIONS = [
  { value: "15m", label: "Last 15 min" },
  { value: "1h", label: "Last 1 hour" },
  { value: "6h", label: "Last 6 hours" },
  { value: "24h", label: "Last 24 hours" },
];

/** Replicates the Grafana "MAS Overview" dashboard panels. */
const PANELS: { title: string; query: string; nameLabel?: string; unit?: string }[] = [
  { title: "Task Queue Depth", query: "mas_task_queue_depth" },
  { title: "Task Errors Rate", query: "rate(mas_task_errors_total[5m])", unit: "/s" },
  { title: "Active Agents", query: "mas_agent_count", nameLabel: "status" },
];

const PALETTE = ["blue.5", "teal.5", "grape.5", "orange.5", "lime.5", "pink.5", "cyan.5"];

const selectClassNames = {
  input: "!bg-[var(--bg)] !text-[var(--text)] rounded-xl !border-white/10",
  dropdown:
    "!bg-[var(--bgSoft)] !backdrop-blur-xl !border-white/10 !rounded-xl !shadow-2xl p-1",
  option:
    "!rounded-lg !text-[var(--textSoft)] !hover:bg-white/10 !hover:text-white !data-[checked]:bg-blue-600 !data-[checked]:text-white mb-1",
};

function timeFormatter(since: string): (t: number) => string {
  const withSeconds = since === "15m" || since === "1h";
  return (t: number) =>
    new Date(t).toLocaleTimeString([], {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      ...(withSeconds ? { second: "2-digit" } : {}),
    });
}

type WideRow = Record<string, number | string | null>;

function toWideData(
  series: MetricSeries[],
  fmt: (t: number) => string
): { data: WideRow[]; names: string[] } {
  const rows = new Map<number, WideRow>();
  const names: string[] = [];
  for (const s of series) {
    if (!names.includes(s.name)) names.push(s.name);
    for (const p of s.points) {
      let row = rows.get(p.t);
      if (!row) {
        row = { __t: p.t, time: fmt(p.t) };
        rows.set(p.t, row);
      }
      row[s.name] = p.v;
    }
  }
  const data = Array.from(rows.values()).sort(
    (a, b) => (a.__t as number) - (b.__t as number)
  );
  return { data, names };
}

interface PanelProps {
  title: string;
  query: string;
  nameLabel?: string;
  unit?: string;
  since: string;
  refreshKey: number;
  onError: (msg: string) => void;
}

function MetricPanel({
  title,
  query,
  nameLabel,
  unit,
  since,
  refreshKey,
  onError,
}: PanelProps) {
  const [series, setSeries] = useState<MetricSeries[]>([]);
  const [loading, setLoading] = useState(false);
  const [emptyReason, setEmptyReason] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    metricsApi.query({ query, since, nameLabel }).then((res) => {
      if (cancelled) return;
      if (!res.ok) {
        setEmptyReason(res.error ?? "Query failed.");
        setSeries([]);
        onError(`${title}: ${res.error ?? "query failed"}`);
      } else {
        setSeries(res.series);
        setEmptyReason(res.series.length ? null : "No data in this range.");
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [query, nameLabel, since, refreshKey, title, onError]);

  const { data, names } = toWideData(series, timeFormatter(since));
  const chartSeries = names.map((name, i) => ({
    name,
    color: PALETTE[i % PALETTE.length],
  }));

  return (
    <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text)]">{title}</h2>
          <code className="text-[10px] text-[var(--textSoft)]">{query}</code>
        </div>
        {loading && <span className="text-xs text-[var(--textSoft)]">Loading…</span>}
      </div>
      {data.length === 0 ? (
        <div className="flex h-[220px] items-center justify-center text-sm text-[var(--textSoft)]">
          {emptyReason ?? "No data."}
        </div>
      ) : (
        <LineChart
          h={220}
          data={data}
          dataKey="time"
          series={chartSeries}
          curveType="linear"
          withDots={false}
          withLegend={chartSeries.length > 1}
          tickLine="y"
          gridAxis="xy"
          valueFormatter={(v) => `${v}${unit ?? ""}`}
          xAxisProps={{ minTickGap: 40 }}
        />
      )}
    </div>
  );
}

const AdminMetricsPage = () => {
  const { error: notifyError } = useNotification();

  const [since, setSince] = useState("1h");
  const [refreshKey, setRefreshKey] = useState(0);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [targets, setTargets] = useState<ScrapeTarget[]>([]);

  const [customQuery, setCustomQuery] = useState("");
  const [runCustom, setRunCustom] = useState<string | null>(null);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    metricsApi.targets().then(setTargets);
  }, [refreshKey]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [autoRefresh, refresh]);

  // Stable error handler so panels don't refetch on every render.
  const handleError = useCallback(
    (msg: string) => notifyError(msg),
    [notifyError]
  );

  return (
    <div className="space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text)]">Metrics</h1>
          <p className="text-sm text-[var(--textSoft)]">
            MAS overview from Prometheus (replaces the Grafana dashboard).
          </p>
        </div>
        <ObservabilityTabs />
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-end gap-3 rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-3">
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
          onClick={refresh}
          className="rounded-xl bg-blue-600 px-3 py-2 text-sm text-white shadow hover:bg-blue-700 cursor-pointer flex items-center gap-2"
        >
          <IconRefresh size={16} />
          Refresh
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

        {/* Scrape target health */}
        {targets.length > 0 && (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {targets.map((t) => (
              <span
                key={`${t.job}-${t.instance}`}
                title={t.lastError || t.instance}
                className={`rounded-full px-2 py-1 text-[11px] ${
                  t.health === "up"
                    ? "bg-green-600/20 text-green-300"
                    : "bg-red-600/20 text-red-300"
                }`}
              >
                {t.job}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Fixed panels */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {PANELS.map((p) => (
          <MetricPanel
            key={p.title}
            {...p}
            since={since}
            refreshKey={refreshKey}
            onError={handleError}
          />
        ))}

        {/* Custom PromQL */}
        <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4">
          <h2 className="mb-2 text-sm font-semibold text-[var(--text)]">Custom query</h2>
          <div className="mb-3 flex gap-2">
            <TextInput
              className="flex-1"
              value={customQuery}
              onChange={(e) => setCustomQuery(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && customQuery.trim()) setRunCustom(customQuery.trim());
              }}
              placeholder="PromQL, e.g. rate(mas_task_errors_total[5m])"
              leftSection={<IconSearch size={14} className="text-[var(--textSoft)]" />}
              classNames={{ input: "!bg-[var(--bg)] !text-[var(--text)] rounded-xl !border-white/10" }}
            />
            <button
              onClick={() => customQuery.trim() && setRunCustom(customQuery.trim())}
              className="rounded-xl bg-blue-600 px-3 py-2 text-sm text-white shadow hover:bg-blue-700 cursor-pointer"
            >
              Run
            </button>
          </div>
          {runCustom ? (
            <MetricPanel
              title="Result"
              query={runCustom}
              since={since}
              refreshKey={refreshKey}
              onError={handleError}
            />
          ) : (
            <div className="flex h-[220px] items-center justify-center text-sm text-[var(--textSoft)]">
              Enter a PromQL expression to chart it.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default AdminMetricsPage;
