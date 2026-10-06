import React from "react";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { AuthProvider, useAuth } from "@/components/auth/auth-provider";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { NavbarMinimal } from "@/components/ui/mantine/navbar/navbar-minimal";
import { authApi } from "@/lib/auth/api";
import { userApi } from "@/lib/users/api";
import type { User } from "@/lib/types";

const routerPush = vi.fn();
const routerReplace = vi.fn();
const locationReplace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ push: routerPush, replace: routerReplace }),
}));

vi.mock("@/lib/auth/api", () => ({
  authApi: {
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  },
}));

vi.mock("@/lib/users/api", () => ({
  userApi: {
    getCurrentUser: vi.fn(),
  },
}));

const signedInUser: User = {
  id: 1,
  username: "tester",
  role: "user",
};

const AuthStatusProbe = () => {
  const { status } = useAuth();
  return <output data-testid="auth-status">{status}</output>;
};

const renderProtectedPageWithNavbar = () =>
  render(
    <MantineProvider>
      <AuthProvider>
        <AuthStatusProbe />
        <ProtectedRoute>
          <NavbarMinimal />
          <p>Logged-in dashboard</p>
        </ProtectedRoute>
      </AuthProvider>
    </MantineProvider>
  );

const showPage = (persisted: boolean) =>
  act(async () => {
    window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted }));
  });

const logOutFromNavbar = async () => {
  fireEvent.click(screen.getByRole("button", { name: "Logout" }));
  await waitFor(() =>
    expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated")
  );
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("location", { ...window.location, replace: locationReplace });
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
  );
  vi.mocked(authApi.logout).mockResolvedValue(undefined);
  vi.mocked(userApi.getCurrentUser).mockResolvedValue(signedInUser);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// Regression F7 (B-50).
// What: after logout, Back showed the logged-in view again: the navbar logged out
// without telling the auth context, and the login redirect kept the protected page
// in the history.
// How: log out from the navbar, then check the auth context, that the history entry
// is replaced by the login page and that a logged-out visit is redirected with replace.
// When: found in ATP v7 (18/09/2026), fixed in 905cedb.
describe("regression F7 navbar logout", () => {
  it("marks the auth context unauthenticated and replaces the history entry with the login page", async () => {
    renderProtectedPageWithNavbar();
    expect(await screen.findByText("Logged-in dashboard")).toBeInTheDocument();

    await logOutFromNavbar();

    expect(authApi.logout).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/auth/login"));
    expect(routerPush).not.toHaveBeenCalled();
    expect(screen.queryByText("Logged-in dashboard")).not.toBeInTheDocument();
  });

  it("leaves the protected page out of the history when redirecting a logged-out user", async () => {
    renderProtectedPageWithNavbar();
    await screen.findByText("Logged-in dashboard");

    await logOutFromNavbar();

    await waitFor(() => expect(locationReplace).toHaveBeenCalledWith("/auth/login"));
    expect(window.location.href).not.toBe("/auth/login");
  });
});

// Regression F7 (B-50), back-forward cache.
// What: a protected page that the browser restored from its back-forward cache after
// logout still showed the logged-in view.
// How: fire pageshow with and without persisted set, and check that a restored page
// checks the session again and redirects only once logged out.
// When: found in ATP v7 (18/09/2026), fixed in 905cedb.
describe("regression F7 back-forward cache restore", () => {
  it("re-checks the session when the page is restored and redirects once logged out", async () => {
    renderProtectedPageWithNavbar();
    await screen.findByText("Logged-in dashboard");
    vi.mocked(userApi.getCurrentUser).mockResolvedValue(null);

    await showPage(true);

    await waitFor(() =>
      expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated")
    );
    expect(userApi.getCurrentUser).toHaveBeenCalledTimes(2);
    expect(locationReplace).toHaveBeenCalledWith("/auth/login");
    expect(screen.queryByText("Logged-in dashboard")).not.toBeInTheDocument();
  });

  it("redirects again when a page restored after logout was already unauthenticated", async () => {
    renderProtectedPageWithNavbar();
    await screen.findByText("Logged-in dashboard");
    vi.mocked(userApi.getCurrentUser).mockResolvedValue(null);
    await logOutFromNavbar();
    await waitFor(() => expect(locationReplace).toHaveBeenCalledTimes(1));

    await showPage(true);

    await waitFor(() => expect(locationReplace).toHaveBeenCalledTimes(2));
    expect(locationReplace).toHaveBeenLastCalledWith("/auth/login");
  });

  it("keeps the logged-in view when the restored page still has a valid session", async () => {
    renderProtectedPageWithNavbar();
    await screen.findByText("Logged-in dashboard");

    await showPage(true);

    expect(await screen.findByText("Logged-in dashboard")).toBeInTheDocument();
    expect(userApi.getCurrentUser).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("auth-status")).toHaveTextContent(/^authenticated$/);
    expect(locationReplace).not.toHaveBeenCalled();
  });

  it("does not re-check the session on a regular page load", async () => {
    renderProtectedPageWithNavbar();
    await screen.findByText("Logged-in dashboard");

    await showPage(false);

    expect(userApi.getCurrentUser).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Logged-in dashboard")).toBeInTheDocument();
  });
});
