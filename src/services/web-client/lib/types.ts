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

export interface AnswerSource {
  doc_id: string | null;
  chunk_id: string | null;
  title: string | null;
  page: number | null;
}

export interface HistoryItem {
  role: HistoryItemRole;
  message: string;
  timestamp?: string;
  /** Agent UUID — present when the assistant turn was from a named agent. */
  agentId?: string;
  /** Agent display name — used to restore attribution chips + Manager styling on reload. */
  agentName?: string;
  /** Skill the agent exercised for this turn. */
  skillUsed?: string;
  messageId?: number;
  sources?: AnswerSource[];
  aiProvider?: string;
}

export type TaskMode =
  | "auto"
  | "specific_agent"
  | "any_with_skill"
  | "decompose";

export interface KnowledgeStoreFileRef {
  filename: string;
  doc_id?: string;
}

export interface InlineTaskFile {
  filename: string;
  mime?: string;
  /** Base64-encoded file bytes (no data-URL prefix). */
  content_b64: string;
}

export interface NewTaskPayload {
  demand: string;
  /** Optional — omit for standalone tasks created from /tasks/new. */
  conversation_id?: string;
  skills_required: string[];
  /** Required when mode === "specific_agent". */
  agent_id?: string;
  /** Defaults to "auto" server-side when omitted. */
  mode?: TaskMode;
  /** Files already stored in the knowledge store, attached by filename. */
  attached_files?: KnowledgeStoreFileRef[];
  /** One-shot files sent inline (capped server-side at ~2 MB each). */
  inline_files?: InlineTaskFile[];
}

export interface NewTaskResponse {
  task_id: string;
  status: string;
  conversation_id?: number | string | null;
}

export type TaskEventType = "progress" | "token" | "heartbeat" | "result" | "error";

export type TaskStage = "queued" | "routing" | "retrieval" | "generation" | "aggregation";

export interface TaskEvent {
  task_id: string;
  seq: number;
  type: TaskEventType;
  stage: TaskStage | null;
  data: Record<string, unknown>;
  ts: string;
}

export interface TaskEventsPage {
  task_id: string;
  status: string;
  since: number;
  events: TaskEvent[];
  last_seq: number;
  has_more: boolean;
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

/** Coarse phase label emitted by the agent worker as a task runs. */
export type TaskStepType =
  | "retrieval.start"
  | "retrieval.results"
  | "reasoning.start"
  | "reasoning.done"
  | "tool.invoke"
  | "error"
  | (string & {});

/**
 * A single "thought process" event broadcast on the chat WebSocket as the
 * agent works through a task. Rendered live in {@link ThoughtProcessCard}
 * — the final answer still arrives as the existing ``agent``/``task_complete``
 * WS frame, unaffected by these events.
 */
export interface TaskStepEvent {
  taskId: string;
  agentId?: string;
  agentName?: string;
  stepType: TaskStepType;
  title: string;
  detail?: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}
