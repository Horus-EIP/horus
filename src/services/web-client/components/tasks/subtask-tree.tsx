'use client';

import { Subtask, TaskStatus } from '@/lib/tasks/types';
import { formatTaskDuration } from '@/lib/tasks/timing';

const STATUS_CONFIG: Record<TaskStatus, { label: string; dot: string; text: string }> = {
  completed: { label: 'Completed', dot: 'bg-emerald-400', text: 'text-emerald-400' },
  running:   { label: 'Running',   dot: 'bg-amber-400 animate-pulse', text: 'text-amber-400' },
  pending:   { label: 'Pending',   dot: 'bg-white/20', text: 'text-[var(--textSoft)]' },
  failed:    { label: 'Failed',    dot: 'bg-red-400', text: 'text-red-400' },
  cancelled: { label: 'Cancelled', dot: 'bg-gray-400', text: 'text-gray-400' },
};

function SubtaskNode({ subtask, depth = 0 }: { subtask: Subtask; depth?: number }) {
  const config = STATUS_CONFIG[subtask.status];
  const duration = formatTaskDuration(subtask.createdAt, subtask.completedAt);

  return (
    <div className={depth > 0 ? 'ml-5 border-l border-white/10 pl-4' : ''}>
      <div className="flex items-start gap-2 py-2">
        <span className={`mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ${config.dot}`} />
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="text-sm text-[var(--text)]">{subtask.title}</span>
          <div className="flex items-center gap-2">
            <span className={`text-[10px] font-medium ${config.text}`}>{config.label}</span>
            <span className="text-[10px] text-[var(--textSoft)]">→ {subtask.assignedAgent}</span>
            {duration && (
              <span className="text-[10px] text-[var(--textSoft)]">· {duration}</span>
            )}
          </div>
        </div>
      </div>
      {subtask.children?.map((child) => (
        <SubtaskNode key={child.id} subtask={child} depth={depth + 1} />
      ))}
    </div>
  );
}

export function SubtaskTree({ subtasks }: { subtasks: Subtask[] }) {
  const completed = subtasks.filter(s => s.status === 'completed').length;

  return (
    <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 shadow-sm backdrop-blur-sm">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-[var(--text)]">Subtask Breakdown</h3>
        <span className="text-xs text-[var(--textSoft)]">{completed}/{subtasks.length} completed</span>
      </div>
      <div className="flex flex-col">
        {subtasks.map((subtask) => (
          <SubtaskNode key={subtask.id} subtask={subtask} />
        ))}
      </div>
    </div>
  );
}