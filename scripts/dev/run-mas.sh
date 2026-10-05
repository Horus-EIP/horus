#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MAS_DIR="$REPO_ROOT/src/services/mas"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🚀 Starting MAS Service Locally...${NC}"

# Check if .env exists in infra, if so export variables
if [ -f "$REPO_ROOT/src/infra/.env" ]; then
    echo -e "${YELLOW}📝 Loading environment variables from src/infra/.env${NC}"
    # Use sed to remove comments (lines starting with # and inline comments)
    export $(grep -v '^#' "$REPO_ROOT/src/infra/.env" | sed 's/#.*//g' | xargs)
    # Override DB_HOST for local execution if it's set to a container name
    if [ "$DB_HOST" = "postgres" ]; then
        export DB_HOST=localhost
        echo -e "${YELLOW}🔄 Overriding DB_HOST to localhost${NC}"
    fi
    if [ "$REDIS_HOST" = "redis" ]; then
        export REDIS_HOST=localhost
        echo -e "${YELLOW}🔄 Overriding REDIS_HOST to localhost${NC}"
    fi
    if [ "$RABBITMQ_HOST" = "rabbitmq" ]; then
        export RABBITMQ_HOST=localhost
        echo -e "${YELLOW}🔄 Overriding RABBITMQ_HOST to localhost${NC}"
    fi
fi

cd "$MAS_DIR" || exit 1

# 1. Run Migrations
echo -e "${YELLOW}🔄 Running Database Migrations...${NC}"
(cd db && alembic upgrade head)
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Migration failed!${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Migrations applied successfully.${NC}"

# 2. Initialize Database (Create Admin User)
echo -e "${YELLOW}👤 Initializing Database (Admin User)...${NC}"
python3 -c "from db.init_setup import init_db; init_db()"
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Database initialization failed!${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Database initialized successfully.${NC}"

# 3. Start Uvicorn
echo -e "${GREEN}🚀 Starting Uvicorn Server...${NC}"
# Disable LLM auto-init for faster local startup by default, unless specified
export LLM_AUTOINIT=${LLM_AUTOINIT:-0}
uvicorn main:app --host 0.0.0.0 --port 8000 --ws-ping-interval 20 --ws-ping-timeout 120
