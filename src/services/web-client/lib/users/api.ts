'use client';

import { apiClient } from "@/lib/api-client";
import { User, UpdatePassword, UpdateRole, UserRole } from "@/lib/types";

export interface CreateUserPayload {
  username: string;
  password: string;
  role?: UserRole;
}

export interface CreateUserResponse {
  id: number;
  username: string;
  role: string;
}

export const userApi = {
  async createUser(payload: CreateUserPayload): Promise<{ ok: boolean; data?: CreateUserResponse; error?: string }> {
    const response = await apiClient.post<CreateUserResponse>(
      "/auth/register",
      {
        username: payload.username,
        password: payload.password,
      },
      { retry: 1 }
    );

    if (!response.ok) {
      return {
        ok: false,
        error: response.error || "Failed to create user",
      };
    }

    // If a role other than default is specified, update it
    if (payload.role && payload.role !== 'user' && response.data) {
      const roleResponse = await apiClient.post<{ message: string }>(
        "/users/update_role",
        {
          user_id: payload.username,
          new_role: payload.role,
        }
      );

      if (!roleResponse.ok) {
        // User created but role update failed
        return {
          ok: true,
          data: response.data,
          error: "User created but role assignment failed",
        };
      }
    }

    return {
      ok: true,
      data: response.data,
    };
  },

  async getCurrentUser(): Promise<User | null> {
    const response = await apiClient.get<User>("/users/me", {
      retry: 1,
    });

    if (!response.ok || !response.data) {
      return null;
    }

    const data = response.data;

    return {
      id: data.id,
      username: data.username,
      role: data.role,
    };
  },

  async listUsers(): Promise<User[]> {
    const response = await apiClient.get<User[]>("/users/users_list", {
      retry: 1,
    });

    if (!response.ok || !response.data) {
      return [];
    }

    return response.data.map((u) => ({
      id: u.id,
      username: u.username,
      role: u.role,
    }));
  },

  async getUserDetails(userId: number): Promise<User | null> {
    const response = await apiClient.get<User>(
      `/users/user_details/${userId}`,
      { retry: 1 }
    );

    if (!response.ok || !response.data) {
      return null;
    }

    const data = response.data;

    return {
      id: data.id,
      username: data.username,
      role: data.role,
    };
  },

  async updateRole(payload: UpdateRole): Promise<boolean> {
    const response = await apiClient.post<{ message: string }>(
      "/users/update_role",
      {
        user_id: payload.username,
        new_role: payload.newRole,
      }
    );

    if (!response.ok) {
      return false;
    }

    return response.ok;
  },

  async deleteUser(userId: number): Promise<boolean> {
    const response = await apiClient.delete<{
      message: string;
      username: string;
    }>(`/users/${userId}`);

    if (!response.ok) {
      return false;
    }

    return response.ok;
  },

  async changePassword(payload: UpdatePassword): Promise<boolean> {
    const response = await apiClient.post<{ message: string }>(
      "/users/me/password_modification",
      {
        old_password: payload.oldPassword,
        new_password: payload.newPassword,
      }
    );

    if (!response.ok) {
      return false;
    }

    return response.ok;
  },

  async changeUsername(newUsername: string): Promise<boolean> {
    const response = await apiClient.post<{ message: string }>(
      `/users/me/username_modification/${encodeURIComponent(newUsername)}`
    );

    if (!response.ok) {
      return false;
    }

    return response.ok;
  },
};
