'use client';

import { useCallback, useEffect, useRef, useState } from "react";
import { useNotification } from "@/contexts/notification-context";

export type WebSocketStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

type UseWebSocketOptions = {
  url: string | null;
  autoReconnect?: boolean;
  maxRetries?: number;
  backoffBaseMs?: number;
  onMessage?: (event: MessageEvent) => void;
  onReconnect?: () => void;
};

type UseWebSocketReturn = {
  status: WebSocketStatus;
  error: string | null;
  sendMessage: (data: string | object) => void;
  disconnect: () => void;
};

export function useWebSocket(options: UseWebSocketOptions): UseWebSocketReturn {
  const {
    url,
    autoReconnect = true,
    maxRetries = 5,
    backoffBaseMs = 1000,
    onMessage,
    onReconnect,
  } = options;

  const { error: notifyError } = useNotification();

  const [status, setStatus] = useState<WebSocketStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const attemptsRef = useRef(0);
  const queueRef = useRef<string[]>([]);
  const onMessageRef = useRef(onMessage);
  const onReconnectRef = useRef(onReconnect);
  const lastOpenedUrlRef = useRef<string | null>(null);
  const intentionalCloseRef = useRef(false);  // Track intentional closes

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    onReconnectRef.current = onReconnect;
  }, [onReconnect]);

  const clearReconnectTimeout = () => {
    if (reconnectTimeoutRef.current !== null) {
      window.clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  };

  const disconnect = useCallback(() => {
    clearReconnectTimeout();
    attemptsRef.current = 0;
    intentionalCloseRef.current = true;  // Mark as intentional

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setStatus("disconnected");
  }, []);

  const connect = useCallback(() => {
    if (!url || typeof window === "undefined") {
      return;
    }

    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    // Reset intentional close flag when connecting
    intentionalCloseRef.current = false;
    setStatus("connecting");
    setError(null);

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      const isReconnect = lastOpenedUrlRef.current === url;
      lastOpenedUrlRef.current = url;
      setStatus("connected");
      setError(null);
      attemptsRef.current = 0;

      if (queueRef.current.length > 0) {
        queueRef.current.forEach((msg) => ws.send(msg));
        queueRef.current = [];
      }

      if (isReconnect) {
        onReconnectRef.current?.();
      }
    };

    ws.onmessage = (event) => {
      const handler = onMessageRef.current;
      if (handler) {
        handler(event);
      }
    };

    ws.onerror = () => {
      setStatus("error");
      setError("Connection error. The assistant may not respond.");
      notifyError("Connection error. Trying to reconnect...");
    };

    ws.onclose = () => {
      setStatus("disconnected");

      // Don't reconnect if it was an intentional close (e.g., React Strict Mode cleanup)
      if (intentionalCloseRef.current) {
        intentionalCloseRef.current = false;  // Reset for next connection
        return;
      }

      if (!autoReconnect) return;

      const attempt = attemptsRef.current++;
      if (attempt >= maxRetries) {
        notifyError("Connection lost. Please refresh the page.");
        return;
      }

      const delay = Math.min(backoffBaseMs * 2 ** attempt, 30000); // cap em 30s
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect();
      }, delay);
    };
  }, [autoReconnect, backoffBaseMs, maxRetries, notifyError, url]);

  useEffect(() => {
    if (!url) {
      disconnect();
      return;
    }

    // Reset intentional close flag when starting new connection
    intentionalCloseRef.current = false;
    connect();

    return () => {
      clearReconnectTimeout();
      intentionalCloseRef.current = true;  // Mark cleanup close as intentional
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [url, connect, disconnect]);

  const sendMessage = useCallback((data: string | object) => {
    const payload = typeof data === "string" ? data : JSON.stringify(data);
    const ws = wsRef.current;

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(payload);
    } else {
      queueRef.current.push(payload);
    }
  }, []);

  return {
    status,
    error,
    sendMessage,
    disconnect,
  };
}
