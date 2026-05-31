#!/usr/bin/env bash
# Capture Grafana dashboards as PNGs while a load test is running.
#
# Drives a headless Chromium/Chrome to take screenshots of the configured
# Grafana panels and drops them in greenlight/grafana-screenshots/, which is
# part of the EIP greenlight deliverables (Tech 4 Objective D).
#
# Usage:
#   # 1. Make sure the stack is up and a load test is generating traffic, e.g.:
#   cd scripts/perf && locust -f load-locust.py --headless -u 20 -r 5 -t 5m &
#
#   # 2. Run this script to capture screenshots:
#   scripts/perf/capture-dashboards.sh
#
# Requires:
#   - Chromium or Google Chrome on PATH (any of: chromium, chromium-browser,
#     google-chrome, "Google Chrome", chrome).
#   - Grafana reachable at GRAFANA_URL (default http://localhost:3301).
#
# Configure dashboards to capture by editing the DASHBOARDS array below.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3301}"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/greenlight/grafana-screenshots}"
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
WIDTH="${WIDTH:-1600}"
HEIGHT="${HEIGHT:-1000}"

mkdir -p "$OUT_DIR"

# (slug, friendly-name) pairs. Slug must match the dashboard URL slug or the
# UID path. Adjust to your Grafana dashboard URLs.
DASHBOARDS=(
    "mas-overview:MAS Overview"
    "horus-stack-logs:Stack Logs"
)

# --- find chromium binary ---
CHROME_BIN=""
for candidate in chromium chromium-browser google-chrome "google-chrome-stable" chrome; do
    if command -v "$candidate" >/dev/null 2>&1; then
        CHROME_BIN="$(command -v "$candidate")"
        break
    fi
done
# macOS Chrome fallback
if [[ -z "$CHROME_BIN" && -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]]; then
    CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
fi
if [[ -z "$CHROME_BIN" ]]; then
    echo "ERROR: no Chromium/Chrome binary found on PATH." >&2
    echo "Install one of: chromium, google-chrome." >&2
    exit 1
fi

echo "Using browser: $CHROME_BIN"
echo "Grafana: $GRAFANA_URL"
echo "Output:  $OUT_DIR"
echo ""

# Grafana anonymous viewing is enabled in src/infra/docker-compose.yml
# (GF_AUTH_ANONYMOUS_ENABLED=true), so we don't need credentials.

for entry in "${DASHBOARDS[@]}"; do
    slug="${entry%%:*}"
    name="${entry#*:}"
    url="$GRAFANA_URL/d/$slug?orgId=1&kiosk&from=now-${GRAFANA_WINDOW:-30m}&to=now"
    out="$OUT_DIR/${slug}-${STAMP}.png"
    echo "→ $name"
    echo "   URL: $url"
    echo "   PNG: $out"
    "$CHROME_BIN" \
        --headless=new \
        --hide-scrollbars \
        --disable-gpu \
        --no-sandbox \
        --window-size="${WIDTH},${HEIGHT}" \
        --screenshot="$out" \
        --virtual-time-budget=25000 \
        "$url" >/dev/null 2>&1 || {
            echo "   FAILED (browser exited non-zero)"
            continue
        }
    echo "   OK"
done

echo ""
echo "Done. Captured PNGs in $OUT_DIR"
ls -1 "$OUT_DIR" | tail -n +1
