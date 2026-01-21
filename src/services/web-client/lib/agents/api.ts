import { apiClient } from "@/lib/api-client";

export interface Agent {
  id: string;
  name: string;
  skills: string[];
  status: string;
  last_heartbeat: string;
  description: string;
  created_at: string;
}

export interface RegisterAgentPayload {
  name: string;
  skills: string[];
  description: string;
}

export interface RegisterAgentResponse {
  message: string;
  agent_id: string;
  api_key: string;
}

export interface AgentResponse<T = void> {
  ok: boolean;
  data?: T;
  error?: string;
}

export const agentApi = {
  async getAgents(): Promise<AgentResponse<Agent[]>> {
    const response = await apiClient.get<Agent[]>("/agents/details/", { retry: 1 });

    if (!response.ok || !response.data) {
      return {
        ok: false,
        error: response.error || "Failed to fetch agents",
      };
    }

    return {
      ok: true,
      data: response.data,
    };
  },

  async getAgent(agentId: string): Promise<AgentResponse<Agent>> {
    const response = await apiClient.get<Agent>(`/agents/details/${agentId}`, { retry: 1 });

    if (!response.ok || !response.data) {
      return {
        ok: false,
        error: response.error || "Failed to fetch agent details",
      };
    }

    return {
      ok: true,
      data: response.data,
    };
  },

  async registerAgent(payload: RegisterAgentPayload): Promise<AgentResponse<RegisterAgentResponse>> {
    const response = await apiClient.post<RegisterAgentResponse>(
      "/agents/register",
      payload,
      { retry: 1 }
    );

    if (!response.ok || !response.data) {
      return {
        ok: false,
        error: response.error || "Failed to register agent",
      };
    }

    return {
      ok: true,
      data: response.data,
    };
  },

  async deleteAgent(agentId: string): Promise<AgentResponse<void>> {
    const response = await apiClient.delete<void>(`/agents/unregister/${agentId}`, { retry: 1 });

    if (!response.ok) {
      return {
        ok: false,
        error: response.error || "Failed to delete agent",
      };
    }

    return { ok: true };
  },
};
