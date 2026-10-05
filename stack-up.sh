#!/usr/bin/env bash
# Create src/infra/.env when missing (init-env.sh), validate Compose, then build and start the stack.
#
# Usage (from the top of this folder):
#   ./stack-up.sh                  # build + up (foreground; Ctrl+C stops containers)
#   ./stack-up.sh -d               # detached
#   ./stack-up.sh -d --no-deps     # extra args are passed to: docker compose up --build
#
# Requires: docker compose, bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
INFRA="$ROOT/src/infra"

if [[ ! -d "$INFRA" ]] || [[ ! -f "$INFRA/docker-compose.yml" ]]; then
  echo "Error: expected Docker Compose at $INFRA/docker-compose.yml (run this script from the top of this folder)."
  exit 1
fi

cd "$INFRA"
bash "$INFRA/init-env.sh"
export HORUS_REGISTRY=

echo ""
echo "Validating Docker Compose configuration..."
docker compose config -q
echo "Compose file OK."

cat <<'EOF'

Horus — URLs from your host (browser / curl)
  Web UI             http://localhost:3000   (health: /api/health)
  MAS API            http://localhost:8000   (Swagger: /docs)
  Knowledge Store    http://localhost:8080   (health: /health, list: GET /file, search: GET /)
  Agent              http://localhost:8001   (health: /health)

Docker-only hostnames (do NOT put these in NEXT_PUBLIC_* — the browser cannot resolve them):
  mas, knowledge_store, agent, rabbitmq, postgres, redis, tempo, …

Service wiring (Compose overrides):
  agent → MAS:     ORCHESTRATOR_URL=http://mas:8000
  agent → store:   KNOWLEDGE_STORE_URL=http://knowledge_store:8080  (HTTP paths are / and /file, no /api prefix)
  web (server) → MAS: ORCHESTRATOR_URL=http://mas:8000
  browser → store: NEXT_PUBLIC_KNOWLEDGE_STORE_URL=http://localhost:8080 (default build arg)

If the knowledge store is behind a reverse proxy with a path prefix, set in .env:
  KNOWLEDGE_STORE_API_PREFIX=/api/knowledge-store          # agent
  NEXT_PUBLIC_KNOWLEDGE_STORE_API_PREFIX=...               # web rebuild

Starting stack (docker compose up --build)...
Building from source: the app images keep local names, so they never replace
the prebuilt images the installer pulled (HORUS_REGISTRY is ignored here).
EOF

exec docker compose up --build "$@"
