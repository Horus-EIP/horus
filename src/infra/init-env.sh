#!/usr/bin/env bash
# Create .env from .env.example and set JWT_SECRET_KEY to a random value (openssl).
# If .env already exists, does nothing (exit 0) so wrapper scripts can call this safely.
# Usage: from this directory: ./init-env.sh   or: bash init-env.sh
# One-shot stack: run ./stack-up.sh from the repository root (runs this, then docker compose up --build)

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
EXAMPLE="$DIR/.env.example"
TARGET="$DIR/.env"

if [[ ! -f "$EXAMPLE" ]]; then
  echo "Error: missing $EXAMPLE"
  exit 1
fi

if [[ -f "$TARGET" ]]; then
  echo "Using existing $TARGET (remove it to recreate from $EXAMPLE)."
  exit 0
fi

cp "$EXAMPLE" "$TARGET"
SECRET="$(openssl rand -hex 32)"

if command -v perl >/dev/null 2>&1; then
  perl -i -pe "s/^JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$SECRET/" "$TARGET"
else
  # macOS / Linux sed (no perl)
  if [[ "$(uname -s)" == Darwin ]]; then
    sed -i '' "s/^JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$SECRET/" "$TARGET"
  else
    sed -i "s/^JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$SECRET/" "$TARGET"
  fi
fi

if ! grep -q "^JWT_SECRET_KEY=$SECRET\$" "$TARGET"; then
  echo "Error: failed to write JWT_SECRET_KEY into $TARGET"
  exit 1
fi

echo "Created $TARGET with a generated JWT_SECRET_KEY (64 hex chars)."
echo "Next: docker compose up --build from this directory, or ./stack-up.sh from the repo root, then sign in in the web UI."
