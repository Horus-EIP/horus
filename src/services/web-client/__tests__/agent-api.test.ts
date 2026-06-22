import { vi, describe, it, expect, beforeEach } from "vitest";
import { agentApi } from "@/lib/agents/api";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("agentApi.regenerateApiKey", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns the new key when the backend rotates it", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: {
        message: "API key regenerated for agent a-1",
        agent_id: "a-1",
        api_key: "fresh-key",
      },
    });

    const result = await agentApi.regenerateApiKey("a-1");

    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/regenerate-key/a-1",
      undefined,
      { retry: 1 }
    );
    expect(result.ok).toBe(true);
    expect(result.data?.api_key).toBe("fresh-key");
  });

  it("returns an error when the backend rejects the request", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: false,
      status: 404,
      error: "Agent a-1 not found",
    });

    const result = await agentApi.regenerateApiKey("a-1");

    expect(result.ok).toBe(false);
    expect(result.error).toBe("Agent a-1 not found");
  });

  it("returns an error when the response has no data", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: undefined,
    });

    const result = await agentApi.regenerateApiKey("a-1");

    expect(result.ok).toBe(false);
  });
});
