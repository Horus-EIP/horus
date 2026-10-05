import React from "react";
import { describe, it, expect, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { MessageList } from "@/components/message-list";

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
