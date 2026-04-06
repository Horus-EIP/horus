'use client';

import { useState } from 'react';
import { AgentTypeBadge, getRole } from './agent-type-badge';
import { Agent } from '@/lib/agents/api';
import { Loader2 } from 'lucide-react';

interface CollaborationViewProps {
  agents?: Agent[];
  isLoading?: boolean;
  title?: string;
}

// TMP: Mock data until we connect real data in Sprint 2
const MOCK_AGENTS: Agent[] = [
  { id: '1', name: 'ResearchBot', skills: ['search', 'retrieval', 'fetch'], status: 'active', last_heartbeat: new Date().toISOString(), description: 'Searches and retrieves documents from external sources.', created_at: '2025-01-01T00:00:00Z' },
  { id: '2', name: 'DataAnalyst', skills: ['nlp', 'summarization', 'data'], status: 'active', last_heartbeat: new Date(Date.now() - 3 * 60000).toISOString(), description: 'Analyses and summarises large volumes of text.', created_at: '2025-01-02T00:00:00Z' },
  { id: '3', name: 'ContentWriter', skills: ['writing', 'draft', 'content'], status: 'idle', last_heartbeat: new Date(Date.now() - 120 * 60000).toISOString(), description: 'Generates structured written content from briefs.', created_at: '2025-01-03T00:00:00Z' },
  { id: '4', name: 'GeneralBot', skills: [], status: 'idle', last_heartbeat: new Date(Date.now() - 120 * 60000).toISOString(), description: 'A general-purpose agent for handling various tasks.', created_at: '2025-01-04T00:00:00Z' },
];

function AgentNode({ agent }: { agent: Agent }) {
  const role = getRole(agent.skills);
  const isWorking = agent.status === 'active';

  return (
    <div className="group relative w-full transition-transform duration-200 hover:-translate-y-0.5">
      <div className="absolute inset-px rounded-2xl bg-gradient-to-br from-cyan-400/25 via-fuchsia-400/15 to-indigo-400/25 blur-sm opacity-50 group-hover:opacity-80 transition-opacity" />
      <div className="relative rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-4 shadow-sm backdrop-blur-sm">

        {/* Header */}
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-[var(--text)] truncate pr-2">{agent.name}</span>
          {isWorking && <Loader2 className="w-4 h-4 animate-spin text-[var(--textSoft)] flex-shrink-0" />}
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
  agents = MOCK_AGENTS,
  isLoading = false,
  title = "Active Collaboration",
}: CollaborationViewProps) {

  if (isLoading) {
    return (
      <div className="rounded-2xl border border-white/10 bg-[var(--bgSoft)]/70 p-6 flex items-center justify-center gap-2 text-[var(--textSoft)]">
        <Loader2 className="w-4 h-4 animate-spin" />
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
        <span className="text-xs text-[var(--textSoft)]">{agents.filter(a => a.status === 'active').length} active</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {agents.map((agent) => (
          <AgentNode key={agent.id} agent={agent} />
        ))}
      </div>
    </div>
  );
}