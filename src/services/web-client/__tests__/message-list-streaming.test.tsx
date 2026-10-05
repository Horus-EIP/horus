import React from "react";
import { describe, it, expect, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { MessageList, type Message } from "@/components/message-list";

function renderList(streamingText: string, isLoading = true) {
  const messagesEndRef = React.createRef<HTMLDivElement>();
  return render(
    <MantineProvider env="test">
      <MessageList
        messages={[]}
        isHistoryLoading={false}
        isLoading={isLoading}
        messagesEndRef={messagesEndRef}
        streamingText={streamingText}
      />
    </MantineProvider>
  );
}

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

describe("MessageList streamed answer preview", () => {
  it("shows the streamed markdown instead of the thinking spinner", () => {
    renderList("## Q4 revenue\n\nRevenue was **$4.2M**.");
    expect(screen.getByRole("heading", { name: "Q4 revenue" })).toBeInTheDocument();
    expect(screen.getByText("$4.2M").tagName).toBe("STRONG");
    expect(screen.queryByLabelText("Agent is thinking...")).not.toBeInTheDocument();
  });

  it("shows the spinner until the first chunk arrives", () => {
    renderList("");
    expect(screen.getByLabelText("Agent is thinking...")).toBeInTheDocument();
  });

  it("drops the preview once the answer is no longer loading", () => {
    renderList("Revenue was $4.2M.", false);
    expect(screen.queryByText("Revenue was $4.2M.")).not.toBeInTheDocument();
  });
});

describe("MessageList failed answer", () => {
  function renderMessage(status: Message["status"]) {
    return render(
      <MantineProvider env="test">
        <MessageList
          messages={[
            {
              id: "a-1",
              text: "The model did not finish its answer within 900s.",
              sender: "agent",
              timestamp: new Date("2026-10-05T09:45:00Z"),
              status,
            },
          ]}
          isHistoryLoading={false}
          isLoading={false}
          messagesEndRef={React.createRef<HTMLDivElement>()}
        />
      </MantineProvider>
    );
  }

  it("labels the answer of a failed task as failed", () => {
    renderMessage("error");
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("shows no failure label on an answer", () => {
    renderMessage("sent");
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
  });
});
