#!/usr/bin/env bash
# Create src/infra/.env when missing (init-env.sh), then build images and start the stack.
#
# Usage (from the repository root):
#   ./stack-up.sh                  # build + up (foreground; Ctrl+C stops containers)
#   ./stack-up.sh -d               # detached
#   ./stack-up.sh -d --no-deps     # extra args are passed to: docker compose up --build
#
# Requires: docker compose, bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
INFRA="$ROOT/src/infra"

if [[ ! -d "$INFRA" ]] || [[ ! -f "$INFRA/docker-compose.yml" ]]; then
  echo "Error: expected Docker Compose at $INFRA/docker-compose.yml (run this script from the repo root)."
  exit 1
fi

cd "$INFRA"
bash "$INFRA/init-env.sh"
exec docker compose up --build "$@"
