#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🚀 Starting Knowledge Store Service Locally...${NC}"

# Check if .env exists in infra, if so export variables
if [ -f "../../infra/.env" ]; then
    echo -e "${YELLOW}📝 Loading environment variables from ../../infra/.env${NC}"
    export $(grep -v '^#' ../../infra/.env | sed 's/#.*//g' | xargs)
fi

# Ensure we are in the right directory
cd "$(dirname "$0")"

# Start Uvicorn
echo -e "${GREEN}🚀 Starting Uvicorn Server...${NC}"
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
