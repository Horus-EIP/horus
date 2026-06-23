'use client';

import React, {
  useState,
  useEffect,
  useLayoutEffect,
  useRef,
  useCallback,
  Suspense,
  useMemo,
} from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { IconRobot, IconSend } from '@tabler/icons-react';
import { Modal, Button, Group, Text, Textarea, TextInput } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { config } from '@/utils/config';
import { chatApi, type Conversation, type TaskDetails } from '@/lib/chat/api';
import { agentApi, type Agent } from '@/lib/agents/api';
import { ErrorBoundary } from '@/components/error-boundary';
import { useNotification } from '@/contexts/notification-context';
import { useWebSocket } from '@/hooks/use-web-socket';
import { MessageList, type Message } from '@/components/message-list';
import type { TaskStepEvent } from '@/lib/types';
import { ConversationSidebar } from '@/components/chat/conversation-sidebar';
import { WorkingAgentsBar } from '@/components/chat/working-agents-bar';
import { useAuth } from '@/components/auth/auth-provider';
import {
  FileAttachments,
  type FileAttachmentsValue,
} from '@/components/tasks/file-attachments';

const MAX_MESSAGE_LENGTH = 1000;
const MAX_ROWS = 6;

const getAuthToken = (): string | null => {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('auth_token');
};

function ChatPageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const conversationFromUrl = searchParams.get('conversation');

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [conversationId, setConversationId] = useState<string>('');
  const [attachments, setAttachments] = useState<FileAttachmentsValue>({
    attached: [],
    inline: [],
  });
  const [isHistoryLoading, setHistoryLoading] = useState<boolean>(false);
  const [hasShownLimitToast, setHasShownLimitToast] = useState(false);

  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [authToken, setAuthToken] = useState<string | null>(null);

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [opened, { open, close }] = useDisclosure(false);
  const [deletingConversation, setDeletingConversation] = useState<Conversation | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const [
    newChatModalOpened,
    { open: openNewChatModal, close: closeNewChatModal },
  ] = useDisclosure(false);
  const [newConversationName, setNewConversationName] = useState('');

  const [agentsById, setAgentsById] = useState<Map<string, Agent>>(new Map());
  const [workingTaskId, setWorkingTaskId] = useState<string | null>(null);
  const [workingTaskDetail, setWorkingTaskDetail] = useState<TaskDetails | null>(null);
  // Streamed "thought process" steps, keyed by task_id. Populated by the
  // task_step WS frames the agent worker emits as it runs.
  const [stepsByTaskId, setStepsByTaskId] = useState<Record<string, TaskStepEvent[]>>({});
  // Live answer text accumulated from reasoning.delta frames (Phase 1 token
  // streaming), keyed by the (root) task_id. Rendered as a "typing" preview in
  // the thinking slot until the authoritative task_complete answer commits.
  const [streamingByTaskId, setStreamingByTaskId] = useState<Record<string, string>>({});

  const { user } = useAuth();
  const { error: notifyError, success: notifySuccess } = useNotification();
  const notifyErrorRef = useRef(notifyError);
  notifyErrorRef.current = notifyError;

  useLayoutEffect(() => {
    setAuthToken(getAuthToken());
  }, []);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);

  const [isCreatingChat, setIsCreatingChat] = useState(false);

  const loadConversations = useCallback(async () => {
    try {
      setConversationsLoading(true);
      const result = await chatApi.getConversations();
      if (result.ok && result.data) {
        setConversations(result.data);
      } else {
        notifyErrorRef.current(result.error || 'Failed to load conversations');
      }
    } catch {
      notifyErrorRef.current('Failed to load conversations');
    } finally {
      setConversationsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadConversations();
    (async () => {
      const res = await agentApi.getAgents();
      if (res.ok && res.data) {
        setAgentsById(new Map(res.data.map((a) => [a.id, a])));
      }
    })();
  }, [loadConversations]);

  const loadHistory = useCallback(
    async (cursor?: string) => {
      if (cursor) {
        setIsLoadingMore(true);
      } else {
        setHistoryLoading(true);
        setMessages([]);
        setHistoryCursor(null);
        setHasMoreHistory(false);
      }

      const result = await chatApi.getHistory(conversationId, cursor);

      if (cursor) {
        setIsLoadingMore(false);
      } else {
        setHistoryLoading(false);
      }

      if (!result.ok || !result.data) {
        notifyError('Could not fetch conversation history.');
        return;
      }

      const { items = [], nextCursor } = result.data;

      const historyMessages: Message[] = (items || []).map((msg, idx) => ({
        id: `${Date.now()}-${idx}-${cursor || 'initial'}`,
        text: msg.message,
        sender: msg.role === 'user' ? 'user' : 'agent',
        timestamp: msg.timestamp ? new Date(msg.timestamp) : new Date(),
        status: 'sent',
        // Carry attribution from persisted rows so reload restores Manager
        // violet bubbles + per-specialist chips. User-role messages have
        // no attribution and these come through as undefined cleanly.
        agentId: msg.agentId,
        agentName: msg.agentName,
        skillUsed: msg.skillUsed,
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

  const wsUrl =
    conversationId && authToken
      ? `${config.wsUrl}/chat/${conversationId}/?token=${authToken}`
      : null;

  const { status: wsStatus } = useWebSocket({
    url: wsUrl,
    autoReconnect: true,
    maxRetries: 5,
    backoffBaseMs: 1000,
    onMessage: (event) => {
      const message = JSON.parse(event.data);
      // 'reasoning.delta' = a streamed chunk of the answer itself (Phase 1).
      // Accumulated into the live preview, NOT the thought-process card.
      if (
        message.type === 'task_step' &&
        message.step_type === 'reasoning.delta'
      ) {
        const taskId =
          typeof message.task_id === 'string' ? message.task_id : '';
        const meta =
          message.metadata && typeof message.metadata === 'object'
            ? (message.metadata as Record<string, unknown>)
            : {};
        const chunk = typeof meta.chunk === 'string' ? meta.chunk : '';
        if (taskId && chunk) {
          setStreamingByTaskId((prev) => ({
            ...prev,
            [taskId]: (prev[taskId] ?? '') + chunk,
          }));
        }
        return;
      }
      // 'task_step' = streaming "thought process" event from the agent worker.
      // Appended to the per-task bucket so the ThoughtProcessCard renders it
      // live under the user message that kicked off this task.
      if (message.type === 'task_step') {
        const taskId = typeof message.task_id === 'string' ? message.task_id : '';
        if (!taskId) return;
        const step: TaskStepEvent = {
          taskId,
          agentId:
            typeof message.agent_id === 'string' ? message.agent_id : undefined,
          agentName:
            typeof message.agent_name === 'string'
              ? message.agent_name
              : undefined,
          stepType: String(message.step_type ?? 'unknown'),
          title: String(message.title ?? message.step_type ?? 'Step'),
          detail:
            typeof message.detail === 'string' && message.detail.length
              ? message.detail
              : undefined,
          timestamp:
            typeof message.timestamp === 'string'
              ? message.timestamp
              : new Date().toISOString(),
          metadata:
            message.metadata && typeof message.metadata === 'object'
              ? (message.metadata as Record<string, unknown>)
              : undefined,
        };
        setStepsByTaskId((prev) => {
          const next = { ...prev };
          next[taskId] = [...(next[taskId] ?? []), step];
          return next;
        });
        return;
      }
      // 'agent' = legacy bare-text broadcast (direct-answer / pre-attribution path)
      // 'task_complete' = answer with agent attribution metadata for the chip
      if (message.type === 'agent' || message.type === 'task_complete') {
        const text = String(message.content ?? '').trim();
        // Manager messages are intermediate orchestration updates (plan
        // announcement, per-step "routing to X" progress, review decisions).
        // They should NOT clear the loading state — the chain is still
        // running and the user expects to see the spinner until the actual
        // final answer from the last specialist arrives.
        const isManagerMessage =
          typeof message.agent_name === 'string' &&
          message.agent_name === 'Manager';
        if (!text) {
          if (!isManagerMessage) {
            setIsLoading(false);
          }
          return;
        }
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.sender === 'agent' && last.text === text) {
            return prev;
          }
          const agentMessage: Message = {
            id: Date.now().toString(),
            text: message.content,
            sender: 'agent',
            timestamp: new Date(message.timestamp),
            status: 'sent',
            agentId:
              typeof message.agent_id === 'string' ? message.agent_id : undefined,
            agentName:
              typeof message.agent_name === 'string'
                ? message.agent_name
                : undefined,
            skillUsed:
              typeof message.skill_used === 'string'
                ? message.skill_used
                : undefined,
          };
          return [...prev, agentMessage];
        });
        if (!isManagerMessage) {
          // Only a real specialist's terminal answer clears the spinner.
          // The chain is still running while Manager messages flow.
          setIsLoading(false);
          // The committed message now owns the text; drop the live preview.
          setStreamingByTaskId({});
        }
      }
    },
  });

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  useEffect(() => {
    const existing = conversationFromUrl?.trim() ?? '';
    if (existing && /^\d+$/.test(existing)) {
      setConversationId(existing);
      setHistoryLoading(true);
      return;
    }

    setConversationId('');
    setMessages([]);
    setHistoryLoading(false);
    setHistoryCursor(null);
    setHasMoreHistory(false);
  }, [conversationFromUrl]);

  useEffect(() => {
    if (!conversationId) return;
    loadHistory();
  }, [conversationId, loadHistory]);

  // Hydrate the in-progress chain state when the user navigates back to a
  // conversation whose chain is still running on the backend. Without this,
  // the chat looks idle ("nothing happening") even though the Manager and
  // specialists are mid-execution — the WS reconnects but the working bar +
  // spinner + thought-process card require local state we lost on unmount.
  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    (async () => {
      const r = await chatApi.getRunningTasksForConversation(conversationId);
      if (cancelled || !r.ok || !r.data || r.data.length === 0) return;
      // Most recent running root task — the one the user is waiting on.
      const running = r.data[0];
      setWorkingTaskId(running.id);
      setIsLoading(true);
      // Attach the root task id to the most recent USER message so the
      // thought-process card pinned to it can pick up incoming step events.
      // Best-effort: the message exists because loadHistory ran first.
      setMessages((prev) => {
        // Walk from the end to find the latest user message without an
        // attached taskId — that's the demand that kicked off this chain.
        for (let i = prev.length - 1; i >= 0; i--) {
          if (prev[i].sender === 'user' && !prev[i].taskId) {
            const updated = [...prev];
            updated[i] = { ...updated[i], taskId: running.id };
            return updated;
          }
        }
        return prev;
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => {
    if (!isLoading) {
      setWorkingTaskId(null);
      setWorkingTaskDetail(null);
    }
  }, [isLoading]);

  useEffect(() => {
    if (!workingTaskId || !isLoading) return;
    let cancelled = false;

    const tick = async () => {
      const r = await chatApi.getTask(workingTaskId);
      if (cancelled || !r.ok || !r.data) return;
      setWorkingTaskDetail(r.data);
    };

    void tick();
    const id = window.setInterval(tick, 1600);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [workingTaskId, isLoading]);

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

  const canDelete = useCallback(
    (conversation: Conversation) => {
      if (!user) return false;
      if (conversation.owner_username === user.username) return true;
      if (user.role === 'admin' || user.role === 'manager') return true;
      return false;
    },
    [user]
  );

  const handleDeleteClick = (c: Conversation) => {
    if (!canDelete(c)) {
      notifyError("You don't have permission to delete this conversation");
      return;
    }
    setDeletingConversation(c);
    open();
  };

  const handleConfirmDelete = async () => {
    if (!deletingConversation) return;

    try {
      setIsDeleting(true);
      const result = await chatApi.deleteConversation(deletingConversation.id);

      if (result.ok) {
        setConversations((prev) => prev.filter((c) => c.id !== deletingConversation.id));
        notifySuccess('Conversation deleted successfully');
        if (String(deletingConversation.id) === conversationId) {
          router.replace('/chat');
        }
        close();
      } else {
        notifyError(result.error || 'Failed to delete conversation');
      }
    } catch {
      notifyError('Failed to delete conversation');
    } finally {
      setIsDeleting(false);
      setDeletingConversation(null);
    }
  };

  const handleSelectConversation = (id: number) => {
    router.replace(`/chat?conversation=${id}`);
  };

  const requestNewConversation = useCallback(() => {
    // Pre-fill with a sensible default; user can edit before confirming.
    setNewConversationName(`Chat ${new Date().toLocaleString()}`);
    openNewChatModal();
  }, [openNewChatModal]);

  const confirmNewConversation = useCallback(async () => {
    const name = newConversationName.trim();
    if (!name) {
      notifyError('Please give the conversation a name.');
      return;
    }

    setIsCreatingChat(true);
    try {
      const result = await chatApi.createConversation(name);
      if (!result.ok || !result.data) {
        const detail =
          typeof result.error === 'string' && result.error.trim()
            ? result.error
            : 'Could not create a conversation. Please try again.';
        notifyError(detail);
        return;
      }
      closeNewChatModal();
      router.replace(`/chat?conversation=${result.data}`);
      void loadConversations();
    } finally {
      setIsCreatingChat(false);
    }
  }, [
    newConversationName,
    notifyError,
    router,
    loadConversations,
    closeNewChatModal,
  ]);

  const mobileOptions = useMemo(() => {
    const q = searchTerm.toLowerCase();
    return conversations.filter((c) => {
      const text = `${c.name ?? ''} ${c.id}`.toLowerCase();
      return text.includes(q);
    });
  }, [conversations, searchTerm]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>): void => {
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
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);
    setWorkingTaskId(null);
    setWorkingTaskDetail(null);

    // Empty skills_required + no mode → orchestrator runs its LLM router on
    // the demand and picks the best-matching specialist (e.g. Finance-Analyst
    // for "summarise Q4 financial risk"). Falls back to General-Assistant via
    // the catch-all path when nothing matches. Previously hardcoded to
    // ``['knowledge_retrieval']``, which short-circuited routing onto the
    // General-Assistant for every chat message and starved the specialists.
    const result = await chatApi.createTask({
      demand,
      conversation_id: String(conversationId),
      skills_required: [],
      attached_files: attachments.attached,
      inline_files: attachments.inline,
    });

    if (!result.ok) {
      notifyError('Your message could not be sent. Please try again.');
      setMessages((prev) =>
        prev.map((msg) => (msg.id === userMessageId ? { ...msg, status: 'error' } : msg))
      );
      setIsLoading(false);
      return;
    }

    const newTaskId = result.data?.task_id;
    const directAnswer = !newTaskId && Boolean(result.data?.result);
    // Direct-answer path: MAS's orchestrator router decided no agent dispatch
    // was needed (typical for arithmetic / greetings / DIRECT_ANSWER class).
    // Synthesize a task_id and one step so the thought-process card still
    // renders — that way the user sees *why* there's no agent attribution
    // and which model actually answered (the small 1.5B router, not the 4B
    // worker). The agent never runs in this path, so no real steps come.
    const effectiveTaskId = newTaskId ?? (directAnswer ? `direct-${Date.now()}` : undefined);
    if (newTaskId) {
      setWorkingTaskId(newTaskId);
    }
    if (directAnswer && effectiveTaskId) {
      setStepsByTaskId((prev) => ({
        ...prev,
        [effectiveTaskId]: [
          {
            taskId: effectiveTaskId,
            stepType: 'reasoning.done',
            title: 'Orchestrator answered directly',
            detail:
              "MAS's router classified this as a DIRECT_ANSWER and replied " +
              'without dispatching to an agent worker. No retrieval ran, no ' +
              'specialist persona was applied.',
            timestamp: new Date().toISOString(),
            metadata: { path: 'orchestrator_direct_answer' },
          },
        ],
      }));
    }

    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === userMessageId
          ? { ...msg, status: 'sent', taskId: effectiveTaskId ?? msg.taskId }
          : msg
      )
    );
    // Attachments are scoped to a single message — clear them after dispatch
    // so the next one starts clean unless the user picks again.
    setAttachments({ attached: [], inline: [] });
  };

  return (
    <>
      <Modal
        opened={newChatModalOpened}
        onClose={closeNewChatModal}
        title={
          <span className="text-lg font-semibold text-[var(--text)]">New Conversation</span>
        }
        centered
        styles={{
          content: {
            backgroundColor: 'var(--bgSoft)',
            border: '1px solid rgba(255,255,255,0.1)',
          },
          header: { backgroundColor: 'var(--bgSoft)' },
          body: { backgroundColor: 'var(--bgSoft)' },
        }}
        overlayProps={{ backgroundOpacity: 0.55, blur: 3 }}
      >
        <div className="flex flex-col gap-4">
          <Text size="sm" className="text-[var(--textSoft)]">
            Give this conversation a name so you can find it later.
          </Text>
          <TextInput
            value={newConversationName}
            onChange={(e) => setNewConversationName(e.currentTarget.value)}
            placeholder="e.g. Q4 financial review"
            data-autofocus
            maxLength={120}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && newConversationName.trim() && !isCreatingChat) {
                e.preventDefault();
                void confirmNewConversation();
              }
            }}
            classNames={{
              input:
                'bg-[var(--bg)] border-white/10 text-[var(--text)] placeholder:text-[var(--textSoft)]',
            }}
          />
          <Group justify="flex-end" mt="sm">
            <Button
              variant="default"
              onClick={closeNewChatModal}
              disabled={isCreatingChat}
              className="border-white/10 bg-white/5 text-[var(--text)] hover:bg-white/10"
            >
              Cancel
            </Button>
            <Button
              onClick={confirmNewConversation}
              loading={isCreatingChat}
              disabled={!newConversationName.trim()}
              className="bg-blue-600 text-white hover:bg-blue-700"
            >
              Create
            </Button>
          </Group>
        </div>
      </Modal>

      <Modal
        opened={opened}
        onClose={close}
        title={
          <span className="text-lg font-semibold text-[var(--text)]">Delete Conversation</span>
        }
        centered
        styles={{
          content: {
            backgroundColor: 'var(--bgSoft)',
            border: '1px solid rgba(255,255,255,0.1)',
          },
          header: { backgroundColor: 'var(--bgSoft)' },
          body: { backgroundColor: 'var(--bgSoft)' },
        }}
        overlayProps={{ backgroundOpacity: 0.55, blur: 3 }}
      >
        <div className="flex flex-col gap-4">
          <Text size="md" className="text-[var(--textSoft)]">
            Are you sure you want to{' '}
            <span className="text-red-500 underline">permanently</span> delete the conversation{' '}
            <span className="font-bold text-[var(--text)]">&quot;{deletingConversation?.name}&quot;</span>?
          </Text>
          <Text size="sm" className="text-[var(--textSoft)]">
            This action <span className="text-red-500 underline">cannot</span> be undone. All messages in
            this conversation will be lost.
          </Text>

          <Group justify="flex-end" mt="md">
            <Button
              variant="default"
              onClick={close}
              disabled={isDeleting}
              className="border-white/10 bg-white/5 text-[var(--text)] hover:bg-white/10"
            >
              Cancel
            </Button>
            <Button
              onClick={handleConfirmDelete}
              loading={isDeleting}
              color="red"
              className="bg-red-600 text-white hover:bg-red-700"
            >
              Delete Conversation
            </Button>
          </Group>
        </div>
      </Modal>

      <div className="mx-auto flex h-[85vh] max-w-[min(1600px,96vw)] flex-col gap-2 overflow-hidden md:flex-row">
        <div className="hidden min-h-0 md:flex">
          <ConversationSidebar
            conversations={conversations}
            selectedId={conversationId}
            searchTerm={searchTerm}
            onSearchChange={setSearchTerm}
            onSelect={handleSelectConversation}
            onNewChat={requestNewConversation}
            onDelete={handleDeleteClick}
            canDelete={canDelete}
            isLoading={conversationsLoading}
            onRefresh={loadConversations}
            newChatPending={isCreatingChat}
          />
        </div>

        <div className="flex shrink-0 flex-col gap-2 px-1 md:hidden">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={requestNewConversation}
              disabled={isCreatingChat}
              className="shrink-0 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {isCreatingChat ? '…' : 'New'}
            </button>
            <select
              className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-[var(--bgSoft)] px-3 py-2 text-sm text-[var(--text)] dark:border-gray-700"
              value={conversationFromUrl && /^\d+$/.test(conversationFromUrl) ? conversationFromUrl : ''}
              onChange={(e) => {
                const v = e.target.value;
                if (v) handleSelectConversation(Number(v));
              }}
            >
              <option value="" disabled hidden>
                Choose a conversation…
              </option>
              {mobileOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name || `Conversation ${c.id}`}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={loadConversations}
              disabled={conversationsLoading}
              className="rounded-lg border border-gray-200 px-3 py-2 text-sm dark:border-gray-700"
            >
              ↻
            </button>
          </div>
          <input
            type="search"
            placeholder="Filter conversations…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="rounded-lg border border-gray-200 bg-[var(--bg)] px-3 py-2 text-sm dark:border-gray-700"
          />
        </div>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg bg-[var(--bg)]">
          <div className="z-10 flex-none border-b border-gray-200 bg-[var(--bgSoft)] p-3 shadow-sm dark:border-gray-800 md:mt-0">
            <div className="mx-auto max-w-[100vw] md:max-w-[60vw]">
              <h1 className="flex items-center justify-center gap-2 text-lg font-bold text-[var(--text)]">
                <IconRobot className="h-6 w-6 text-blue-500" stroke={1.25} />
                Horus Agent Chat
                <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-gray-200 bg-[var(--bg)] px-2 py-0.5 text-xs text-[var(--textSoft)] dark:border-gray-700">
                  <span
                    className={`h-2 w-2 rounded-full ${
                      wsStatus === 'connected'
                        ? 'bg-green-500'
                        : wsStatus === 'connecting'
                          ? 'bg-yellow-400'
                          : wsStatus === 'error'
                            ? 'bg-red-500'
                            : 'bg-gray-400'
                    }`}
                  />
                  <span className="hidden sm:inline">
                    {wsStatus === 'connected' && 'Connected'}
                    {wsStatus === 'connecting' && 'Connecting...'}
                    {wsStatus === 'disconnected' && 'Disconnected'}
                    {wsStatus === 'error' && 'Error'}
                    {wsStatus === 'idle' && 'Idle'}
                  </span>
                </span>
              </h1>
            </div>
          </div>

          {isLoading && workingTaskId && !workingTaskDetail && (
            <div className="border-b border-amber-500/20 bg-amber-500/5 px-3 py-2 text-center text-xs text-[var(--textSoft)]">
              Dispatching task to agents…
            </div>
          )}

          <WorkingAgentsBar taskDetail={workingTaskDetail} agentsById={agentsById} />

          {hasMoreHistory && (
            <button
              type="button"
              onClick={() => loadHistory(historyCursor || undefined)}
              disabled={isLoadingMore}
              className="mx-auto mb-2 mt-1 cursor-pointer rounded-lg border border-gray-200 bg-[var(--bg)] p-1 text-xs text-[var(--textSoft)] dark:border-gray-700"
            >
              {isLoadingMore ? 'Loading more...' : 'Load older messages'}
            </button>
          )}

          <div
            ref={scrollContainerRef}
            className="chat-scroll flex-1 space-y-4 overflow-x-hidden overflow-y-auto scroll-smooth p-4"
          >
            <MessageList
              messages={messages}
              isHistoryLoading={isHistoryLoading}
              isLoading={isLoading}
              messagesEndRef={messagesEndRef}
              stepsByTaskId={stepsByTaskId}
              workingTaskId={workingTaskId}
              streamingText={
                workingTaskId ? streamingByTaskId[workingTaskId] ?? '' : ''
              }
              emptyStateTitle={
                conversationId ? undefined : 'No conversation selected'
              }
              emptyStateSubtitle={
                conversationId
                  ? undefined
                  : 'Choose one from the list or click New chat to start.'
              }
            />
          </div>

          {showScrollToBottom && (
            <button
              onClick={() =>
                messagesEndRef.current?.scrollIntoView({
                  behavior: 'smooth',
                })
              }
              className="fixed bottom-20 left-1/2 z-20 -translate-x-1/2 cursor-pointer rounded-full bg-[var(--bgInputArea)] p-2 text-white shadow-md hover:bg-[var(--bg)] focus:ring-1 focus:ring-[var(--textSoft)] focus:outline-none"
              aria-label="Scroll to bottom"
            >
              ↓
            </button>
          )}

          <div className="safe-area-bottom mx-auto w-full flex-none rounded-3xl border border-[var(--textSoft)] bg-[var(--bgInputArea)] px-4 py-2 text-base text-[var(--text)] md:p-3">
            {conversationId && (
              <div className="mx-auto mb-2 max-w-[75vw] md:max-w-[60vw]">
                <FileAttachments
                  value={attachments}
                  onChange={setAttachments}
                  compact
                  onError={notifyError}
                />
              </div>
            )}
            <form
              onSubmit={submit}
              className="mx-auto flex max-w-[75vw] items-end gap-2 md:max-w-[60vw]"
            >
              <Textarea
                value={input}
                onChange={handleInputChange}
                placeholder={
                  conversationId
                    ? 'Type a message...'
                    : 'Select or create a conversation to start messaging…'
                }
                className="input-scroll min-h-[44px] flex-1 placeholder:text-[var(--textSoft)]"
                classNames={{
                  input: 'bg-transparent border-0 focus:ring-0 resize-none overflow-y-auto',
                }}
                maxLength={MAX_MESSAGE_LENGTH}
                autosize
                maxRows={MAX_ROWS}
                minRows={1}
                disabled={!conversationId}
              />
              <button
                type="submit"
                disabled={!input.trim() || isLoading || !conversationId}
                className="flex h-11 w-11 flex-none items-center justify-center rounded-full bg-blue-500 text-white shadow-md transition-colors hover:bg-blue-600 disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                <IconSend className="ml-0.5 h-5 w-5" stroke={1.25} />
              </button>
            </form>
          </div>
        </div>
      </div>
    </>
  );
}

export default function ChatPage() {
  return (
    <ErrorBoundary>
      <Suspense
        fallback={
          <div className="mx-auto flex h-[85vh] max-w-[75vw] items-center justify-center rounded-lg bg-[var(--bg)] text-[var(--textSoft)] md:max-w-[60vw]">
            Loading chat…
          </div>
        }
      >
        <ChatPageContent />
      </Suspense>
    </ErrorBoundary>
  );
}
