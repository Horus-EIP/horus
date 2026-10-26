#!/usr/bin/env bash
# Create .env from .env.example and generate passwords.
# If .env already exists, does nothing (exit 0) so wrapper scripts can call this safely.
#
# Usage: from this directory: ./init-env.sh   or: bash init-env.sh
#   ./init-env.sh            create .env only when it is missing; ask about LAN access
#   ./init-env.sh --force    back up an existing .env to .env.bak.<timestamp>, then recreate
#   ./init-env.sh --quiet    suppress output and use safe local-only defaults
#
# --force exists for the beta installer, which needs to (re)generate a .env it then layers
# hardware-profile settings on top of. Quiet/non-interactive runs keep LAN access disabled.
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

set_key() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$TARGET"; then
    if command -v perl >/dev/null 2>&1; then
      perl -i -pe "s/^${key}=.*/${key}=${value}/" "$TARGET"
    elif [[ "$(uname -s)" == Darwin ]]; then
      sed -i '' "s/^${key}=.*/${key}=${value}/" "$TARGET"
    else
      sed -i "s/^${key}=.*/${key}=${value}/" "$TARGET"
    fi
  else
    printf '%s=%s\n' "$key" "$value" >> "$TARGET"
  fi
  if ! grep -q "^${key}=${value}\$" "$TARGET"; then
    echo "Error: failed to write ${key} into $TARGET"
    exit 1
  fi
}

detect_lan_ipv4() {
  local python
  python="$(command -v python3 || command -v python || true)"
  [[ -n "$python" ]] || return 1
  "$python" -c 'import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("192.0.2.1", 80)); print(s.getsockname()[0]); s.close()' 2>/dev/null
}

valid_lan_ipv4() {
  local address="$1" octet
  local -a parts
  IFS=. read -r -a parts <<< "$address"
  [[ ${#parts[@]} -eq 4 ]] || return 1
  for octet in "${parts[@]}"; do
    [[ "$octet" =~ ^[0-9]{1,3}$ ]] && (( 10#$octet <= 255 )) || return 1
  done
  [[ "$address" != 0.0.0.0 && ! "$address" =~ ^127\. ]]
}

configure_network_access() {
  local current_bind="${1:-127.0.0.1}"
  local default_ip lan_ip answer response

  [[ -t 0 && "$QUIET" -eq 0 ]] || return 0
  if [[ "$current_bind" == "0.0.0.0" ]]; then
    printf 'Allow other devices on your trusted LAN to access Horus? [Y/n] '
    answer="y"
  else
    printf 'Allow other devices on your trusted LAN to access Horus? [y/N] '
    answer="n"
  fi
  if IFS= read -r response; then
    case "$response" in
      y|Y|[yY][eE][sS]) answer="y" ;;
      n|N|[nN][oO]) answer="n" ;;
      "") ;;
      *) say "Unrecognized answer; keeping the current setting." ;;
    esac
  fi

  if [[ "$answer" == "n" ]]; then
    set_key HORUS_WEB_BIND "127.0.0.1"
    set_key HORUS_LAN_TLS "0"
    say "LAN access disabled; the local web client is available at http://localhost:3000."
    return
  fi

  default_ip="$(detect_lan_ipv4 || true)"
  if [[ -z "$default_ip" ]] || ! valid_lan_ipv4 "$default_ip"; then
    default_ip=""
    say "Could not detect this PC's LAN IPv4 address."
  fi
  if [[ -n "$default_ip" ]]; then
    printf "Enter this PC's LAN IPv4 address [%s]: " "$default_ip"
  else
    printf "Enter this PC's LAN IPv4 address: "
  fi
  IFS= read -r lan_ip || lan_ip=""
  lan_ip="${lan_ip:-$default_ip}"
  if ! valid_lan_ipv4 "$lan_ip"; then
    echo "Error: '$lan_ip' is not a usable IPv4 address. LAN access was not enabled." >&2
    exit 1
  fi

  set_key HORUS_WEB_BIND "0.0.0.0"
  if ! grep -q '^HORUS_LAN_TLS=' "$TARGET"; then
    set_key HORUS_LAN_TLS "0"
  fi
  say "Local access is available at http://localhost:3000."
  say "LAN HTTPS stays disabled until a trusted certificate and matching key are installed in src/infra/certs/."
  say "Then set HORUS_LAN_TLS=1 in src/infra/.env and use https://$lan_ip:3443."
}

if [[ ! -f "$EXAMPLE" ]]; then
  echo "Error: missing $EXAMPLE"
  exit 1
fi

if [[ -f "$TARGET" ]]; then
  if [[ "$FORCE" -eq 0 ]]; then
    current_bind="$(sed -n 's/^HORUS_WEB_BIND=//p' "$TARGET" | tail -n 1)"
    configure_network_access "${current_bind:-127.0.0.1}"
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
random_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_hex(32))'
  elif command -v python >/dev/null 2>&1; then
    python -c 'import secrets; print(secrets.token_hex(32))'
  elif [[ -r /dev/urandom ]]; then
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
  else
    echo "Error: no way to generate a random secret (need openssl, python3, or /dev/urandom)" >&2
    return 1
  fi
}

random_text() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 18 | tr '+/' '-_'
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(18))'
  elif command -v python >/dev/null 2>&1; then
    python -c 'import secrets; print(secrets.token_urlsafe(18))'
  elif [[ -r /dev/urandom ]] && command -v base64 >/dev/null 2>&1; then
    head -c 18 /dev/urandom | base64 | tr '+/' '-_'
  else
    echo "Error: no way to generate a random password (need openssl, python3, or /dev/urandom)" >&2
    return 1
  fi
}

random_password() {
  local candidate=""
  until [[ "$candidate" =~ ^[[:alnum:]] && "$candidate" =~ [[:lower:]] && "$candidate" =~ [[:upper:]] \
        && "$candidate" =~ [[:digit:]] && "$candidate" =~ [-_] ]]; do
    candidate="$(random_text | tr -d '\r\n')" || return 1
  done
  printf '%s\n' "$candidate"
}



configure_network_access "127.0.0.1"

JWT_SECRET="$(random_hex)"
VALKEY_PASSWORD="$(random_hex)"
ADMIN_PASSWORD="$(random_password)"
AGENT_PASSWORD="$(random_password)"
set_key JWT_SECRET_KEY "$JWT_SECRET"
set_key REDIS_PASSWORD "$VALKEY_PASSWORD"
set_key SUPER_USER_PASSWORD "$ADMIN_PASSWORD"
set_key SUPER_AGENT_PASSWORD "$AGENT_PASSWORD"

# The file holds database, broker and account passwords. Owner-only where the OS supports it.
chmod 600 "$TARGET" 2>/dev/null || true

say "Created $TARGET with generated JWT_SECRET_KEY and REDIS_PASSWORD (64 hex chars each), plus admin and agent account passwords."
say "The admin account signs in with the SUPER_USER_USERNAME and the generated SUPER_USER_PASSWORD in $TARGET."
say "The Agent service uses SUPER_AGENT_USERNAME and SUPER_AGENT_PASSWORD from $TARGET to register its workers."
say "Local access uses http://localhost:3000; LAN HTTPS needs a trusted certificate configured in $DIR/certs."
say "Next: docker compose up --build from this directory, or ./stack-up.sh from the top of this folder."
