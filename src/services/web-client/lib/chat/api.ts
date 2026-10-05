import { apiClient } from "@/lib/api-client";
import {
  CreateConversationResponse,
  NewTaskPayload,
  NewTaskResponse,
  PaginatedHistory,
} from "@/lib/types";

export interface ChatResponse<T = void> {
  ok: boolean;
  data?: T;
  error?: string;
  /** True when the underlying request was aborted (navigation or timeout). */
  aborted?: boolean;
}

export interface Conversation {
  id: number;
  name: string;
  owner_username: string;
  created_at: string;
  modified_at: string;
}

export interface SuggestedSkill {
  skill: string;
  score: number;
  agent_id: string;
  agent_name: string;
}

export interface TaskQueueStats {
  pending: number;
  running: number;
  completed: number;
  failed: number;
  cancelled: number;
  total: number;
}

export interface AnalyticsAgentSnapshot {
  total: number;
  active: number;
  inactive: number;
}

export interface AnalyticsOverview {
  generated_at: string;
  agents: AnalyticsAgentSnapshot;
  tasks: TaskQueueStats;
}

export interface TaskSubtaskRow {
  id: string;
  title: string;
  status: string;
  assignedAgent: string;
}

export interface TaskDetails {
  task_id: string;
  status: string;
  agent_id: string;
  conversation_id: number;
  query: string;
  created_at: string;
  result?: string;
  history?: unknown[];
  future_actions?: unknown[];
  subtasks?: TaskSubtaskRow[];
}

/** Row shape returned by GET /tasks/list. Mirrors the SQLAlchemy ``Task`` model. */
export interface TaskSummary {
  id: string;
  status: string;
  agent_id: string;
  conversation_id: number | null;
  query: string;
  created_at: string;
  updated_at?: string;
  parent_task_id?: string | null;
}

export const chatApi = {
  async createConversation(name?: string): Promise<ChatResponse<string>> {
    const conversationName = name || `Chat ${new Date().toLocaleString()}`;
    const response = await apiClient.post<CreateConversationResponse>(
      "/conversations/create-conversation",
      { name: conversationName },
      { retry: 2 }
    );

    if (!response.ok || !response.data) {
      return {
        ok: false,
        error: response.error || "Failed to create conversation",
      };
    }

    return {
      ok: true,
      data: response.data.conversation_id,
    };
  },

  async getHistory(
    conversationId: string,
    cursor?: string
  ): Promise<ChatResponse<PaginatedHistory>> {
    // Backend returns array directly, we wrap it in PaginatedHistory format
    const response = await apiClient.get<unknown>(
      `/conversations/get_history/${conversationId}${cursor ? `?cursor=${cursor}` : ""}`,
      { retry: 1 }
    );

    if (!response.ok) {
      return {
        ok: false,
        error: response.error || "Failed to fetch history",
      };
    }

    // Handle both array format (backend) and PaginatedHistory format
    const data = response.data;
    let paginatedData: PaginatedHistory;

    if (Array.isArray(data)) {
      // Backend returns array directly - wrap it. Carry the attribution
      // metadata (agent_id / agent_name / skill_used) through so reloaded
      // history can restore Manager violet styling + per-agent chips.
      paginatedData = {
        items: data.map((msg: any) => ({
          role: msg.role === 'user' ? 'user' : 'assistant',
          message: msg.content || msg.message || '',
          timestamp: msg.created_at || msg.timestamp,
          agentId: typeof msg.agent_id === 'string' ? msg.agent_id : undefined,
          agentName: typeof msg.agent_name === 'string' ? msg.agent_name : undefined,
          skillUsed: typeof msg.skill_used === 'string' ? msg.skill_used : undefined,
        })),
        nextCursor: null,
      };
    } else if (data && typeof data === 'object' && 'items' in data) {
      // Already in PaginatedHistory format
      paginatedData = data as PaginatedHistory;
    } else {
      // Empty or unexpected format
      paginatedData = { items: [], nextCursor: null };
    }

    return {
      ok: true,
      data: paginatedData,
    };
  },

  async createTask(
    payload: NewTaskPayload
  ): Promise<ChatResponse<NewTaskResponse | void>> {
    const response = await apiClient.post<NewTaskResponse>(
      "/tasks/new_task",
      payload,
      { retry: 2 }
    );

    if (!response.ok) {
      return {
        ok: false,
        error: response.error || "Failed to assign task",
      };
    }

    return { ok: true, data: response.data ?? undefined };
  },

  async suggestSkills(
    demand: string,
    topK = 3
  ): Promise<ChatResponse<SuggestedSkill[]>> {
    const response = await apiClient.post<{ suggestions: SuggestedSkill[] }>(
      "/tasks/suggest-skills",
      { demand, top_k: topK },
      { retry: 0 }
    );

    if (!response.ok) {
      return {
        ok: false,
        error: response.error || "Failed to suggest skills",
      };
    }

    return { ok: true, data: response.data?.suggestions ?? [] };
  },

  async getConversations(): Promise<ChatResponse<Conversation[]>> {
    const response = await apiClient.get<unknown>(
      "/conversations/get-conversations",
      { retry: 1 }
    );

    if (!response.ok) {
      return {
        ok: false,
        error: response.error || "Failed to fetch conversations",
      };
    }

    if (!Array.isArray(response.data)) {
      return {
        ok: false,
        error: response.error || "Failed to fetch conversations",
      };
    }

    return {
      ok: true,
      data: response.data as Conversation[],
    };
  },

  async deleteConversation(conversationId: number): Promise<ChatResponse<void>> {
    const response = await apiClient.delete<void>(
      `/conversations/delete-conversation/${conversationId}`,
      { retry: 1 }
    );

    if (!response.ok) {
      return {
        ok: false,
        error: response.error || "Failed to delete conversation",
      };
    }

    return { ok: true };
  },

  async getTaskQueueStats(
    options?: { signal?: AbortSignal }
  ): Promise<ChatResponse<TaskQueueStats>> {
    const response = await apiClient.get<TaskQueueStats>(
      "/tasks/stats/queue",
      { retry: 1, signal: options?.signal }
    );

    if (!response.ok || !response.data) {
      return {
        ok: false,
        error: response.error || "Failed to fetch task queue stats",
        aborted: response.aborted,
      };
    }

    return {
      ok: true,
      data: response.data,
    };
  },

  async getAnalyticsOverview(): Promise<ChatResponse<AnalyticsOverview>> {
    const response = await apiClient.get<AnalyticsOverview>(
      "/analytics/overview",
      { retry: 1 }
    );

    if (!response.ok || !response.data) {
      return {
        ok: false,
        error: response.error || "Failed to fetch analytics overview",
      };
    }

    return {
      ok: true,
      data: response.data,
    };
  },

  async listTasks(
    options?: { signal?: AbortSignal }
  ): Promise<ChatResponse<TaskSummary[]>> {
    const response = await apiClient.get<TaskSummary[]>("/tasks/list", {
      retry: 1,
      signal: options?.signal,
    });
    if (!response.ok || !Array.isArray(response.data)) {
      return {
        ok: false,
        error: response.error || "Failed to list tasks",
        aborted: response.aborted,
      };
    }
    return { ok: true, data: response.data };
  },

  async getRunningTasksForConversation(
    conversationId: string
  ): Promise<ChatResponse<TaskSummary[]>> {
    const response = await apiClient.get<TaskSummary[]>(
      `/tasks/conversation/${conversationId}/running`,
      { retry: 1 }
    );
    if (!response.ok || !Array.isArray(response.data)) {
      return {
        ok: false,
        error: response.error || "Failed to fetch running tasks",
      };
    }
    return { ok: true, data: response.data };
  },

  async getTask(
    taskId: string,
    options?: { signal?: AbortSignal }
  ): Promise<ChatResponse<TaskDetails>> {
    const response = await apiClient.get<TaskDetails>(
      `/tasks/${taskId}`,
      { retry: 1, signal: options?.signal }
    );

    if (!response.ok || !response.data) {
      return {
        ok: false,
        error: response.error || "Failed to fetch task details",
        aborted: response.aborted,
      };
    }

    return {
      ok: true,
      data: response.data,
    };
  },

  async cancelTask(taskId: string, reason?: string): Promise<ChatResponse<void>> {
    const response = await apiClient.patch<void>(
      `/tasks/${taskId}/cancel`,
      { reason: reason || "User requested cancellation" },
      { retry: 1 }
    );

    if (!response.ok) {
      return {
        ok: false,
        error: response.error || "Failed to cancel task",
      };
    }

    return { ok: true };
  },
};
