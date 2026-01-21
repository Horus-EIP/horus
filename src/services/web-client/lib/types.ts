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

export interface NewTaskPayload {
  demand: string;
  conversation_id: string;
  skills_required: string[];
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
