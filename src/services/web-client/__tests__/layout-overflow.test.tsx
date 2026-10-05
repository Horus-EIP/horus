import React from "react";
import { vi, describe, it, expect, beforeAll, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import ProtectedLayout from "@/app/(protected)/layout";
import KnowledgeStorePage from "@/app/(protected)/knowledge-store/page";
import DashboardPage from "@/app/(protected)/dashboard/page";
import Info from "@/components/ui/info";
import { MessageList, type Message } from "@/components/message-list";

vi.mock("next/navigation", () => ({
  usePathname: () => "/knowledge-store",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/components/auth/protected-route", () => ({
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({ status: "unauthenticated", user: null, logout: vi.fn() }),
}));

vi.mock("@/contexts/notification-context", () => ({
  useNotification: () => ({ error: vi.fn(), success: vi.fn() }),
}));

const longFileName =
  "Q4_2025_Consolidated_Financial_Report_reviewed_by_the_finance_team_final_v12.md";

const longSummary =
  "Quarterly revenue grew to $4.2M while operating costs stayed flat, the travel " +
  "policy now caps hotel nights at $250, and the board approved two new hires " +
  "for the platform team in Q1 2026.";

const storedDocument = {
  id: "8c1f2a4e-5b6d-4e7f-9a0b-1c2d3e4f5a6b",
  title: longFileName,
  date: "2026-10-01 09:00:00.000001+00:00",
  size: 4096,
  summary: longSummary,
  excerpt: "",
  category: "finance",
  document_type: "report",
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function knowledgeStoreFetch(input: RequestInfo | URL) {
  const url = String(input);
  if (url.endsWith("/file")) {
    return Promise.resolve(jsonResponse(200, { documents: [storedDocument] }));
  }
  if (url.endsWith("/categories")) {
    return Promise.resolve(
      jsonResponse(200, {
        total_documents: 1,
        categories: [{ category: "finance", count: 1 }],
      })
    );
  }
  return Promise.resolve(jsonResponse(404, { error: "Not found" }));
}

function describeElement(element: HTMLElement): string {
  return `<${element.tagName.toLowerCase()} class="${element.className}">`;
}

function rowFlexItemsThatCannotShrink(element: HTMLElement): string[] {
  const blocked: string[] = [];
  for (let node = element.parentElement; node?.parentElement; node = node.parentElement) {
    const container = node.parentElement;
    const isRowFlexItem =
      container.classList.contains("flex") && !container.classList.contains("flex-col");
    if (isRowFlexItem && !node.classList.contains("min-w-0")) {
      blocked.push(describeElement(node));
    }
  }
  return blocked;
}

function renderInLayout(page: React.ReactNode) {
  return render(
    <MantineProvider>
      <ProtectedLayout>{page}</ProtectedLayout>
    </MantineProvider>
  );
}

describe("Layout width at 1366 px and on tablets", () => {
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
    global.fetch = vi.fn(knowledgeStoreFetch) as typeof fetch;
  });

  it("lets the main column shrink below the width of the page it shows", () => {
    renderInLayout(<p>Page content</p>);

    expect(screen.getByRole("main")).toHaveClass("min-w-0");
  });

  it("lets every column around the knowledge-store table shrink to the screen", async () => {
    renderInLayout(<KnowledgeStorePage />);

    const table = await screen.findByRole("table");
    await within(table).findByText(longFileName);

    expect(rowFlexItemsThatCannotShrink(table)).toEqual([]);
  });

  it("sizes the knowledge-store cards and table to the column, not to a fixed or viewport width", async () => {
    const { container } = renderInLayout(<KnowledgeStorePage />);
    await screen.findByText(longFileName);

    expect(container.querySelector('[class~="md:w-200"]')).toBeNull();
    expect(container.querySelector('[class~="max-w-[75vw]"]')).toBeNull();
  });

  it("lets every column around the dashboard agent table shrink to the screen", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const { container } = renderInLayout(<DashboardPage />);

    const table = screen.getByRole("table");

    expect(rowFlexItemsThatCannotShrink(table)).toEqual([]);
    expect(container.querySelector('[class~="max-w-[75vw]"]')).toBeNull();
  });

  it("wraps long summaries and file names inside a capped column and clamps them to three lines", () => {
    render(
      <Info
        header={["Document", "Summary", "Status"]}
        body={[[longFileName, longSummary, "completed"]]}
      />
    );

    const [fileCell, summaryCell] = screen.getAllByRole("cell");
    for (const [cell, text] of [
      [fileCell, longFileName],
      [summaryCell, longSummary],
    ] as const) {
      expect(cell).not.toHaveClass("whitespace-nowrap");
      expect(within(cell).getByTitle(text)).toHaveClass(
        "min-w-48",
        "max-w-xs",
        "line-clamp-3",
        "wrap-anywhere"
      );
    }
  });

  it("keeps short values such as categories and dates in whole words", () => {
    const indexedAt = "2026-10-01 09:00:00.000001+00:00";
    render(<Info header={["Category", "Date"]} body={[["finance", indexedAt]]} />);

    for (const text of ["finance", indexedAt]) {
      const value = screen.getByTitle(text);
      expect(value).toHaveClass("max-w-xs", "wrap-break-word");
      expect(value).not.toHaveClass("wrap-anywhere");
      expect(value.closest("td")).not.toHaveClass("whitespace-nowrap");
    }
  });

  it("lets a long unbroken token in an agent answer wrap inside its bubble", () => {
    const longUrl = `https://intranet.example.com/finance/reports/${longFileName}`;
    const messages: Message[] = [
      { id: "m-1", text: longUrl, sender: "agent", timestamp: new Date("2026-10-05T09:30:00Z") },
    ];

    render(
      <MantineProvider>
        <div className="flex">
          <div className="min-w-0 flex-1">
            <MessageList
              messages={messages}
              isHistoryLoading={false}
              isLoading={false}
              messagesEndRef={React.createRef<HTMLDivElement>()}
            />
          </div>
        </div>
      </MantineProvider>
    );

    const answer = screen.getByText(longUrl);

    expect(rowFlexItemsThatCannotShrink(answer)).toEqual([]);
    expect(answer.closest('[class~="wrap-break-word"]')).not.toBeNull();
  });
});
