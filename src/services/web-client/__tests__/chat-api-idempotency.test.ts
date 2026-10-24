import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { chatApi, IDEMPOTENCY_HEADER } from "@/lib/chat/api";

const QUESTION = {
  demand: "What was Q4 2025 revenue?",
  conversation_id: "42",
  skills_required: [],
};

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function sentKeys(): (string | undefined)[] {
  return vi.mocked(global.fetch).mock.calls.map(([, init]) => {
    const candidate = init?.headers;
    if (!candidate) return undefined;
    if (candidate instanceof Headers) {
      return candidate.get(IDEMPOTENCY_HEADER) ?? undefined;
    }
    if (Array.isArray(candidate)) {
      const pair = candidate.find(([key]) => key === IDEMPOTENCY_HEADER);
      return pair?.[1];
    }
    return (candidate as Record<string, string>)[IDEMPOTENCY_HEADER];
  });
}

describe("new task submission", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("answers with the queued task id", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      reply(202, { task_id: "root-7", status: "queued", conversation_id: 42 })
    );

    const result = await chatApi.createTask(QUESTION);

    expect(result).toEqual({
      ok: true,
      data: { task_id: "root-7", status: "queued", conversation_id: 42 },
    });
  });

  it("reuses one idempotency key on its automatic retries", async () => {
    vi.mocked(global.fetch)
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(reply(503, { detail: "busy" }))
      .mockResolvedValueOnce(reply(202, { task_id: "root-7", status: "queued" }));

    const submitted = chatApi.createTask(QUESTION);
    await vi.runAllTimersAsync();
    const result = await submitted;

    expect(result.ok).toBe(true);
    const keys = sentKeys();
    expect(keys).toHaveLength(3);
    expect(keys[0]).toBeTruthy();
    expect(new Set(keys).size).toBe(1);
  });

  it("uses a new key for every submit", async () => {
    vi.mocked(global.fetch).mockImplementation(async () =>
      reply(202, { task_id: "root-7", status: "queued" })
    );

    await chatApi.createTask(QUESTION);
    await chatApi.createTask(QUESTION);

    const [first, second] = sentKeys();
    expect(first).toBeTruthy();
    expect(second).toBeTruthy();
    expect(first).not.toBe(second);
  });

  it("sends a key the caller chose", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(reply(202, { task_id: "root-7", status: "queued" }));

    await chatApi.createTask(QUESTION, "submit-1");

    expect(sentKeys()).toEqual(["submit-1"]);
  });
});
