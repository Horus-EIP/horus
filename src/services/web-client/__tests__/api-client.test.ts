import { vi, describe, it, expect, beforeEach } from "vitest";
import { apiClient } from "@/lib/api-client";

// Helper to create a mock Response object
function createMockResponse(options: {
  ok: boolean;
  status: number;
  json?: () => Promise<unknown>;
}): Response {
  return {
    ok: options.ok,
    status: options.status,
    json: options.json ?? (() => Promise.resolve({})),
    headers: new Headers(),
    redirected: false,
    statusText: options.ok ? "OK" : "Error",
    type: "basic",
    url: "",
    clone: () => createMockResponse(options),
    body: null,
    bodyUsed: false,
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
    blob: () => Promise.resolve(new Blob()),
    formData: () => Promise.resolve(new FormData()),
    text: () => Promise.resolve(""),
    bytes: () => Promise.resolve(new Uint8Array()),
  } as Response;
}

describe("apiClient", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it("should handle successful POST response", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      createMockResponse({
        ok: true,
        status: 200,
        json: async () => ({ foo: "bar" }),
      })
    );

    const res = await apiClient.post<{ foo: string }>("/test", { hello: "world" });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/test"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ hello: "world" }),
      })
    );
    expect(res.ok).toBe(true);
    expect(res.data?.foo).toBe("bar");
    expect(res.status).toBe(200);
  });

  it("should map 4xx errors to user-friendly message", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      createMockResponse({
        ok: false,
        status: 400,
        json: async () => ({ message: "Invalid payload" }),
      })
    );

    const res = await apiClient.post("/test", {});

    expect(res.ok).toBe(false);
    expect(res.error).toBe("Invalid payload");
    expect(res.status).toBe(400);
  });

  it("should map 5xx errors to generic server message", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      createMockResponse({
        ok: false,
        status: 500,
        json: async () => ({}),
      })
    );

    const res = await apiClient.get("/test");

    expect(res.ok).toBe(false);
    expect(res.error).toMatch(/server/i);
    expect(res.status).toBe(500);
  });

  it("should handle network errors gracefully", async () => {
    vi.mocked(global.fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const res = await apiClient.get("/test");

    expect(res.ok).toBe(false);
    expect(res.error).toMatch(/Network error/i);
  });
});
