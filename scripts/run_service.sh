#!/bin/bash

# ATMS - Run Service Script
# Usage: ./scripts/run_service.sh <service-name>

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check arguments
if [ -z "$1" ]; then
    echo -e "${RED}Error: Service name required${NC}"
    echo -e "${YELLOW}Usage: $0 <service-name>${NC}"
    echo -e "${YELLOW}Example: $0 sensor-fusion${NC}"
    exit 1
fi

SERVICE_NAME=$1
SERVICE_DIR="services/${SERVICE_NAME}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Check if service exists
if [ ! -d "${PROJECT_ROOT}/${SERVICE_DIR}" ]; then
    echo -e "${RED}Error: Service '${SERVICE_NAME}' not found${NC}"
    echo -e "${YELLOW}Available services:${NC}"
    ls -1 "${PROJECT_ROOT}/services/" 2>/dev/null || echo "  (none)"
    exit 1
fi

echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           ATMS - Running ${SERVICE_NAME} Service        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

cd "${PROJECT_ROOT}/${SERVICE_DIR}"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Virtual environment not found. Creating...${NC}"
    python3.11 -m venv venv || python3 -m venv venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi

# Activate virtual environment
source venv/bin/activate

# Check if requirements are installed
if [ -f "requirements.txt" ]; then
    echo -e "${YELLOW}Checking dependencies...${NC}"
    pip install -q -r requirements.txt
    echo -e "${GREEN}✓ Dependencies installed${NC}"
fi

# Check for .env file
if [ ! -f ".env" ] && [ -f "env.example" ]; then
    echo -e "${YELLOW}⚠ .env file not found${NC}"
    echo -e "${YELLOW}Creating from env.example...${NC}"
    cp env.example .env
    echo -e "${GREEN}✓ .env file created (please configure)${NC}"
fi

# Run the service
if [ -f "src/main.py" ]; then
    echo ""
    echo -e "${GREEN}Starting ${SERVICE_NAME} service...${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    cd src
    python main.py
else
    echo -e "${RED}Error: main.py not found in ${SERVICE_DIR}/src/${NC}"
    exit 1
fi

