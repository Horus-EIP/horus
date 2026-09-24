#!/usr/bin/env bash
# Create .env from .env.example and set JWT_SECRET_KEY to a random value.
# If .env already exists, does nothing (exit 0) so wrapper scripts can call this safely.
#
# Usage: from this directory: ./init-env.sh   or: bash init-env.sh
#   ./init-env.sh            create .env only when it is missing (default, unchanged)
#   ./init-env.sh --force    back up an existing .env to .env.bak.<timestamp>, then recreate
#   ./init-env.sh --quiet    suppress the informational output (errors still print)
#
# --force exists for the beta installer, which needs to (re)generate a .env it then layers
# hardware-profile settings on top of. Without a flag the behaviour is exactly as before.
#
# One-shot stack: run ./stack-up.sh from the top of this folder (runs this, then docker compose up --build)

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
EXAMPLE="$DIR/.env.example"
TARGET="$DIR/.env"

FORCE=0
QUIET=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --quiet) QUIET=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "Error: unknown option '$arg' (expected --force, --quiet or --help)" >&2
      exit 2
      ;;
  esac
done

say() { [[ "$QUIET" -eq 1 ]] || echo "$@"; }

if [[ ! -f "$EXAMPLE" ]]; then
  echo "Error: missing $EXAMPLE"
  exit 1
fi

if [[ -f "$TARGET" ]]; then
  if [[ "$FORCE" -eq 0 ]]; then
    say "Using existing $TARGET (remove it to recreate from $EXAMPLE)."
    exit 0
  fi
  BACKUP="$TARGET.bak.$(date +%Y%m%d-%H%M%S)"
  cp "$TARGET" "$BACKUP"
  chmod 600 "$BACKUP" 2>/dev/null || true
  say "Backed up existing .env to $BACKUP"
fi

cp "$EXAMPLE" "$TARGET"

# 64 hex chars. openssl is the usual source; fall back so a machine without it
# (some minimal Windows/Git-Bash setups) still gets a real random secret rather
# than silently keeping the placeholder.
if command -v openssl >/dev/null 2>&1; then
  SECRET="$(openssl rand -hex 32)"
elif command -v python3 >/dev/null 2>&1; then
  SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
elif command -v python >/dev/null 2>&1; then
  SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
elif [[ -r /dev/urandom ]]; then
  SECRET="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
else
  echo "Error: no way to generate a random secret (need openssl, python3, or /dev/urandom)"
  exit 1
fi

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

# The file holds database, broker and admin passwords. Owner-only where the OS supports it.
chmod 600 "$TARGET" 2>/dev/null || true

say "Created $TARGET with a generated JWT_SECRET_KEY (64 hex chars)."
say "Next: docker compose up --build from this directory, or ./stack-up.sh from the top of this folder, then sign in in the web UI."
