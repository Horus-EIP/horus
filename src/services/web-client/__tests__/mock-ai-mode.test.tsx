import React from "react";
import { vi, describe, it, expect, beforeAll, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";

import { AiModeBanner, MOCK_BANNER_TEXT } from "@/components/ai-mode-banner";
import { MessageList, SIMULATED_TITLE, type Message } from "@/components/message-list";
import { appendAgentAnswer, finishedTaskAnswer } from "@/lib/chat/agent-answer";
import { chatApi, type TaskDetails } from "@/lib/chat/api";
import { routeTaskFrame } from "@/lib/chat/task-events";
import { systemApi } from "@/lib/system/api";

function reply(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const MOCK = { mode: "mock", model: "horus-mock", server: "horus-mock", simulated: true };
const LOCAL = { mode: "local", model: "qwen3-4b", server: "llamacpp", simulated: false };

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

beforeEach(() => {
  global.fetch = vi.fn();
});

describe("the AI mode", () => {
  it("is read from the public MAS route", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(reply(MOCK));

    const result = await systemApi.getAiMode();

    expect(result).toEqual({ ok: true, data: MOCK });
    expect(String(vi.mocked(global.fetch).mock.calls[0][0])).toContain("/system/ai");
  });

  it("is an error, not a mode, when MAS cannot say", async () => {
    vi.mocked(global.fetch).mockImplementation(async () => reply({ detail: "down" }, 503));

    const result = await systemApi.getAiMode();

    expect(result.ok).toBe(false);
    expect(result.data).toBeUndefined();
  });
});

describe("the mock mode banner", () => {
  it("is shown on the page in mock mode", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(reply(MOCK));

    render(<AiModeBanner />);

    const banner = await screen.findByRole("status");
    expect(banner).toHaveTextContent("Mock AI mode:");
    expect(banner).toHaveTextContent(MOCK_BANNER_TEXT);
  });

  it.each([["a local model", LOCAL, 200], ["an error", {}, 500]])(
    "is not shown with %s",
    async (_name, body, status) => {
      vi.mocked(global.fetch).mockImplementation(async () => reply(body, status));

      render(<AiModeBanner />);

      await waitFor(() => expect(global.fetch).toHaveBeenCalled());
      expect(screen.queryByRole("status")).toBeNull();
    }
  );
});

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

const ANSWER: Message = {
  id: "a-1",
  text: "Q4 2025 revenue was **$4.2M**.",
  sender: "agent",
  timestamp: new Date("2026-10-09T09:45:00Z"),
  status: "sent",
};

describe("the Simulated badge", () => {
  it("marks an answer whose provider is the mock, with or without an agent name", () => {
    renderMessages([
      { ...ANSWER, aiProvider: "mock", agentName: "Finance-Analyst" },
      { ...ANSWER, id: "a-2", aiProvider: "mock" },
    ]);

    const badges = screen.getAllByText("Simulated");
    expect(badges).toHaveLength(2);
    expect(badges[0]).toHaveAttribute("title", SIMULATED_TITLE);
  });

  it("is absent from local answers, older answers and the user's own messages", () => {
    renderMessages([
      { ...ANSWER, aiProvider: "local", agentName: "Finance-Analyst" },
      { ...ANSWER, id: "a-2" },
      { ...ANSWER, id: "u-1", sender: "user", aiProvider: "mock", text: "What was Q4 revenue?" },
    ]);

    expect(screen.queryByText("Simulated")).toBeNull();
  });
});

describe("the provider of an answer", () => {
  it("comes back with the conversation history", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      reply([
        { id: 1, role: "user", content: "What was Q4 revenue?" },
        { id: 2, role: "assistant", content: "Revenue was $4.2M.", ai_provider: "mock" },
        { id: 3, role: "assistant", content: "Older answer", ai_provider: null },
      ])
    );

    const history = await chatApi.getHistory("42");

    expect(history.data!.items.map((item) => item.aiProvider)).toEqual([undefined, "mock", undefined]);
  });

  it("comes with the live answer frame and is kept on the message", () => {
    const onAnswer = vi.fn();
    routeTaskFrame(
      { type: "task_complete", content: "Revenue was $4.2M.", agent_name: "Finance-Analyst",
        task_id: "root-7", seq: 4, event: "result", ai_provider: "mock" },
      { onStep: vi.fn(), onStreamChunk: vi.fn(), onAnswer, onProgress: vi.fn() }
    );

    const answer = onAnswer.mock.calls[0][0];
    expect(answer.aiProvider).toBe("mock");
    expect(appendAgentAnswer([], answer)[0].aiProvider).toBe("mock");
  });

  it("comes with a finished task read again after a reconnect", () => {
    const task = { task_id: "t1", status: "completed", agent_id: "a1", conversation_id: 7,
                   query: "q", created_at: "", result: "Revenue was $4.2M.",
                   ai_provider: "mock" } as TaskDetails;

    expect(finishedTaskAnswer(task).aiProvider).toBe("mock");
    expect(finishedTaskAnswer({ ...task, ai_provider: null }).aiProvider).toBeUndefined();
  });
});
