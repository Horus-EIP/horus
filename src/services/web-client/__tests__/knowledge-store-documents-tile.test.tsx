import React from "react";
import { vi, describe, it, expect, beforeAll, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MantineProvider } from "@mantine/core";
import KnowledgeStorePage from "@/app/(protected)/knowledge-store/page";
import { knowledgeStoreApi } from "@/lib/knowledge-store/api";

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

function storedDocument(id: string, title: string): StoredDocument {
  return {
    id,
    title,
    date: "2026-10-01 09:00:00.000001+00:00",
    size: 100,
    summary: `${title} summary`,
    excerpt: "",
    category: "finance",
    document_type: "policy",
  };
}

const documentsBeforeUpload = [
  storedDocument("doc-report", "1_Q4_2025_Financial_Report.md"),
  storedDocument("doc-handbook", "2_Employee_Handbook.md"),
  storedDocument("doc-expense", "4_Expense_Policy.md"),
];
const uploadedDocument = storedDocument("doc-travel", "6_Travel_Policy.md");
const documentsAfterUpload = [...documentsBeforeUpload, uploadedDocument];

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

let listDocuments: () => Promise<Response>;

function knowledgeStoreFetch(input: RequestInfo | URL, init?: RequestInit) {
  const url = String(input);
  const method = init?.method ?? "GET";
  if (method === "GET" && url.endsWith("/file")) return listDocuments();
  if (method === "GET" && url.endsWith("/categories")) {
    return Promise.resolve(jsonResponse(200, { total_documents: 0, categories: [] }));
  }
  return Promise.resolve(jsonResponse(404, { error: "Not found" }));
}

function documentListRequests(): number {
  return vi
    .mocked(global.fetch)
    .mock.calls.filter(
      ([url, init]) => String(url).endsWith("/file") && (init?.method ?? "GET") === "GET"
    ).length;
}

function documentsTile(): HTMLElement {
  return screen.getByText("Total Documents").closest("div.relative") as HTMLElement;
}

function renderPage() {
  render(
    <MantineProvider env="test">
      <KnowledgeStorePage />
    </MantineProvider>
  );
}

function listing(documents: StoredDocument[]): Promise<Response> {
  return Promise.resolve(jsonResponse(200, { documents }));
}

async function uploadOneFile() {
  await userEvent.click(screen.getByRole("button", { name: "Add files" }));
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(
    input,
    new File(["Travel rules"], uploadedDocument.title, { type: "text/markdown" })
  );
  await screen.findByText(uploadedDocument.title);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
}

describe("KnowledgeStorePage documents tile", () => {
  beforeAll(() => {
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
  });

  beforeEach(() => {
    localStorage.clear();
    listDocuments = () => listing(documentsBeforeUpload);
    global.fetch = vi.fn(knowledgeStoreFetch) as typeof fetch;
    vi.spyOn(knowledgeStoreApi, "uploadDocumentsWithProgress").mockImplementation(async () => {
      listDocuments = () => listing(documentsAfterUpload);
      return { ok: true, data: [{ filename: uploadedDocument.title, doc_id: uploadedDocument.id }] };
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads the document list once when the page opens", async () => {
    renderPage();

    await waitFor(() => expect(within(documentsTile()).getByText("3")).toBeInTheDocument());
    expect(documentListRequests()).toBe(1);
  });

  it("refreshes the document list once after an upload and counts the new file", async () => {
    renderPage();
    await waitFor(() => expect(within(documentsTile()).getByText("3")).toBeInTheDocument());
    const requestsBeforeUpload = documentListRequests();

    await uploadOneFile();

    await waitFor(() => expect(within(documentsTile()).getByText("4")).toBeInTheDocument());
    expect(documentListRequests() - requestsBeforeUpload).toBe(1);
  });

  it("keeps the post-upload count when older list requests answer last", async () => {
    const answerOlderListings: ((response: Response) => void)[] = [];
    listDocuments = () =>
      new Promise<Response>((resolve) => {
        answerOlderListings.push(resolve);
      });
    renderPage();
    await waitFor(() => expect(documentListRequests()).toBeGreaterThan(0));

    await uploadOneFile();
    await waitFor(() => expect(within(documentsTile()).getByText("4")).toBeInTheDocument());
    await act(async () => {
      answerOlderListings.forEach((answer) =>
        answer(jsonResponse(200, { documents: documentsBeforeUpload }))
      );
    });

    expect(within(documentsTile()).getByText("4")).toBeInTheDocument();
  });
});
