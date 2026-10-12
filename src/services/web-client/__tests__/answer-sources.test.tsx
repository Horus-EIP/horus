import React from "react";
import { describe, it, expect, beforeAll } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { AnswerSources } from "@/components/chat/answer-sources";
import { MessageList, type Message } from "@/components/message-list";
import {
  answerSourcesOf,
  distinctSources,
  knowledgeStoreDocumentHref,
  requestedDocumentId,
  sourceLabel,
} from "@/lib/chat/answer-sources";
import type { AnswerSource } from "@/lib/types";

const Q4: AnswerSource = {
  doc_id: "doc-q4",
  chunk_id: "doc-q4:3",
  title: "1_Q4_2025_Financial_Report.md",
  page: 2,
};
const EXPENSES: AnswerSource = {
  doc_id: "doc-expense",
  chunk_id: "doc-expense:0",
  title: "4_Expense_Policy.md",
  page: null,
};
const INLINE: AnswerSource = { doc_id: null, chunk_id: null, title: "notes.txt", page: null };

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
});

describe("answer sources", () => {
  it("reads the sources of a frame and drops what is not a source", () => {
    expect(
      answerSourcesOf([
        { doc_id: "doc-q4", chunk_id: "doc-q4:3", title: "1_Q4_2025_Financial_Report.md", page: 2 },
        "doc-q4",
        null,
        { title: "notes.txt", page: "2" },
      ])
    ).toEqual([Q4, INLINE]);
    expect(answerSourcesOf(undefined)).toBeUndefined();
  });

  it("names a source by its title and page", () => {
    expect(sourceLabel(Q4)).toBe("1_Q4_2025_Financial_Report.md, page 2");
    expect(sourceLabel(EXPENSES)).toBe("4_Expense_Policy.md");
    expect(sourceLabel({ ...INLINE, title: null })).toBe("Untitled document");
  });

  it("links a stored document to its view in the knowledge store", () => {
    expect(knowledgeStoreDocumentHref({ ...Q4, doc_id: "doc q4/1" })).toBe(
      "/knowledge-store?doc=doc%20q4%2F1"
    );
    expect(knowledgeStoreDocumentHref(INLINE)).toBeNull();
  });

  it("shows two passages of one page once", () => {
    expect(distinctSources([Q4, { ...Q4, chunk_id: "doc-q4:4" }, EXPENSES])).toEqual([Q4, EXPENSES]);
  });

  it("reads the requested document from the address", () => {
    expect(requestedDocumentId("?doc=doc-q4")).toBe("doc-q4");
    expect(requestedDocumentId("?doc=")).toBeNull();
    expect(requestedDocumentId("")).toBeNull();
  });
});

describe("AnswerSources", () => {
  function renderSources(sources?: AnswerSource[]) {
    return render(
      <MantineProvider env="test">
        <AnswerSources sources={sources} />
      </MantineProvider>
    );
  }

  it("lists each source with a link to its document", () => {
    renderSources([Q4, EXPENSES, INLINE]);

    const list = screen.getByRole("list", { name: "Sources" });
    const links = within(list).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "1_Q4_2025_Financial_Report.md, page 2",
      "4_Expense_Policy.md",
    ]);
    expect(links[0]).toHaveAttribute("href", "/knowledge-store?doc=doc-q4");
    expect(links[0]).toHaveAttribute("target", "_blank");
    expect(within(list).getByText("notes.txt").closest("a")).toBeNull();
  });

  it("shows nothing for an answer without sources", () => {
    renderSources([]);
    expect(screen.queryByText("Sources")).not.toBeInTheDocument();
    renderSources(undefined);
    expect(screen.queryByText("Sources")).not.toBeInTheDocument();
  });
});

describe("MessageList sources", () => {
  function renderMessages(messages: Message[]) {
    return render(
      <MantineProvider env="test">
        <MessageList
          messages={messages}
          isHistoryLoading={false}
          isLoading={false}
          messagesEndRef={React.createRef<HTMLDivElement>()}
        />
      </MantineProvider>
    );
  }

  it("shows the sources under the answer", () => {
    renderMessages([
      {
        id: "a-1",
        text: "Q4 2025 revenue was **$4.2M**.",
        sender: "agent",
        timestamp: new Date("2026-10-05T09:45:00Z"),
        status: "sent",
        sources: [Q4],
      },
    ]);

    const link = screen.getByRole("link", { name: /1_Q4_2025_Financial_Report\.md, page 2/ });
    expect(link).toHaveAttribute("href", "/knowledge-store?doc=doc-q4");
    expect(screen.getByText("$4.2M").tagName).toBe("STRONG");
  });

  it("never shows sources under a question", () => {
    renderMessages([
      {
        id: "u-1",
        text: "What was Q4 revenue?",
        sender: "user",
        timestamp: new Date("2026-10-05T09:44:00Z"),
        sources: [Q4],
      },
    ]);

    expect(screen.queryByText("Sources")).not.toBeInTheDocument();
  });
});
