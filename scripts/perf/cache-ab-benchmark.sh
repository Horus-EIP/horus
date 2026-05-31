#!/usr/bin/env bash
# Cache A/B benchmark — measures the lift from Redis-cached read endpoints.
#
# Runs scripts/perf/benchmark-mas.py twice:
#   1. with MAS_READ_CACHE_ENABLED=0 (baseline)
#   2. with MAS_READ_CACHE_ENABLED=1 (optimized)
#
# Both JSON files are written to scripts/perf/results-archive/ so the
# before/after diff is obvious in git. Updates the K3 row in
# docs/eip/performance.md is a manual step after running.
#
# Usage:
#   scripts/perf/cache-ab-benchmark.sh                     # default: 100 iterations
#   scripts/perf/cache-ab-benchmark.sh --iterations 500    # heavier run
#
# Prerequisites:
#   - Docker Compose stack running (mas, redis, postgres at least)
#   - MAS image supports the MAS_READ_CACHE_ENABLED env var
#   - Active venv with httpx installed (or run via docker exec)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

ITERATIONS="${ITERATIONS:-100}"
MAS_URL="${MAS_URL:-http://localhost:8000}"
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"

# Optional flag passthrough
if [[ "${1:-}" == "--iterations" ]] && [[ -n "${2:-}" ]]; then
    ITERATIONS="$2"
fi

ARCHIVE="$SCRIPT_DIR/results-archive"
mkdir -p "$ARCHIVE"

run_phase() {
    local phase="$1"        # baseline | optimized
    local cache_val="$2"    # 0 | 1
    echo ""
    echo "================================================================"
    echo "Phase: $phase  (MAS_READ_CACHE_ENABLED=$cache_val, iterations=$ITERATIONS)"
    echo "================================================================"

    # Toggle the env var on the running mas container, then restart it.
    # `docker compose up -d --force-recreate mas` re-reads env when paired
    # with an env override; the simplest portable approach is `docker exec`
    # the new value via a .env override + compose restart.
    pushd "$REPO_ROOT/src/infra" >/dev/null
    MAS_READ_CACHE_ENABLED="$cache_val" docker compose up -d --force-recreate mas
    popd >/dev/null

    # Give MAS a moment to come up
    echo "Waiting 15s for MAS to settle..."
    sleep 15

    local out_file="$ARCHIVE/cache-${phase}-${STAMP}.json"
    python3 "$SCRIPT_DIR/benchmark-mas.py" \
        --url "$MAS_URL" \
        --iterations "$ITERATIONS" \
        --output "$out_file"

    echo ""
    echo "Wrote: $out_file"
}

run_phase "baseline" "0"
run_phase "optimized" "1"

echo ""
echo "================================================================"
echo "Done. Compare the two JSONs:"
echo "  diff -u <(jq . $ARCHIVE/cache-baseline-${STAMP}.json) \\"
echo "          <(jq . $ARCHIVE/cache-optimized-${STAMP}.json) | less"
echo ""
echo "Then update docs/eip/performance.md (Opt-1 entry)."
echo "================================================================"
