#!/usr/bin/env bash
# generate_docs.sh
# ----------------
# Build browsable HTML documentation from all project sources and open
# the result in a browser.
#
# Three documentation layers are generated:
#   1. Markdown docs  -> MkDocs site          (docs/ folder)
#   2. Python API     -> pdoc HTML            (all three Python services)
#   3. TypeScript API -> TypeDoc HTML         (web-client)
#
# Prerequisites (install once):
#   pip install mkdocs mkdocs-material mkdocs-mermaid2-plugin pdoc
#   cd src/services/web-client && npm install --save-dev typedoc
#
# Python API docs (pdoc) import your service code. You need the same
# dependencies as the apps (at least FastAPI and transitive imports), e.g.:
#
#   python3 -m venv .venv && source .venv/bin/activate   # recommended
#   python3 -m pip install -r src/services/mas/requirements-cpu.txt
#   python3 -m pip install -r src/services/agent/requirements.txt
#   python3 -m pip install -r src/services/knowledge-store/requirements.txt
#
# Or install in one step (large download; may take several minutes):
#   ./scripts/generate_docs.sh --install-python-deps
#
# pdoc is invoked as "${PYTHON3:-python3} -m pdoc" so it uses the SAME interpreter
# as "${PYTHON3} -m pip install". If you use a venv, point PYTHON3 at it:
#   PYTHON3=.venv/bin/python3 ./scripts/generate_docs.sh
#
# Usage:
#   ./scripts/generate_docs.sh                       # build + open in browser
#   ./scripts/generate_docs.sh --serve               # build + live-reload MkDocs
#   ./scripts/generate_docs.sh --install-python-deps # pip install service deps, then build
#   ./scripts/generate_docs.sh --help

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="${REPO_ROOT}/_docs_build"
PYTHON3="${PYTHON3:-python3}"

DO_SERVE=0
INSTALL_PY_DEPS=0
for arg in "$@"; do
    case "$arg" in
        --serve) DO_SERVE=1 ;;
        --install-python-deps) INSTALL_PY_DEPS=1 ;;
        --help|-h)
            grep '^# ' "$0" | sed 's/^# \{0,1\}//' | head -40
            exit 0
            ;;
    esac
done

echo "=== Horus AI Documentation Generator ==="
echo ""

# -----------------------------------------------------------------
# 0. Check dependencies
# -----------------------------------------------------------------
check_cmd() {
    if ! command -v "$1" &> /dev/null; then
        echo "ERROR: '$1' is not installed."
        echo "  Install it with: $2"
        exit 1
    fi
}

check_cmd mkdocs   "pip install mkdocs mkdocs-material mkdocs-mermaid2-plugin"

if ! "$PYTHON3" -c "import pdoc" 2>/dev/null; then
    echo "ERROR: pdoc is not installed for: $("$PYTHON3" -c 'import sys; print(sys.executable)')"
    echo "  Install with:  ${PYTHON3} -m pip install pdoc"
    exit 1
fi

echo "[ok] All required CLI tools found."
echo "    Python for pdoc / pip: $("$PYTHON3" -c 'import sys; print(sys.executable)')"
echo ""

if [[ "$INSTALL_PY_DEPS" -eq 1 ]]; then
    echo "--- Installing Python dependencies for pdoc (service requirements) ---"
    "$PYTHON3" -m pip install -r "${REPO_ROOT}/src/services/mas/requirements-cpu.txt"
    "$PYTHON3" -m pip install -r "${REPO_ROOT}/src/services/agent/requirements.txt"
    "$PYTHON3" -m pip install -r "${REPO_ROOT}/src/services/knowledge-store/requirements.txt"
    echo "[ok] Python service requirements installed."
    echo ""
fi

# -----------------------------------------------------------------
# 1. Build Markdown docs site with MkDocs
# -----------------------------------------------------------------
echo "--- Building MkDocs site (Markdown docs) ---"

MKDOCS_DIR="${BUILD_DIR}/mkdocs"

# Generate mkdocs.yml on the fly (lives under docs/; docs_dir is this folder)
cat > "${REPO_ROOT}/docs/mkdocs.yml" <<'MKDOCSEOF'
site_name: Horus AI Documentation
site_description: Documentation for the Horus AI multi-agent orchestration platform
docs_dir: .
site_dir: ../_docs_build/mkdocs

theme:
  name: material
  palette:
    - scheme: default
      primary: deep purple
      accent: amber
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - scheme: slate
      primary: deep purple
      accent: amber
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
  features:
    - navigation.sections
    - navigation.expand
    - search.suggest
    - content.code.copy

plugins:
  - search
  - mermaid2

markdown_extensions:
  - tables
  - fenced_code
  - codehilite
  - toc:
      permalink: true
  - admonition
  # Enables {#custom-id} on headings (e.g. MAS API TOC anchor for RabbitMQ section)
  - attr_list
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:mermaid2.fence_mermaid_custom

nav:
  - Home: README.md
  - Getting Started:
      - Onboarding: getting-started/onboarding.md
      - Configuration: getting-started/configuration.md
      - Troubleshooting: getting-started/troubleshooting.md
  - Architecture:
      - Overview: architecture/overview.md
      - Data Model: architecture/data-model.md
  - API Reference:
      - MAS API: api/mas-api.md
      - Knowledge Store API: api/knowledge-store-api.md
      - WebSocket API: api/websocket-api.md
  - Operations:
      - Deployment: operations/deployment.md
      - Monitoring: operations/monitoring.md
      - Secrets Management: operations/secrets-management.md
      - Environment Matrix: operations/environment-matrix.md
  - Contributing:
      - Guide: contributing/contributing.md
      - Workflow: contributing/workflow.md
      - Commit Convention: contributing/commit-convention.md
      - Testing Policy: contributing/testing-policy.md
      - Issues: contributing/issues.md
  - Security:
      - RBAC: security/rbac.md
      - Security Audit: security/security-audit.md
  - Compliance:
      - Architecture Fiche: compliance/architecture_fiche.md
      - Data Protection: compliance/data_protection.md
      - Telemetry: compliance/telemetry.md
MKDOCSEOF

cd "${REPO_ROOT}"
mkdocs build -f docs/mkdocs.yml --clean --quiet
echo "[ok] MkDocs site built at ${MKDOCS_DIR}"
echo ""

# -----------------------------------------------------------------
# 2. Build Python API docs with pdoc
# -----------------------------------------------------------------
echo "--- Building Python API docs (pdoc) ---"

if ! "$PYTHON3" -c "import fastapi" 2>/dev/null; then
    echo "  [hint] FastAPI is not installed for ${PYTHON3}."
    echo "        pdoc imports your services; install their requirements, for example:"
    echo "          ./scripts/generate_docs.sh --install-python-deps"
    echo "        (or ${PYTHON3} -m pip install -r src/services/mas/requirements-cpu.txt \\"
    echo "            && ${PYTHON3} -m pip install -r src/services/agent/requirements.txt \\"
    echo "            && ${PYTHON3} -m pip install -r src/services/knowledge-store/requirements.txt)"
    echo ""
fi

PYTHON_DOCS="${BUILD_DIR}/python-api"
mkdir -p "${PYTHON_DOCS}"

pdoc_log_and_run() {
    local svc_label="$1"
    shift
    local log
    log="$(mktemp)"
    if "$@" 2>"$log"; then
        rm -f "$log"
        return 0
    fi
    echo "  [warn] pdoc exited with errors for ${svc_label}. Last output:"
    tail -40 "$log" | sed 's/^/    /'
    rm -f "$log"
    return 0
}

# MAS service (-- same Python as "${PYTHON3} -m pip" so site-packages match)
echo "  -> MAS service..."
pdoc_log_and_run "MAS" env PYTHONPATH="${REPO_ROOT}/src/services/mas" "$PYTHON3" -m pdoc \
    --output-directory "${PYTHON_DOCS}/mas" \
    --docformat google \
    core db schemas auth agents tasks chat conversations users main

# Agent service
echo "  -> Agent service..."
pdoc_log_and_run "Agent" env PYTHONPATH="${REPO_ROOT}/src/services/agent/app" "$PYTHON3" -m pdoc \
    --output-directory "${PYTHON_DOCS}/agent" \
    --docformat google \
    config core ai_agents specialized agent_server

# Knowledge Store
echo "  -> Knowledge Store..."
pdoc_log_and_run "Knowledge Store" env PYTHONPATH="${REPO_ROOT}/src/services/knowledge-store" "$PYTHON3" -m pdoc \
    --output-directory "${PYTHON_DOCS}/knowledge-store" \
    --docformat google \
    app

echo "[ok] Python API docs at ${PYTHON_DOCS}"
echo ""

# -----------------------------------------------------------------
# 3. Build TypeScript API docs with TypeDoc (optional)
# -----------------------------------------------------------------
echo "--- Building TypeScript API docs (TypeDoc) ---"

TS_DOCS="${BUILD_DIR}/typescript-api"
WEB_CLIENT="${REPO_ROOT}/src/services/web-client"

if [ -f "${WEB_CLIENT}/node_modules/.bin/typedoc" ]; then
    cd "${WEB_CLIENT}"
    npx typedoc \
        --entryPoints "lib" "hooks" "contexts" "components" "utils" \
        --entryPointStrategy expand \
        --out "${TS_DOCS}" \
        --skipErrorChecking \
        --exclude "**/__tests__/**" \
        --exclude "**/node_modules/**" \
        2>/dev/null || echo "  [warn] TypeDoc had some errors. Partial docs generated."
    echo "[ok] TypeScript docs at ${TS_DOCS}"
else
    echo "  [skip] typedoc not installed. Run: cd src/services/web-client && npm install --save-dev typedoc"
fi
echo ""

# -----------------------------------------------------------------
# 4. Create index page linking everything together
# -----------------------------------------------------------------
INDEX="${BUILD_DIR}/index.html"
cat > "${INDEX}" <<'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Horus AI - Documentation</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #0f0f23; color: #e0e0e0; min-height: 100vh;
               display: flex; align-items: center; justify-content: center; }
        .container { max-width: 700px; padding: 3rem 2rem; }
        h1 { font-size: 2.4rem; margin-bottom: 0.5rem; color: #fff; }
        .subtitle { color: #888; margin-bottom: 2.5rem; font-size: 1.1rem; }
        .cards { display: grid; gap: 1rem; }
        a.card { display: block; padding: 1.4rem 1.6rem; background: #1a1a3e;
                 border: 1px solid #2a2a5e; border-radius: 10px; text-decoration: none;
                 color: #e0e0e0; transition: all 0.2s; }
        a.card:hover { background: #24245a; border-color: #7c3aed; transform: translateY(-2px); }
        .card h2 { font-size: 1.15rem; color: #a78bfa; margin-bottom: 0.3rem; }
        .card p { font-size: 0.9rem; color: #888; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Horus AI</h1>
        <p class="subtitle">Project Documentation</p>
        <div class="cards">
            <a class="card" href="mkdocs/index.html">
                <h2>Project Documentation</h2>
                <p>Architecture, API reference, guides, configuration, and operations.</p>
            </a>
            <a class="card" href="python-api/mas/index.html">
                <h2>Python API -- MAS Orchestrator</h2>
                <p>Auto-generated from docstrings (pdoc). Modules: core, db, auth, agents, tasks, chat.</p>
            </a>
            <a class="card" href="python-api/agent/index.html">
                <h2>Python API -- Agent Service</h2>
                <p>Auto-generated from docstrings (pdoc). Modules: ai_agents, specialized, config.</p>
            </a>
            <a class="card" href="python-api/knowledge-store/index.html">
                <h2>Python API -- Knowledge Store</h2>
                <p>Auto-generated from docstrings (pdoc). Modules: api, chroma_db, services.</p>
            </a>
            <a class="card" href="typescript-api/index.html">
                <h2>TypeScript API -- Web Client</h2>
                <p>Auto-generated from TSDoc (TypeDoc). Modules: lib, hooks, components.</p>
            </a>
        </div>
    </div>
</body>
</html>
HTMLEOF

echo "[ok] Index page at ${INDEX}"
echo ""

# -----------------------------------------------------------------
# 5. Open or serve
# -----------------------------------------------------------------
if [[ "$DO_SERVE" -eq 1 ]]; then
    echo "Starting live-reload server for MkDocs on http://localhost:8800 ..."
    echo "(Python/TS API docs are static at ${BUILD_DIR})"
    cd "${REPO_ROOT}"
    mkdocs serve -f docs/mkdocs.yml --dev-addr localhost:8800
else
    echo "=== Build complete ==="
    echo ""
    echo "Open in browser:"
    echo "  ${INDEX}"
    echo ""
    echo "Or start a live-reload server:"
    echo "  ./scripts/generate_docs.sh --serve"
    echo ""

    # Try to open automatically
    if command -v open &> /dev/null; then
        open "${INDEX}"
    elif command -v xdg-open &> /dev/null; then
        xdg-open "${INDEX}"
    fi
fi
