import { vi, describe, it, expect, beforeEach } from "vitest";
import { authApi } from "@/lib/auth/api";
import { apiClient } from "@/lib/api-client";
import { userApi } from "@/lib/users/api";
import type { User } from "@/lib/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    postForm: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock("@/lib/users/api", () => ({
  userApi: {
    getCurrentUser: vi.fn(),
  },
}));

describe("authApi", () => {
  const mockUser: User = {
    id: 1,
    username: "test@example.com",
    role: "user",
  };

  beforeEach(() => {
    vi.clearAllMocks();

    const localStorageMock: Storage = {
      length: 0,
      clear: vi.fn(),
      getItem: vi.fn(),
      key: vi.fn(),
      removeItem: vi.fn(),
      setItem: vi.fn(),
    };

    Object.defineProperty(window, "localStorage", {
      value: localStorageMock,
      writable: true,
    });
  });

  it("login stores token, calls /auth/token, fetches current user and returns AuthResponse", async () => {
    vi.mocked(apiClient.postForm).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: {
        access_token: "jwt-token-123",
        token_type: "bearer",
      },
    });

    vi.mocked(userApi.getCurrentUser).mockResolvedValueOnce(mockUser);

    const setItemSpy = vi.spyOn(window.localStorage, "setItem");

    const result = await authApi.login({
      username: "test@example.com",
      password: "Password123!",
    });

    expect(apiClient.postForm).toHaveBeenCalledWith(
      "/auth/token",
      {
        username: "test@example.com",
        password: "Password123!",
        grant_type: "password",
      },
      { retry: 1 }
    );

    expect(setItemSpy).toHaveBeenCalledWith("auth_token", "jwt-token-123");
    expect(userApi.getCurrentUser).toHaveBeenCalled();

    expect(result.ok).toBe(true);
    expect(result.user).toEqual(mockUser);
    expect(result.token).toBe("jwt-token-123");
    expect(result.status).toBe(200);
  });

  it("login returns error when backend responds with error", async () => {
    vi.mocked(apiClient.postForm).mockResolvedValueOnce({
      ok: false,
      status: 401,
      error: "Invalid credentials",
    });

    const result = await authApi.login({
      username: "wrong@example.com",
      password: "bad",
    });

    expect(apiClient.postForm).toHaveBeenCalled();
    expect(result.ok).toBe(false);
    expect(result.error).toBe("Invalid credentials");
    expect(result.status).toBe(401);
  });

  it("register calls /auth/register and then login", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: true,
      status: 201,
      data: mockUser,
    });

    const loginSpy = vi
      .spyOn(authApi, "login")
      .mockResolvedValueOnce({
        ok: true,
        user: mockUser,
        token: "jwt-token-123",
        status: 200,
      });

    const result = await authApi.register({
      username: "test@example.com",
      password: "Password123!",
      confirmPassword: "Password123!",
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      "/auth/register",
      {
        username: "test@example.com",
        password: "Password123!",
      },
      { retry: 1 }
    );

    expect(loginSpy).toHaveBeenCalledWith({
      username: "test@example.com",
      password: "Password123!",
    });

    expect(result.ok).toBe(true);
    expect(result.user).toEqual(mockUser);
    expect(result.token).toBe("jwt-token-123");
  });

  it("register returns error when /auth/register fails", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: false,
      status: 409,
      error: "Username already exists",
    });

    const result = await authApi.register({
      username: "test@example.com",
      password: "Password123!",
      confirmPassword: "Password123!",
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      "/auth/register",
      {
        username: "test@example.com",
        password: "Password123!",
      },
      { retry: 1 }
    );

    expect(result.ok).toBe(false);
    expect(result.error).toBe("Username already exists");
    expect(result.status).toBe(409);
  });

  it("logout calls /auth/logout and removes token from localStorage", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: true,
      status: 200,
    });

    const removeItemSpy = vi.spyOn(window.localStorage, "removeItem");

    await authApi.logout();

    expect(apiClient.post).toHaveBeenCalledWith("/auth/logout");
    expect(removeItemSpy).toHaveBeenCalledWith("auth_token");
  });
});
