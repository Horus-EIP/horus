'use client';

import { SubtaskTree } from '@/components/tasks/subtask-tree';
import { MessageFlow } from '@/components/tasks/message-flow';
import { DelegationChain } from '@/components/tasks/delegation-chain';
import { CollaborationView } from '@/components/agents/collaboration-view';
import { TaskDetail } from '@/lib/tasks/types';

//TMP: MOCK
export const MOCK_TASK: TaskDetail = {
  id: 'task-1',
  title: 'Analyse and summarise Q3 financial report',
  status: 'running',
  createdAt: new Date(Date.now() - 30 * 60000).toISOString(),
  collaboratingAgents: ['ResearchBot', 'DataAnalyst', 'ContentWriter'],
  subtasks: [
    {
      id: 'st-1',
      title: 'Fetch report documents',
      status: 'completed',
      assignedAgent: 'ResearchBot',
      children: [
        { id: 'st-1-1', title: 'Search internal storage', status: 'completed', assignedAgent: 'ResearchBot' },
        { id: 'st-1-2', title: 'Fetch external sources', status: 'completed', assignedAgent: 'ResearchBot' },
      ],
    },
    {
      id: 'st-2',
      title: 'Analyse financial data',
      status: 'running',
      assignedAgent: 'DataAnalyst',
      children: [
        { id: 'st-2-1', title: 'Extract key metrics', status: 'completed', assignedAgent: 'DataAnalyst' },
        { id: 'st-2-2', title: 'Identify trends', status: 'running', assignedAgent: 'DataAnalyst' },
      ],
    },
    {
      id: 'st-3',
      title: 'Write executive summary',
      status: 'pending',
      assignedAgent: 'ContentWriter',
    },
  ],
  messages: [
    { id: 'm-1', fromAgent: 'GeneralBot', toAgent: 'ResearchBot', type: 'instruction', content: 'Fetch all Q3 financial documents.', timestamp: new Date(Date.now() - 28 * 60000).toISOString() },
    { id: 'm-2', fromAgent: 'ResearchBot', toAgent: 'GeneralBot', type: 'result', content: 'Found 4 documents. Passing to DataAnalyst.', timestamp: new Date(Date.now() - 20 * 60000).toISOString() },
    { id: 'm-3', fromAgent: 'GeneralBot', toAgent: 'DataAnalyst', type: 'instruction', content: 'Analyse the retrieved documents for key metrics.', timestamp: new Date(Date.now() - 19 * 60000).toISOString() },
    { id: 'm-4', fromAgent: 'DataAnalyst', toAgent: 'GeneralBot', type: 'question', content: 'Should I include YoY comparison?', timestamp: new Date(Date.now() - 10 * 60000).toISOString() },
    { id: 'm-5', fromAgent: 'GeneralBot', toAgent: 'DataAnalyst', type: 'answer', content: 'Yes, include YoY comparison for all metrics.', timestamp: new Date(Date.now() - 9 * 60000).toISOString() },
  ],
  delegationChain: [
    { agentName: 'GeneralBot', action: 'Task received and decomposed', timestamp: new Date(Date.now() - 30 * 60000).toISOString() },
    { agentName: 'ResearchBot', action: 'Delegated: document retrieval', timestamp: new Date(Date.now() - 28 * 60000).toISOString() },
    { agentName: 'DataAnalyst', action: 'Delegated: data analysis', timestamp: new Date(Date.now() - 19 * 60000).toISOString() },
    { agentName: 'ContentWriter', action: 'Pending: summary writing', timestamp: new Date(Date.now() - 1 * 60000).toISOString() },
  ],
};


const STATUS_COLORS = {
  completed: 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/30',
  running:   'bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/30',
  pending:   'bg-white/10 text-[var(--textSoft)] ring-1 ring-white/10',
  failed:    'bg-red-500/20 text-red-300 ring-1 ring-red-500/30',
  cancelled: 'bg-gray-500/20 text-gray-300 ring-1 ring-gray-500/30',
};

export default function TaskDetailPage() {
  const task = MOCK_TASK;

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-[var(--text)]">{task.title}</h1>
          <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${STATUS_COLORS[task.status]}`}>
            {task.status}
          </span>
        </div>
        <span className="text-xs text-[var(--textSoft)]">Task ID: {task.id}</span>
      </div>

      <CollaborationView title="Collaborating Agents" />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SubtaskTree subtasks={task.subtasks} />
        <MessageFlow messages={task.messages} />
      </div>

      <DelegationChain steps={task.delegationChain} />
    </div>
  );
}