# Vision AI Training Platform - Production Implementation

**Status**: 🚧 Under Development (Started 2025-11-10)

This directory contains the **production-ready implementation** of the Vision AI Training Platform. Unlike the MVP in `mvp/`, this implementation follows production-first principles with proper orchestration, observability, and cloud-agnostic design.

## 🎯 Design Philosophy

### Production-First Approach

```
❌ MVP Thinking: "Make it work, fix it later"
✅ Production-First: "Build it right from the start"
```

**Core Principles:**
1. **No Shortcuts**: No hardcoded data, no temporary workarounds, no "quick fixes"
2. **Cloud-Agnostic**: Works identically on Railway, AWS, or on-premise Kubernetes
3. **Proper Orchestration**: Temporal Workflows for reliability and observability
4. **Complete Isolation**: Backend and Trainers communicate only via APIs
5. **Production Observability**: OpenTelemetry, Loki, Prometheus, Grafana from day one

### Why Separate from MVP?

The MVP served its purpose for rapid prototyping, but accumulated technical debt:
- Hardcoded configurations
- Direct file system access between services
- Simplified error handling
- Environment-specific code paths

This production implementation starts fresh with:
- Dynamic configuration from sources of truth
- API-based communication only
- Comprehensive error handling and retries
- Single codebase for all environments

## 📁 Directory Structure

```
platform/
├── backend/              # FastAPI backend service
│   ├── api/             # REST API endpoints
│   ├── core/            # Business logic
│   ├── db/              # Database models and migrations
│   ├── workflows/       # Temporal activity implementations
│   └── config/          # Settings and environment management
│
├── frontend/            # Next.js 14 frontend application
│   ├── app/            # App router pages
│   ├── components/     # React components
│   └── lib/            # Utilities and API clients
│
├── trainers/           # Framework-specific training services
│   ├── ultralytics/    # YOLO models (YOLOv8, YOLOv11, YOLO-World, SAM2)
│   ├── timm/           # PyTorch Image Models (ResNet, EfficientNet)
│   ├── huggingface/    # Transformers-based models (future)
│   └── base/           # Common interfaces and utilities (optional)
│
├── workflows/          # Temporal workflow definitions
│   ├── training.py     # Main training orchestration
│   ├── preprocessing.py # Data preparation workflow
│   ├── inference.py    # Inference workflow
│   └── monitoring.py   # Health check and metrics collection
│
├── infrastructure/     # Infrastructure as Code
│   ├── helm/           # Kubernetes Helm charts
│   │   ├── backend/
│   │   ├── temporal/
│   │   └── observability/
│   ├── terraform/      # Cloud infrastructure
│   │   ├── railway/
│   │   ├── aws/
│   │   └── onprem/
│   └── k8s/           # Raw Kubernetes manifests (if needed)
│
└── observability/     # Monitoring and observability configs
    ├── grafana/       # Dashboards and alerts
    ├── prometheus/    # Metrics collection configs
    ├── loki/          # Log aggregation configs
    └── otel/          # OpenTelemetry collector config
```

## 🏗️ Architecture Overview

### High-Level Flow

```
User → Frontend → Backend → Temporal Workflow
                    ↓            ↓
              Redis Streams  K8s Job (Trainer)
                    ↓            ↓
            WebSocket ← ─── HTTP Callbacks
                             ↓
                        OTel Collector
                             ↓
                    ┌────────┼────────┐
                    ↓        ↓        ↓
                  Loki  Prometheus  Jaeger
```

### Key Design Decisions

From `docs/k8s_refactoring/README.md`:

1. **Complete File System Isolation**
   - Backend NEVER accesses Trainer files directly (even locally)
   - All data exchange via S3-compatible storage
   - Trainers download datasets, upload checkpoints to storage

2. **API Contract-Based Plugins**
   - Trainers implement standardized API Contract
   - Input: Environment variables (JOB_ID, CALLBACK_TOKEN, etc.)
   - Output: HTTP callbacks (heartbeat, event, done)
   - Optional utils.py provided as reference implementation

3. **JWT Callback Authentication**
   - Short-lived tokens (6-24h)
   - job_id binding prevents token reuse
   - Validation on every callback

4. **State Machine**
   ```
   PENDING → QUEUED → RUNNING → {SUCCEEDED | FAILED | CANCELLED}
   ```

5. **Trace ID for Distributed Tracing**
   - Unique trace_id per job
   - Propagated through all services
   - Enables end-to-end request tracing

6. **Temporal Orchestration**
   - Automatic retries with exponential backoff
   - Timeouts and heartbeat monitoring
   - Workflow history for debugging
   - Graceful cancellation

7. **OpenTelemetry Standard**
   - OTLP protocol for traces, metrics, logs
   - Works with any OTLP-compatible backend
   - Easy integration with Grafana Cloud, Datadog, etc.

8. **S3-Compatible Storage**
   ```python
   # Works with MinIO, R2, S3 - just change endpoint
   boto3.client('s3', endpoint_url=STORAGE_ENDPOINT)
   ```

9. **Environment Variable Configuration**
   - No code changes between environments
   - Single source of truth: `.env` files or K8s ConfigMaps

## 🚀 Getting Started

### Prerequisites

- **Python 3.11+**
- **Node.js 18+** and pnpm
- **Docker Desktop** with Kubernetes enabled
- **Helm 3**
- **kubectl**

### Quick Start

```bash
# 1. Start infrastructure (Temporal, PostgreSQL, Redis, MinIO)
cd infrastructure/helm
helm install temporal temporalio/temporal
helm install postgres bitnami/postgresql
helm install redis bitnami/redis
helm install minio bitnami/minio

# 2. Start backend
cd platform/backend
poetry install
poetry run uvicorn app.main:app --reload

# 3. Start frontend
cd platform/frontend
pnpm install
pnpm dev

# 4. Build trainer images
cd platform/trainers/ultralytics
docker build -t trainer-ultralytics:latest .
```

Detailed setup instructions: [GETTING_STARTED.md](./GETTING_STARTED.md) (coming soon)

## 📊 Deployment Environments

### Local Development (Docker Compose)
- **Storage**: MinIO
- **Database**: PostgreSQL (Docker)
- **Training**: Subprocess or Kind cluster
- **Observability**: Local Grafana stack

### Staging/Production (Railway)
- **Storage**: Cloudflare R2
- **Database**: Railway PostgreSQL
- **Training**: Railway Kubernetes
- **Observability**: Grafana Cloud or self-hosted

### Enterprise (AWS/On-Premise)
- **Storage**: S3 or MinIO
- **Database**: RDS PostgreSQL or self-hosted
- **Training**: EKS or self-hosted Kubernetes
- **Observability**: CloudWatch or self-hosted stack

**Key Point**: Same code, different environment variables only.

## 🔧 Development Workflow

### 1. Make Changes
```bash
# Edit code in platform/backend/, platform/frontend/, or platform/trainers/
```

### 2. Test Locally
```bash
# Backend tests
cd platform/backend
poetry run pytest

# Frontend tests
cd platform/frontend
pnpm test

# Integration tests
cd platform
pytest tests/integration
```

### 3. Deploy
```bash
# Local: Docker Compose
docker-compose up -d

# Railway: Git push
git push origin production-first
# Railway auto-deploys

# AWS: Terraform
cd infrastructure/terraform/aws
terraform apply
```

## 📚 Documentation

- **Architecture**: See `docs/k8s_refactoring/` for detailed design decisions
- **API Contract**: See `docs/k8s_refactoring/PLUGIN_GUIDE.md` for trainer interface
- **Implementation Plan**: See `docs/k8s_refactoring/implementation_plan_v2.md`

## 🎯 Current Status

### ✅ Completed
- [x] Directory structure
- [x] Architecture planning
- [x] API Contract specification
- [x] Backend: Core API endpoints (Chat, Training, Projects, Export, Deployment)
- [x] Frontend: Complete UI (Chat, Training Monitor, Dataset Management, Export & Deployment)
- [x] Workflows: Temporal workflows (Training lifecycle with error handling)
- [x] Trainers: Ultralytics implementation (YOLOv11, YOLO-World, SAM2)
- [x] Observability: Multi-backend support (ClearML, MLflow, W&B, Database)
- [x] Dataset Optimization: Caching, selective download, job restart
- [x] Infrastructure: Docker Compose setup (PostgreSQL, Redis, Temporal, MinIO, ClearML)
- [x] SDK Integration: Training callbacks for real-time metrics
- [x] Testing: Observability testing infrastructure

### 🚧 In Progress
- [ ] Infrastructure: Helm charts for Kubernetes deployment
- [ ] Trainers: timm, HuggingFace implementations
- [ ] Documentation: Complete setup guides
- [ ] Testing: Comprehensive integration test suite
- [ ] Production Deployment: Railway/AWS configurations

### 📋 Planned
- [ ] Observability: Advanced Grafana dashboards
- [ ] Export: Additional formats (TensorRT, CoreML, TFLite)
- [ ] Multi-GPU training support
- [ ] Auto-scaling based on job queue
- [ ] Enterprise features (multi-tenancy, billing)

## 🤝 Contributing

When adding new features:

1. **Follow the API Contract**: See `PLUGIN_GUIDE.md`
2. **No Hardcoding**: Use environment variables or database
3. **Add Tests**: Unit + integration tests required
4. **Update Docs**: Keep documentation in sync
5. **Cloud-Agnostic**: Must work on Railway, AWS, on-premise

## 📝 Related Documentation

- [CLAUDE.md](../CLAUDE.md) - Development guidelines
- [MVP vs Production](../docs/k8s_refactoring/README.md) - Why we separated
- [API Specification](../docs/k8s_refactoring/PLUGIN_GUIDE.md) - Trainer interface
- [Implementation Plan](../docs/k8s_refactoring/implementation_plan_v2.md) - Phase-by-phase plan

---

**Last Updated**: 2025-11-10
**Maintainer**: Vision AI Platform Team
