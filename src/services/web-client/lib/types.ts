export type HistoryItemRole = "user" | "assistant";

export type UserRole = "admin" | "manager" | "user";

export interface UpdateRole {
  username: string;
  newRole: UserRole;
}

export interface UpdatePassword {
  oldPassword: string;
  newPassword: string;
}

export interface CreateConversationResponse {
  conversation_id: string;
}

export interface HistoryItem {
  role: HistoryItemRole;
  message: string;
  timestamp?: string;
}

export type TaskMode = "auto" | "specific_agent" | "any_with_skill";

export interface NewTaskPayload {
  demand: string;
  conversation_id: string;
  skills_required: string[];
  /** Required when mode === "specific_agent". */
  agent_id?: string;
  /** Defaults to "auto" server-side when omitted. */
  mode?: TaskMode;
}

/** POST /tasks/new_task success body (orchestrator may return an immediate `result` without an agent). */
export interface NewTaskResponse {
  message?: string;
  conversation_id?: number | string;
  task_id?: string;
  result?: string;
}

export interface User {
  id: number;
  username: string;
  role?: string;
}

export interface AuthResponse {
  ok: boolean;
  user?: User;
  token?: string;
  error?: string;
  status?: number;
}

export interface PaginatedHistory {
  items: HistoryItem[];
  nextCursor?: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}
