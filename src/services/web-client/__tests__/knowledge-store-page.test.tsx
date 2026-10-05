import React from "react";
import { vi, describe, it, expect, beforeAll, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MantineProvider } from "@mantine/core";
import KnowledgeStorePage from "@/app/(protected)/knowledge-store/page";

interface StoredDocument {
  id: string;
  title: string;
  date: string;
  size: number;
  summary: string;
  excerpt: string;
  category: string;
  document_type: string;
}

interface SearchRequestBody {
  query: string;
  n_results?: number;
  categories?: string[];
}

const expensePolicy: StoredDocument = {
  id: "doc-expense",
  title: "4_Expense_Policy.md",
  date: "2026-10-01 09:00:00.000001+00:00",
  size: 100,
  summary: "Expense rules",
  excerpt: "",
  category: "finance",
  document_type: "policy",
};

const securityPolicy: StoredDocument = {
  id: "doc-security",
  title: "5_IT_Security_Policy.md",
  date: "2026-10-01 09:00:00.000002+00:00",
  size: 200,
  summary: "Security rules",
  excerpt: "",
  category: "technical",
  document_type: "policy",
};

const handbook: StoredDocument = {
  id: "doc-handbook",
  title: "2_Employee_Handbook.md",
  date: "2026-10-01 09:00:00.000003+00:00",
  size: 300,
  summary: "Handbook",
  excerpt: "",
  category: "general",
  document_type: "handbook",
};

const storedDocuments = [expensePolicy, securityPolicy, handbook];

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function rankedMatches(request: SearchRequestBody): StoredDocument[] {
  const ranked = request.query === "rules" ? [securityPolicy, expensePolicy] : [];
  if (!request.categories) return ranked;
  return ranked.filter((doc) => request.categories!.includes(doc.category));
}

function smartSearchResponse(request: SearchRequestBody): Response {
  const matches = rankedMatches(request);
  if (!matches.length) return jsonResponse(404, { error: "No results found" });
  return jsonResponse(200, {
    query: request.query,
    total: matches.length,
    results: {
      documents: matches.map((doc) => doc.summary),
      metadatas: matches.map((doc) => ({
        title: doc.title,
        date: doc.date,
        size: doc.size,
        auto_category: doc.category,
      })),
      distances: matches.map((_, rank) => 0.1 * (rank + 1)),
    },
  });
}

function knowledgeStoreFetch(input: RequestInfo | URL, init?: RequestInit) {
  const url = String(input);
  const method = init?.method ?? "GET";
  if (method === "GET" && url.endsWith("/file")) {
    return Promise.resolve(jsonResponse(200, { documents: storedDocuments }));
  }
  if (method === "GET" && url.endsWith("/categories")) {
    return Promise.resolve(
      jsonResponse(200, {
        total_documents: 3,
        categories: [
          { category: "finance", count: 1 },
          { category: "technical", count: 1 },
          { category: "general", count: 1 },
        ],
      })
    );
  }
  if (method === "POST" && url.endsWith("/smart-search")) {
    return Promise.resolve(smartSearchResponse(JSON.parse(String(init?.body))));
  }
  if (method === "DELETE") {
    return Promise.resolve(jsonResponse(200, { status: "Document deleted" }));
  }
  return Promise.resolve(jsonResponse(404, { error: "Not found" }));
}

function smartSearchBodies(): SearchRequestBody[] {
  return vi
    .mocked(global.fetch)
    .mock.calls.filter(([url]) => String(url).endsWith("/smart-search"))
    .map(([, init]) => JSON.parse(String(init?.body)));
}

function listedTitles(): string[] {
  const table = screen.getByRole("table");
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0].textContent ?? "");
}

function renderPage() {
  render(
    <MantineProvider>
      <KnowledgeStorePage />
    </MantineProvider>
  );
}

async function waitForFullList() {
  await waitFor(() =>
    expect(listedTitles()).toEqual(storedDocuments.map((doc) => doc.title))
  );
}

async function chooseCategory(category: string) {
  const select = screen.getByRole("combobox");
  await within(select).findByRole("option", { name: `${category} (1)` });
  await userEvent.selectOptions(select, category);
}

function stubMatchMedia() {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
}

describe("KnowledgeStorePage search and category filter", () => {
  beforeAll(stubMatchMedia);

  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn(knowledgeStoreFetch) as typeof fetch;
  });

  it("shows every stored document while the search field is empty", async () => {
    renderPage();

    await waitForFullList();
    expect(smartSearchBodies()).toEqual([]);
  });

  it("offers the store's categories in the filter", async () => {
    renderPage();

    const select = screen.getByRole("combobox");
    await within(select).findByRole("option", { name: "finance (1)" });
    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent)
    ).toEqual(["All categories", "finance (1)", "technical (1)", "general (1)"]);
  });

  it("filters the list by category without a search term", async () => {
    renderPage();
    await waitForFullList();

    await chooseCategory("finance");

    await waitFor(() => expect(listedTitles()).toEqual([expensePolicy.title]));
    expect(smartSearchBodies()).toEqual([]);
  });

  it("shows the smart-search hits in ranked order for a search term", async () => {
    renderPage();
    await waitForFullList();

    await userEvent.type(screen.getByPlaceholderText("Search documents..."), "rules");

    await waitFor(() =>
      expect(listedTitles()).toEqual([securityPolicy.title, expensePolicy.title])
    );
    expect(smartSearchBodies()).toEqual([{ query: "rules", n_results: 10 }]);
  });

  it("sends the selected category along with the search term", async () => {
    renderPage();
    await waitForFullList();

    await chooseCategory("finance");
    await userEvent.type(screen.getByPlaceholderText("Search documents..."), "rules");

    await waitFor(() =>
      expect(smartSearchBodies()).toEqual([
        { query: "rules", n_results: 10, categories: ["finance"] },
      ])
    );
    await waitFor(() => expect(listedTitles()).toEqual([expensePolicy.title]));
  });

  it("shows an empty table when nothing matches the search term", async () => {
    renderPage();
    await waitForFullList();

    await userEvent.type(screen.getByPlaceholderText("Search documents..."), "zebra");

    await waitFor(() => expect(listedTitles()).toEqual([]));
  });

  it("returns to the full list when the search term is cleared", async () => {
    renderPage();
    await waitForFullList();
    const search = screen.getByPlaceholderText("Search documents...");

    await userEvent.type(search, "rules");
    await waitFor(() => expect(listedTitles()).toHaveLength(2));
    await userEvent.clear(search);

    await waitForFullList();
  });

  it("matches a search hit to its row by document id when the store sends one", async () => {
    const undated = { ...handbook, date: "Unknown" };
    global.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (method === "GET" && url.endsWith("/file")) {
        return Promise.resolve(
          jsonResponse(200, { documents: [expensePolicy, securityPolicy, undated] })
        );
      }
      if (method === "POST" && url.endsWith("/smart-search")) {
        return Promise.resolve(
          jsonResponse(200, {
            results: {
              ids: [undated.id],
              documents: [undated.summary],
              metadatas: [{ title: undated.title }],
              distances: [0.1],
            },
          })
        );
      }
      return knowledgeStoreFetch(input, init);
    }) as typeof fetch;
    renderPage();
    await waitFor(() => expect(listedTitles()).toHaveLength(3));

    await userEvent.type(screen.getByPlaceholderText("Search documents..."), "handbook");

    await waitFor(() => expect(listedTitles()).toEqual([handbook.title]));
  });

  it("deletes the document shown in the filtered row", async () => {
    renderPage();
    await waitForFullList();
    await chooseCategory("technical");
    await waitFor(() => expect(listedTitles()).toEqual([securityPolicy.title]));

    await userEvent.click(screen.getByRole("button", { name: "Delete file" }));

    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/doc-security$/),
        expect.objectContaining({ method: "DELETE" })
      )
    );
  });
});

describe("KnowledgeStorePage delete and duplicate upload", () => {
  let stored: StoredDocument[];

  beforeAll(() => {
    stubMatchMedia();
    window.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  });

  beforeEach(() => {
    localStorage.clear();
    stored = [...storedDocuments];
  });

  function storeFetch(deleteStatus: number) {
    return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (method === "GET" && url.endsWith("/file")) {
        return Promise.resolve(jsonResponse(200, { documents: stored }));
      }
      if (method === "DELETE") {
        stored = stored.filter((doc) => !url.endsWith(`/${doc.id}`));
        return Promise.resolve(jsonResponse(deleteStatus, { detail: "deleted" }));
      }
      return knowledgeStoreFetch(input, init);
    }) as typeof fetch;
  }

  async function deleteRow(title: string) {
    const row = within(screen.getByRole("table"))
      .getAllByRole("row")
      .find((candidate) => within(candidate).queryByText(title));
    await userEvent.click(within(row!).getByRole("button", { name: "Delete file" }));
  }

  async function queueUpload(name: string) {
    await userEvent.click(screen.getByRole("button", { name: "Add files" }));
    await screen.findByText("Files to Upload");
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    await userEvent.upload(input!, new File(["body"], name, { type: "text/markdown" }));
    await screen.findAllByText(name);
  }

  it("refreshes the list after a delete", async () => {
    global.fetch = storeFetch(200);
    renderPage();
    await waitForFullList();

    await deleteRow(securityPolicy.title);

    await waitFor(() =>
      expect(listedTitles()).toEqual([expensePolicy.title, handbook.title])
    );
  });

  it("refreshes the list when the row was already deleted in another tab", async () => {
    global.fetch = storeFetch(404);
    renderPage();
    await waitForFullList();

    await deleteRow(securityPolicy.title);

    await waitFor(() =>
      expect(listedTitles()).toEqual([expensePolicy.title, handbook.title])
    );
  });

  it("warns before upload when a file with the same name is already stored", async () => {
    global.fetch = storeFetch(200);
    renderPage();
    await waitForFullList();

    await queueUpload(expensePolicy.title);

    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent(expensePolicy.title);
    expect(warning).toHaveTextContent(/already in the knowledge store/i);
  });

  it("does not warn when the queued file name is new", async () => {
    global.fetch = storeFetch(200);
    renderPage();
    await waitForFullList();

    await queueUpload("Board_Minutes.md");

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
