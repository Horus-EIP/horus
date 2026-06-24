'use client';

import React, { useMemo, useState } from 'react';
import {
  IconAlertCircle,
  IconBolt,
  IconBrain,
  IconChevronDown,
  IconChevronRight,
  IconDatabase,
  IconTool,
} from '@tabler/icons-react';
import type { TaskStepEvent, TaskStepType } from '@/lib/types';
import { formatTimestamp } from '@/utils/format';

export interface ThoughtProcessCardProps {
  /** Task this card belongs to. Used purely as a key/label hint. */
  taskId: string;
  /** Step events for this task, in arrival order. */
  steps: TaskStepEvent[];
  /** When true, the task is still running and the card stays auto-expanded. */
  isRunning: boolean;
}

const STEP_ICON: Record<string, React.ComponentType<{ className?: string; stroke?: number }>> = {
  'retrieval.start': IconDatabase,
  'retrieval.results': IconDatabase,
  'reasoning.start': IconBrain,
  'reasoning.done': IconBrain,
  'tool.invoke': IconTool,
  error: IconAlertCircle,
};

function iconFor(stepType: TaskStepType) {
  return STEP_ICON[stepType] ?? IconBolt;
}

function isErrorStep(stepType: TaskStepType): boolean {
  return stepType === 'error';
}

/** Read a positive integer from a step's free-form metadata, else 0. */
function metaNum(metadata: Record<string, unknown> | undefined, key: string): number {
  if (!metadata) return 0;
  const v = Number(metadata[key]);
  return Number.isFinite(v) && v > 0 ? v : 0;
}

export const ThoughtProcessCard: React.FC<ThoughtProcessCardProps> = ({
  taskId,
  steps,
  isRunning,
}) => {
  // Auto-collapse once the task stops running; the user can still toggle.
  const [override, setOverride] = useState<boolean | null>(null);
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const open = override ?? isRunning;

  // Token usage aggregated across steps. reasoning.done carries
  // generated_tokens / prompt_tokens in its metadata (set by the agent).
  const tokens = useMemo(() => {
    let gen = 0;
    let prompt = 0;
    let seen = false;
    for (const s of steps) {
      const g = metaNum(s.metadata as Record<string, unknown> | undefined, 'generated_tokens');
      const p = metaNum(s.metadata as Record<string, unknown> | undefined, 'prompt_tokens');
      if (g || p) seen = true;
      gen += g;
      prompt += p;
    }
    return seen ? { gen, prompt, total: gen + prompt } : null;
  }, [steps]);

  // Distinct specialists that participated, in first-seen order.
  const agents = useMemo(() => {
    const out: string[] = [];
    const set = new Set<string>();
    for (const s of steps) {
      const a = s.agentName;
      if (a && !set.has(a)) {
        set.add(a);
        out.push(a);
      }
    }
    return out;
  }, [steps]);

  // The agent currently working — the most recent step that has a name.
  const activeAgent = useMemo(() => {
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i].agentName) return steps[i].agentName as string;
    }
    return null;
  }, [steps]);

  const headerLabel = useMemo(() => {
    if (steps.length === 0) return isRunning ? 'Thinking…' : 'No thought process';
    const last = steps[steps.length - 1];
    if (isRunning) {
      // Live "agent working" view: who is active and on what.
      return activeAgent ? `${activeAgent} · ${last.title}` : last.title;
    }
    const hasError = steps.some((s) => isErrorStep(s.stepType));
    if (hasError) return 'Thought process (failed)';
    return `Thought process (${steps.length} step${steps.length === 1 ? '' : 's'})`;
  }, [steps, isRunning, activeAgent]);

  if (steps.length === 0 && !isRunning) {
    // Nothing to show — older agent without step emission, or task already
    // done before any step arrived. Keep silent rather than render a stub.
    return null;
  }

  return (
    <div
      className="mb-2 ml-10 max-w-[min(640px,75vw)] rounded-lg border border-blue-500/20 bg-blue-500/5 text-[var(--text)]"
      data-testid="thought-process-card"
      data-task-id={taskId}
    >
      <button
        type="button"
        onClick={() => setOverride(!open)}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-xs font-medium text-blue-700 hover:bg-blue-500/10 dark:text-blue-300"
        aria-expanded={open}
      >
        {open ? (
          <IconChevronDown className="h-4 w-4 shrink-0" stroke={1.5} />
        ) : (
          <IconChevronRight className="h-4 w-4 shrink-0" stroke={1.5} />
        )}
        {isRunning ? (
          <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-blue-500" aria-hidden />
        ) : (
          <IconBrain className="h-4 w-4 shrink-0" stroke={1.5} />
        )}
        <span className="min-w-0 truncate">{headerLabel}</span>
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          {agents.length > 0 && (
            <span
              className="rounded-full bg-blue-500/15 px-1.5 py-0.5 text-[10px] font-medium"
              title={agents.join(' → ')}
            >
              {agents.length === 1 ? agents[0] : `${agents.length} agents`}
            </span>
          )}
          {tokens && (
            <span
              className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-300"
              title={`prompt ${tokens.prompt.toLocaleString()} + output ${tokens.gen.toLocaleString()} tokens`}
            >
              {tokens.total.toLocaleString()} tok
            </span>
          )}
        </span>
      </button>

      {open && (
        <ol className="space-y-1 border-t border-blue-500/10 px-3 py-2">
          {steps.map((step, idx) => {
            const Icon = iconFor(step.stepType);
            const isErr = isErrorStep(step.stepType);
            const isOpen = openIndex === idx;
            const stepTokens = metaNum(
              step.metadata as Record<string, unknown> | undefined,
              'generated_tokens',
            );
            const hasMore =
              Boolean(step.detail) || Boolean(step.metadata && Object.keys(step.metadata).length);
            return (
              <li key={`${step.timestamp}-${idx}`} className="text-xs">
                <button
                  type="button"
                  onClick={() => setOpenIndex(isOpen ? null : idx)}
                  disabled={!hasMore}
                  className={`flex w-full items-center gap-2 rounded px-1 py-0.5 text-left ${
                    hasMore ? 'cursor-pointer hover:bg-blue-500/10' : 'cursor-default'
                  } ${isErr ? 'text-red-600 dark:text-red-400' : 'text-[var(--text)]'}`}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" stroke={1.5} />
                  {step.agentName && (
                    <span className="shrink-0 rounded bg-blue-500/15 px-1 py-px text-[9px] font-medium text-blue-700 dark:text-blue-300">
                      {step.agentName}
                    </span>
                  )}
                  <span className="min-w-0 truncate font-medium">{step.title}</span>
                  {stepTokens > 0 && (
                    <span className="shrink-0 text-[9px] text-emerald-600 dark:text-emerald-400">
                      {stepTokens.toLocaleString()} tok
                    </span>
                  )}
                  <span className="ml-auto shrink-0 text-[10px] text-[var(--textSoft)]">
                    {formatTimestamp(new Date(step.timestamp))}
                  </span>
                </button>
                {isOpen && hasMore && (
                  <div className="mt-1 ml-5 space-y-1 rounded bg-black/5 p-2 text-[11px] text-[var(--textSoft)] dark:bg-white/5">
                    {step.detail && <p className="whitespace-pre-wrap">{step.detail}</p>}
                    {step.metadata && Object.keys(step.metadata).length > 0 && (
                      <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[10px]">
                        {JSON.stringify(step.metadata, null, 2)}
                      </pre>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
};
