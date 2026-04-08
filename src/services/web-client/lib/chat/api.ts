import { apiClient } from "@/lib/api-client";
import {
  CreateConversationResponse,
  NewTaskPayload,
  PaginatedHistory,
} from "@/lib/types";

export interface ChatResponse<T = void> {
  ok: boolean;
  data?: T;
  error?: string;
}

export interface Conversation {
  id: number;
  name: string;
  owner_username: string;
  created_at: string;
  modified_at: string;
}

export interface TaskQueueStats {
  pending: number;
  running: number;
  completed: number;
  failed: number;
  cancelled: number;
  timeout: number;
  total: number;
}

export interface TaskDetails {
  task_id: string;
  status: string;
  agent_id: string;
  conversation_id: number;
  query: string;
  created_at: string;
  result?: string;
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
      // Backend returns array directly - wrap it
      paginatedData = {
        items: data.map((msg: any) => ({
          role: msg.role === 'user' ? 'user' : 'assistant',
          message: msg.content || msg.message || '',
          timestamp: msg.created_at || msg.timestamp,
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

  async createTask(payload: NewTaskPayload): Promise<ChatResponse<void>> {
    const response = await apiClient.post<void>(
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

    return { ok: true };
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

  async getTaskQueueStats(): Promise<ChatResponse<TaskQueueStats>> {
    const response = await apiClient.get<TaskQueueStats>(
      "/tasks/stats/queue",
      { retry: 1 }
    );

    if (!response.ok || !response.data) {
      return {
        ok: false,
        error: response.error || "Failed to fetch task queue stats",
      };
    }

    return {
      ok: true,
      data: response.data,
    };
  },

  async getTask(taskId: string): Promise<ChatResponse<TaskDetails>> {
    const response = await apiClient.get<TaskDetails>(
      `/tasks/${taskId}`,
      { retry: 1 }
    );

    if (!response.ok || !response.data) {
      return {
        ok: false,
        error: response.error || "Failed to fetch task details",
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
