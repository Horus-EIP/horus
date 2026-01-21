import { getCsrfHeaders } from "@/utils/csrf";
import { config } from "@/utils/config";

export interface ApiResponse<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
  status?: number;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private getHeaders(): HeadersInit {
    const headers: HeadersInit = {
      "Content-Type": "application/json",
      ...getCsrfHeaders(),
    };

    if (typeof window !== "undefined") {
      const token = localStorage.getItem("auth_token");
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    }

    return headers;
  }

  private async requestOnce<T>(
    endpoint: string,
    init: RequestInit
  ): Promise<ApiResponse<T>> {
    try {
      const result = await fetch(`${this.baseUrl}${endpoint}`, {
        ...init,
        headers: {
          ...this.getHeaders(),
          ...(init.headers || {}),
        },
        credentials: "include",
      });

      const status = result.status;

      let body = null;
      try {
        body = await result.json();
      } catch {
        body = null;
      }

      if (!result.ok) {
        const messageFromBackend =
          body?.detail ||
          body?.message ||
          body?.error ||
          body?.errors?.[0] ||
          null;

        const fallbackMessage =
          status >= 500
            ? "Something went wrong on the server. Please try again later."
            : "Your request could not be processed. Please check your input.";

        return {
          ok: false,
          status,
          error: messageFromBackend || fallbackMessage,
        };
      }

      return {
        ok: true,
        status,
        data: body as T,
      };
    } catch (error) {
      if (process.env.NODE_ENV !== "production") {
        console.warn(
          "ApiClient request error:",
          (error as Error)?.message ?? error
        );
      }
      return {
        ok: false,
        error: "Network error. Please check your connection.",
      };
    }
  }

  private async withRetry<T>(
    fn: () => Promise<ApiResponse<T>>,
    retries = 0,
    baseDelayMs = 500
  ): Promise<ApiResponse<T>> {
    let lastResult: ApiResponse<T> = { ok: false, error: "Unknown error" };

    for (let attempt = 0; attempt <= retries; attempt++) {
      lastResult = await fn();

      if (lastResult.ok) {
        return lastResult;
      }

      if (attempt === retries) {
        return lastResult;
      }

      const delay = baseDelayMs * (attempt + 1);
      await new Promise((res) => setTimeout(res, delay));
    }

    return lastResult;
  }

  get<T>(
    endpoint: string,
    options?: { retry?: number }
  ): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;
    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "GET",
        }),
      retry
    );
  }

  post<T>(
    endpoint: string,
    body?: unknown,
    options?: { retry?: number }
  ): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;
    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "POST",
          body: body ? JSON.stringify(body) : undefined,
        }),
      retry
    );
  }

  postForm<T>(
    endpoint: string,
    body: Record<string, string>,
    options?: { retry?: number }
  ): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;

    const formBody = new URLSearchParams(body).toString();

    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: formBody,
        }),
      retry
    );
  }

  put<T>(
    endpoint: string,
    body?: unknown,
    options?: { retry?: number }
  ): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;
    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "PUT",
          body: body ? JSON.stringify(body) : undefined,
        }),
      retry
    );
  }

  delete<T>(
    endpoint: string,
    options?: { retry?: number }
  ): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;
    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "DELETE",
        }),
      retry
    );
  }

  patch<T>(
    endpoint: string,
    body?: unknown,
    options?: { retry?: number }
  ): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;
    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "PATCH",
          body: body ? JSON.stringify(body) : undefined,
        }),
      retry
    );
  }
}

export const apiClient = new ApiClient(config.orchestratorUrl);
