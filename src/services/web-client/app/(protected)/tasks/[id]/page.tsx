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

function buildTaskDetail(data: TaskDetails): TaskDetail {
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
    (async () => {
      setLoading(true);
      const [taskRes, agentsRes] = await Promise.all([
        chatApi.getTask(taskId),
        agentApi.getAgents(),
      ]);
      if (cancelled) return;
      if (!taskRes.ok || !taskRes.data) {
        notifyError(taskRes.error || 'Failed to load task');
        setTask(null);
      } else {
        setTask(buildTaskDetail(taskRes.data));
      }
      if (agentsRes.ok && agentsRes.data) {
        setAgents(agentsRes.data);
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
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
