import { vi, describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useWebSocket } from "@/hooks/use-web-socket";

vi.mock("@/contexts/notification-context", () => ({
  useNotification: () => ({
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  }),
}));

class MockWebSocket {
  url: string;
  readyState = 0;
  onopen: (() => void) | null = null;
  listeners: Record<string, Array<(...args: []) => void>> = {};

  constructor(url: string) {
    this.url = url;

    setTimeout(() => {
      this.readyState = 1;
      // eslint-disable-next-line
      this.onopen && this.onopen();
      this.listeners["open"]?.forEach((fn) => fn());
    }, 0);
  }

  addEventListener(type: string, listener: (...args: []) => void) {
    if (!this.listeners[type]) {
      this.listeners[type] = [];
    }
    this.listeners[type].push(listener);
  }

  removeEventListener(type: string, listener: (...args: []) => void) {
    this.listeners[type] = (this.listeners[type] || []).filter(
      (fn) => fn !== listener
    );
  }

  // eslint-disable-next-line
  send(_data: string) { }

  close() {
    this.readyState = 3;
    this.listeners["close"]?.forEach((fn) => fn());
  }
}

describe("useWebSocket", () => {
  beforeEach(() => {
    (global).WebSocket = MockWebSocket as unknown as typeof WebSocket;
  });

  it("sets status to connected when WebSocket opens", async () => {
    const { result } = renderHook(() =>
      useWebSocket({
        url: "ws://example.com",
        autoReconnect: false,
      })
    );

    expect(result.current.status).toBe("connecting");

    await waitFor(() => {
      expect(result.current.status).toBe("connected");
    }, { timeout: 1000 });
  });
});
