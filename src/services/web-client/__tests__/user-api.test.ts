import { vi, describe, it, expect, beforeEach } from "vitest";
import { userApi } from "@/lib/users/api";
import { apiClient } from "@/lib/api-client";
import type { User } from "@/lib/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("userApi", () => {
  const mockUser: User = {
    id: 1,
    username: "testuser",
    role: "user",
  };

  const mockUserAdmin: User[] = [
    {
        id: 1,
        username: "user1",
        role: "user",
    },
    {
        id: 2,
        username: "admin",
        role: "admin",
    }
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("getCurrentUser returns mapped user when /users/me succeeds", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: mockUser,
    });

    const result = await userApi.getCurrentUser();

    expect(apiClient.get).toHaveBeenCalledWith("/users/me", { retry: 1 });
    expect(result).toEqual(mockUser);
  });

  it("getCurrentUser returns null when backend returns error", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      ok: false,
      status: 401,
      error: "Authentication Failed",
    });

    const result = await userApi.getCurrentUser();

    expect(apiClient.get).toHaveBeenCalledWith("/users/me", { retry: 1 });
    expect(result).toBeNull();
  });

  it("getCurrentUser returns null when response has no data", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: undefined,
    });

    const result = await userApi.getCurrentUser();

    expect(result).toBeNull();
  });

  it("listUsers returns mapped users when /users/users_list succeeds", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: mockUserAdmin,
    });

    const result = await userApi.listUsers();

    expect(apiClient.get).toHaveBeenCalledWith("/users/users_list", {
      retry: 1,
    });
    expect(result).toEqual(mockUserAdmin);
  });

  it("listUsers returns empty array when backend returns error", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      ok: false,
      status: 403,
      error: "Forbidden",
    });

    const result = await userApi.listUsers();

    expect(apiClient.get).toHaveBeenCalledWith("/users/users_list", {
      retry: 1,
    });
    expect(result).toEqual([]);
  });

  it("getUserDetails returns mapped user when request succeeds", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { id: 42, username: "detailUser", role: "user" },
    });

    const result = await userApi.getUserDetails(42);

    expect(apiClient.get).toHaveBeenCalledWith("/users/user_details/42", {
      retry: 1,
    });
    expect(result).toEqual({
      id: 42,
      username: "detailUser",
      role: "user",
    });
  });

  it("getUserDetails returns null when backend returns error", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      ok: false,
      status: 404,
      error: "User not found",
    });

    const result = await userApi.getUserDetails(42);

    expect(apiClient.get).toHaveBeenCalledWith("/users/user_details/42", {
      retry: 1,
    });
    expect(result).toBeNull();
  });

  it("updateRole returns true when backend returns ok", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { message: "Operation successfully happened" },
    });

    const result = await userApi.updateRole({
      username: "user1",
      newRole: "admin",
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      "/users/update_role",
      {
        user_id: "user1",
        new_role: "admin",
      }
    );
    expect(result).toBe(true);
  });

  it("updateRole returns false when backend returns error", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: false,
      status: 403,
      error: "User already has role",
    });

    const result = await userApi.updateRole({
      username: "user1",
      newRole: "admin",
    });

    expect(result).toBe(false);
  });

  it("deleteUser returns true when backend returns ok", async () => {
    vi.mocked(apiClient.delete).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { message: "User successfully deleted", username: "user1" },
    });

    const result = await userApi.deleteUser(5);

    expect(apiClient.delete).toHaveBeenCalledWith("/users/5");
    expect(result).toBe(true);
  });

  it("deleteUser returns false when backend returns error", async () => {
    vi.mocked(apiClient.delete).mockResolvedValueOnce({
      ok: false,
      status: 404,
      error: "User not found",
    });

    const result = await userApi.deleteUser(5);

    expect(apiClient.delete).toHaveBeenCalledWith("/users/5");
    expect(result).toBe(false);
  });

  it("changePassword returns true when backend returns ok", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { message: "Password successfully changed" },
    });

    const result = await userApi.changePassword({
      oldPassword: "oldpass",
      newPassword: "newPass123!",
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      "/users/me/password_modification",
      {
        old_password: "oldpass",
        new_password: "newPass123!",
      }
    );
    expect(result).toBe(true);
  });

  it("changePassword returns false when backend returns error", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: false,
      status: 400,
      error: "Failed to change password",
    });

    const result = await userApi.changePassword({
      oldPassword: "oldpass",
      newPassword: "newPass123!",
    });

    expect(result).toBe(false);
  });

  it("changeUsername returns true when backend returns ok", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { message: "Username successfully changed" },
    });

    const result = await userApi.changeUsername("new user");

    expect(apiClient.post).toHaveBeenCalledWith(
      "/users/me/username_modification/new%20user"
    );
    expect(result).toBe(true);
  });

  it("changeUsername returns false when backend returns error", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: false,
      status: 400,
      error: "Failed to change username",
    });

    const result = await userApi.changeUsername("bad user");

    expect(result).toBe(false);
  });
});
