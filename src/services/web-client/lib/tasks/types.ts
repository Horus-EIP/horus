export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
export type MessageType = 'instruction' | 'result' | 'question' | 'answer';

export interface Subtask {
  id: string;
  title: string;
  status: TaskStatus;
  assignedAgent: string;
  skillsRequired?: string[];
  createdAt?: string | null;
  completedAt?: string | null;
  children?: Subtask[];
}

export interface AgentMessage {
  id: string;
  fromAgent: string;
  toAgent: string;
  type: MessageType;
  content: string;
  timestamp: string;
}

export interface DelegationStep {
  agentName: string;
  action: string;
  timestamp: string;
}

export interface TaskDetail {
  id: string;
  title: string;
  status: TaskStatus;
  agentId: string;
  skills: string[];
  createdAt: string;
  completedAt: string | null;
  subtasks: Subtask[];
  messages: AgentMessage[];
  delegationChain: DelegationStep[];
  collaboratingAgents: string[];
}