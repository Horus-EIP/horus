#!/bin/bash
#
# Horus Demo Runner Script
# 
# This script sets up and runs the complete Horus demo environment.
# It starts all services, seeds demo data, and provides access URLs.
#
# Usage:
#   ./run_demo.sh              # Start demo
#   ./run_demo.sh --reset      # Reset and restart demo
#   ./run_demo.sh --stop       # Stop demo
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
INFRA_DIR="$PROJECT_ROOT/src/infra"

# URLs
MAS_URL="http://localhost:8000"
KNOWLEDGE_STORE_URL="http://localhost:8080"
WEB_CLIENT_URL="http://localhost:3000"
GRAFANA_URL="http://localhost:3001"
JAEGER_URL="http://localhost:16686"
PROMETHEUS_URL="http://localhost:9090"

print_header() {
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  🦅 HORUS MULTI-AGENT SYSTEM - DEMO${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo ""
}

print_urls() {
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  🌐 ACCESS URLS                                            ║${NC}"
    echo -e "${GREEN}╠════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║  Web Client:      ${NC}$WEB_CLIENT_URL"
    echo -e "${GREEN}║  MAS API:         ${NC}$MAS_URL"
    echo -e "${GREEN}║  API Docs:        ${NC}$MAS_URL/docs"
    echo -e "${GREEN}║  Knowledge Store: ${NC}$KNOWLEDGE_STORE_URL"
    echo -e "${GREEN}║  Grafana:         ${NC}$GRAFANA_URL ${YELLOW}(admin/admin)${NC}"
    echo -e "${GREEN}║  Jaeger:          ${NC}$JAEGER_URL"
    echo -e "${GREEN}║  Prometheus:      ${NC}$PROMETHEUS_URL"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

wait_for_service() {
    local url=$1
    local name=$2
    local max_attempts=30
    local attempt=1
    
    echo -n "   Waiting for $name"
    while [ $attempt -le $max_attempts ]; do
        if curl -s -o /dev/null -w "%{http_code}" "$url" | grep -q "200\|301\|302"; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        fi
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    echo -e " ${RED}✗${NC}"
    return 1
}

start_services() {
    echo -e "${YELLOW}1️⃣  Starting Docker services...${NC}"
    cd "$INFRA_DIR"
    docker compose up -d
    echo -e "   ${GREEN}✓ Services starting${NC}"
    echo ""
    
    echo -e "${YELLOW}2️⃣  Waiting for services to be ready...${NC}"
    sleep 10  # Initial wait
    
    wait_for_service "$MAS_URL/docs" "MAS API"
    wait_for_service "$KNOWLEDGE_STORE_URL/health" "Knowledge Store"
    wait_for_service "$PROMETHEUS_URL/-/ready" "Prometheus"
    
    echo ""
}

seed_data() {
    echo -e "${YELLOW}3️⃣  Seeding demo data...${NC}"
    cd "$SCRIPT_DIR"
    
    if command -v python3 &> /dev/null; then
        python3 seed_demo_data.py --url "$MAS_URL" --ks-url "$KNOWLEDGE_STORE_URL"
    else
        echo -e "   ${RED}Python3 not found. Please run seed_demo_data.py manually.${NC}"
    fi
    echo ""
}

stop_services() {
    echo -e "${YELLOW}Stopping services...${NC}"
    cd "$INFRA_DIR"
    docker compose down
    echo -e "${GREEN}✓ Services stopped${NC}"
}

reset_demo() {
    echo -e "${YELLOW}Resetting demo environment...${NC}"
    cd "$INFRA_DIR"
    docker compose down -v
    echo -e "${GREEN}✓ Volumes removed${NC}"
    
    start_services
    seed_data
}

# Main script
print_header

case "${1:-}" in
    --stop)
        stop_services
        ;;
    --reset)
        reset_demo
        print_urls
        ;;
    *)
        start_services
        seed_data
        print_urls
        
        echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║  🎬 DEMO READY!                                            ║${NC}"
        echo -e "${GREEN}║                                                            ║${NC}"
        echo -e "${GREEN}║  Try these queries in the Web Client:                      ║${NC}"
        echo -e "${GREEN}║  • \"What was our Q1 revenue?\"                              ║${NC}"
        echo -e "${GREEN}║  • \"Summarize the product roadmap\"                         ║${NC}"
        echo -e "${GREEN}║  • \"What is our customer acquisition cost?\"                ║${NC}"
        echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
        echo ""
        ;;
esac
