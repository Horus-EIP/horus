#!/bin/bash
set -e

# Setup environment for testing
export PYTHONPATH=$PYTHONPATH:$(pwd)/src/services/agent/app
export TEST_MODE=true
export LANGCHAIN_TRACING_V2=false
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1

echo "================================================="
echo "Running Robust Test Suite for Agent Services"
echo "================================================="
echo "Python: $(python3 --version)"
echo "Pytest: $(pytest --version)"
echo "Current Dir: $(pwd)"
echo "Mode: TEST_MODE=$TEST_MODE"
echo "================================================="

# Clean previous reports
rm -rf htmlcov
rm -f .coverage

# Run tests with coverage
# -v: Verbose
# --cov: Coverage source
# --cov-report: Generate HTML report
# -p no:langsmith: Disable LangSmith tracing to prevent network hangs/errors
pytest -v \
    -p no:langsmith \
    --cov-report=html:htmlcov \
    --cov-report=term-missing \
    app/tests/ 

echo "================================================="
echo "Tests Completed."
echo "Coverage report generated at: htmlcov/index.html"
echo "================================================="
