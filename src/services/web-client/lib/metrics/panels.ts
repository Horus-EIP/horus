export interface MetricPanelSpec {
  title: string;
  query: string;
  nameLabel?: string;
  unit?: string;
}

export interface LatencyPanelSpec extends MetricPanelSpec {
  histogram: string;
}

export const LATENCY_QUANTILES = [
  { label: "p50", quantile: 0.5 },
  { label: "p95", quantile: 0.95 },
] as const;

const LATENCY_RATE_WINDOW = "5m";

export function latencyQuantilesQuery(histogram: string): string {
  return LATENCY_QUANTILES.map(
    ({ label, quantile }) =>
      `label_replace(histogram_quantile(${quantile}, sum by (le) (rate(${histogram}_bucket[${LATENCY_RATE_WINDOW}]))), "quantile", "${label}", "", "")`
  ).join(" or ");
}

function latencyPanel(title: string, histogram: string): LatencyPanelSpec {
  return {
    title,
    histogram,
    query: latencyQuantilesQuery(histogram),
    nameLabel: "quantile",
    unit: " s",
  };
}

export const LATENCY_PANELS: LatencyPanelSpec[] = [
  latencyPanel("MAS Task Processing Time", "mas_task_processing_seconds"),
  latencyPanel("Agent Task Processing Time", "agent_task_processing_duration_seconds"),
  latencyPanel("Agent Model Inference Time", "agent_model_inference_duration_seconds"),
  latencyPanel(
    "Agent Knowledge Store Request Time",
    "agent_knowledge_store_request_duration_seconds"
  ),
  latencyPanel("Knowledge Store Query Time", "knowledge_store_query_duration_seconds"),
];

export const ROUTING_DECISIONS_COUNTER = "mas_routing_decisions_total";
export const ROUTING_DECISION_HISTOGRAM = "mas_routing_decision_seconds";

export const ROUTING_PANELS: MetricPanelSpec[] = [
  {
    title: "Routing Decisions by Method",
    query: `sum by (method) (rate(${ROUTING_DECISIONS_COUNTER}[${LATENCY_RATE_WINDOW}]))`,
    nameLabel: "method",
    unit: "/s",
  },
  {
    title: "Routing Time p95 by Method",
    query: `histogram_quantile(0.95, sum by (le, method) (rate(${ROUTING_DECISION_HISTOGRAM}_bucket[${LATENCY_RATE_WINDOW}])))`,
    nameLabel: "method",
    unit: " s",
  },
];

export const METRIC_PANELS: MetricPanelSpec[] = [
  { title: "Task Queue Depth", query: "mas_task_queue_depth" },
  { title: "Task Errors Rate", query: "rate(mas_task_errors_total[5m])", unit: "/s" },
  { title: "Active Agents", query: "mas_agent_count", nameLabel: "status" },
  ...LATENCY_PANELS,
  ...ROUTING_PANELS,
];
