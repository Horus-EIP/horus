#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
KS_DIR="$REPO_ROOT/src/services/knowledge-store"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🚀 Starting Knowledge Store Service Locally...${NC}"

# Check if .env exists in infra, if so export variables
if [ -f "$REPO_ROOT/src/infra/.env" ]; then
    echo -e "${YELLOW}📝 Loading environment variables from src/infra/.env${NC}"
    export $(grep -v '^#' "$REPO_ROOT/src/infra/.env" | sed 's/#.*//g' | xargs)
fi

cd "$KS_DIR" || exit 1

# Start Uvicorn
echo -e "${GREEN}🚀 Starting Uvicorn Server...${NC}"
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
