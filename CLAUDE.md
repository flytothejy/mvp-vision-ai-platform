# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Vision AI Training Platform** is a natural language-driven platform for training computer vision models. Users can configure and train models (ResNet, YOLO, etc.) by conversing with an LLM instead of writing configuration files.

**Current Stage:** Production Implementation (Started 2025-11-10)

**Project Structure:**
- **`platform/`**: Production-ready implementation with Temporal orchestration, complete observability, and cloud-agnostic design (ACTIVE DEVELOPMENT)

**Key Concept:** Natural language → LLM Intent Parser → Training Config → Temporal Workflow → Kubernetes Training Pod

## 📋 TODO Management Guidelines

### CRITICAL: Always Update Implementation Progress

**Every implementation MUST be tracked in the central TODO list.**

#### Required Actions for Every Implementation

1. **Before Starting**:
   - Read `docs/todo/IMPLEMENTATION_TO_DO_LIST.md` to understand current status
   - Identify the relevant Phase and sub-section
   - Check if the task is already listed

2. **During Implementation**:
   - Mark tasks as in-progress when starting
   - Mark tasks as completed immediately after finishing (not in batches)
   - Update progress percentages when completing sub-sections
   - Add new discovered tasks to the list as they are identified

3. **When Creating Detailed Documentation**:
   - Create detailed plans in `docs/todo/reference/` for complex features
   - Link from `IMPLEMENTATION_TO_DO_LIST.md` using relative paths
   - Use descriptive filenames (e.g., `CLEARML_MIGRATION_PLAN.md`, `REDIS_INTEGRATION_DESIGN.md`)

4. **Update Format**:
   ```markdown
   # In IMPLEMENTATION_TO_DO_LIST.md

   ## Phase X: Feature Name (Progress%)

   ### X.1 Sub-feature ✅/🔄/⬜
   - [x] Completed task
   - [x] Another completed task
   - [ ] Pending task

   **Reference**: [DETAILED_PLAN.md](reference/DETAILED_PLAN.md)
   ```

#### When to Create Reference Documents

Create detailed plans in `docs/todo/reference/` when:
- Implementation requires >3 days
- Multiple team members need coordination
- Complex architecture decisions involved
- Migration/refactoring affects multiple components

**Examples**:
- ✅ `CLEARML_MIGRATION_PLAN.md` - Complex 7-day migration
- ✅ `BACKEND_REFACTORING_PLAN.md` - Multi-component refactoring
- ✅ `PHASE_11_MICROSERVICE_SEPARATION.md` - Major architectural change
- ❌ Simple bug fixes - Update TODO list directly

#### Progress Tracking

**Update `IMPLEMENTATION_TO_DO_LIST.md` header**:
```markdown
**총 진행률**: XX% (completed/total tasks)
**최종 업데이트**: YYYY-MM-DD (Brief description of what was completed)
```

**Phase Progress Calculation**:
```
Phase Progress = (Completed Tasks / Total Tasks) × 100%
```

**Status Indicators**:
- ✅ **Completed** (100%)
- 🔄 **In Progress** (1-99%)
- ⬜ **Not Started** (0%)

#### Example Workflow

```
1. Start Feature Implementation
   → Read IMPLEMENTATION_TO_DO_LIST.md
   → Mark relevant tasks as in-progress

2. Complete Sub-task
   → Mark sub-task as [x] completed
   → Update progress percentage if needed
   → Commit changes

3. Finish Feature
   → Mark all tasks as [x] completed
   → Update phase progress percentage
   → Update header "최종 업데이트"
   → Commit with message: "docs(todo): update Phase X progress"

4. Discover New Requirements
   → Add new tasks to appropriate Phase
   → Update total task count
   → Recalculate progress percentage
```

## Code Quality & Implementation Standards

### ⚠️ CRITICAL: No Shortcuts, No Workarounds

**This project prioritizes correct implementation over quick solutions.**

#### Forbidden Practices

❌ **NEVER use these shortcuts:**
- Hardcoded data (예: `STATIC_MODELS = [...]`)
- Temporary workarounds (예: "임시로 이렇게 하고 나중에 고치자")
- Dummy data (예: mock responses, fake data)
- "Quick fixes" that don't align with architecture
- Solutions that "pretend" to work but don't actually solve the problem

✅ **ALWAYS implement properly:**
- Follow the planned architecture
- Use dynamic data loading (예: from database, API, registry)
- Implement complete solutions even if it takes more time
- If something needs to be fixed, fix it the right way now, not later

#### Implementation Philosophy

```
"If we don't implement it correctly now, we'll have to redo it later anyway."
```

**Key Principles:**
1. **Quality over Speed**: Better to take time and implement correctly
2. **Architecture Compliance**: Follow the planned design, don't deviate
3. **Production-Ready**: Every feature should work in both local AND production
4. **Dependency Isolation**: Critical goal - never compromise on this

#### Example: Model Registry

❌ **Wrong (Hardcoded):**
```python
STATIC_MODELS = [
    {"model_name": "yolo11n", "framework": "ultralytics"},
    {"model_name": "yolo11s", "framework": "ultralytics"},  # Arbitrary models!
]
```

✅ **Correct (Dynamic from Training Services):**
```python
# Backend fetches from Training Service API
models = requests.get(f"{ULTRALYTICS_SERVICE_URL}/models/list").json()
# Returns actual implemented models: yolo11n, yolo11n-seg, yolo11n-pose, yolo_world_v2_s, sam2_t
```

### Production Branch Goals

**Branch: `production`**

**Mission:** Make production deployment work EXACTLY like local development.

**Specific Goals:**
1. ✅ All APIs work identically (local SQLite vs production PostgreSQL)
2. ✅ LLM chat functions properly in production
3. ✅ Dependency isolation (Backend ↔ Training Services via HTTP API)
4. ✅ Dynamic model registration (no hardcoded models)
5. ✅ Framework-specific Training Services (timm, ultralytics, huggingface)
6. ✅ Environment variable configuration (not code changes)

**Success Criteria:**
- Same source code works in both environments
- Only difference: environment variables (`.env` vs Railway Variables)
- All features tested in production match local behavior

### When Implementing Features

**Before writing code, ask:**
1. Does this follow the architecture plan?
2. Is this a proper solution or a workaround?
3. Will this work in BOTH local and production?
4. Am I using dynamic data or hardcoding?

**If the answer to any question is uncertain:**
- Re-read the relevant documentation
- Ask the user for clarification
- DON'T proceed with a "quick fix"

## Architecture Overview

### High-Level Flow
```
User (자연어) → Frontend (Next.js) → API Gateway (Kong)
  → Intent Parser (LLM) → Orchestrator (Temporal)
  → VM Controller (K8s) → Training Runner (Pod with Sidecar)
```

### Core Components

**Frontend (Next.js 14)**
- Chat interface for natural language model configuration
- Real-time training monitoring via WebSocket
- Tech: React 18, TailwindCSS, Zustand, React Query, Socket.io

**Backend Services (All FastAPI + Python 3.11)**
1. **Intent Parser** - Parses natural language into `TrainingIntent` using LangChain + Claude/GPT-4
2. **Orchestrator** - Manages training workflows using Temporal
3. **Model Registry** - Adapter pattern for multiple frameworks (timm, HuggingFace, Ultralytics, MMDetection)
4. **Data Service** - Dataset upload, validation, format conversion (COCO, YOLO, Pascal VOC)
5. **VM Controller** - Kubernetes pod lifecycle management
6. **Telemetry Service** - Real-time metrics collection and WebSocket broadcast

**Training Runner (Kubernetes Pod)**
- Dual container pattern: User Container (runs actual training) + Sidecar Container (monitors, uploads checkpoints, sends telemetry)
- Sidecar parses stdout for metrics and auto-uploads checkpoints to S3

**Orchestration & Data**
- Temporal 1.22.x for workflow orchestration
- PostgreSQL 16 (users, projects, metadata)
- MongoDB 7 (configs, workflow definitions)
- Redis 7.2 (cache, Celery queue, real-time state)
- S3/MinIO (datasets, models, checkpoints)

## Key Patterns & Principles

### 1. Adapter Pattern for Model Frameworks
All model sources (timm, HuggingFace, Ultralytics, etc.) implement `ModelAdapter` interface with:
- `load_model()` - Load model metadata
- `prepare_training_script()` - Generate training code
- `normalize_output()` - Standardize training results

See ARCHITECTURE.md:276-338 for implementation details.

### 2. Temporal Workflow Orchestration
Training workflow steps:
1. Validate dataset
2. Prepare model
3. Allocate VM (Kubernetes pod)
4. Run training (up to 24h timeout, 5min heartbeat)
5. Cleanup resources

See ARCHITECTURE.md:200-253 for workflow definition.

### 3. Intent Parsing Flow
LLM parses user message → Returns either:
- `ParseResult.complete` with full `TrainingIntent`
- `ParseResult.needs_clarification` with list of questions

User fills gaps → LLM generates executable `TrainingConfig`

See API_SPECIFICATION.md:106-187 for request/response examples.

## Development Commands

**Active Development:** `platform/` is the only active codebase.

### Platform Development

```bash
# Backend
cd platform/backend
poetry install
poetry run uvicorn app.main:app --reload --port 8000

# Frontend
cd platform/frontend
pnpm install
pnpm dev

# Temporal Worker
cd platform/backend
poetry run python -m app.workflows.worker

# Build Trainer Images
cd platform/trainers/ultralytics
docker build -t trainer-ultralytics:latest .
```

### Infrastructure (Docker Compose)
```bash
# Start infrastructure services
cd platform/infrastructure
docker-compose up -d

# Check status
docker-compose ps

# Shutdown
docker-compose down
```

### Database
```bash
# Initialize databases
cd platform/backend
python init_db.py

# Access PostgreSQL
docker exec -it platform-postgres psql -U admin -d platform
```

### Temporal
```bash
# Start Temporal dev server
temporal server start-dev

# Or via Docker
docker run -d -p 7233:7233 -p 8233:8233 temporalio/auto-setup:latest

# Temporal UI: http://localhost:8233
```

## Code Style & Conventions

### Python
- Formatter: Black (line-length 100)
- Import sorting: isort (profile="black")
- Linting: flake8, pylint
- Type checking: mypy (python_version="3.11")
- Docstrings: Google style

```bash
black .
isort .
flake8 .
mypy .
```

### TypeScript/JavaScript
- Formatter: Prettier (semi, singleQuote, printWidth 100)
- Linting: ESLint (next/core-web-vitals, @typescript-eslint)

```bash
pnpm lint
pnpm format
```

### Git Workflow
- Branch naming: `feature/<name>`, `bugfix/<name>`, `hotfix/<issue>`
- Commits: Conventional Commits format
  ```
  feat(scope): add new feature
  fix(scope): fix bug
  docs(scope): update documentation
  ```
- Main branch: `main` (protected)
- Development branch: `develop` (default)

See DEVELOPMENT.md:466-563 for detailed git workflow.

## API Structure

### Public REST API
Base URL: `/api/v1`
Authentication: JWT Bearer tokens

**Key Endpoints:**
- `POST /chat/message` - Send natural language message, get parsed intent or clarification questions
- `POST /workflows` - Create training workflow
- `GET /workflows/{id}` - Get workflow status and metrics
- `ws://api/v1/ws/workflows/{id}` - WebSocket for real-time training updates
- `POST /datasets/upload` - Upload dataset (multipart/form-data)
- `GET /models` - List available models (filter by task_type, framework)
- `POST /inference/{workflow_id}/predict` - Run inference on trained model

**WebSocket Message Types:**
- `training_progress` - Epoch, step, metrics, ETA
- `training_complete` - Final results
- `training_error` - Error details
- `checkpoint_saved` - Checkpoint info

See API_SPECIFICATION.md for complete API reference.

### Internal Service APIs
Prefix: `/internal/<service>`
Authentication: `X-Internal-Auth` header

Used for service-to-service communication only.

## Environment Variables

Required environment variables (see DEVELOPMENT.md:160-187):

```bash
# LLM APIs
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-...

# Databases
DATABASE_URL=postgresql://admin:devpass@localhost:5432/vision_platform
MONGODB_URL=mongodb://localhost:27017/vision_platform
REDIS_URL=redis://localhost:6379

# Object Storage
S3_ENDPOINT=http://localhost:9000
S3_BUCKET=vision-platform-dev
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin

# Temporal
TEMPORAL_HOST=localhost:7233

# Auth
JWT_SECRET=your-super-secret-key-change-this-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

Frontend needs separate `.env.local`:
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
NEXT_PUBLIC_ENVIRONMENT=development
```

## Important Implementation Details

### Training Runner Sidecar Pattern
The sidecar container monitors user training code without requiring instrumentation:
- Parses stdout for metrics using regex (e.g., "Epoch 5, Loss: 0.234")
- Watches `/workspace/*.pth` for auto-upload to S3
- Collects GPU/memory metrics via system APIs
- Sends heartbeats to Temporal workflow

See ARCHITECTURE.md:490-536 for sidecar implementation.

### Dataset Format Support
Supported formats: COCO, YOLO, Pascal VOC, ImageNet
Data Service can convert between formats using `convert_format()` method.

### Supported Model Frameworks
- timm (PyTorch Image Models)
- HuggingFace Transformers
- Ultralytics YOLO
- MMDetection
- MMSegmentation
- Detectron2
- Custom Docker Images

Each framework has its own adapter implementing the `ModelAdapter` interface.

### Model Export & Deployment

**CRITICAL**: When adding new trainers, follow the **Convention-Based Export** design to maintain dependency isolation.

#### Export Workflow

```
TrainingJob (checkpoint.pt)
    ↓
ExportJob (ONNX, TensorRT, CoreML, etc.)
    ↓
Exported Model + Metadata + Runtime Wrappers
    ↓
Deployment (Platform Endpoint, Edge Package, Container, Download)
```

#### Convention-Based Export Design

**Key Principle**: Each trainer is an isolated service with independent dependencies. DO NOT create shared base modules.

**For New Trainers**:
1. Copy `docs/examples/export_template.py` to your trainer directory
2. Implement framework-specific functions (~50-100 lines):
   - `load_model()`: Load your framework's checkpoint
   - `get_metadata()`: Extract model metadata (input shape, class names, etc.)
   - `export_{format}()`: Call framework's native export methods
3. Follow the Export Convention (CLI interface, output files, metadata schema)

**See**:
- `docs/EXPORT_CONVENTION.md` - **MUST READ** for new trainers
- `docs/examples/export_template.py` - Reference implementation
- `platform/trainers/ultralytics/EXPORT_GUIDE.md` - Complete Ultralytics export guide

#### Supported Export Formats

| Format | Use Case | Hardware |
|--------|----------|----------|
| ONNX | Cross-platform, cloud inference | CPU, GPU (CUDA) |
| TensorRT | NVIDIA GPU optimized | NVIDIA GPU |
| CoreML | iOS/macOS deployment | Apple Silicon |
| TFLite | Mobile & embedded | CPU, EdgeTPU |
| TorchScript | PyTorch native deployment | CPU, GPU |
| OpenVINO | Intel hardware optimized | Intel CPU/iGPU/VPU |

#### Deployment Types

1. **Platform Endpoint** (`platform_endpoint`):
   - Managed inference API on platform infrastructure
   - ONNX Runtime with GPU support (CUDA + CPU)
   - Bearer token authentication
   - Auto-scaling and usage tracking
   - API: `POST /v1/infer/{deployment_id}`

2. **Edge Package** (`edge_package`):
   - Optimized for edge devices
   - Includes runtime wrappers (Python, C++, Swift, Kotlin)
   - Size and speed optimized

3. **Container** (`container`):
   - Docker image with model + inference server
   - Self-hosted deployment
   - Registry options: Docker Hub, GitHub Container Registry, GCR

4. **Direct Download** (`download`):
   - Presigned S3 URL for raw model files
   - Custom integration

#### API Examples

**Create Export Job**:
```bash
curl -X POST $API_URL/api/v1/export/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "training_job_id": 123,
    "export_format": "onnx",
    "export_config": {"opset_version": 17}
  }'
```

**Create Platform Endpoint**:
```bash
curl -X POST $API_URL/api/v1/deployments \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "export_job_id": 456,
    "deployment_type": "platform_endpoint",
    "deployment_config": {"auto_activate": true}
  }'
```

**Run Inference**:
```bash
curl -X POST $API_URL/v1/infer/789 \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "image": "base64_encoded_image",
    "confidence_threshold": 0.25
  }'
```

#### Frontend Integration

Export & Deployment UI is integrated in TrainingPanel as "📦 Export & Deploy" tab:

**Components** (`platform/frontend/components/export/`):
- `ExportJobList` + `ExportJobCard` - List and manage export jobs
- `CreateExportModal` - 3-step wizard (Format → Options → Review)
- `DeploymentList` + `DeploymentCard` - List and manage deployments
- `CreateDeploymentModal` - 3-step wizard (Export → Type → Config)
- `InferenceTestPanel` - Test deployed models with drag & drop image upload

**User Flow**:
1. Train model → Completed
2. Click "📦 Export & Deploy" tab
3. Create export job → Select format (ONNX, TensorRT, etc.) → Configure options
4. Wait for export to complete (~30s-2min depending on format)
5. Create deployment → Select export → Choose deployment type
6. For Platform Endpoint: Get API key + endpoint URL → Test inference inline

#### Why Convention-Based (Not Shared Base Module)?

**Problem**: Each trainer runs in isolated Docker container with independent dependencies.

**Rejected Approach**: Shared base module (`trainers.common.export.base`)
- ❌ Breaks dependency isolation
- ❌ Requires copying `common/` to all Docker images
- ❌ Version sync issues across trainers
- ❌ Only ~10% of export code is truly duplicatable

**Adopted Approach**: Convention + Template
- ✅ Complete dependency isolation preserved
- ✅ Each trainer is fully independent
- ✅ Template reduces duplication (50-100 lines vs 600 lines)
- ✅ Backend only needs to know the convention, not implementation

**Impact**: New trainer implementation = ~50-100 lines (vs 600 lines without template)

## Design System

The platform uses a custom design system based on:
- Font: SUIT (Korean) + Inter (English fallback)
- Colors: Brand Primary (#4F46E5 Indigo), Success (#10B981), Warning (#F59E0B), Error (#EF4444)
- Shadows: Layered elevation system
- Spacing: 4px base unit

Components follow atomic design: Atoms → Molecules → Organisms

See DESIGN_SYSTEM.md and UI_COMPONENTS.md for complete specifications.

## Common Troubleshooting

### Port Conflicts
```bash
lsof -i :3000   # Check what's using port 3000
kill -9 <PID>   # Kill process
PORT=3001 pnpm dev  # Use different port
```

### Docker Disk Space
```bash
docker system df        # Check usage
docker system prune -a  # Clean up
```

### Database Reset
```bash
docker-compose down -v                    # Remove volumes
docker-compose up -d postgres             # Start fresh
cd backend/orchestrator
poetry run alembic upgrade head           # Re-run migrations
```

### Python Dependency Conflicts
```bash
cd backend/<service>
rm -rf .venv
poetry install
```

See DEVELOPMENT.md:872-952 for more troubleshooting scenarios.

## Custom Slash Commands

This repository includes custom slash commands to streamline development workflows.

### /commit - Smart Git Commit

Automatically analyzes code changes and creates a well-formatted git commit.

**Usage:**
```
/commit
```

**What it does:**
1. Runs `git status` and `git diff` to analyze changes
2. Categorizes changes by type (feat, fix, docs, etc.)
3. Generates a Conventional Commits message
4. Stages appropriate files (excluding secrets)
5. Creates the commit with proper formatting
6. Verifies the commit was created successfully

**Example output:**
```bash
# Analyzes changes to platform/backend/app/api/chat.py
# Creates commit:
feat(backend): add chat capabilities endpoint

Create main FastAPI app with health check endpoint and CORS middleware.
Add configuration management with pydantic-settings.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**Safety features:**
- Never commits secrets or `.env` files
- Never uses `--amend` unless explicitly requested
- Never pushes unless explicitly requested
- Warns about suspicious files

See `.claude/commands/commit.md` for full implementation.

### /log-session - Session Timeline Logger

Records the current conversation session to a timeline log for future reference.

**Usage:**
```
/log-session
```

**What it does:**
1. Analyzes the current conversation session
2. Identifies key decisions and technical discussions
3. Creates a timeline summary with:
   - Discussion topics
   - Major decisions with reasoning
   - Implementation details
   - Next steps
   - Related documents
4. Appends to `docs/CONVERSATION_LOG.md` (most recent at top)
5. Maintains conversation context across sessions

**When to use:**
- After completing a major design discussion
- Before ending a long coding session
- When making important architectural decisions
- To maintain continuity between sessions

**Example output:**
```markdown
## [2025-01-04 13:00] 데이터셋 관리 설계 논의

### 주요 결정사항
1. **task_type은 데이터셋 속성이 아니다**
   - 배경: 같은 이미지를 다양한 task에 활용 가능
   - 결정: Dataset에서 task_type 제거, TrainingJob에 추가

### 구현 내용
- DatasetPanel 컴포넌트 생성
- 버전닝 전략 확정 (Mutable + Snapshot)

### 관련 문서
- [DATASET_MANAGEMENT_DESIGN.md](docs/datasets/DATASET_MANAGEMENT_DESIGN.md)
```

**Benefits:**
- Quick context recovery when switching sessions
- Design decision history tracking
- Better team communication
- Complements detailed documentation

See `.claude/commands/log-session.md` for full implementation.

## Documentation References

All documentation is organized in the `/docs` folder by category. See [docs/README.md](./docs/README.md) for the complete index.

### Quick Links

**Architecture & Design:**
- [docs/architecture/ARCHITECTURE.md](./docs/architecture/ARCHITECTURE.md) - System design, component responsibilities, data flows
- [docs/architecture/DATABASE_SCHEMA.md](./docs/architecture/DATABASE_SCHEMA.md) - Database schemas and migration guides

**UI/UX Design:**
- [docs/design/DESIGN_SYSTEM.md](./docs/design/DESIGN_SYSTEM.md) - Design tokens, colors, typography
- [docs/design/UI_COMPONENTS.md](./docs/design/UI_COMPONENTS.md) - Component specifications and usage

**Development:**
- [docs/development/DEVELOPMENT.md](./docs/development/DEVELOPMENT.md) - Setup instructions, coding conventions, testing
- [docs/development/PROJECT_SETUP.md](./docs/development/PROJECT_SETUP.md) - Initial project setup

**API:**
- [docs/api/API_SPECIFICATION.md](./docs/api/API_SPECIFICATION.md) - Complete REST API and WebSocket reference

**Planning:**
- [docs/planning/MVP_PLAN.md](./docs/planning/MVP_PLAN.md) - 2-week MVP implementation plan
- [docs/planning/MVP_STRUCTURE.md](./docs/planning/MVP_STRUCTURE.md) - Detailed MVP folder structure
- [docs/planning/MVP_DESIGN_GUIDE.md](./docs/planning/MVP_DESIGN_GUIDE.md) - MVP design decisions

**Features:**
- [docs/features/DATASET_SOURCES_DESIGN.md](./docs/features/DATASET_SOURCES_DESIGN.md) - Dataset source types and auto-detection design

**Root Level:**
- [README.md](./README.md) - Project overview, quick start, roadmap
- [CONTRIBUTING.md](./CONTRIBUTING.md) - Contribution guidelines

## Notes for Future Implementation

When implementing features, remember:
1. The project structure (frontend/, backend/, infrastructure/) doesn't exist yet - create as needed
2. Use the Adapter pattern for all model frameworks to maintain consistency
3. All training is orchestrated via Temporal workflows - never start training directly
4. Real-time updates MUST go through WebSocket, not polling
5. The sidecar pattern is critical for framework-agnostic monitoring
6. All natural language processing goes through the Intent Parser service
7. Use Poetry for Python dependencies, pnpm for Node.js
8. Follow the branching strategy: feature branches → develop → main

## Current Development Status (Phase 1 MVP - Q1 2025)

From README.md roadmap:
- [x] Basic UI/UX design
- [x] Natural language parsing (LLM) architecture
- [x] Model framework support (timm, HuggingFace) specification
- [x] Local training execution design
- [ ] Basic telemetry implementation
- [ ] Actual code implementation

**Next Steps:** Begin implementation starting with infrastructure setup (Docker Compose), then backend services, then frontend.
