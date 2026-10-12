import React from "react";
import { vi, describe, it, expect, beforeAll } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { CollaborationView } from "@/components/agents/collaboration-view";
import type { Agent } from "@/lib/agents/api";
import type { Subtask, TaskStatus } from "@/lib/tasks/types";
import { taskStatusByAgentId } from "@/lib/tasks/agent-activity";

function onlineAgent(id: string, name: string): Agent {
  return {
    id,
    name,
    skills: ["financial_analysis"],
    status: "active",
    last_heartbeat: "2026-10-05T09:30:00+00:00",
    description: "Answers finance questions",
    created_at: "2026-10-01T08:00:00+00:00",
  };
}

const manager = onlineAgent("manager", "Manager");
const researcher = onlineAgent("researcher", "Researcher");
const writer = onlineAgent("writer", "Writer");

function subtask(id: string, assignedAgent: string, status: TaskStatus): Subtask {
  return { id, title: `Step ${id}`, status, assignedAgent };
}

function renderView(agents: Agent[], statuses?: Record<string, TaskStatus>) {
  render(
    <MantineProvider>
      <CollaborationView
        title="Collaborating agents"
        agents={agents}
        taskStatusByAgentId={statuses}
      />
    </MantineProvider>
  );
}

function agentCard(name: string): HTMLElement {
  return screen.getByText(name).closest("div.relative") as HTMLElement;
}

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
});

describe("CollaborationView spinner follows the task status", () => {
  it("spins for an agent whose task is running", () => {
    renderView([researcher], { researcher: "running" });

    expect(within(agentCard("Researcher")).getByLabelText("Working")).toBeInTheDocument();
  });

  it("spins for an agent whose task is still pending", () => {
    renderView([researcher], { researcher: "pending" });

    expect(within(agentCard("Researcher")).getByLabelText("Working")).toBeInTheDocument();
  });

  it.each<TaskStatus>(["completed", "failed", "cancelled"])(
    "stops spinning for an online agent once its task is %s",
    (status) => {
      renderView([researcher], { researcher: status });

      expect(screen.queryByLabelText("Working")).not.toBeInTheDocument();
    }
  );

  it("does not spin for an online agent without a task status", () => {
    renderView([researcher]);

    expect(screen.queryByLabelText("Working")).not.toBeInTheDocument();
  });

  it("counts the agents working on the task, not the online ones", () => {
    renderView([researcher, writer], { researcher: "running", writer: "completed" });

    expect(screen.getByText("1 working")).toBeInTheDocument();
    expect(within(agentCard("Writer")).queryByLabelText("Working")).not.toBeInTheDocument();
  });
});

describe("taskStatusByAgentId", () => {
  it("gives a single-agent task's status to its agent", () => {
    expect(
      taskStatusByAgentId({ agentId: "researcher", status: "running", subtasks: [] })
    ).toEqual({ researcher: "running" });
  });

  it("marks only the agents with an unfinished step as working in a running chain", () => {
    const statuses = taskStatusByAgentId({
      agentId: "manager",
      status: "running",
      subtasks: [
        subtask("1", "researcher", "completed"),
        subtask("2", "writer", "running"),
      ],
    });

    expect(statuses).toEqual({ manager: "running", researcher: "completed", writer: "running" });
  });

  it("keeps an agent working while one of its steps is unfinished", () => {
    const statuses = taskStatusByAgentId({
      agentId: "manager",
      status: "running",
      subtasks: [
        subtask("1", "researcher", "running"),
        subtask("2", "researcher", "completed"),
      ],
    });

    expect(statuses.researcher).toBe("running");
  });

  it("stops every agent once the chain is finished, even with a stale step", () => {
    const statuses = taskStatusByAgentId({
      agentId: "manager",
      status: "completed",
      subtasks: [
        subtask("1", "researcher", "completed"),
        subtask("2", "writer", "running"),
      ],
    });

    expect(statuses).toEqual({
      manager: "completed",
      researcher: "completed",
      writer: "completed",
    });
  });

  it("drives the view so a finished chain shows no spinner", () => {
    renderView(
      [manager, researcher],
      taskStatusByAgentId({
        agentId: "manager",
        status: "cancelled",
        subtasks: [subtask("1", "researcher", "running")],
      })
    );

    expect(screen.queryByLabelText("Working")).not.toBeInTheDocument();
    expect(screen.getByText("0 working")).toBeInTheDocument();
  });
});
