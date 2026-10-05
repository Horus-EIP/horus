import { chatApi } from "@/lib/chat/api";
import type { AgentAnswer } from "@/lib/chat/agent-answer";
import type { TaskEvent, TaskStepEvent } from "@/lib/types";

export type TaskFrame = Record<string, unknown>;

export type TaskProgress = {
  taskId: string;
  status?: string;
  stage?: string;
  detail?: string;
  elapsedS?: number;
  position?: number;
};

export type TaskFrameHandlers = {
  onStep: (step: TaskStepEvent) => void;
  onStreamChunk: (taskId: string, subtaskId: string, chunk: string) => void;
  onAnswer: (answer: AgentAnswer, endsTurn: boolean) => void;
  onProgress: (progress: TaskProgress) => void;
};

const TERMINAL_EVENTS = new Set(["result", "error"]);
const PROGRESS_FRAME_TYPES = new Set(["task_status", "heartbeat"]);
const MAX_REPLAY_PAGES = 20;
const BUSY_STATUS = "busy";
const FAILED_STATUS = "failed";

const STAGE_LABELS: Record<string, string> = {
  queued: "Queued, waiting for the orchestrator",
  routing: "Choosing the right agents",
  retrieval: "Searching the documents",
  generation: "Writing the answer",
  aggregation: "Combining the answers",
};

const KNOWN_STATUSES = new Set(["queued", "routing", "running", "aggregating"]);

function textOf(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function metadataOf(frame: TaskFrame): Record<string, unknown> {
  return frame.metadata && typeof frame.metadata === "object"
    ? (frame.metadata as Record<string, unknown>)
    : {};
}

export function taskIdOf(frame: TaskFrame): string {
  return textOf(frame.task_id) ?? "";
}

export function isTerminalFrame(frame: TaskFrame): boolean {
  return typeof frame.event === "string" && TERMINAL_EVENTS.has(frame.event);
}

export function frameFromTaskEvent(event: TaskEvent): TaskFrame {
  return {
    ...event.data,
    task_id: event.task_id,
    seq: event.seq,
    event: event.type,
    stage: event.stage,
    ts: event.ts,
  };
}

export class TaskEventLog {
  private readonly seen = new Map<string, Set<number>>();
  private readonly finished = new Set<string>();

  accept(frame: TaskFrame): boolean {
    const taskId = taskIdOf(frame);
    if (taskId && typeof frame.seq === "number") {
      const seen = this.seen.get(taskId) ?? new Set<number>();
      if (seen.has(frame.seq)) return false;
      seen.add(frame.seq);
      this.seen.set(taskId, seen);
    }
    if (taskId && isTerminalFrame(frame)) this.finished.add(taskId);
    return true;
  }

  since(taskId: string): number {
    const seen = this.seen.get(taskId);
    let since = 0;
    while (seen?.has(since + 1)) since += 1;
    return since;
  }

  hasFinished(taskId: string): boolean {
    return this.finished.has(taskId);
  }
}

export async function fetchMissedTaskFrames(taskId: string, since: number): Promise<TaskFrame[]> {
  const frames: TaskFrame[] = [];
  let cursor = since;
  for (let page = 0; page < MAX_REPLAY_PAGES; page += 1) {
    let response: Awaited<ReturnType<typeof chatApi.getTaskEvents>>;
    try {
      response = await chatApi.getTaskEvents(taskId, cursor);
    } catch {
      break;
    }
    if (!response.ok || !response.data) break;
    frames.push(...response.data.events.map(frameFromTaskEvent));
    if (!response.data.has_more || response.data.events.length === 0) break;
    cursor = response.data.last_seq;
  }
  return frames;
}

function stepOf(frame: TaskFrame, taskId: string): TaskStepEvent {
  const detail = textOf(frame.detail);
  return {
    taskId,
    agentId: textOf(frame.agent_id),
    agentName: textOf(frame.agent_name),
    stepType: String(frame.step_type ?? "unknown"),
    title: String(frame.title ?? frame.step_type ?? "Step"),
    detail: detail && detail.length ? detail : undefined,
    timestamp: textOf(frame.timestamp) ?? new Date().toISOString(),
    metadata:
      frame.metadata && typeof frame.metadata === "object"
        ? (frame.metadata as Record<string, unknown>)
        : undefined,
  };
}

function directAnswerStep(taskId: string): TaskStepEvent {
  return {
    taskId,
    stepType: "reasoning.done",
    title: "Orchestrator answered directly",
    detail:
      "MAS's router classified this as a DIRECT_ANSWER and replied " +
      "without dispatching to an agent worker. No retrieval ran, no " +
      "specialist persona was applied.",
    timestamp: new Date().toISOString(),
    metadata: { path: "orchestrator_direct_answer" },
  };
}

function numberOf(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

function answerOf(frame: TaskFrame): AgentAnswer {
  return {
    content: String(frame.content ?? ""),
    timestamp: new Date(String(frame.timestamp ?? frame.ts ?? Date.now())),
    agentId: textOf(frame.agent_id),
    agentName: textOf(frame.agent_name),
    skillUsed: textOf(frame.skill_used),
    messageId: numberOf(frame.message_id),
    failed: frame.event === "error" && frame.status === FAILED_STATUS,
  };
}

function endsTurn(frame: TaskFrame): boolean {
  if (typeof frame.event === "string") return isTerminalFrame(frame);
  return frame.agent_name !== "Manager";
}

export function routeTaskFrame(frame: TaskFrame, handlers: TaskFrameHandlers): void {
  const taskId = taskIdOf(frame);
  if (frame.type === "task_step") {
    if (!taskId) return;
    if (frame.step_type === "reasoning.delta") {
      const chunk = textOf(metadataOf(frame).chunk) ?? "";
      if (chunk) handlers.onStreamChunk(taskId, textOf(frame.subtask_id) ?? taskId, chunk);
      return;
    }
    handlers.onStep(stepOf(frame, taskId));
    return;
  }
  if (frame.type === "task_status" || frame.type === "heartbeat") {
    if (!taskId) return;
    handlers.onProgress({
      taskId,
      status: textOf(frame.status),
      stage: textOf(frame.stage),
      detail: textOf(frame.detail),
      elapsedS: numberOf(frame.elapsed_s),
      position: numberOf(frame.position),
    });
    return;
  }
  if (frame.type === "agent" || frame.type === "task_complete") {
    if (taskId && frame.route === "direct_answer") handlers.onStep(directAnswerStep(taskId));
    handlers.onAnswer(answerOf(frame), endsTurn(frame));
  }
}

export function applyTaskFrame(
  log: TaskEventLog,
  frame: TaskFrame,
  handlers: TaskFrameHandlers
): boolean {
  const taskId = taskIdOf(frame);
  const finishedBefore = taskId !== "" && log.hasFinished(taskId);
  if (!log.accept(frame)) return false;
  if (finishedBefore && PROGRESS_FRAME_TYPES.has(String(frame.type))) return false;
  routeTaskFrame(frame, handlers);
  return true;
}

export function mergeTaskProgress(
  current: TaskProgress | null,
  next: TaskProgress
): TaskProgress {
  if (!current || current.taskId !== next.taskId) return next;
  return {
    taskId: next.taskId,
    status: next.status ?? current.status,
    stage: next.stage ?? current.stage,
    detail: next.status ? next.detail : current.detail,
    elapsedS: next.elapsedS ?? current.elapsedS,
    position: next.status ? next.position : current.position,
  };
}

export function formatElapsed(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return minutes > 0 ? `${minutes}m ${String(rest).padStart(2, "0")}s` : `${rest}s`;
}

export function taskProgressLabel(progress: TaskProgress | null): string | null {
  if (!progress) return null;
  if (progress.status === BUSY_STATUS && progress.position !== undefined) {
    const label = `Busy, position ${progress.position}`;
    return progress.elapsedS !== undefined ? `${label} · ${formatElapsed(progress.elapsedS)}` : label;
  }
  if (progress.status && !KNOWN_STATUSES.has(progress.status) && progress.detail) {
    return progress.detail;
  }
  const stage = progress.stage ?? (progress.status === "queued" ? "queued" : undefined);
  const label = (stage && STAGE_LABELS[stage]) || progress.detail || "Working on your request";
  return progress.elapsedS !== undefined ? `${label} · ${formatElapsed(progress.elapsedS)}` : label;
}
