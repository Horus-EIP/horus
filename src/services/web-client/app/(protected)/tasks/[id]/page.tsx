'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { SubtaskTree } from '@/components/tasks/subtask-tree';
import { MessageFlow } from '@/components/tasks/message-flow';
import { DelegationChain } from '@/components/tasks/delegation-chain';
import { CollaborationView } from '@/components/agents/collaboration-view';
import type { TaskDetail, TaskStatus, Subtask, AgentMessage, DelegationStep } from '@/lib/tasks/types';
import { chatApi, type TaskDetails } from '@/lib/chat/api';
import { agentApi, type Agent } from '@/lib/agents/api';
import { useNotification } from '@/contexts/notification-context';

const STATUS_COLORS: Record<string, string> = {
  completed: 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/30',
  running: 'bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/30',
  pending: 'bg-white/10 text-[var(--textSoft)] ring-1 ring-white/10',
  failed: 'bg-red-500/20 text-red-300 ring-1 ring-red-500/30',
  cancelled: 'bg-gray-500/20 text-gray-300 ring-1 ring-gray-500/30',
};

function normalizeStatus(s: string): TaskStatus {
  if (s === 'canceled') return 'cancelled';
  const allowed: TaskStatus[] = ['pending', 'running', 'completed', 'failed', 'cancelled'];
  return (allowed.includes(s as TaskStatus) ? s : 'pending') as TaskStatus;
}

function historyToMessages(history: unknown[] | undefined): AgentMessage[] {
  if (!Array.isArray(history)) return [];
  return history.map((raw, i) => {
    const h = raw as Record<string, unknown>;
    const role = String(h.role ?? 'assistant');
    const content = String(h.message ?? h.content ?? '');
    return {
      id: `h-${i}`,
      fromAgent: role === 'user' ? 'User' : 'Assistant',
      toAgent: '—',
      type: 'result',
      content,
      timestamp: typeof h.timestamp === 'string' ? h.timestamp : new Date().toISOString(),
    };
  });
}

function buildTaskDetail(data: TaskDetails): TaskDetail & { result?: string; query: string } {
  const subtasks: Subtask[] = (data.subtasks ?? []).map((st) => ({
    id: st.id,
    title: st.title,
    status: normalizeStatus(st.status),
    assignedAgent: st.assignedAgent,
  }));
  const agents = new Set<string>([data.agent_id]);
  subtasks.forEach((s) => agents.add(s.assignedAgent));

  const messages = historyToMessages(data.history as unknown[] | undefined);
  const delegationChain: DelegationStep[] =
    subtasks.length > 0
      ? subtasks.map((s) => ({
          agentName: s.assignedAgent,
          action: s.title,
          timestamp: data.created_at,
        }))
      : [
          {
            agentName: data.agent_id,
            action: data.query.slice(0, 120) + (data.query.length > 120 ? '…' : ''),
            timestamp: data.created_at,
          },
        ];

  return {
    id: data.task_id,
    title: data.query.length > 120 ? `${data.query.slice(0, 120)}…` : data.query,
    status: normalizeStatus(data.status),
    createdAt: data.created_at,
    collaboratingAgents: Array.from(agents),
    subtasks,
    messages,
    delegationChain,
    // Keep these so the page can render the final answer + original query.
    result: data.result,
    query: data.query,
  };
}

export default function TaskDetailPage() {
  const params = useParams();
  const taskId = typeof params.id === 'string' ? params.id : '';
  const { error: notifyError } = useNotification();
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!taskId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    let pollId: number | null = null;
    // One controller for the effect's lifetime: cleanup aborts every in-flight
    // request (and the shared signal is OR'd with a per-request timeout in the
    // api client) so navigating away can't leave doomed fetches hanging.
    const ac = new AbortController();

    const fetchOnce = async (isInitial: boolean) => {
      if (isInitial) setLoading(true);

      const taskRes = await chatApi.getTask(taskId, { signal: ac.signal });
      if (cancelled || ac.signal.aborted) return;
      if (!taskRes.ok || !taskRes.data) {
        if (isInitial) {
          notifyError(
            taskRes.aborted
              ? 'Timed out loading task. Retrying…'
              : taskRes.error || 'Failed to load task'
          );
          setTask(null);
        }
      } else {
        setTask(buildTaskDetail(taskRes.data));
        // Stop polling once the task reaches a terminal state.
        const status = normalizeStatus(taskRes.data.status);
        if (
          (status === 'completed' || status === 'failed' || status === 'cancelled') &&
          pollId !== null
        ) {
          window.clearInterval(pollId);
          pollId = null;
        }
      }
      // Drop the spinner as soon as the task itself is resolved — the agent
      // list below fills in independently and shouldn't gate first paint.
      if (isInitial) setLoading(false);

      const agentsRes = await agentApi.getAgents({ signal: ac.signal });
      if (cancelled || ac.signal.aborted) return;
      if (agentsRes.ok && agentsRes.data) {
        setAgents(agentsRes.data);
      }
    };

    void fetchOnce(true);
    // Poll every 3 s while the task is still active — the worker posts
    // results asynchronously, so the page would otherwise sit on "running"
    // forever without manual refresh.
    pollId = window.setInterval(() => void fetchOnce(false), 3000);

    return () => {
      cancelled = true;
      ac.abort();
      if (pollId !== null) window.clearInterval(pollId);
    };
  }, [taskId, notifyError]);

  const collaborating = useMemo(() => {
    if (!task) return [];
    const ids = new Set(task.collaboratingAgents);
    return agents.filter((a: Agent) => ids.has(a.id));
  }, [task, agents]);

  if (!taskId) {
    return (
      <div className="p-4 md:p-6 text-[var(--textSoft)] text-sm">Invalid task id.</div>
    );
  }

  if (loading) {
    return (
      <div className="p-4 md:p-6 text-[var(--textSoft)] text-sm">Loading task…</div>
    );
  }

  if (!task) {
    return (
      <div className="p-4 md:p-6 text-[var(--textSoft)] text-sm">Task not found or could not be loaded.</div>
    );
  }

  const statusClass = STATUS_COLORS[task.status] ?? STATUS_COLORS.pending;

  const taskWithExtras = task as TaskDetail & { result?: string; query?: string };
  const finalAnswer = taskWithExtras.result ?? '';
  const originalQuery = taskWithExtras.query ?? task.title;

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-[var(--text)]">{task.title}</h1>
          <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${statusClass}`}>
            {task.status}
          </span>
        </div>
        <span className="text-xs text-[var(--textSoft)]">Task ID: {task.id}</span>
      </div>

      {/* Original request */}
      <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4">
        <p className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--textSoft)]">
          Request
        </p>
        <p className="whitespace-pre-wrap text-sm text-[var(--text)]">
          {originalQuery}
        </p>
      </div>

      {/* Final answer — only when completed. */}
      {task.status === 'completed' && (
        <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-4">
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-emerald-300">
            Result
          </p>
          {finalAnswer ? (
            <pre className="whitespace-pre-wrap font-sans text-sm text-[var(--text)]">
              {finalAnswer}
            </pre>
          ) : (
            <p className="text-sm text-[var(--textSoft)]">
              Task is marked completed but no result body was returned by the
              agent. Check the message history below or the agent logs.
            </p>
          )}
        </div>
      )}

      {(task.status === 'running' || task.status === 'pending') && (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-200">
          Task is still {task.status}. The page auto-refreshes every few
          seconds — the result will appear here once the agent finishes.
        </div>
      )}

      {task.status === 'failed' && (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-200">
          Task failed. See the agent logs for details.
        </div>
      )}

      <CollaborationView title="Collaborating agents" agents={collaborating} isLoading={false} />

      {task.subtasks.length > 0 || task.messages.length > 0 ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SubtaskTree subtasks={task.subtasks} />
          <MessageFlow messages={task.messages} />
        </div>
      ) : (
        <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 text-sm text-[var(--textSoft)]">
          No subtasks or message history recorded for this task yet. When the agent finishes, refresh this page to
          see updates.
        </div>
      )}

      <DelegationChain steps={task.delegationChain} />
    </div>
  );
}
