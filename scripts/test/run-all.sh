#!/bin/bash
# Run pytest for each Python service (separate PYTHONPATH; do not merge).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# No OTLP collector in CI/local unless explicitly enabled; avoids jaeger:4317 DNS errors
# and logging thread issues when redirecting stdout (e.g. ./run_all_python_tests.sh > log).
export OTEL_ENABLED="${OTEL_ENABLED:-false}"
export OTEL_TRACES_EXPORTER="${OTEL_TRACES_EXPORTER:-none}"

# passlib 1.7.4 is incompatible with bcrypt>=4.1 (long-password self-test fails).
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python
"$PY" -m pip install "bcrypt==5.0.0" -q

echo "=== MAS (unit, excluding integration) ==="
pytest -c tests/mas/pytest.ini tests/mas \
    --ignore=tests/mas/test_integration.py \
    --ignore=tests/mas/client_tests/test_beta_integration.py \
    "$@"

echo "=== Knowledge Store ==="
pytest -c tests/knowledge_store/pytest.ini tests/knowledge_store "$@"

echo "=== Agent ==="
pytest -c tests/agent/pytest.ini tests/agent "$@"
