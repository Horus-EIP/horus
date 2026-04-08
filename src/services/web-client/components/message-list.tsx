'use client';

import React from "react";
import { Skeleton } from '@mantine/core';
import {
  IconExclamationCircle,
  IconRobot,
  IconUser,
} from '@tabler/icons-react';
import { Spinner } from "@/components/ui/spinner";
import { formatTimestamp } from "@/utils/format";

export interface Message {
  id: string;
  text: string;
  sender: "user" | "agent";
  timestamp: Date;
  status?: "sending" | "sent" | "error";
}

interface MessageListProps {
  messages: Message[];
  isHistoryLoading: boolean;
  isLoading: boolean;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
}

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
}) => {
  return (
    <div className="mx-auto max-w-[75vw] md:max-w-[60vw] space-y-4">
      {isHistoryLoading && messages.length === 0 && <ChatHistorySkeleton />}

      {!isHistoryLoading && messages.length === 0 && (
        <div className="text-center text-gray-500 mt-8 flex flex-col items-center justify-center h-full">
          <IconRobot className="w-12 h-12 mb-4 text-[var(--textSoft)] opacity-50" stroke={1.25} />
          <p className="text-lg font-medium text-[var(--textSoft)]">
            Start a conversation
          </p>
          <p className="text-sm text-[var(--textSoft)]">
            How can we help you?
          </p>
        </div>
      )}

      {messages.map((message) => (
        <div
          key={message.id}
          className={`flex ${message.sender === "user" ? "justify-end" : "justify-start"
            }`}
        >
          <div
            className={`flex gap-2 max-w-[85%] sm:max-w-[75%]
              ${message.sender === "user"
                ? "flex-row-reverse"
                : "flex-row"
              }
            `}
          >
            <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-[var(--bgSoft)] text-[var(--text)] border border-gray-200 dark:border-gray-700">
              {message.sender === "user" ? (
                <IconUser className="w-5 h-5" stroke={1.25} />
              ) : (
                <IconRobot className="w-5 h-5 text-blue-500" stroke={1.25} />
              )}
            </div>

            <div
              className={`rounded-2xl px-4 py-2 text-[var(--text)] text-base shadow-sm ${message.sender === "user"
                ? "bg-blue-500 text-white rounded-tr-none"
                : "bg-[var(--bgSoft)] mr-auto rounded-tl-none border border-gray-200 dark:border-gray-700"
                }`}
            >
              <p>{message.text}</p>

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
      ))}

      {isLoading && !isHistoryLoading && (
        <div className="flex justify-start opacity-95 transition-opacity">
          <div className="flex gap-2">
            <div className="w-8 h-8 rounded-full flex items-center justify-center bg-[var(--bgSoft)] border border-gray-200 dark:border-gray-700">
              <IconRobot className="w-5 h-5 text-blue-500" stroke={1.25} />
            </div>
            <div className="bg-[var(--bgSoft)] border border-gray-200 dark:border-gray-700 rounded-2xl rounded-tl-none p-3 shadow-sm">
              <Spinner aria-label="Agent is thinking..." />
            </div>
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
};
