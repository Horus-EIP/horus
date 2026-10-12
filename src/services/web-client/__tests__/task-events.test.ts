import { vi, describe, it, expect, beforeEach } from "vitest";
import type { TaskEvent } from "@/lib/types";

const { chatApiMock } = vi.hoisted(() => ({
  chatApiMock: { getTaskEvents: vi.fn() },
}));

vi.mock("@/lib/chat/api", () => ({ chatApi: chatApiMock }));

import {
  TaskEventLog,
  applyTaskFrame,
  fetchMissedTaskFrames,
  frameFromTaskEvent,
  mergeTaskProgress,
  routeTaskFrame,
  taskProgressLabel,
  type TaskFrame,
  type TaskFrameHandlers,
} from "@/lib/chat/task-events";

function handlers(): TaskFrameHandlers & { [K in keyof TaskFrameHandlers]: ReturnType<typeof vi.fn> } {
  return {
    onStep: vi.fn(),
    onStreamChunk: vi.fn(),
    onAnswer: vi.fn(),
    onProgress: vi.fn(),
  };
}

function event(seq: number, type: TaskEvent["type"], data: Record<string, unknown>): TaskEvent {
  return { task_id: "root-7", seq, type, stage: "generation", data, ts: "2026-10-05T09:30:12Z" };
}

const STEP = event(1, "progress", {
  type: "task_step",
  step_type: "retrieval.start",
  title: "Searching",
  task_id: "root-7",
});
const TOKEN = event(2, "token", {
  type: "task_step",
  step_type: "reasoning.delta",
  subtask_id: "sub-1",
  metadata: { chunk: "Revenue " },
});
const RESULT = event(3, "result", {
  type: "task_complete",
  content: "Revenue grew 12%.",
  agent_name: "Finance-Analyst",
  timestamp: "2026-10-05T09:33:00",
  message_id: 77,
  route: "agent",
});

describe("TaskEventLog", () => {
  it("accepts each seq of a task once", () => {
    const log = new TaskEventLog();

    expect(log.accept({ task_id: "root-7", seq: 1 })).toBe(true);
    expect(log.accept({ task_id: "root-7", seq: 1 })).toBe(false);
    expect(log.accept({ task_id: "root-8", seq: 1 })).toBe(true);
  });

  it("always accepts frames without a seq", () => {
    const log = new TaskEventLog();

    expect(log.accept({ type: "agent", content: "Hello" })).toBe(true);
    expect(log.accept({ type: "agent", content: "Hello" })).toBe(true);
  });

  it("asks for events after the last unbroken seq", () => {
    const log = new TaskEventLog();
    [1, 2, 4, 5].forEach((seq) => log.accept({ task_id: "root-7", seq }));

    expect(log.since("root-7")).toBe(2);
    expect(log.since("unknown")).toBe(0);
  });

  it("remembers which tasks have ended", () => {
    const log = new TaskEventLog();
    log.accept({ task_id: "root-7", seq: 1, event: "progress" });
    expect(log.hasFinished("root-7")).toBe(false);

    log.accept({ task_id: "root-7", seq: 2, event: "error" });

    expect(log.hasFinished("root-7")).toBe(true);
  });
});

describe("replaying task events", () => {
  it("replays stored events through the same handler as live frames", () => {
    const log = new TaskEventLog();
    const live = handlers();

    [STEP, TOKEN, RESULT].map(frameFromTaskEvent).forEach((frame) => applyTaskFrame(log, frame, live));

    expect(live.onStep).toHaveBeenCalledWith(
      expect.objectContaining({ taskId: "root-7", stepType: "retrieval.start", title: "Searching" })
    );
    expect(live.onStreamChunk).toHaveBeenCalledWith("root-7", "sub-1", "Revenue ", undefined);
    expect(live.onAnswer).toHaveBeenCalledWith(
      expect.objectContaining({
        content: "Revenue grew 12%.",
        agentName: "Finance-Analyst",
        messageId: 77,
      }),
      true
    );
  });

  it("drops replayed events the socket already delivered", () => {
    const log = new TaskEventLog();
    const sink = handlers();
    const liveResult: TaskFrame = { ...RESULT.data, task_id: "root-7", seq: 3, event: "result" };
    applyTaskFrame(log, liveResult, sink);

    [STEP, TOKEN, RESULT].map(frameFromTaskEvent).forEach((frame) => applyTaskFrame(log, frame, sink));

    expect(sink.onAnswer).toHaveBeenCalledTimes(1);
    expect(sink.onStep).toHaveBeenCalledTimes(1);
    expect(sink.onStreamChunk).toHaveBeenCalledTimes(1);
    expect(log.since("root-7")).toBe(3);
  });

  it("ignores progress that arrives after the task ended", () => {
    const log = new TaskEventLog();
    const sink = handlers();
    applyTaskFrame(log, frameFromTaskEvent(RESULT), sink);

    const applied = applyTaskFrame(
      log,
      { type: "heartbeat", task_id: "root-7", seq: 4, event: "heartbeat", elapsed_s: 185 },
      sink
    );

    expect(applied).toBe(false);
    expect(sink.onProgress).not.toHaveBeenCalled();
  });

  it("fetches every page of missed events", async () => {
    chatApiMock.getTaskEvents
      .mockResolvedValueOnce({
        ok: true,
        data: { task_id: "root-7", status: "running", since: 0, events: [STEP, TOKEN], last_seq: 2, has_more: true },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { task_id: "root-7", status: "completed", since: 2, events: [RESULT], last_seq: 3, has_more: false },
      });

    const frames = await fetchMissedTaskFrames("root-7", 0);

    expect(chatApiMock.getTaskEvents.mock.calls).toEqual([
      ["root-7", 0],
      ["root-7", 2],
    ]);
    expect(frames.map((frame) => frame.seq)).toEqual([1, 2, 3]);
    expect(frames[2]).toMatchObject({ type: "task_complete", event: "result", task_id: "root-7" });
  });

  it("replays nothing when the event store cannot be read", async () => {
    chatApiMock.getTaskEvents.mockReset();
    chatApiMock.getTaskEvents.mockResolvedValue({ ok: false, error: "The task event store is unavailable" });

    expect(await fetchMissedTaskFrames("root-7", 4)).toEqual([]);
  });
});

describe("routing task frames", () => {
  beforeEach(() => {
    chatApiMock.getTaskEvents.mockReset();
  });

  it("does not end the turn on a Manager progress message", () => {
    const sink = handlers();

    routeTaskFrame(
      { type: "task_complete", content: "Routing to Writer", agent_name: "Manager", task_id: "root-7", seq: 5, event: "progress" },
      sink
    );

    expect(sink.onAnswer).toHaveBeenCalledWith(expect.anything(), false);
  });

  it("ends the turn on a failure with its message", () => {
    const sink = handlers();

    routeTaskFrame(
      {
        type: "agent",
        content: "This request was cancelled before it finished.",
        status: "cancelled",
        task_id: "root-7",
        seq: 6,
        event: "error",
      },
      sink
    );

    expect(sink.onAnswer).toHaveBeenCalledWith(
      expect.objectContaining({ content: "This request was cancelled before it finished." }),
      true
    );
  });

  it("keeps the legacy rule for frames without an event type", () => {
    const sink = handlers();

    routeTaskFrame({ type: "task_complete", content: "Plan", agent_name: "Manager" }, sink);
    routeTaskFrame({ type: "agent", content: "Hello!" }, sink);

    expect(sink.onAnswer.mock.calls.map((call) => call[1])).toEqual([false, true]);
  });

  it("explains a direct answer in the thought-process card", () => {
    const sink = handlers();

    routeTaskFrame(
      { type: "agent", content: "4", route: "direct_answer", task_id: "root-7", seq: 3, event: "result" },
      sink
    );

    expect(sink.onStep).toHaveBeenCalledWith(
      expect.objectContaining({ taskId: "root-7", title: "Orchestrator answered directly" })
    );
  });

  it("reports queue, stage and heartbeat progress", () => {
    const sink = handlers();

    routeTaskFrame({ type: "task_status", status: "queued", stage: "queued", task_id: "root-7", seq: 1 }, sink);
    routeTaskFrame({ type: "heartbeat", stage: "retrieval", elapsed_s: 65, task_id: "root-7", seq: 4 }, sink);

    expect(sink.onProgress.mock.calls.map((call) => call[0])).toEqual([
      { taskId: "root-7", status: "queued", stage: "queued", detail: undefined, elapsedS: undefined },
      { taskId: "root-7", status: undefined, stage: "retrieval", detail: undefined, elapsedS: 65 },
    ]);
  });
});

describe("answer contract frames", () => {
  const source = { doc_id: "doc-q4", chunk_id: "doc-q4:3", title: "q4.md", page: 2 };

  it("passes the sources of the final answer on", () => {
    const sink = handlers();

    routeTaskFrame(
      { ...RESULT.data, sources: [source, "not a source"], task_id: "root-7", seq: 3, event: "result" },
      sink
    );

    expect(sink.onAnswer).toHaveBeenCalledWith(
      expect.objectContaining({ content: "Revenue grew 12%.", sources: [source] }),
      true
    );
  });

  it("leaves the sources out when the agent sent none", () => {
    const sink = handlers();

    routeTaskFrame({ ...RESULT.data, task_id: "root-7", seq: 3, event: "result" }, sink);

    expect(sink.onAnswer.mock.calls[0][0].sources).toBeUndefined();
  });

  it("passes the index of each streamed chunk on", () => {
    const sink = handlers();

    routeTaskFrame(
      {
        type: "task_step",
        step_type: "reasoning.delta",
        task_id: "root-7",
        subtask_id: "sub-1",
        metadata: { chunk: "Revenue ", index: 0 },
      },
      sink
    );

    expect(sink.onStreamChunk).toHaveBeenCalledWith("root-7", "sub-1", "Revenue ", 0);
  });

  it("explains a second attempt in the progress line", () => {
    const sink = handlers();

    routeTaskFrame(
      {
        type: "task_status",
        status: "retrying",
        detail: "The documents found did not answer it; searching again with another query.",
        attempt: 2,
        task_id: "root-7",
        stage: "retrieval",
      },
      sink
    );

    const progress = sink.onProgress.mock.calls[0][0];
    expect(progress.status).toBe("retrying");
    expect(taskProgressLabel(progress)).toBe(
      "The documents found did not answer it; searching again with another query."
    );
  });
});

describe("task progress label", () => {
  it("describes the stage and the time spent", () => {
    const queued = mergeTaskProgress(null, { taskId: "root-7", status: "queued", stage: "queued" });
    const working = mergeTaskProgress(
      mergeTaskProgress(queued, { taskId: "root-7", status: "running", stage: "retrieval" }),
      { taskId: "root-7", stage: "generation", elapsedS: 65 }
    );

    expect(taskProgressLabel(queued)).toBe("Queued, waiting for the orchestrator");
    expect(taskProgressLabel(working)).toBe("Writing the answer · 1m 05s");
    expect(taskProgressLabel(null)).toBeNull();
  });

  it("shows the server's own words for a status it does not know", () => {
    expect(
      taskProgressLabel({ taskId: "root-7", status: "busy", detail: "Busy, position 3" })
    ).toBe("Busy, position 3");
  });

  it("shows the place in line of a request that waits for a full queue", () => {
    const busy = mergeTaskProgress(null, {
      taskId: "root-7",
      status: "busy",
      stage: "queued",
      detail: "Busy, position 11",
      position: 11,
    });
    const waiting = mergeTaskProgress(busy, { taskId: "root-7", stage: "queued", elapsedS: 25 });
    const moved = mergeTaskProgress(waiting, {
      taskId: "root-7",
      status: "busy",
      stage: "queued",
      detail: "Busy, position 4",
      position: 4,
    });
    const running = mergeTaskProgress(moved, {
      taskId: "root-7",
      status: "running",
      stage: "retrieval",
    });

    expect(taskProgressLabel(busy)).toBe("Busy, position 11");
    expect(taskProgressLabel(waiting)).toBe("Busy, position 11 · 25s");
    expect(taskProgressLabel(moved)).toBe("Busy, position 4 · 25s");
    expect(running.position).toBeUndefined();
    expect(taskProgressLabel(running)).toBe("Searching the documents · 25s");
  });
});

describe("failed and busy frames", () => {
  it("passes the place in line of a busy status on", () => {
    const sink = handlers();

    routeTaskFrame(
      {
        type: "task_status",
        status: "busy",
        stage: "queued",
        detail: "Busy, position 11",
        position: 11,
        task_id: "root-7",
        seq: 2,
        event: "progress",
      },
      sink
    );

    expect(sink.onProgress).toHaveBeenCalledWith(
      expect.objectContaining({ taskId: "root-7", status: "busy", position: 11 })
    );
  });

  it("marks the answer of a failed task as failed and ends the turn", () => {
    const sink = handlers();

    routeTaskFrame(
      {
        type: "task_complete",
        content: "The model did not finish its answer within 900s.",
        agent_name: "General-Assistant",
        status: "failed",
        reason: "timeout",
        task_id: "root-7",
        seq: 9,
        event: "error",
      },
      sink
    );

    expect(sink.onAnswer).toHaveBeenCalledWith(expect.objectContaining({ failed: true }), true);
  });

  it("does not mark a cancelled task as failed", () => {
    const sink = handlers();

    routeTaskFrame(
      {
        type: "agent",
        content: "This request was cancelled before it finished.",
        status: "cancelled",
        task_id: "root-7",
        seq: 6,
        event: "error",
      },
      sink
    );

    expect(sink.onAnswer).toHaveBeenCalledWith(expect.objectContaining({ failed: false }), true);
  });
});
