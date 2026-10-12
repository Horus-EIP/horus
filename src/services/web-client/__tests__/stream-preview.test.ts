import { describe, it, expect } from "vitest";
import {
  appendStreamChunk,
  dropStreamPreview,
  type StreamPreviews,
} from "@/lib/chat/stream-preview";

describe("appendStreamChunk", () => {
  it("appends the chunks of one task in the order they arrive", () => {
    let previews: StreamPreviews = {};
    for (const chunk of ["The Q4 ", "revenue was ", "$4.2M."]) {
      previews = appendStreamChunk(previews, "task-1", "task-1", chunk);
    }
    expect(previews["task-1"].text).toBe("The Q4 revenue was $4.2M.");
  });

  it("starts over when the next specialist of a chain streams", () => {
    let previews = appendStreamChunk({}, "root", "step-1", "Research notes.");
    previews = appendStreamChunk(previews, "root", "step-2", "Final ");
    previews = appendStreamChunk(previews, "root", "step-2", "draft");
    expect(previews.root).toEqual({ subtaskId: "step-2", text: "Final draft" });
  });

  it("keeps the preview of another task apart", () => {
    let previews = appendStreamChunk({}, "task-1", "task-1", "one");
    previews = appendStreamChunk(previews, "task-2", "task-2", "two");
    expect(previews["task-1"].text).toBe("one");
    expect(previews["task-2"].text).toBe("two");
  });

  it("starts over when the same task streams a new answer from its first chunk", () => {
    let previews = appendStreamChunk({}, "task-1", "task-1", "The documents ", 0);
    previews = appendStreamChunk(previews, "task-1", "task-1", "do not say.", 1);
    previews = appendStreamChunk(previews, "task-1", "task-1", "Revenue was ", 0);
    previews = appendStreamChunk(previews, "task-1", "task-1", "$4.2M.", 1);
    expect(previews["task-1"].text).toBe("Revenue was $4.2M.");
  });

  it("drops the preview of one task only", () => {
    let previews = appendStreamChunk({}, "task-1", "task-1", "one");
    previews = appendStreamChunk(previews, "task-2", "task-2", "two");

    const dropped = dropStreamPreview(previews, "task-1");

    expect(dropped).toEqual({ "task-2": { subtaskId: "task-2", text: "two" } });
    expect(dropStreamPreview(dropped, "task-1")).toBe(dropped);
  });

  it("returns a new object so React sees the change", () => {
    const before = appendStreamChunk({}, "task-1", "task-1", "a");
    const after = appendStreamChunk(before, "task-1", "task-1", "b");
    expect(after).not.toBe(before);
    expect(before["task-1"].text).toBe("a");
  });
});
