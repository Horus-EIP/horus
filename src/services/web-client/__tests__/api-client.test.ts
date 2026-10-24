import { vi, describe, it, expect, beforeEach } from "vitest";
import { apiClient } from "@/lib/api-client";

// Helper to create a mock Response object
function createMockResponse(options: {
  ok: boolean;
  status: number;
  json?: () => Promise<unknown>;
  headerMap?: Record<string, string>;
}): Response {
  const headers = new Headers(options.headerMap ?? undefined);
  const jsonFn = options.json ?? (() => Promise.resolve({}));
  return {
    ok: options.ok,
    status: options.status,
    json: jsonFn,
    text: async () => {
      const v = await jsonFn();
      return v === undefined || v === null ? "" : JSON.stringify(v);
    },
    headers,
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

  it("sends multipart form data without overriding its boundary content type", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      createMockResponse({
        ok: true,
        status: 200,
        json: async () => ({ message: "installed", state: "valid" }),
      })
    );
    const formData = new FormData();
    formData.append("file", new File(["signed-license"], "license.jws"));

    const res = await apiClient.postMultipart("/license/upload", formData);

    const request = vi.mocked(global.fetch).mock.calls[0]?.[1];
    expect(request?.body).toBe(formData);
    expect(new Headers(request?.headers).has("Content-Type")).toBe(false);
    expect(res.ok).toBe(true);
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

  it("rewrites 307 Location from Docker internal host to same-origin BFF URL", async () => {
    vi.stubGlobal("location", {
      ...window.location,
      origin: "http://localhost:3000",
    });

    vi.mocked(global.fetch)
      .mockResolvedValueOnce(
        createMockResponse({
          ok: false,
          status: 307,
          headerMap: {
            Location: "http://mas:8000/conversations/create-conversation",
          },
        })
      )
      .mockResolvedValueOnce(
        createMockResponse({
          ok: true,
          status: 200,
          json: async () => ({ conversation_id: 42 }),
        })
      );

    const res = await apiClient.post<{ conversation_id: number }>(
      "/conversations/create-conversation",
      { name: "Test" }
    );

    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(vi.mocked(global.fetch).mock.calls[1]?.[0]).toBe(
      "http://localhost:3000/api/orchestrator/conversations/create-conversation"
    );
    expect(res.ok).toBe(true);
    expect(res.data?.conversation_id).toBe(42);
  });
});
