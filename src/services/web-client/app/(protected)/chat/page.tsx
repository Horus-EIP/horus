'use client';

import React, {
  useState,
  useEffect,
  useLayoutEffect,
  useRef,
  useCallback,
} from 'react';
import { IconRobot, IconSend } from '@tabler/icons-react';
import { config } from "@/utils/config";
import { chatApi } from "@/lib/chat/api";
import { ErrorBoundary } from '@/components/error-boundary';
import { useNotification } from "@/contexts/notification-context";
import { useWebSocket } from "@/hooks/use-web-socket";
import { Textarea } from '@mantine/core';
import { MessageList, type Message } from "@/components/message-list";

const MAX_MESSAGE_LENGTH = 1000;
const MAX_ROWS = 6;

// Helper to get auth token
const getAuthToken = (): string | null => {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('auth_token');
};

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [conversationId, setConversationId] = useState<string>('');
  const [isHistoryLoading, setHistoryLoading] = useState<boolean>(true);
  const [hasShownLimitToast, setHasShownLimitToast] = useState(false);

  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [authToken, setAuthToken] = useState<string | null>(null);

  useLayoutEffect(() => {
    setAuthToken(getAuthToken());
  }, []);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);

  const { error: notifyError } = useNotification();
  
  // Guard against multiple conversation initializations
  const initCalledRef = useRef(false);

  const loadHistory = useCallback(
    async (cursor?: string) => {
      if (cursor) {
        setIsLoadingMore(true);
      } else {
        setHistoryLoading(true);
      }

      const result = await chatApi.getHistory(conversationId, cursor);

      if (cursor) {
        setIsLoadingMore(false);
      } else {
        setHistoryLoading(false);
      }

      if (!result.ok || !result.data) {
        const errorMessage = typeof result.error === 'object' 
          ? JSON.stringify(result.error) 
          : result.error;

        notifyError("Could not fetch conversation history.");
        return;
      }

      const { items = [], nextCursor } = result.data;

      const historyMessages: Message[] = (items || []).map((msg, idx) => ({
        id: `${Date.now()}-${idx}-${cursor || 'initial'}`,
        text: msg.message,
        sender: msg.role === 'user' ? 'user' : 'agent',
        timestamp: msg.timestamp ? new Date(msg.timestamp) : new Date(),
        status: 'sent',
      }));

      if (cursor) {
        setMessages((prev) => [...historyMessages, ...prev]);
      } else {
        setMessages(historyMessages);
      }

      setHistoryCursor(nextCursor ?? null);
      setHasMoreHistory(!!nextCursor);
    },
    [conversationId, notifyError]
  );

  // Build WebSocket URL with auth token
  const wsUrl = conversationId && authToken 
    ? `${config.wsUrl}/chat/${conversationId}/?token=${authToken}` 
    : null;

  const { status: wsStatus } = useWebSocket({
    url: wsUrl,
    autoReconnect: true,
    maxRetries: 5,
    backoffBaseMs: 1000,
    onMessage: (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "agent") {
        const agentMessage: Message = {
          id: Date.now().toString(),
          text: message.content,
          sender: "agent",
          timestamp: new Date(message.timestamp),
          status: 'sent',
        };
        setMessages((prev) => [...prev, agentMessage]);
        setIsLoading(false);
      }
    },
  });

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // Initialisation de la conversation et connexion WebSocket
  useEffect(() => {
    // Guard against concurrent calls within the same mount
    if (initCalledRef.current) return;
    initCalledRef.current = true;
    
    let isCancelled = false;
    
    const initConversation = async () => {
      const result = await chatApi.createConversation();
      
      // Don't update state if unmounted
      if (isCancelled) return;
      
      if (!result.ok || !result.data) {
        const detail =
          typeof result.error === "string" && result.error.trim()
            ? result.error
            : "Could not start the conversation. Please try again.";
        notifyError(detail);
        setIsLoading(false);
        return;
      }

      setConversationId(result.data);
    };

    initConversation();
    
    return () => {
      isCancelled = true;
      // Reset the ref on cleanup so Strict Mode remount can re-initialize
      initCalledRef.current = false;
    };
  }, [notifyError]);

  // Récupération de l'historique
  useEffect(() => {
    if (!conversationId) return;
    loadHistory();
  }, [conversationId, loadHistory]);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;

    const handleScroll = () => {
      const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      setShowScrollToBottom(!nearBottom);
    };

    handleScroll();
    el.addEventListener('scroll', handleScroll);
    return () => el.removeEventListener('scroll', handleScroll);
  }, [messages.length]);

  const handleInputChange = (
    e: React.ChangeEvent<HTMLTextAreaElement>
  ): void => {
    const value = e.target.value;

    if (value.length > MAX_MESSAGE_LENGTH) return;

    if (value.length === MAX_MESSAGE_LENGTH && !hasShownLimitToast) {
      notifyError(`Maximum message length of ${MAX_MESSAGE_LENGTH} characters reached.`);
      setHasShownLimitToast(true);
    }

    if (value.length < MAX_MESSAGE_LENGTH && hasShownLimitToast) {
      setHasShownLimitToast(false);
    }

    setInput(value);
  };

  // Soumission des messages
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || !conversationId || isLoading) return;

    const userMessageId = Date.now().toString();

    const userMessage: Message = {
      id: userMessageId,
      text: input,
      sender: 'user',
      timestamp: new Date(),
      status: 'sending',
    };

    const demand = input;
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    const result = await chatApi.createTask({
      demand,
      conversation_id: String(conversationId),  // Ensure it's a string for API
      skills_required: ["knowledge_retrieval"],
    });

    if (!result.ok) {
      const errorMessage = typeof result.error === 'object'
        ? JSON.stringify(result.error)
        : result.error;

      notifyError("Your message could not be sent. Please try again.");
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === userMessageId ? { ...msg, status: 'error' } : msg
        )
      );
      setIsLoading(false);
      return;
    }

    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === userMessageId ? { ...msg, status: 'sent' } : msg
      )
    );
  };

  return (
    <ErrorBoundary>
      <div className="bg-[var(--bg)] h-[85vh] flex flex-col overflow-hidden mx-auto rounded-lg max-w-[75vw] md:max-w-[60vw]">
        <div className="flex-none bg-[var(--bgSoft)] p-3 mt-3 md:mt-0 border-b border-gray-200 dark:border-gray-800 shadow-sm z-10">
          <div className="max-w-[100vw] md:max-w-[60vw] mx-auto">
            <h1 className="text-lg font-bold text-[var(--text)] flex items-center justify-center gap-2">
              <IconRobot className="w-6 h-6 text-blue-500" stroke={1.25} />
              Horus Agent Chat
              <span className="ml-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs bg-[var(--bg)] text-[var(--textSoft)] border border-gray-200 dark:border-gray-700">
                <span
                  className={`h-2 w-2 rounded-full ${wsStatus === "connected"
                    ? "bg-green-500"
                    : wsStatus === "connecting"
                      ? "bg-yellow-400"
                      : wsStatus === "error"
                        ? "bg-red-500"
                        : "bg-gray-400"
                    }`}
                />
                <span className="hidden sm:inline">
                  {wsStatus === "connected" && "Connected"}
                  {wsStatus === "connecting" && "Connecting..."}
                  {wsStatus === "disconnected" && "Disconnected"}
                  {wsStatus === "error" && "Error"}
                  {wsStatus === "idle" && "Idle"}
                </span>
              </span>
            </h1>
          </div>
        </div>

        {hasMoreHistory && (
          <button
            type="button"
            onClick={() => loadHistory(historyCursor || undefined)}
            disabled={isLoadingMore}
            className="mx-auto mb-2 mt-1 text-xs text-[var(--textSoft)] border border-gray-200 dark:border-gray-700 bg-[var(--bg)] p-1 cursor-pointer rounded-lg"
          >
            {isLoadingMore ? "Loading more..." : "Load older messages"}
          </button>
        )}

        <div
          ref={scrollContainerRef}
          className="flex-1 overflow-y-auto p-4 space-y-4 scroll-smooth overflow-x-hidden chat-scroll"
        >
          <MessageList messages={messages} isHistoryLoading={isHistoryLoading} isLoading={isLoading} messagesEndRef={messagesEndRef} />
        </div>

        {showScrollToBottom && (
          <button
            onClick={() =>
              messagesEndRef.current?.scrollIntoView({
                behavior: "smooth",
              })
            }
            className="fixed bottom-20 left-1/2 -translate-x-1/2 p-2 rounded-full bg-[var(--bgInputArea)] text-white shadow-md hover:bg-[var(--bg)] focus:outline-none focus:ring-1 focus:ring-[var(--textSoft)] cursor-pointer"
            aria-label="Scroll to bottom"
          >
            ↓
          </button>
        )}

        <div className="flex-none md:p-3 safe-area-bottom mx-auto w-full rounded-3xl border border-[var(--textSoft)] px-4 py-2 text-base bg-[var(--bgInputArea)] text-[var(--text)]">
          <form
            onSubmit={submit}
            className="max-w-[75vw] md:max-w-[60vw] mx-auto flex gap-2 items-end"
          >
            <Textarea
              value={input}
              onChange={handleInputChange}
              placeholder="Type a message..."
              className="flex-1 min-h-[44px] placeholder:text-[var(--textSoft)] input-scroll"
              classNames={{ input: 'bg-transparent border-0 focus:ring-0 resize-none overflow-y-auto' }}
              maxLength={MAX_MESSAGE_LENGTH}
              autosize
              maxRows={MAX_ROWS}
              minRows={1}
              disabled={!conversationId}
            />
            <button
              type="submit"
              disabled={!input.trim() || isLoading || !conversationId}
              className="flex-none w-11 h-11 rounded-full bg-blue-500 text-white flex items-center justify-center transition-colors hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed shadow-md"
            >
              <IconSend className="w-5 h-5 ml-0.5" stroke={1.25} />
            </button>
          </form>
        </div>
      </div>
    </ErrorBoundary>
  );
};
