export type MonitoringState = "on" | "off";

export const MONITORING_OFF_TITLE = "Monitoring is off on this install";

export const MONITORING_CHECKING = "Checking whether monitoring runs…";

export const MONITORING_OFF_HELP =
  "Prometheus, Loki, Tempo and Alloy are not running, so there are no logs, metrics or " +
  "traces to show. To turn monitoring on, set HORUS_MONITORING=on in src/infra/.env, " +
  "then run START-HERE with --restart.";
