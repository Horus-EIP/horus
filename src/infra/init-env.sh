#!/usr/bin/env bash
# Create .env from .env.example, configure optional LAN access, and generate passwords.
# If .env already exists, does nothing (exit 0) so wrapper scripts can call this safely.
#
# Usage: from this directory: ./init-env.sh   or: bash init-env.sh
#   ./init-env.sh            create .env only when it is missing; ask about LAN access
#   ./init-env.sh --force    back up an existing .env to .env.bak.<timestamp>, then recreate
#   ./init-env.sh --quiet    suppress output and use safe local-only defaults
#
# --force exists for the beta installer, which needs to (re)generate a .env it then layers
# hardware-profile settings on top of. Quiet/non-interactive runs keep local-only access.
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
  if command -v perl >/dev/null 2>&1; then
    perl -i -pe "s/^${key}=.*/${key}=${value}/" "$TARGET"
  elif [[ "$(uname -s)" == Darwin ]]; then
    sed -i '' "s/^${key}=.*/${key}=${value}/" "$TARGET"
  else
    sed -i "s/^${key}=.*/${key}=${value}/" "$TARGET"
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

generate_local_certificate() {
  local cert_dir="$DIR/certs"
  local cert="$cert_dir/horus.crt"
  local key="$cert_dir/horus.key"
  local lan_ip="${1:-}"
  local san="DNS:localhost,IP:127.0.0.1,IP:::1"

  if ! command -v openssl >/dev/null 2>&1; then
    echo "Error: openssl is required to generate the local HTTPS certificate." >&2
    echo "Install OpenSSL, then run this script again." >&2
    exit 1
  fi

  mkdir -p "$cert_dir"
  if [[ -e "$cert" || -e "$key" ]]; then
    local backup_stamp
    backup_stamp="$(date +%Y%m%d-%H%M%S)"
    if [[ -f "$cert" ]]; then cp "$cert" "$cert.$backup_stamp.bak"; fi
    if [[ -f "$key" ]]; then cp "$key" "$key.$backup_stamp.bak"; fi
    if [[ -f "$key.$backup_stamp.bak" ]]; then
      chmod 600 "$key.$backup_stamp.bak" 2>/dev/null || true
    fi
    say "Backed up the previous certificate pair in $cert_dir."
  fi
  if [[ -n "$lan_ip" ]]; then
    san="$san,IP:$lan_ip"
  fi
  if ! openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
      -keyout "$key" -out "$cert" -subj "/CN=localhost" \
      -addext "subjectAltName=$san"; then
    rm -f "$key" "$cert"
    echo "Error: could not generate the HTTPS certificate." >&2
    exit 1
  fi
  chmod 600 "$key"
  chmod 644 "$cert"
  say "Generated a self-signed HTTPS certificate in $cert_dir."
  if [[ -n "$lan_ip" ]]; then
    say "The certificate covers localhost and this PC's LAN address ($lan_ip)."
    say "On other devices, install and trust this certificate before connecting."
  else
    say "The certificate covers localhost only. Browsers may show a certificate trust warning."
  fi
}

ensure_local_certificate() {
  local cert="$DIR/certs/horus.crt"
  local key="$DIR/certs/horus.key"
  local lan_ip="${1:-}"

  if [[ -f "$cert" && -f "$key" ]]; then
    if [[ -z "$lan_ip" ]] || openssl x509 -in "$cert" -noout -ext subjectAltName 2>/dev/null \
        | grep -Fq "IP Address:$lan_ip"; then
      return
    fi
  elif [[ -e "$cert" || -e "$key" ]]; then
    echo "Error: only one of $cert and $key exists; refusing to replace either file." >&2
    echo "Restore the matching certificate/key pair or remove both files to generate a local certificate." >&2
    exit 1
  fi

  generate_local_certificate "$lan_ip"
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
    ensure_local_certificate
    say "LAN access disabled; Horus is available on this machine only."
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
  ensure_local_certificate "$lan_ip"
  say "LAN access enabled. Other devices can use https://$lan_ip:3000."
}

if [[ ! -f "$EXAMPLE" ]]; then
  echo "Error: missing $EXAMPLE"
  exit 1
fi

if [[ -f "$TARGET" ]]; then
  if [[ "$FORCE" -eq 0 ]]; then
    current_bind="$(sed -n 's/^HORUS_WEB_BIND=//p' "$TARGET" | tail -n 1)"
    configure_network_access "${current_bind:-127.0.0.1}"
    if [[ ! -t 0 || "$QUIET" -eq 1 ]]; then
      if [[ "$current_bind" == "0.0.0.0" ]]; then
        lan_ip="$(detect_lan_ipv4 || true)"
        if [[ -z "$lan_ip" ]] || ! valid_lan_ipv4 "$lan_ip"; then
          echo "Error: LAN access is enabled but this PC's LAN IPv4 address could not be detected." >&2
          echo "Run init-env.sh interactively or provide a certificate covering the address used by other devices." >&2
          exit 1
        fi
        ensure_local_certificate "$lan_ip"
      else
        ensure_local_certificate
      fi
    fi
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

if [[ ! -t 0 || "$QUIET" -eq 1 ]]; then
  ensure_local_certificate
fi

say "Created $TARGET with generated JWT_SECRET_KEY and REDIS_PASSWORD (64 hex chars each), plus admin and agent account passwords."
say "The admin account signs in with the SUPER_USER_USERNAME and the generated SUPER_USER_PASSWORD in $TARGET."
say "The Agent service uses SUPER_AGENT_USERNAME and SUPER_AGENT_PASSWORD from $TARGET to register its workers."
say "Next: docker compose up --build from this directory, or ./stack-up.sh from the top of this folder, then sign in in the web UI."
