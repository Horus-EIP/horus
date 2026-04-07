#!/bin/bash
# Run pytest for each Python service (separate PYTHONPATH; do not merge).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== MAS (unit, excluding integration) ==="
pytest -c tests/mas/pytest.ini tests/mas \
    --ignore=tests/mas/test_integration.py "$@"

echo "=== Knowledge Store ==="
pytest -c tests/knowledge_store/pytest.ini tests/knowledge_store "$@"

echo "=== Agent ==="
pytest -c tests/agent/pytest.ini tests/agent "$@"
