"use client";

import { useCallback, useEffect, useRef } from "react";
import { chatApi, type TaskDetails, type TaskSummary } from "@/lib/chat/api";

export type TaskResync = {
  runningTasks: TaskSummary[];
  openTask: TaskDetails | null;
};

type UseTaskResyncOptions = {
  conversationId: string | null;
  openTaskId: string | null;
  onResync: (resync: TaskResync) => void;
};

export async function fetchTaskResync(
  conversationId: string,
  openTaskId: string | null
): Promise<TaskResync> {
  const [running, openTask] = await Promise.all([
    chatApi.getRunningTasksForConversation(conversationId),
    openTaskId ? chatApi.getTask(openTaskId) : Promise.resolve(null),
  ]);
  return {
    runningTasks: running.ok && running.data ? running.data : [],
    openTask: openTask?.ok && openTask.data ? openTask.data : null,
  };
}

export function useTaskResync(options: UseTaskResyncOptions): () => Promise<void> {
  const latestRef = useRef(options);

  useEffect(() => {
    latestRef.current = options;
  });

  return useCallback(async () => {
    const { conversationId, openTaskId } = latestRef.current;
    if (!conversationId) return;

    const resync = await fetchTaskResync(conversationId, openTaskId);

    const current = latestRef.current;
    if (current.conversationId !== conversationId || current.openTaskId !== openTaskId) {
      return;
    }
    current.onResync(resync);
  }, []);
}
