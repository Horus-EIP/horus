#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

export LLM_AUTOINIT=0
pytest -c tests/knowledge_store/pytest.ini tests/knowledge_store \
    --cov=src/services/knowledge-store/app \
    --cov-report=html

# Only try to open browser if we have a display
if [ -n "$DISPLAY" ]; then
    python -m webbrowser htmlcov/index.html
fi
