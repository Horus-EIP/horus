#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_VERSION=3.11
PLATFORM=x86_64-manylinux_2_28
EXTRA=("$@")

compile() {
    uv pip compile "$@" "${EXTRA[@]}" \
        --python-version "$PYTHON_VERSION" --python-platform "$PLATFORM" \
        --generate-hashes --no-config --quiet \
        --custom-compile-command "scripts/dev/lock-requirements.sh"
}

for service in mas agent knowledge-store; do
    cd "$REPO_ROOT/src/services/$service"
    compile requirements-gpu.txt -o requirements-gpu.lock
    for requirements in requirements*.txt; do
        case "$requirements" in requirements-gpu.txt | requirements-test.txt) continue ;; esac
        compile "$requirements" --constraint requirements-gpu.lock -o "${requirements%.txt}.lock"
    done
    echo "locked src/services/$service"
done
