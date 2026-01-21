'use client';

import { apiClient } from "@/lib/api-client";
import { LoginFormData, RegisterFormData } from "./schemas";
import { User, AuthResponse, TokenResponse } from "@/lib/types";
import { userApi } from "@/lib/users/api";

export const authApi = {
  async login(data: LoginFormData): Promise<AuthResponse> {

    const response = await apiClient.postForm<TokenResponse>(
      "/auth/token",
      {
        username: data.username,
        password: data.password,
        grant_type: "password",
      },
      { retry: 1 }
    );

    if (!response.ok || !response.data) {
      return {
        ok: false,
        error: response.error || "Login failed",
        status: response.status,
      };
    }

    if (response.data.access_token && typeof window !== "undefined") {
      localStorage.setItem("auth_token", response.data.access_token);
    }

    const user = await userApi.getCurrentUser();

    return {
      ok: true,
      user: user || undefined,
      token: response.data.access_token,
      status: response.status,
    };
  },

  async register(data: RegisterFormData): Promise<AuthResponse> {
    const response = await apiClient.post<User>(
      "/auth/register",
      {
        username: data.username,
        password: data.password,
      },
      { retry: 1 }
    );

    if (!response.ok || !response.data) {
      return {
        ok: false,
        error: response.error || "Registration failed",
        status: response.status,
      };
    }

    const loginResult = await this.login({
      username: data.username,
      password: data.password,
    });

    return loginResult;
  },

  async logout(): Promise<void> {
    await apiClient.post("/auth/logout");
    if (typeof window !== "undefined") {
      localStorage.removeItem("auth_token");
    }
  },
};
