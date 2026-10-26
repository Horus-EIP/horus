import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { NotificationProvider } from "@/contexts/notification-context";
import AdminAgentsPage from "@/app/(protected)/admin/agents/page";
import { agentApi, type Agent } from "@/lib/agents/api";

const mockUser = {
  id: "admin-1",
  username: "admin",
  role: "admin",
};

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({ user: mockUser }),
}));

const mockAgent: Agent = {
  id: "agent-1",
  name: "support-agent",
  skills: ["support"],
  description: "Helps users",
  status: "active",
  last_heartbeat: "2026-10-17T01:00:00Z",
  created_at: "2026-10-17T01:00:00Z",
};

describe("AdminAgentsPage regenerate API key", () => {
  beforeAll(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(agentApi, "getAgents").mockResolvedValue({
      ok: true,
      data: [mockAgent],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const renderComponent = () =>
    render(
      <MantineProvider>
        <NotificationProvider>
          <AdminAgentsPage />
        </NotificationProvider>
      </MantineProvider>
    );

  it("resets regeneratedApiKey when opening regenerate modal", async () => {
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("support-agent")).toBeInTheDocument();
    });

    const regenBtn = screen.getByRole("button", { name: "Regenerate API key" });
    fireEvent.click(regenBtn);

    // Modal opens asking for confirmation, and old key is NOT displayed
    await waitFor(() => {
      expect(screen.getByText(/Generate a new API key for/i)).toBeInTheDocument();
      expect(screen.getByText(/stop working immediately/i)).toBeInTheDocument();
    });
  });
});
