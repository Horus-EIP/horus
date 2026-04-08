/**
 * Base URL for MAS REST from the browser.
 *
 * Always same-origin: Next.js rewrites `/api/orchestrator/*` → MAS (see next.config.ts).
 * We intentionally do not read `process.env` here so the client bundle can never
 * pick up `ORCHESTRATOR_URL` / `NEXT_PUBLIC_API_URL=http://mas:8000` (which causes
 * net::ERR_NAME_NOT_RESOLVED in the browser).
 */
export function getBrowserOrchestratorApiBase(): string {
  return "/api/orchestrator";
}
