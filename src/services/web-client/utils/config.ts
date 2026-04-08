import { isDockerInternalHostname } from "@/utils/docker-internal-hosts";

/**
 * WebSocket must reach MAS directly (Next.js HTTP rewrites do not upgrade to WS).
 * If NEXT_PUBLIC_WS_URL is unset, use the same hostname as the page with port 8000
 * so LAN access (e.g. http://192.168.x.x:3000) still connects to MAS on :8000.
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
      /* use derived URL below */
    }
  }
  if (typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.hostname}:8000`;
  }
  return explicit || "ws://localhost:8000";
}

export const config = {
  knowledgeStoreUrl:
    process.env.NEXT_PUBLIC_KNOWLEDGE_STORE_URL ?? "http://localhost:8080",
  get wsUrl() {
    return wsBaseUrl();
  },
};
