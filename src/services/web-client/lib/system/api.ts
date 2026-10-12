import { apiClient } from "@/lib/api-client";

export interface AiMode {
  mode: "mock" | "local" | "unknown";
  model: string | null;
  server: string | null;
  simulated: boolean;
  embeddings?: string | null;
  spacy?: "on" | "off";
  monitoring?: "on" | "off";
}

export interface SystemResponse<T> {
  ok: boolean;
  data?: T;
  error?: string;
  aborted?: boolean;
}

export const systemApi = {
  async getAiMode(options?: { signal?: AbortSignal }): Promise<SystemResponse<AiMode>> {
    const response = await apiClient.get<AiMode>("/system/ai", {
      retry: 1,
      signal: options?.signal,
    });
    if (!response.ok || !response.data) {
      return {
        ok: false,
        error: response.error || "Failed to read the AI mode",
        aborted: response.aborted,
      };
    }
    return { ok: true, data: response.data };
  },
};
