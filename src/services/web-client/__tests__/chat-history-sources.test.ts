import { vi, describe, it, expect, beforeEach } from "vitest";
import { chatApi } from "@/lib/chat/api";

function reply(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("conversation history", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it("keeps the sources stored with each answer", async () => {
    const source = { doc_id: "doc-q4", chunk_id: "doc-q4:3", title: "q4.md", page: 2 };
    vi.mocked(global.fetch).mockResolvedValueOnce(
      reply([
        { id: 1, role: "user", content: "What was Q4 revenue?", created_at: "2026-10-05T09:30:00" },
        {
          id: 2,
          role: "assistant",
          content: "Revenue was $4.2M.",
          created_at: "2026-10-05T09:33:00",
          agent_name: "Finance-Analyst",
          sources: [source],
        },
        { id: 3, role: "assistant", content: "Older answer", sources: null },
      ])
    );

    const history = await chatApi.getHistory("42");

    expect(history.ok).toBe(true);
    const [question, answer, older] = history.data!.items;
    expect(question.sources).toBeUndefined();
    expect(answer.sources).toEqual([source]);
    expect(older.sources).toBeUndefined();
  });
});
