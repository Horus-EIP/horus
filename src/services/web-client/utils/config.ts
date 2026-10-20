import { isDockerInternalHostname } from "@/utils/docker-internal-hosts";

/**
 * Modernized WebSocket URL resolution:
 * - Directs traffic through Nginx (/ws) using the current page's origin (host + port).
 * - Avoids bypassing Nginx via hardcoded :8000 port on local networks.
 */
function wsBaseUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_WS_URL?.trim().replace(/\/$/, "");
  if (explicit && typeof window === "undefined") {
    return explicit;
  }
  if (explicit && typeof window !== "undefined") {
    try {
      const host = new URL(explicit).hostname;
      if (!isDockerInternalHostname(host)) {
        return explicit;
      }
    } catch {
      /* fallback to derived URL below */
    }
  }
  if (typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    // Utile window.location.host (ip:3000) et la route /ws gérée par Nginx
    return `${proto}//${window.location.host}/ws`;
  }
  return explicit || "ws://localhost:3000/ws";
}

function knowledgeStorePathPrefix(): string {
  const raw = process.env.NEXT_PUBLIC_KNOWLEDGE_STORE_API_PREFIX?.trim() ?? "";
  if (!raw) return "";
  const noTrail = raw.replace(/\/+$/, "");
  return noTrail.startsWith("/") ? noTrail : `/${noTrail}`;
}

export const config = {
  knowledgeStoreUrl:
    process.env.NEXT_PUBLIC_KNOWLEDGE_STORE_URL ?? "http://localhost:8080",
  /** Path before store routes when using a gateway (default: "" = call :8080 directly). */
  knowledgeStoreApiPrefix: knowledgeStorePathPrefix(),
  get wsUrl() {
    return wsBaseUrl();
  },
};