'use client';

import { FiSearch, FiBarChart2, FiEdit3, FiCpu } from 'react-icons/fi';

export type AgentRole = 'researcher' | 'analyst' | 'writer' | 'general';

const ROLE_CONFIG: Record<AgentRole, {
  label: string;
  icon: React.ReactNode;
  colors: string;
}> = {
  researcher: {
    label: 'Researcher',
    icon: <FiSearch className="w-3 h-3" />,
    colors: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  },
  analyst: {
    label: 'Analyst',
    icon: <FiBarChart2 className="w-3 h-3" />,
    colors: 'bg-fuchsia-500/15 text-fuchsia-400 border-fuchsia-500/30',
  },
  writer: {
    label: 'Writer',
    icon: <FiEdit3 className="w-3 h-3" />,
    colors: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  },
  general: {
    label: 'General',
    icon: <FiCpu className="w-3 h-3" />,
    colors: 'bg-white/5 text-[var(--textSoft)] border-white/10',
  },
};

export function getRole(skills: string[]): AgentRole {
  const flat = skills.join(' ').toLowerCase();
  if (/search|retriev|crawl|fetch|research/.test(flat)) return 'researcher';
  if (/analys|chart|metric|report|data|nlp|summar/.test(flat)) return 'analyst';
  if (/writ|generat|draft|content|copy|document/.test(flat)) return 'writer';
  return 'general';
}

export function AgentTypeBadge({ role }: { role: AgentRole }) {
  const config = ROLE_CONFIG[role];
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${config.colors}`}>
      {config.icon}
      {config.label}
    </span>
  );
}
