#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export LLM_AUTOINIT=0
pytest -c tests/mas/pytest.ini tests/mas --cov=src/services/mas --cov-report=html

if [ -n "${DISPLAY:-}" ]; then
    python -m webbrowser htmlcov/index.html
fi
