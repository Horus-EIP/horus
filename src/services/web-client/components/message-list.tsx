'use client';

import React from "react";
import ReactMarkdown from "react-markdown";
import { Skeleton } from '@mantine/core';
import {
  IconExclamationCircle,
  IconHierarchy,
  IconRobot,
  IconUser,
} from '@tabler/icons-react';
import { Spinner } from "@/components/ui/spinner";
import { formatTimestamp } from "@/utils/format";
import { ThoughtProcessCard } from "@/components/chat/thought-process-card";
import type { TaskStepEvent } from "@/lib/types";

export interface Message {
  id: string;
  text: string;
  sender: "user" | "agent";
  timestamp: Date;
  status?: "sending" | "sent" | "error";
  /** Originating agent UUID (set when delivered via task_complete event). */
  agentId?: string;
  /** Human-readable agent name for the attribution chip. */
  agentName?: string;
  /** Skill the agent exercised for this message. */
  skillUsed?: string;
  /** Task ID the message dispatched, used to attach a thought-process card. */
  taskId?: string;
  messageId?: number;
}

interface MessageListProps {
  messages: Message[];
  isHistoryLoading: boolean;
  isLoading: boolean;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  /** When set, overrides the default empty-state copy (no messages, not loading). */
  emptyStateTitle?: string;
  emptyStateSubtitle?: string;
  /** Per-task list of "thought process" events streamed live via WebSocket. */
  stepsByTaskId?: Record<string, TaskStepEvent[]>;
  /** Task ID still in-flight; its card stays auto-expanded until it completes. */
  workingTaskId?: string | null;
  /** Live answer text streamed via reasoning.delta; shown as a typing preview
   *  in the thinking slot until the authoritative task_complete answer commits. */
  streamingText?: string;
}

const mdComponents = {
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="text-xl font-semibold mt-2 mb-1 first:mt-0">{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="text-lg font-semibold mt-2 mb-1 first:mt-0">{children}</h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="text-base font-semibold mt-1.5 mb-0.5">{children}</h3>
  ),
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="my-1.5 first:mt-0 last:mb-0 leading-relaxed">{children}</p>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="list-disc pl-5 my-1.5 space-y-0.5">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="list-decimal pl-5 my-1.5 space-y-0.5">{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li className="leading-relaxed">{children}</li>
  ),
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold text-[var(--text)]">{children}</strong>
  ),
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded bg-black/10 dark:bg-white/10 px-1 py-0.5 text-[0.9em] font-mono">
      {children}
    </code>
  ),
  pre: ({ children }: { children?: React.ReactNode }) => (
    <pre className="overflow-x-auto rounded-lg bg-black/10 dark:bg-white/10 p-2 my-2 text-sm">
      {children}
    </pre>
  ),
};

const ChatHistorySkeleton = () => {
  return (
    <div className="space-y-4">
      {[0, 1].map((i) => {
        const isUser = i % 2 === 1;

        return (
          <div
            key={i}
            className={`flex ${isUser ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`
                flex gap-2 max-w-[80%]
                ${isUser ? "flex-row-reverse" : "flex-row"}
              `}
            >
              <div className="space-y-2 flex-1">
                <div
                  className={`
                    rounded-2xl p-3 shadow-sm
                    ${isUser
                      ? "bg-blue-500/10 border border-blue-500/30"
                      : "bg-gray-200 dark:bg-gray-800 border border-gray-200 dark:border-gray-700"
                    }
                  `}
                >
                  <div className="space-y-2">
                    {Array.from({ length: 6 }).map((_, idx) => (
                      <Skeleton key={idx} height={12} width="70%" />
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  isHistoryLoading,
  isLoading,
  messagesEndRef,
  emptyStateTitle = 'Start a conversation',
  emptyStateSubtitle = 'How can we help you?',
  stepsByTaskId,
  workingTaskId,
  streamingText,
}) => {
  return (
    <div className="mx-auto max-w-[75vw] md:max-w-[60vw] space-y-4">
      {isHistoryLoading && messages.length === 0 && <ChatHistorySkeleton />}

      {!isHistoryLoading && messages.length === 0 && (
        <div className="text-center text-gray-500 mt-8 flex flex-col items-center justify-center h-full">
          <IconRobot className="w-12 h-12 mb-4 text-[var(--textSoft)] opacity-50" stroke={1.25} />
          <p className="text-lg font-medium text-[var(--textSoft)]">
            {emptyStateTitle}
          </p>
          <p className="text-sm text-[var(--textSoft)]">
            {emptyStateSubtitle}
          </p>
        </div>
      )}

      {messages.map((message) => {
        const isManager =
          message.sender === "agent" && message.agentName === "Manager";
        return (
        <React.Fragment key={message.id}>
        <div
          className={`flex ${message.sender === "user" ? "justify-end" : "justify-start"
            }`}
        >
          <div
            className={`flex min-w-0 gap-2 max-w-[85%] sm:max-w-[75%]
              ${message.sender === "user"
                ? "flex-row-reverse"
                : "flex-row"
              }
            `}
          >
            <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center border ${
              isManager
                ? "bg-violet-500/15 text-violet-600 dark:text-violet-300 border-violet-500/40"
                : "bg-[var(--bgSoft)] text-[var(--text)] border-gray-200 dark:border-gray-700"
            }`}>
              {message.sender === "user" ? (
                <IconUser className="w-5 h-5" stroke={1.25} />
              ) : isManager ? (
                <IconHierarchy className="w-5 h-5" stroke={1.25} />
              ) : (
                <IconRobot className="w-5 h-5 text-blue-500" stroke={1.25} />
              )}
            </div>

            <div
              className={`min-w-0 wrap-break-word rounded-2xl px-4 py-2 text-[var(--text)] text-base shadow-sm ${
                message.sender === "user"
                  ? "bg-blue-500 text-white rounded-tr-none"
                  : isManager
                    ? "bg-violet-500/10 mr-auto rounded-tl-none border border-violet-500/30"
                    : "bg-[var(--bgSoft)] mr-auto rounded-tl-none border border-gray-200 dark:border-gray-700"
              }`}
            >
              {message.sender === "agent" ? (
                <div className="agent-message-md max-w-none">
                  <ReactMarkdown components={mdComponents}>
                    {message.text}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap break-words">{message.text}</p>
              )}

              {message.sender === "agent" &&
                (message.agentName || message.skillUsed) && (
                  <div className="mt-2 flex flex-wrap items-center gap-1">
                    {message.agentName && (
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                          isManager
                            ? "border border-violet-500/40 bg-violet-500/15 text-violet-700 dark:text-violet-300"
                            : "border border-blue-500/30 bg-blue-500/10 text-blue-600 dark:text-blue-300"
                        }`}
                        title={
                          message.agentId
                            ? `Agent ID: ${message.agentId}`
                            : undefined
                        }
                      >
                        {isManager ? (
                          <IconHierarchy className="h-3 w-3" stroke={1.5} />
                        ) : (
                          <IconRobot className="h-3 w-3" stroke={1.5} />
                        )}
                        {message.agentName}
                      </span>
                    )}
                    {message.skillUsed && (
                      <span className="inline-flex items-center rounded-full border border-gray-300 bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300">
                        {message.skillUsed}
                      </span>
                    )}
                  </div>
                )}

              <div className="mt-1 flex items-center justify-between gap-2">
                <span className="text-[10px] opacity-70">
                  {formatTimestamp(message.timestamp)}
                </span>

                {message.sender === "user" && (
                  <span className="text-[10px] opacity-80 text-right text-[var(--textSoft)] flex items-center gap-1">
                    {message.status === "sending" && "Sending..."}
                    {message.status === "sent" && "Sent"}
                    {message.status === "error" && (
                      <>
                        <span className="text-red-400">Error</span>
                        <IconExclamationCircle className="w-3 h-3 text-red-400" />
                      </>
                    )}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
        {message.sender === "user" && message.taskId && (
          <ThoughtProcessCard
            taskId={message.taskId}
            steps={(stepsByTaskId && stepsByTaskId[message.taskId]) || []}
            isRunning={workingTaskId === message.taskId}
          />
        )}
        </React.Fragment>
        );
      })}

      {isLoading && !isHistoryLoading && (
        <div className="flex justify-start opacity-95 transition-opacity">
          <div className="flex min-w-0 gap-2 max-w-[85%] sm:max-w-[75%]">
            <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-[var(--bgSoft)] border border-gray-200 dark:border-gray-700">
              <IconRobot className="w-5 h-5 text-blue-500" stroke={1.25} />
            </div>
            <div className="min-w-0 wrap-break-word bg-[var(--bgSoft)] border border-gray-200 dark:border-gray-700 rounded-2xl rounded-tl-none p-3 shadow-sm">
              {streamingText ? (
                // Live "typing" preview — confirmed-clean tokens streamed from
                // the agent. Replaced by the committed message on task_complete.
                <div className="agent-message-md max-w-none">
                  <ReactMarkdown components={mdComponents}>
                    {streamingText}
                  </ReactMarkdown>
                  <span
                    className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-pulse bg-[var(--text)] align-middle"
                    aria-hidden
                  />
                </div>
              ) : (
                <Spinner aria-label="Agent is thinking..." />
              )}
            </div>
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
};
