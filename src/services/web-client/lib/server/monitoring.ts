import { NextResponse } from "next/server";
import {
  MONITORING_OFF_HELP,
  MONITORING_OFF_TITLE,
  type MonitoringState,
} from "@/lib/observability/monitoring";

const OFF_VALUES = new Set(["off", "0", "false", "no"]);

export function monitoringState(): MonitoringState {
  const value = (process.env.HORUS_MONITORING ?? "").trim().toLowerCase();
  return OFF_VALUES.has(value) ? "off" : "on";
}

export function monitoringIsOff(): boolean {
  return monitoringState() === "off";
}

export function monitoringOff(): NextResponse {
  return NextResponse.json(
    { error: `${MONITORING_OFF_TITLE}. ${MONITORING_OFF_HELP}`, monitoring: "off" },
    { status: 503 }
  );
}
