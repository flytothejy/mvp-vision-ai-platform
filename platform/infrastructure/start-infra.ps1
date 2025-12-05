# ================================
# Vision AI Training Platform - Infrastructure Startup Script (Windows)
# ================================
#
# This script starts the required infrastructure services.
#
# Usage:
#   .\start-infra.ps1                    # Start core services only
#   .\start-infra.ps1 -WithObservability # Start with ClearML, MLflow, Grafana
#   .\start-infra.ps1 -Stop              # Stop all services
#   .\start-infra.ps1 -Clean             # Stop and remove volumes (CAUTION!)

param(
    [switch]$WithObservability,
    [switch]$Stop,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

Write-Host "================================" -ForegroundColor Cyan
Write-Host "Vision AI Training Platform" -ForegroundColor Cyan
Write-Host "Infrastructure Management" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# Check if Docker is running
try {
    docker info | Out-Null
} catch {
    Write-Host "ERROR: Docker is not running!" -ForegroundColor Red
    Write-Host "Please start Docker Desktop and try again." -ForegroundColor Yellow
    exit 1
}

# Stop services
if ($Stop -or $Clean) {
    Write-Host "Stopping services..." -ForegroundColor Yellow

    if ($WithObservability) {
        docker-compose -f docker-compose.yml -f docker-compose.observability.yml down
    } else {
        docker-compose down
    }

    if ($Clean) {
        Write-Host "WARNING: This will delete all data!" -ForegroundColor Red
        $confirmation = Read-Host "Are you sure? (yes/no)"
        if ($confirmation -eq "yes") {
            Write-Host "Removing volumes..." -ForegroundColor Yellow
            docker-compose down -v
            if ($WithObservability) {
                docker-compose -f docker-compose.observability.yml down -v
            }
            Write-Host "All data removed." -ForegroundColor Green
        } else {
            Write-Host "Cancelled." -ForegroundColor Yellow
        }
    }

    Write-Host "Services stopped." -ForegroundColor Green
    exit 0
}

# Start services
Write-Host "Starting infrastructure services..." -ForegroundColor Green
Write-Host ""

# Core services
Write-Host "Starting core services:" -ForegroundColor Cyan
Write-Host "  - PostgreSQL (Platform DB): localhost:5432" -ForegroundColor White
Write-Host "  - PostgreSQL (User DB):     localhost:5433" -ForegroundColor White
Write-Host "  - Redis:                    localhost:6379" -ForegroundColor White
Write-Host "  - Temporal:                 localhost:7233 (gRPC), 8233 (UI)" -ForegroundColor White
Write-Host "  - MinIO (Datasets):         localhost:9000 (API), 9001 (Console)" -ForegroundColor White
Write-Host "  - MinIO (Results):          localhost:9002 (API), 9003 (Console)" -ForegroundColor White
Write-Host ""

docker-compose up -d

# Observability services
if ($WithObservability) {
    Write-Host ""
    Write-Host "Starting observability services:" -ForegroundColor Cyan
    Write-Host "  - ClearML API:      localhost:8008" -ForegroundColor White
    Write-Host "  - ClearML Web UI:   localhost:8080" -ForegroundColor White
    Write-Host "  - ClearML Files:    localhost:8081" -ForegroundColor White
    Write-Host "  - MLflow:           localhost:5000" -ForegroundColor White
    Write-Host "  - Loki:             localhost:3100" -ForegroundColor White
    Write-Host "  - Grafana:          localhost:3200" -ForegroundColor White
    Write-Host ""

    docker-compose -f docker-compose.yml -f docker-compose.observability.yml up -d
}

Write-Host ""
Write-Host "================================" -ForegroundColor Green
Write-Host "Infrastructure started successfully!" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green
Write-Host ""

# Wait for services to be healthy
Write-Host "Waiting for services to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# Check service health
Write-Host ""
Write-Host "Service Status:" -ForegroundColor Cyan
docker-compose ps

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Configure environment variables:" -ForegroundColor White
Write-Host "   cd ..\backend" -ForegroundColor Gray
Write-Host "   cp .env.example .env" -ForegroundColor Gray
Write-Host "   # Edit .env with your API keys" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Start Backend:" -ForegroundColor White
Write-Host "   cd ..\backend" -ForegroundColor Gray
Write-Host "   poetry run uvicorn app.main:app --reload --port 8000" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Start Temporal Worker:" -ForegroundColor White
Write-Host "   cd ..\backend" -ForegroundColor Gray
Write-Host "   poetry run python -m app.workflows.worker" -ForegroundColor Gray
Write-Host ""
Write-Host "4. Start Frontend:" -ForegroundColor White
Write-Host "   cd ..\frontend" -ForegroundColor Gray
Write-Host "   pnpm dev" -ForegroundColor Gray
Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host "Access Services:" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Temporal UI:        http://localhost:8233" -ForegroundColor White
Write-Host "MinIO Console:      http://localhost:9001 (minioadmin/minioadmin)" -ForegroundColor White

if ($WithObservability) {
    Write-Host "ClearML Web UI:     http://localhost:8080" -ForegroundColor White
    Write-Host "MLflow:             http://localhost:5000" -ForegroundColor White
    Write-Host "Grafana:            http://localhost:3200 (admin/admin)" -ForegroundColor White
}

Write-Host ""
Write-Host "To stop services: .\start-infra.ps1 -Stop" -ForegroundColor Yellow
Write-Host ""
