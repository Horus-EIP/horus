import { vi, describe, it, expect, beforeEach } from "vitest";
import { knowledgeStoreApi } from "@/lib/knowledge-store/api";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("knowledgeStoreApi.smartSearch", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
    localStorage.clear();
  });

  it("posts the query and category filter as JSON to /smart-search", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      jsonResponse(200, { results: { documents: [], metadatas: [], distances: [] } })
    );

    await knowledgeStoreApi.smartSearch({
      query: "expense limits",
      n_results: 10,
      categories: ["finance"],
    });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/smart-search$/),
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: "expense limits",
          n_results: 10,
          categories: ["finance"],
        }),
      })
    );
  });

  it("sends the signed-in user's bearer token to the gateway", async () => {
    localStorage.setItem("auth_token", "signed-in-jwt");
    vi.mocked(global.fetch).mockResolvedValueOnce(
      jsonResponse(200, { results: { documents: [], metadatas: [], distances: [] } })
    );

    await knowledgeStoreApi.smartSearch({ query: "policy" });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer signed-in-jwt",
        },
      })
    );
  });

  it("pairs each returned document with its metadata and distance", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      jsonResponse(200, {
        query: "policy",
        filters: null,
        total: 2,
        results: {
          documents: ["Expense body", "Security body"],
          metadatas: [
            { title: "4_Expense_Policy.md", date: "d1", auto_category: "finance" },
            { title: "5_IT_Security_Policy.md", date: "d2", auto_category: "technical" },
          ],
          distances: [0.21, 0.48],
        },
      })
    );

    const result = await knowledgeStoreApi.smartSearch({ query: "policy" });

    expect(result).toEqual({
      ok: true,
      data: [
        {
          content: "Expense body",
          metadata: { title: "4_Expense_Policy.md", date: "d1", auto_category: "finance" },
          distance: 0.21,
        },
        {
          content: "Security body",
          metadata: { title: "5_IT_Security_Policy.md", date: "d2", auto_category: "technical" },
          distance: 0.48,
        },
      ],
    });
  });

  it("gives each hit the document id the store returns", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      jsonResponse(200, {
        results: {
          ids: ["doc-expense", "doc-security"],
          documents: ["Expense body", "Security body"],
          metadatas: [{ title: "4_Expense_Policy.md" }, { title: "5_IT_Security_Policy.md" }],
          distances: [0.21, 0.48],
        },
      })
    );

    const result = await knowledgeStoreApi.smartSearch({ query: "policy" });

    expect(result.data?.map((hit) => hit.id)).toEqual(["doc-expense", "doc-security"]);
  });

  it("leaves the id unset when the store sends none", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      jsonResponse(200, {
        results: { documents: ["Body"], metadatas: [{ title: "a.md" }], distances: [0.1] },
      })
    );

    const result = await knowledgeStoreApi.smartSearch({ query: "policy" });

    expect(result.data?.[0]).not.toHaveProperty("id");
  });

  it("treats the store's 404 for no match as an empty result list", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      jsonResponse(404, { error: "No results found" })
    );

    const result = await knowledgeStoreApi.smartSearch({ query: "nothing" });

    expect(result).toEqual({ ok: true, data: [] });
  });

  it("returns an error when the store fails the search", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      jsonResponse(500, { error: "Error performing smart search" })
    );

    const result = await knowledgeStoreApi.smartSearch({ query: "policy" });

    expect(result.ok).toBe(false);
    expect(result.error).toBe("Knowledge store responded 500");
  });

  it("returns an error when the store is unreachable", async () => {
    vi.mocked(global.fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const result = await knowledgeStoreApi.smartSearch({ query: "policy" });

    expect(result).toEqual({ ok: false, error: "Failed to fetch" });
  });
});

describe("knowledgeStoreApi.getCategories", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
    localStorage.clear();
  });

  it("returns the categories with their document counts", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      jsonResponse(200, {
        total_documents: 3,
        categories: [
          { category: "finance", count: 2 },
          { category: "general", count: 1 },
        ],
      })
    );

    const result = await knowledgeStoreApi.getCategories();

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/categories$/),
      expect.objectContaining({ method: "GET" })
    );
    expect(result).toEqual({
      ok: true,
      data: [
        { category: "finance", count: 2 },
        { category: "general", count: 1 },
      ],
    });
  });

  it("returns an error when the store responds with a failure", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      jsonResponse(500, { error: "Error retrieving categories" })
    );

    const result = await knowledgeStoreApi.getCategories();

    expect(result).toEqual({ ok: false, error: "Knowledge store responded 500" });
  });
});
