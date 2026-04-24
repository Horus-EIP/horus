'use client';

import type { TaskDetails } from '@/lib/chat/api';
import type { Agent } from '@/lib/agents/api';
import { Spinner } from '@/components/ui/spinner';

function collectWorkingAgentIds(task: TaskDetails): string[] {
  const ids: string[] = [];
  const root = task.status;
  if ((root === 'pending' || root === 'running') && task.agent_id) {
    ids.push(task.agent_id);
  }
  for (const st of task.subtasks ?? []) {
    if (
      (st.status === 'pending' || st.status === 'running') &&
      st.assignedAgent
    ) {
      ids.push(st.assignedAgent);
    }
  }
  return [...new Set(ids)];
}

function initials(name: string, id: string): string {
  const n = name.trim();
  if (n.length >= 2) return n.slice(0, 2).toUpperCase();
  if (id.length >= 2) return id.replace(/-/g, '').slice(0, 2).toUpperCase();
  return '?';
}

type Props = {
  taskDetail: TaskDetails | null;
  agentsById: Map<string, Agent>;
};

export function WorkingAgentsBar({ taskDetail, agentsById }: Props) {
  if (!taskDetail) return null;
  const ids = collectWorkingAgentIds(taskDetail);
  if (ids.length === 0) return null;

  return (
    <div className="border-b border-gray-200 bg-[var(--bgSoft)]/80 px-3 py-2 dark:border-gray-800">
      <div className="mx-auto flex max-w-[75vw] flex-wrap items-center gap-2 md:max-w-[60vw]">
        <span className="text-xs font-semibold uppercase tracking-wide text-[var(--textSoft)]">
          Working on this task
        </span>
        <div className="flex flex-wrap items-center gap-2">
          {ids.map((id) => {
            const agent = agentsById.get(id);
            const label = agent?.name ?? id.slice(0, 8) + (id.length > 8 ? '…' : '');
            return (
              <div
                key={id}
                className="flex items-center gap-2 rounded-full border border-blue-500/35 bg-blue-500/10 py-1 pl-1 pr-3 text-xs text-[var(--text)]"
                title={id}
              >
                <span className="relative flex h-7 w-7 items-center justify-center rounded-full bg-blue-600/90 text-[10px] font-bold text-white">
                  {initials(agent?.name ?? '', id)}
                  <span className="absolute -bottom-0.5 -right-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-[var(--bg)] ring-1 ring-blue-400/60">
                    <Spinner size="xs" className="h-2.5 w-2.5 text-blue-400" aria-hidden />
                  </span>
                </span>
                <span className="max-w-[140px] truncate font-medium">{label}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
