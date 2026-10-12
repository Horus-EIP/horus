"use client";

import { useCallback, useEffect, useRef } from "react";
import { chatApi, type TaskDetails, type TaskSummary } from "@/lib/chat/api";
import { fetchMissedTaskFrames, type TaskFrame } from "@/lib/chat/task-events";

export type TaskResync = {
  runningTasks: TaskSummary[];
  openTask: TaskDetails | null;
  missedFrames: TaskFrame[];
};

type UseTaskResyncOptions = {
  conversationId: string | null;
  openTaskId: string | null;
  sinceFor?: (taskId: string) => number;
  onResync: (resync: TaskResync) => void;
};

const fromTheStart = () => 0;

export async function fetchTaskResync(
  conversationId: string,
  openTaskId: string | null,
  sinceFor: (taskId: string) => number = fromTheStart
): Promise<TaskResync> {
  const [running, openTask, missedFrames] = await Promise.all([
    chatApi.getRunningTasksForConversation(conversationId),
    openTaskId ? chatApi.getTask(openTaskId) : Promise.resolve(null),
    openTaskId ? fetchMissedTaskFrames(openTaskId, sinceFor(openTaskId)) : Promise.resolve([]),
  ]);
  return {
    runningTasks: running.ok && running.data ? running.data : [],
    openTask: openTask?.ok && openTask.data ? openTask.data : null,
    missedFrames,
  };
}

export function useTaskResync(options: UseTaskResyncOptions): () => Promise<void> {
  const latestRef = useRef(options);

  useEffect(() => {
    latestRef.current = options;
  });

  return useCallback(async () => {
    const { conversationId, openTaskId, sinceFor } = latestRef.current;
    if (!conversationId) return;

    const resync = await fetchTaskResync(conversationId, openTaskId, sinceFor);

    const current = latestRef.current;
    if (current.conversationId !== conversationId || current.openTaskId !== openTaskId) {
      return;
    }
    current.onResync(resync);
  }, []);
}
