#!/bin/bash

# ================================
# Vision AI Training Platform - Infrastructure Startup Script (Linux/Mac)
# ================================
#
# This script starts the required infrastructure services.
#
# Usage:
#   ./start-infra.sh                    # Start core services only
#   ./start-infra.sh --with-obs         # Start with ClearML, MLflow, Grafana
#   ./start-infra.sh --stop             # Stop all services
#   ./start-infra.sh --clean            # Stop and remove volumes (CAUTION!)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Parse arguments
WITH_OBSERVABILITY=false
STOP=false
CLEAN=false

for arg in "$@"; do
    case $arg in
        --with-obs|--observability)
            WITH_OBSERVABILITY=true
            ;;
        --stop)
            STOP=true
            ;;
        --clean)
            CLEAN=true
            STOP=true
            ;;
        *)
            echo -e "${RED}Unknown argument: $arg${NC}"
            echo "Usage: $0 [--with-obs] [--stop] [--clean]"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}Vision AI Training Platform${NC}"
echo -e "${CYAN}Infrastructure Management${NC}"
echo -e "${CYAN}================================${NC}"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}ERROR: Docker is not running!${NC}"
    echo -e "${YELLOW}Please start Docker and try again.${NC}"
    exit 1
fi

# Stop services
if [ "$STOP" = true ]; then
    echo -e "${YELLOW}Stopping services...${NC}"

    if [ "$WITH_OBSERVABILITY" = true ]; then
        docker-compose -f docker-compose.yml -f docker-compose.observability.yml down
    else
        docker-compose down
    fi

    if [ "$CLEAN" = true ]; then
        echo -e "${RED}WARNING: This will delete all data!${NC}"
        read -p "Are you sure? (yes/no): " confirmation
        if [ "$confirmation" = "yes" ]; then
            echo -e "${YELLOW}Removing volumes...${NC}"
            docker-compose down -v
            if [ "$WITH_OBSERVABILITY" = true ]; then
                docker-compose -f docker-compose.observability.yml down -v
            fi
            echo -e "${GREEN}All data removed.${NC}"
        else
            echo -e "${YELLOW}Cancelled.${NC}"
        fi
    fi

    echo -e "${GREEN}Services stopped.${NC}"
    exit 0
fi

# Start services
echo -e "${GREEN}Starting infrastructure services...${NC}"
echo ""

# Core services
echo -e "${CYAN}Starting core services:${NC}"
echo "  - PostgreSQL (Platform DB): localhost:5432"
echo "  - PostgreSQL (User DB):     localhost:5433"
echo "  - Redis:                    localhost:6379"
echo "  - Temporal:                 localhost:7233 (gRPC), 8233 (UI)"
echo "  - MinIO (Datasets):         localhost:9000 (API), 9001 (Console)"
echo "  - MinIO (Results):          localhost:9002 (API), 9003 (Console)"
echo ""

docker-compose up -d

# Observability services
if [ "$WITH_OBSERVABILITY" = true ]; then
    echo ""
    echo -e "${CYAN}Starting observability services:${NC}"
    echo "  - ClearML API:      localhost:8008"
    echo "  - ClearML Web UI:   localhost:8080"
    echo "  - ClearML Files:    localhost:8081"
    echo "  - MLflow:           localhost:5000"
    echo "  - Loki:             localhost:3100"
    echo "  - Grafana:          localhost:3200"
    echo ""

    docker-compose -f docker-compose.yml -f docker-compose.observability.yml up -d
fi

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Infrastructure started successfully!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""

# Wait for services to be healthy
echo -e "${YELLOW}Waiting for services to be ready...${NC}"
sleep 10

# Check service health
echo ""
echo -e "${CYAN}Service Status:${NC}"
docker-compose ps

echo ""
echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}Next Steps:${NC}"
echo -e "${CYAN}================================${NC}"
echo ""
echo "1. Configure environment variables:"
echo "   cd ../backend"
echo "   cp .env.example .env"
echo "   # Edit .env with your API keys"
echo ""
echo "2. Start Backend:"
echo "   cd ../backend"
echo "   poetry run uvicorn app.main:app --reload --port 8000"
echo ""
echo "3. Start Temporal Worker:"
echo "   cd ../backend"
echo "   poetry run python -m app.workflows.worker"
echo ""
echo "4. Start Frontend:"
echo "   cd ../frontend"
echo "   pnpm dev"
echo ""
echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}Access Services:${NC}"
echo -e "${CYAN}================================${NC}"
echo ""
echo "Temporal UI:        http://localhost:8233"
echo "MinIO Console:      http://localhost:9001 (minioadmin/minioadmin)"

if [ "$WITH_OBSERVABILITY" = true ]; then
    echo "ClearML Web UI:     http://localhost:8080"
    echo "MLflow:             http://localhost:5000"
    echo "Grafana:            http://localhost:3200 (admin/admin)"
fi

echo ""
echo -e "${YELLOW}To stop services: ./start-infra.sh --stop${NC}"
echo ""
