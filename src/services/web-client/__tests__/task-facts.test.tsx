import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TaskFacts } from "@/components/tasks/task-facts";
import { formatTaskDuration } from "@/lib/tasks/timing";

const CREATED_AT = "2026-10-05T09:30:00.123456+00:00";
const COMPLETED_AT = "2026-10-05T09:32:14.623456+00:00";

describe("TaskFacts", () => {
  it("shows the task's skills, creation and finish times and duration", () => {
    render(
      <TaskFacts
        skills={["financial_analysis", "writing"]}
        createdAt={CREATED_AT}
        completedAt={COMPLETED_AT}
      />
    );

    expect(screen.getByText("financial_analysis")).toBeInTheDocument();
    expect(screen.getByText("writing")).toBeInTheDocument();
    expect(screen.getByText(new Date(CREATED_AT).toLocaleString())).toBeInTheDocument();
    expect(screen.getByText(new Date(COMPLETED_AT).toLocaleString())).toBeInTheDocument();
    expect(screen.getByText("2m 15s")).toBeInTheDocument();
  });

  it("says a running task is not finished yet", () => {
    render(<TaskFacts skills={["analysis"]} createdAt={CREATED_AT} completedAt={null} />);

    expect(screen.getByText("Not finished yet")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("says when no skill was recorded", () => {
    render(<TaskFacts skills={[]} createdAt={CREATED_AT} completedAt={null} />);

    expect(screen.getByText("None recorded")).toBeInTheDocument();
  });
});

describe("formatTaskDuration", () => {
  it.each([
    ["2026-10-05T09:30:00Z", "2026-10-05T09:30:45Z", "45s"],
    ["2026-10-05T09:30:00Z", "2026-10-05T09:44:03Z", "14m 3s"],
    ["2026-10-05T09:30:00Z", "2026-10-05T11:05:00Z", "1h 35m"],
  ])("formats %s to %s as %s", (start, end, expected) => {
    expect(formatTaskDuration(start, end)).toBe(expected);
  });

  it.each([
    [null, "2026-10-05T09:30:45Z"],
    ["2026-10-05T09:30:00Z", null],
    ["2026-10-05T09:30:00Z", "not a date"],
    ["2026-10-05T09:31:00Z", "2026-10-05T09:30:00Z"],
  ])("gives no duration for %s to %s", (start, end) => {
    expect(formatTaskDuration(start, end)).toBeNull();
  });
});
