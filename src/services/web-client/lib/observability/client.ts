"use client";

/**
 * Shared helpers for the same-origin observability BFF clients (logs, metrics,
 * traces). Each route enforces the admin role server-side; here we just attach
 * the bearer token the way {@link apiClient} does and normalize error bodies.
 */

export function authHeaders(): HeadersInit {
  const headers: HeadersInit = {};
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("auth_token");
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

export async function readApiError(res: Response): Promise<string> {
  const body = (await res.json().catch(() => null)) as { error?: string } | null;
  if (body && typeof body.error === "string" && body.error.trim()) {
    return body.error;
  }
  if (res.status === 401) return "Session expired. Please sign in again.";
  if (res.status === 403) return "Admin role required.";
  return `Request failed (${res.status}).`;
}
