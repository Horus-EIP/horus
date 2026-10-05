import { readFileSync } from "fs";
import path from "path";
import { describe, it, expect } from "vitest";
import {
  LATENCY_PANELS,
  METRIC_PANELS,
  latencyQuantilesQuery,
} from "@/lib/metrics/panels";
import { TRACED_SERVICES } from "@/lib/traces/services";

const servicesDir = path.resolve(__dirname, "../..");

function read(relativePath: string): string {
  return readFileSync(path.resolve(servicesDir, relativePath), "utf-8");
}

const declaredHistograms = [
  "mas/core/metrics.py",
  "agent/app/core/metrics.py",
  "knowledge-store/app/core/metrics.py",
].flatMap((file) =>
  Array.from(read(file).matchAll(/Histogram\(\s*"([a-z_]+)"/g), (match) => match[1])
);

const scrapedHosts = Array.from(
  read("../infra/observability/prometheus.yaml").matchAll(/targets: \['([\w-]+):\d+'\]/g),
  (match) => match[1]
);

const HOST_BY_METRIC_PREFIX: Record<string, string> = {
  mas_: "mas",
  agent_: "agent",
  knowledge_store_: "knowledge_store",
};

function scrapeHostOf(histogram: string): string | undefined {
  const prefix = Object.keys(HOST_BY_METRIC_PREFIX).find((p) => histogram.startsWith(p));
  return prefix ? HOST_BY_METRIC_PREFIX[prefix] : undefined;
}

describe("metrics latency panels", () => {
  it("chart the MAS task histogram, the agent's latency histograms and the knowledge store's query histogram", () => {
    expect(LATENCY_PANELS.map((panel) => panel.histogram)).toEqual([
      "mas_task_processing_seconds",
      "agent_task_processing_duration_seconds",
      "agent_model_inference_duration_seconds",
      "agent_knowledge_store_request_duration_seconds",
      "knowledge_store_query_duration_seconds",
    ]);
  });

  it("query p50 and p95 from each histogram's buckets", () => {
    for (const panel of LATENCY_PANELS) {
      const rate = `sum by (le) (rate(${panel.histogram}_bucket[5m]))`;
      expect(panel.query).toContain(`histogram_quantile(0.5, ${rate})`);
      expect(panel.query).toContain(`histogram_quantile(0.95, ${rate})`);
      expect(panel.nameLabel).toBe("quantile");
      expect(panel.unit).toBe(" s");
    }
  });

  it("name the two series p50 and p95 so the legend tells them apart", () => {
    const parts = latencyQuantilesQuery("mas_task_processing_seconds").split(" or ");

    expect(parts).toHaveLength(2);
    expect(parts[0]).toMatch(/^label_replace\(histogram_quantile\(0\.5, .*"quantile", "p50", "", ""\)$/);
    expect(parts[1]).toMatch(/^label_replace\(histogram_quantile\(0\.95, .*"quantile", "p95", "", ""\)$/);
  });

  it("only chart histograms a service declares", () => {
    for (const panel of LATENCY_PANELS) {
      expect(declaredHistograms).toContain(panel.histogram);
    }
  });

  it("only chart histograms from services Prometheus scrapes", () => {
    for (const panel of LATENCY_PANELS) {
      expect(scrapedHosts).toContain(scrapeHostOf(panel.histogram));
    }
  });

  it("keep the overview panels ahead of the latency panels", () => {
    expect(METRIC_PANELS.map((panel) => panel.title)).toEqual([
      "Task Queue Depth",
      "Task Errors Rate",
      "Active Agents",
      ...LATENCY_PANELS.map((panel) => panel.title),
    ]);
  });
});

describe("traces service filter", () => {
  it("offers exactly the service names the compose stack reports", () => {
    const compose = read("../infra/docker-compose.yml");
    const reported = new Set(
      Array.from(compose.matchAll(/OTEL_SERVICE_NAME=([\w-]+)/g), (match) => match[1])
    );

    expect([...TRACED_SERVICES].sort()).toEqual([...reported].sort());
  });

  it("includes the name MAS reports when OTEL_SERVICE_NAME is unset", () => {
    const defaultName = read("mas/core/tracing.py").match(/DEFAULT_SERVICE_NAME = "([\w-]+)"/);

    expect(TRACED_SERVICES).toContain(defaultName?.[1]);
  });
});
