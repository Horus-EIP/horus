import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side admin gate shared by the observability BFF routes (logs, metrics,
 * traces). MAS is the single source of truth for roles, so we verify the caller's
 * bearer token against `/users/me` and require `role === "admin"` before any
 * upstream (Loki / Prometheus / Tempo) is queried.
 *
 * Server-only: import this from Route Handlers, never from client components.
 */

const orchestratorBase = (
  process.env.ORCHESTRATOR_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

export type AdminGuard = { ok: true } | { ok: false; response: NextResponse };

function deny(status: number, error: string): AdminGuard {
  return { ok: false, response: NextResponse.json({ error }, { status }) };
}

export async function requireAdmin(request: NextRequest): Promise<AdminGuard> {
  const auth = request.headers.get("authorization");
  if (!auth) return deny(401, "Not authenticated.");

  let me: Response;
  try {
    me = await fetch(`${orchestratorBase}/users/me`, {
      headers: { authorization: auth },
      redirect: "follow",
    });
  } catch {
    return deny(502, "Auth service unreachable.");
  }

  if (me.status === 401) return deny(401, "Session expired. Sign in again.");
  if (!me.ok) return deny(403, "Could not verify permissions.");

  const user = (await me.json().catch(() => null)) as { role?: string } | null;
  if (!user || user.role !== "admin") {
    return deny(403, "Admin role required.");
  }
  return { ok: true };
}
