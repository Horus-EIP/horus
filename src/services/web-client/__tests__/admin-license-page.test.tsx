import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import AdminLicensePage from "@/app/(protected)/admin/license/page";
import { userApi } from "@/lib/users/api";

vi.mock("@/lib/users/api", () => ({
  userApi: {
    getLicenseInfo: vi.fn(),
    uploadLicense: vi.fn(),
  },
}));

describe("AdminLicensePage", () => {
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
  });

  it("shows installation identity and verified license details", async () => {
    vi.mocked(userApi.getLicenseInfo).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        site_id: "site-123",
        state: "valid",
        reason: null,
        license: {
          license_id: "license-123",
          license_type: "commercial",
          customer_id: "customer-123",
          customer_name: "Example Customer",
          site_ids: ["site-123"],
          tier: "team",
          user_cap: 100,
          issued_at: "2026-10-24T12:00:00Z",
          valid_from: "2026-01-01",
          valid_until: "2026-12-31",
          grace_days: 15,
          features: ["core"],
        },
      },
    });

    render(
      <MantineProvider>
        <AdminLicensePage />
      </MantineProvider>
    );

    expect(await screen.findByText("Installation site ID: site-123")).toBeTruthy();
    expect(screen.getByText("Verified license details")).toBeTruthy();
    expect(screen.getByText("Example Customer")).toBeTruthy();
    expect(screen.getByText("license-123")).toBeTruthy();
    expect(screen.getByText("team")).toBeTruthy();
    expect(screen.getByText("2026-12-31")).toBeTruthy();
    expect(screen.getByText("100")).toBeTruthy();
  });

  it("does not show a claims summary when no verified license is present", async () => {
    vi.mocked(userApi.getLicenseInfo).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        site_id: "site-123",
        state: "missing",
        reason: null,
        license: null,
      },
    });

    render(
      <MantineProvider>
        <AdminLicensePage />
      </MantineProvider>
    );

    expect(await screen.findByText("Installation site ID: site-123")).toBeTruthy();
    expect(screen.queryByText("Verified license details")).toBeNull();
    expect(
      screen.getByText("No verified license claims are currently available.")
    ).toBeTruthy();
  });
});
