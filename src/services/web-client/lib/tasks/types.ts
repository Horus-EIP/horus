export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
export type MessageType = 'instruction' | 'result' | 'question' | 'answer';

export interface Subtask {
  id: string;
  title: string;
  status: TaskStatus;
  assignedAgent: string;
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
  createdAt: string;
  subtasks: Subtask[];
  messages: AgentMessage[];
  delegationChain: DelegationStep[];
  collaboratingAgents: string[];
}