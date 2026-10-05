'use client';

import { useState } from 'react';
import { AgentTypeBadge, getRole } from './agent-type-badge';
import { Agent } from '@/lib/agents/api';
import { Spinner } from '@/components/ui/spinner';
import { isTaskInProgress } from '@/lib/tasks/agent-activity';
import type { TaskStatus } from '@/lib/tasks/types';

interface CollaborationViewProps {
  agents?: Agent[];
  isLoading?: boolean;
  title?: string;
  taskStatusByAgentId?: Record<string, TaskStatus>;
}

function AgentNode({ agent, isWorking }: { agent: Agent; isWorking: boolean }) {
  const role = getRole(agent.skills);

  return (
    <div className="group relative w-full transition-transform duration-200 hover:-translate-y-0.5">
      <div className="absolute inset-px rounded-2xl bg-gradient-to-br from-cyan-400/25 via-fuchsia-400/15 to-indigo-400/25 blur-sm opacity-50 group-hover:opacity-80 transition-opacity" />
      <div className="relative rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 shadow-sm backdrop-blur-sm">

        {/* Header */}
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-[var(--text)] truncate pr-2">{agent.name}</span>
          {isWorking && (
            <Spinner size="sm" className="text-[var(--textSoft)] flex-shrink-0" aria-label="Working" />
          )}
        </div>

        {/* Badge */}
        <AgentTypeBadge role={role} />

        {/* Status */}
        <div className="mt-3 text-xs font-mono text-[var(--textSoft)] bg-black/20 p-2 rounded-md h-10 flex items-center">
          <span className="line-clamp-2">
            {agent.status === 'idle' ? 'Waiting for task...' : agent.description ?? 'No activity'}
          </span>
        </div>

        {/* Online indicator */}
        <div className="mt-2 flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${agent.status === 'active' ? 'bg-green-400' : 'bg-white/20'}`} />
          <span className="text-[10px] text-[var(--textSoft)] capitalize">{agent.status}</span>
        </div>
      </div>
    </div>
  );
}

export function CollaborationView({
  agents = [],
  isLoading = false,
  title = "Active Collaboration",
  taskStatusByAgentId = {},
}: CollaborationViewProps) {
  const isAgentWorking = (agent: Agent) => isTaskInProgress(taskStatusByAgentId[agent.id]);

  if (isLoading) {
    return (
      <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-6 flex items-center justify-center gap-2 text-[var(--textSoft)]">
        <Spinner size="sm" aria-label="Loading" />
        <span className="text-sm">Loading agents...</span>
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-6 text-center text-[var(--textSoft)] text-sm">
        No agents currently active.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[var(--textSoft)] uppercase tracking-wide">{title}</h2>
        <span className="text-xs text-[var(--textSoft)]">{agents.filter(isAgentWorking).length} working</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {agents.map((agent) => (
          <AgentNode key={agent.id} agent={agent} isWorking={isAgentWorking(agent)} />
        ))}
      </div>
    </div>
  );
}