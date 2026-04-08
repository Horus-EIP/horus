/** Hostnames only resolvable inside Docker; the browser must not use them in fetch() / WS. */
export const DOCKER_INTERNAL_API_HOSTS = new Set(
  [
    "mas",
    "agent",
    "knowledge_store",
    "postgres",
    "redis",
    "rabbitmq",
    "web_client",
    "web-client",
    "tempo",
    "grafana",
    "prometheus",
  ].map((h) => h.toLowerCase())
);

export function isDockerInternalHostname(hostname: string): boolean {
  return DOCKER_INTERNAL_API_HOSTS.has(hostname.toLowerCase());
}
