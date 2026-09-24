#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export TEST_MODE=true
export LANGCHAIN_TRACING_V2=false
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1

echo "================================================="
echo "Running Robust Test Suite for Agent Services"
echo "================================================="
echo "Python: $(python3 --version)"
echo "Pytest: $(pytest --version)"
echo "Repo root: $REPO_ROOT"
echo "Mode: TEST_MODE=$TEST_MODE"
echo "================================================="

rm -rf htmlcov
rm -f .coverage

pytest -c tests/agent/pytest.ini tests/agent -v \
    -p no:langsmith \
    --cov-report=html:htmlcov \
    --cov-report=term-missing \
    --cov=src/services/agent/app

echo "================================================="
echo "Tests Completed."
echo "Coverage report generated at: htmlcov/index.html"
echo "================================================="
