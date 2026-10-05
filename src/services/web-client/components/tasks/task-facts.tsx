"use client";

import type { ReactNode } from "react";
import { formatTaskDuration, formatTaskMoment } from "@/lib/tasks/timing";

interface TaskFactsProps {
  skills: string[];
  createdAt: string;
  completedAt: string | null;
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--textSoft)]">
        {label}
      </dt>
      <dd className="text-sm text-[var(--text)]">{children}</dd>
    </div>
  );
}

export function TaskFacts({ skills, createdAt, completedAt }: TaskFactsProps) {
  return (
    <dl className="grid grid-cols-1 gap-4 rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 sm:grid-cols-2 lg:grid-cols-4">
      <Fact label="Skills">
        {skills.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5">
            {skills.map((skill) => (
              <li
                key={skill}
                className="rounded-full bg-white/5 px-2 py-0.5 text-xs ring-1 ring-white/10"
              >
                {skill}
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-[var(--textSoft)]">None recorded</span>
        )}
      </Fact>
      <Fact label="Created">{formatTaskMoment(createdAt) ?? "Unknown"}</Fact>
      <Fact label="Finished">{formatTaskMoment(completedAt) ?? "Not finished yet"}</Fact>
      <Fact label="Duration">{formatTaskDuration(createdAt, completedAt) ?? "—"}</Fact>
    </dl>
  );
}
