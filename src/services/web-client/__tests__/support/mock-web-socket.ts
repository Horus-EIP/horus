import { expect } from "vitest";
import { act, waitFor } from "@testing-library/react";

export class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static refuseConnections = false;
  static holdOpen = false;

  url: string;
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  listeners: Record<string, Array<(...args: []) => void>> = {};

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);

    setTimeout(() => {
      if (this.readyState !== 0 || MockWebSocket.holdOpen) return;
      if (MockWebSocket.refuseConnections) {
        act(() => {
          this.readyState = 3;
          this.onerror?.();
          this.onclose?.();
        });
        return;
      }
      this.readyState = 1;
      this.onopen?.();
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

  openFromServer() {
    act(() => {
      this.readyState = 1;
      this.onopen?.();
      this.listeners["open"]?.forEach((fn) => fn());
    });
  }

  dropFromServer() {
    act(() => {
      this.readyState = 3;
      this.onclose?.();
    });
  }

  deliver(payload: unknown) {
    act(() => {
      this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
    });
  }
}

export function installMockWebSocket() {
  MockWebSocket.instances = [];
  MockWebSocket.refuseConnections = false;
  MockWebSocket.holdOpen = false;
  (global).WebSocket = MockWebSocket as unknown as typeof WebSocket;
}

export function latestSocket(): MockWebSocket {
  return MockWebSocket.instances[MockWebSocket.instances.length - 1];
}

export async function waitForOpenSockets(created: number, timeout = 1000) {
  await waitFor(
    () => {
      expect(MockWebSocket.instances).toHaveLength(created);
      expect(latestSocket().readyState).toBe(1);
    },
    { timeout }
  );
}
