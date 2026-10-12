'use client';

import { useEffect, useState, type ReactNode } from "react";
import { IconActivityHeartbeat } from "@tabler/icons-react";
import { ObservabilityTabs } from "@/components/admin/observability-tabs";
import { readMonitoringState } from "@/lib/observability/client";
import {
  MONITORING_CHECKING,
  MONITORING_OFF_HELP,
  MONITORING_OFF_TITLE,
  type MonitoringState,
} from "@/lib/observability/monitoring";

export function MonitoringGate({ title, children }: { title: string; children: ReactNode }) {
  const [state, setState] = useState<MonitoringState | null>(null);

  useEffect(() => {
    let current = true;
    void readMonitoringState().then((read) => {
      if (current) setState(read);
    });
    return () => {
      current = false;
    };
  }, []);

  if (state === "on") return <>{children}</>;
  return (
    <div className="space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-xl font-semibold text-[var(--text)]">{title}</h1>
        <ObservabilityTabs />
      </div>
      {state === null ? (
        <p className="text-sm text-[var(--textSoft)]">{MONITORING_CHECKING}</p>
      ) : (
      <div
        role="status"
        className="flex items-start gap-3 rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-6"
      >
        <IconActivityHeartbeat size={22} className="mt-0.5 shrink-0 text-[var(--textSoft)]" />
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-[var(--text)]">{MONITORING_OFF_TITLE}</h2>
          <p className="text-sm text-[var(--textSoft)]">{MONITORING_OFF_HELP}</p>
        </div>
      </div>
      )}
    </div>
  );
}
