"use client";

import { getCsrfHeaders } from "@/utils/csrf";
import { isDockerInternalHostname } from "@/utils/docker-internal-hosts";
import { getBrowserOrchestratorApiBase } from "@/utils/orchestrator-browser-base";

/** MAS HTTP paths (no /api/orchestrator prefix) — used to fix same-origin slash redirects from the BFF. */
const MAS_ROOT_PATH = /^\/(auth|agents|conversations|tasks|users|chat|rabbitmq|system)(\/|$)/;

/** Default ceiling for GET requests so a stalled MAS can't hang a page forever. */
const DEFAULT_GET_TIMEOUT_MS = 15000;

/** Per-request options shared by all verbs. */
interface RequestOptions {
  retry?: number;
  /** Caller abort signal (e.g. an effect's AbortController) — aborts the request. */
  signal?: AbortSignal;
  /** Abort the request after this many ms (combined with ``signal``). 0 disables. */
  timeoutMs?: number;
  headers?: Record<string, string>;
}

function stripBodyHeaders(headers: HeadersInit | undefined): HeadersInit {
  const h = new Headers(headers ?? undefined);
  h.delete("Content-Type");
  h.delete("Content-Length");
  return h;
}

/** Normalize FastAPI / Starlette error payloads and plain text bodies. */
function extractBackendErrorMessage(
  parsed: unknown,
  rawText: string,
  jsonParseOk: boolean,
  status: number
): string | null {
  if (typeof parsed === "string" && parsed.trim()) return parsed;

  if (typeof parsed === "object" && parsed !== null) {
    const b = parsed as Record<string, unknown>;
    const d = b.detail;
    if (typeof d === "string" && d.trim()) return d;
    if (Array.isArray(d) && d.length > 0) {
      const first = d[0];
      if (typeof first === "string") return first;
      if (first && typeof first === "object" && "msg" in first) {
        const msg = (first as { msg?: unknown }).msg;
        if (typeof msg === "string") return msg;
      }
    }
    if (typeof b.message === "string" && b.message.trim()) return b.message;
    if (typeof b.error === "string" && b.error.trim()) return b.error;
    const err0 = b.errors;
    if (Array.isArray(err0) && typeof err0[0] === "string") return err0[0];
    // Parsed JSON but no known fields — don't show raw "{}" to users
    return null;
  }

  if (!jsonParseOk) {
    const trimmed = rawText.trim();
    if (trimmed && !trimmed.startsWith("<")) {
      return trimmed.length > 500 ? `${trimmed.slice(0, 500)}…` : trimmed;
    }
  }

  if (status === 401) return "Not authenticated. Please sign in again.";
  if (status === 403) return "You do not have permission for this action.";
  if (status === 404) return "The requested resource was not found.";
  if (status === 422) return "Validation failed. Check the form fields and try again.";
  return null;
}

export interface ApiResponse<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
  status?: number;
  /** True when the request was aborted (caller signal or timeout) — callers should not retry. */
  aborted?: boolean;
}

class ApiClient {
  private baseUrl(): string {
    return getBrowserOrchestratorApiBase();
  }

  /**
   * FastAPI/Starlette often responds with 307 + absolute Location using the upstream Host
   * (e.g. http://mas:8000/...). The browser cannot resolve `mas`, so we follow redirects
   * manually and map those URLs back to same-origin /api/orchestrator/...
   */
  private resolveOrchestratorRedirect(
    location: string,
    currentUrl: string
  ): string | null {
    if (typeof window === "undefined") return null;

    const bffBase = getBrowserOrchestratorApiBase();
    const absoluteCurrent =
      currentUrl.startsWith("http://") || currentUrl.startsWith("https://")
        ? currentUrl
        : `${window.location.origin}${
            currentUrl.startsWith("/") ? currentUrl : `/${currentUrl}`
          }`;
    const resolved = new URL(location, absoluteCurrent);
    const host = resolved.hostname.toLowerCase();

    if (isDockerInternalHostname(host)) {
      return `${window.location.origin}${bffBase}${resolved.pathname}${resolved.search}`;
    }

    if (resolved.origin === window.location.origin) {
      const path = resolved.pathname;
      if (path === bffBase || path.startsWith(`${bffBase}/`)) {
        return resolved.href;
      }
      if (MAS_ROOT_PATH.test(path)) {
        return `${window.location.origin}${bffBase}${path}${resolved.search}`;
      }
    }

    return null;
  }

  private async fetchFollowingOrchestratorRedirects(
    url: string,
    init: RequestInit
  ): Promise<Response> {
    const maxHops = 8;
    let currentUrl = url;
    let method = init.method ?? "GET";
    let headers: HeadersInit | undefined = init.headers;
    let body: RequestInit["body"] = init.body;
    const { redirect: _r, ...rest } = init;
    void _r;

    for (let i = 0; i < maxHops; i++) {
      const res = await fetch(currentUrl, {
        ...rest,
        method,
        headers,
        body,
        redirect: "manual",
      });

      if (res.status < 300 || res.status >= 400) {
        return res;
      }

      const loc = res.headers.get("Location");
      if (!loc) {
        return res;
      }

      const nextUrl = this.resolveOrchestratorRedirect(loc, currentUrl);
      if (!nextUrl) {
        return res;
      }

      currentUrl = nextUrl;

      if (res.status === 303) {
        method = "GET";
        body = undefined;
        headers = stripBodyHeaders(headers);
      }
    }

    throw new Error("Too many redirects");
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

  /**
   * Combine an optional caller signal with an optional timeout into one signal.
   * ``AbortSignal.any`` lets either a navigation-cleanup abort OR a timeout fire
   * the request's ``AbortError`` — using a bare timeout would clobber the
   * caller's own abort.
   */
  private buildSignal(
    signal: AbortSignal | undefined,
    timeoutMs: number | undefined
  ): AbortSignal | undefined {
    const signals: AbortSignal[] = [];
    if (signal) signals.push(signal);
    if (typeof timeoutMs === "number" && timeoutMs > 0) {
      signals.push(AbortSignal.timeout(timeoutMs));
    }
    if (signals.length === 0) return undefined;
    if (signals.length === 1) return signals[0];
    return AbortSignal.any(signals);
  }

  private async requestOnce<T>(
    endpoint: string,
    init: RequestInit
  ): Promise<ApiResponse<T>> {
    try {
      const url = `${this.baseUrl()}${endpoint}`;
      const headers = new Headers(this.getHeaders());
      if (typeof FormData !== "undefined" && init.body instanceof FormData) {
        headers.delete("Content-Type");
      }
      new Headers(init.headers).forEach((value, key) => {
        headers.set(key, value);
      });
      const result = await this.fetchFollowingOrchestratorRedirects(url, {
        ...init,
        headers,
        credentials: "include",
      });

      const status = result.status;
      const rawText = await result.text();
      let body: unknown = null;
      let jsonParseOk = false;
      if (rawText) {
        try {
          body = JSON.parse(rawText) as unknown;
          jsonParseOk = true;
        } catch {
          body = null;
          jsonParseOk = false;
        }
      }

      if (!result.ok) {
        const messageFromBackend = extractBackendErrorMessage(
          body,
          rawText,
          jsonParseOk,
          status
        );

        const fallbackMessage =
          status >= 500
            ? "Something went wrong on the server. Please try again later."
            : `Request failed (${status}). Please try again or contact support if it continues.`;

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
      // A caller-aborted (navigation cleanup) or timed-out request is expected:
      // don't surface a scary "network error" and don't let withRetry retry it.
      const name = (error as Error)?.name;
      if (name === "AbortError" || name === "TimeoutError") {
        return { ok: false, aborted: true, error: "Request aborted" };
      }
      if (process.env.NODE_ENV !== "production") {
        console.warn(
          "ApiClient request error:",
          (error as Error)?.message ?? error
        );
      }
      const hint =
        process.env.NODE_ENV !== "production"
          ? ` (${(error as Error)?.message ?? String(error)}). Ensure the MAS API is running and reachable.`
          : "";
      return {
        ok: false,
        error: `Network error. Please check your connection.${hint}`,
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

      // Aborted (navigation or timeout) — retrying would fire one more doomed
      // request after the caller has moved on.
      if (lastResult.aborted) {
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

  get<T>(endpoint: string, options?: RequestOptions): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;
    const signal = this.buildSignal(
      options?.signal,
      options?.timeoutMs ?? DEFAULT_GET_TIMEOUT_MS
    );
    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "GET",
          signal,
        }),
      retry
    );
  }

  post<T>(
    endpoint: string,
    body?: unknown,
    options?: RequestOptions
  ): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;
    const signal = this.buildSignal(options?.signal, options?.timeoutMs);
    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "POST",
          body: body ? JSON.stringify(body) : undefined,
          headers: options?.headers,
          signal,
        }),
      retry
    );
  }

  postMultipart<T>(
    endpoint: string,
    body: FormData,
    options?: RequestOptions
  ): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;
    const signal = this.buildSignal(options?.signal, options?.timeoutMs);
    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "POST",
          body,
          signal,
        }),
      retry
    );
  }

  postForm<T>(
    endpoint: string,
    body: Record<string, string>,
    options?: RequestOptions
  ): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;
    const signal = this.buildSignal(options?.signal, options?.timeoutMs);

    const formBody = new URLSearchParams(body).toString();

    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: formBody,
          signal,
        }),
      retry
    );
  }

  put<T>(
    endpoint: string,
    body?: unknown,
    options?: RequestOptions
  ): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;
    const signal = this.buildSignal(options?.signal, options?.timeoutMs);
    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "PUT",
          body: body ? JSON.stringify(body) : undefined,
          signal,
        }),
      retry
    );
  }

  delete<T>(endpoint: string, options?: RequestOptions): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;
    const signal = this.buildSignal(options?.signal, options?.timeoutMs);
    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "DELETE",
          signal,
        }),
      retry
    );
  }

  patch<T>(
    endpoint: string,
    body?: unknown,
    options?: RequestOptions
  ): Promise<ApiResponse<T>> {
    const retry = options?.retry ?? 0;
    const signal = this.buildSignal(options?.signal, options?.timeoutMs);
    return this.withRetry(
      () =>
        this.requestOnce<T>(endpoint, {
          method: "PATCH",
          body: body ? JSON.stringify(body) : undefined,
          signal,
        }),
      retry
    );
  }
}

export const apiClient = new ApiClient();
