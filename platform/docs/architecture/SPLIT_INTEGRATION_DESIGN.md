# Split Integration Design (Phase 11.5.5)

## Overview

**User Requirement**: Dataset의 기본 split과 Training job별 split이 독립적으로 동작해야 함.

### Two-Layer Split Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Dataset Default Split (Labeler 관리)               │
│ - annotations_{task-type}.json에 split_config 저장          │
│ - Annotation 생성 단계에서 기본 split 설정                   │
│ - 여러 training job에서 공유되는 기본값                      │
└─────────────────────────────────────────────────────────────┘
                           ↓ (사용 또는 Override)
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Training-Specific Split (Platform 관리)             │
│ - TrainingJob.split_strategy에 저장                          │
│ - Training job 생성 시 사용자가 override 가능                 │
│ - 비율 변경, 이미지 포함/제외, seed 변경 등                   │
│ - DatasetSnapshot과 함께 저장되어 재현성 보장                 │
└─────────────────────────────────────────────────────────────┘
```

## 3-Level Priority System

기존 DATASET_SPLIT_STRATEGY.md의 설계를 Platform-Labeler 통합 환경에 적용:

```python
Priority 1: Job-Level Override (TrainingJob.split_strategy)
    ↓ (if None)
Priority 2: Dataset-Level Metadata (Labeler annotations.json의 split_config)
    ↓ (if None)
Priority 3: Runtime Auto-Split (80/20, seed=42)
```

## Database Schema Changes

### TrainingJob Model

```python
class TrainingJob(Base):
    __tablename__ = "training_jobs"

    # 기존 필드들...

    # Phase 11.5: Split strategy override
    split_strategy = Column(JSON, nullable=True)
    # Example: {
    #   "method": "auto",           # "auto" | "manual" | "use_default"
    #   "ratio": [0.7, 0.2, 0.1],   # [train, val, test]
    #   "seed": 123,
    #   "splits": {                 # manual method only
    #     "image_001": "train",
    #     "image_002": "val"
    #   },
    #   "exclude_images": ["corrupted_001.jpg"]
    # }

    # Foreign key 수정 (datasets 제거됨)
    dataset_id = Column(String(100), nullable=True, index=True)  # Labeler dataset ID (no FK)
    dataset_snapshot_id = Column(String(100), ForeignKey('dataset_snapshots.id', ondelete='SET NULL'), nullable=True, index=True)
```

**Foreign Key Changes**:
- `dataset_id`: FK 제거 (Labeler의 dataset UUID 참조하므로 local FK 불가능)
- `dataset_snapshot_id`: `dataset_snapshots.id`로 FK 설정 (Platform DB 내 참조)

### DatasetSnapshot Model

DatasetSnapshot에 사용된 split 정보를 기록하여 재현성 보장:

```python
class DatasetSnapshot(Base):
    __tablename__ = "dataset_snapshots"

    # 기존 필드들...

    # Split configuration used for this snapshot
    split_config = Column(JSON, nullable=True)
    # Example: {
    #   "source": "job_override",  # "job_override" | "dataset_default" | "auto"
    #   "method": "auto",
    #   "ratio": [0.8, 0.2],
    #   "seed": 42,
    #   "num_train": 800,
    #   "num_val": 200
    # }
```

## API Design

### 1. Split Endpoints (Platform)

#### GET /api/v1/datasets/{dataset_id}/split

**목적**: Dataset의 split 정보 조회 (Labeler default)

```python
@router.get("/{dataset_id}/split", response_model=DatasetSplitResponse)
async def get_dataset_split(
    dataset_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get dataset split configuration from Labeler.

    Returns:
    - Dataset default split (from annotations.json)
    - Split statistics (num_train, num_val, num_test)
    """
    from app.clients.labeler_client import labeler_client

    # Query Labeler for dataset metadata
    dataset = await labeler_client.get_dataset(dataset_id)

    # Get annotations from R2
    annotations_path = dataset['storage_path'] + f"/annotations_{dataset['task_type']}.json"
    annotations = await load_annotations_from_r2(annotations_path)

    split_config = annotations.get('split_config', None)

    if not split_config:
        return {
            "has_split": False,
            "message": "No default split configured. Will use auto-split (80/20) during training."
        }

    # Calculate statistics
    stats = calculate_split_statistics(split_config)

    return {
        "has_split": True,
        "split_config": split_config,
        "statistics": stats  # {train: 800, val: 200, ...}
    }
```

#### POST /api/v1/datasets/{dataset_id}/split

**목적**: Dataset 기본 split 설정 (Labeler annotations.json 업데이트)

```python
@router.post("/{dataset_id}/split", response_model=DatasetSplitResponse)
async def update_dataset_default_split(
    dataset_id: str,
    request: DatasetSplitCreateRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Update dataset default split configuration.

    This updates the split_config in annotations.json (Layer 1).
    Requires dataset owner permission.
    """
    from app.clients.labeler_client import labeler_client

    # Check permission (owner only)
    permission = await labeler_client.check_permission(dataset_id, current_user.id)
    if not permission['is_owner']:
        raise HTTPException(403, "Only dataset owner can update default split")

    # Get dataset metadata
    dataset = await labeler_client.get_dataset(dataset_id)

    # Load and update annotations.json
    annotations_path = dataset['storage_path'] + f"/annotations_{dataset['task_type']}.json"
    annotations = await load_annotations_from_r2(annotations_path)

    # Generate or validate split
    if request.method == "auto":
        splits = generate_auto_split(annotations['images'], request.ratio, request.seed)
    elif request.method == "manual":
        splits = validate_manual_split(annotations['images'], request.splits)

    # Update annotations
    annotations['split_config'] = {
        "method": request.method,
        "default_ratio": request.ratio,
        "seed": request.seed,
        "splits": splits
    }

    # Save back to R2
    await save_annotations_to_r2(annotations_path, annotations)

    return {"success": True, "split_config": annotations['split_config']}
```

### 2. Training Job API (Split Override)

#### POST /api/v1/training/jobs

**Request Schema 업데이트**:

```python
class TrainingJobCreateRequest(BaseModel):
    # 기존 필드들...

    # Phase 11.5: Split override
    split_strategy: Optional[dict] = None
    # Options:
    # 1. None (use dataset default or auto 80/20)
    # 2. {"method": "use_default"} (explicit: use dataset default)
    # 3. {"method": "auto", "ratio": [0.7, 0.3], "seed": 99}
    # 4. {"method": "manual", "splits": {...}, "exclude_images": [...]}
```

**Implementation**:

```python
@router.post("/jobs", response_model=TrainingJobResponse)
async def create_training_job(
    config: TrainingJobCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create training job with optional split override."""

    # ... existing dataset validation ...

    # Create training job
    job = TrainingJob(
        # ... existing fields ...
        split_strategy=config.split_strategy,  # Can be None
        status="pending"
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    return job
```

#### POST /api/v1/training/jobs/{job_id}/start

**Updated to resolve split and create snapshot**:

```python
@router.post("/jobs/{job_id}/start")
async def start_training_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start training job and create snapshot with resolved split."""

    job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    # Step 1: Resolve split configuration (3-Level Priority)
    resolved_split = await resolve_split_configuration(job.dataset_id, job.split_strategy, db)

    # Step 2: Create snapshot with resolved split
    snapshot = await snapshot_service.create_snapshot(
        dataset_id=job.dataset_id,
        dataset_path=...,
        user_id=current_user.id,
        db=db,
        split_config=resolved_split  # Include split info
    )

    job.dataset_snapshot_id = snapshot.id
    job.status = "running"
    db.commit()

    # Step 3: Start training with resolved split
    await start_training_with_split(job, resolved_split)

    return {"status": "started", "snapshot_id": snapshot.id}
```

### 3. Split Resolution Logic

```python
async def resolve_split_configuration(
    dataset_id: str,
    job_split_strategy: Optional[dict],
    db: Session
) -> dict:
    """
    Resolve split configuration using 3-Level Priority System.

    Returns:
        {
            "source": "job_override" | "dataset_default" | "auto",
            "method": "auto" | "manual",
            "ratio": [0.8, 0.2],
            "seed": 42,
            "splits": {...}  # if manual
        }
    """

    # Priority 1: Job-Level Override
    if job_split_strategy is not None:
        if job_split_strategy.get("method") == "use_default":
            # Explicitly requesting dataset default
            pass  # Fall through to Priority 2
        else:
            # Custom split strategy
            return {
                "source": "job_override",
                **job_split_strategy
            }

    # Priority 2: Dataset-Level Metadata (from Labeler)
    try:
        from app.clients.labeler_client import labeler_client

        dataset = await labeler_client.get_dataset(dataset_id)
        annotations_path = dataset['storage_path'] + f"/annotations_{dataset['task_type']}.json"
        annotations = await load_annotations_from_r2(annotations_path)

        split_config = annotations.get('split_config')
        if split_config:
            return {
                "source": "dataset_default",
                **split_config
            }
    except Exception as e:
        logger.warning(f"Failed to get dataset default split: {e}")

    # Priority 3: Runtime Auto-Split (fallback)
    return {
        "source": "auto",
        "method": "auto",
        "ratio": [0.8, 0.2],
        "seed": 42
    }
```

## Training Execution Integration

### Environment Variables for Trainer

Trainer 컨테이너에 split 정보를 환경변수로 전달:

```python
# In training_subprocess.py or k8s_executor.py

env_vars = {
    "DATASET_PATH": dataset_path,
    "DATASET_FORMAT": job.dataset_format,

    # Split configuration
    "SPLIT_METHOD": resolved_split["method"],
    "SPLIT_RATIO": json.dumps(resolved_split.get("ratio", [0.8, 0.2])),
    "SPLIT_SEED": str(resolved_split.get("seed", 42)),
    "SPLIT_SOURCE": resolved_split["source"],  # For logging
}

# If manual split
if resolved_split["method"] == "manual":
    # Save splits to file
    split_file = f"/tmp/splits_{job.id}.json"
    with open(split_file, 'w') as f:
        json.dump(resolved_split["splits"], f)
    env_vars["SPLIT_FILE"] = split_file
```

### Trainer Implementation (adapters)

각 Trainer adapter는 환경변수를 읽어 split 적용:

```python
# In ultralytics_adapter.py, timm_adapter.py, etc.

def prepare_training_script(self, job: TrainingJob, env_vars: dict) -> str:
    """Generate training script with split configuration."""

    split_method = env_vars.get("SPLIT_METHOD", "auto")
    split_ratio = json.loads(env_vars.get("SPLIT_RATIO", "[0.8, 0.2]"))
    split_seed = int(env_vars.get("SPLIT_SEED", "42"))

    script = f"""
import random
random.seed({split_seed})

# Load dataset
dataset = load_dataset("{env_vars['DATASET_PATH']}")

# Apply split
if "{split_method}" == "manual":
    # Load split assignments from file
    with open("{env_vars.get('SPLIT_FILE')}") as f:
        splits = json.load(f)
    train_set = [img for img in dataset if splits.get(img.id) == 'train']
    val_set = [img for img in dataset if splits.get(img.id) == 'val']
else:
    # Auto split with ratio
    train_size = int(len(dataset) * {split_ratio[0]})
    train_set = dataset[:train_size]
    val_set = dataset[train_size:]

# Training loop
...
"""
    return script
```

## User Experience Flow

### Scenario 1: Use Dataset Default Split

```python
# User creates training job without split override
POST /api/v1/training/jobs
{
  "model_name": "yolo11n",
  "dataset_id": "abc123",
  "epochs": 100,
  # No split_strategy specified
}

# Platform resolves split:
# Priority 1: None
# Priority 2: Query Labeler → annotations.json has split_config → Use it
# Result: Dataset default split (e.g., 80/20 from annotation phase)
```

### Scenario 2: Override with Custom Ratio

```python
# User wants 70/30 split instead of dataset default 80/20
POST /api/v1/training/jobs
{
  "model_name": "yolo11n",
  "dataset_id": "abc123",
  "epochs": 100,
  "split_strategy": {
    "method": "auto",
    "ratio": [0.7, 0.3],
    "seed": 99
  }
}

# Platform resolves split:
# Priority 1: Job override exists → Use 70/30 with seed 99
```

### Scenario 3: Exclude Specific Images

```python
# User wants to exclude corrupted images
POST /api/v1/training/jobs
{
  "model_name": "yolo11n",
  "dataset_id": "abc123",
  "epochs": 100,
  "split_strategy": {
    "method": "manual",
    "splits": {
      "image_001": "train",
      "image_002": "val",
      # ... (other images)
    },
    "exclude_images": ["corrupted_001.jpg", "corrupted_002.jpg"]
  }
}
```

### Scenario 4: Maintain Split Across Experiments

```python
# First experiment
job1 = create_training_job(split_strategy={"method": "auto", "ratio": [0.8, 0.2], "seed": 42})
# Snapshot created: snapshot_001 with split_config saved

# Second experiment (reproduce same split)
job2 = create_training_job(split_strategy={"method": "auto", "ratio": [0.8, 0.2], "seed": 42})
# Uses same seed → identical split

# Or: Copy split from previous snapshot
snapshot = get_snapshot("snapshot_001")
job3 = create_training_job(split_strategy=snapshot.split_config)
```

## Migration Plan

### Step 1: Database Migration

```python
# migrate_phase_11_5_split.py

def upgrade():
    # Add split_strategy to TrainingJob
    op.add_column('training_jobs', sa.Column('split_strategy', sa.JSON(), nullable=True))

    # Fix foreign keys
    op.drop_constraint('training_jobs_dataset_id_fkey', 'training_jobs', type_='foreignkey')
    # dataset_id는 FK 없이 유지 (Labeler UUID 참조)

    # dataset_snapshot_id FK 수정
    op.drop_constraint('training_jobs_dataset_snapshot_id_fkey', 'training_jobs', type_='foreignkey')
    op.create_foreign_key(
        'training_jobs_dataset_snapshot_id_fkey',
        'training_jobs', 'dataset_snapshots',
        ['dataset_snapshot_id'], ['id'],
        ondelete='SET NULL'
    )

    # Add split_config to DatasetSnapshot
    op.add_column('dataset_snapshots', sa.Column('split_config', sa.JSON(), nullable=True))
```

### Step 2: API Refactoring

1. **Remove Platform Dataset CRUD**:
   - DELETE `/api/v1/datasets` (POST, DELETE)
   - DELETE `/api/v1/datasets/{dataset_id}` (GET single dataset - use Labeler proxy)
   - DELETE `/api/v1/datasets/list` (use Labeler `/available`)
   - DELETE `/api/v1/datasets/analyze` (Labeler responsibility)
   - DELETE `/api/v1/datasets/compare` (not used)

2. **Refactor Split Endpoints**:
   - KEEP `POST /datasets/{dataset_id}/split` (update Labeler annotations.json)
   - KEEP `GET /datasets/{dataset_id}/split` (query Labeler default)

3. **Update Training API**:
   - Add `split_strategy` to TrainingJobCreateRequest
   - Implement `resolve_split_configuration()`
   - Update snapshot creation to include split_config

### Step 3: Testing

```python
# test_split_integration.py

async def test_use_dataset_default_split():
    """Test Priority 2: Dataset default split"""
    # Setup: Dataset has default split in annotations.json
    # Create job without split_strategy
    # Assert: Uses dataset default

async def test_job_level_override():
    """Test Priority 1: Job-level override"""
    # Create job with custom split_strategy
    # Assert: Uses job's split, not dataset default

async def test_auto_fallback():
    """Test Priority 3: Auto-split fallback"""
    # Dataset has no default split
    # Create job without split_strategy
    # Assert: Uses auto 80/20 split

async def test_snapshot_captures_split():
    """Test split reproducibility via snapshot"""
    # Create job with custom split
    # Start training → snapshot created
    # Assert: snapshot.split_config contains used split
```

## Summary

### Key Design Decisions

1. **Two-Layer Architecture**:
   - Layer 1 (Labeler): Dataset default split in annotations.json
   - Layer 2 (Platform): Training-specific override in TrainingJob.split_strategy

2. **3-Level Priority System** (existing design from DATASET_SPLIT_STRATEGY.md):
   - Priority 1: Job override → Priority 2: Dataset default → Priority 3: Auto 80/20

3. **Snapshot Integration**:
   - DatasetSnapshot.split_config records actual split used
   - Ensures reproducibility across experiments

4. **Foreign Key Changes**:
   - `dataset_id`: No FK (references Labeler's UUID)
   - `dataset_snapshot_id`: FK to `dataset_snapshots.id`

5. **API Cleanup**:
   - Remove: Dataset CRUD, analyze, compare
   - Keep: Split endpoints (refactored for Labeler integration)
   - Update: Training API to support split_strategy

### Implementation Checklist

- [ ] Database migration (add split fields, fix FKs)
- [ ] Update TrainingJob and DatasetSnapshot models
- [ ] Implement `resolve_split_configuration()`
- [ ] Refactor Split endpoints (GET/POST)
- [ ] Update `create_training_job()` to accept split_strategy
- [ ] Update `start_training_job()` to resolve and save split
- [ ] Update SnapshotService to capture split_config
- [ ] Update training executors to pass split to trainers
- [ ] Remove Dataset CRUD endpoints
- [ ] Write integration tests
- [ ] Update TODO list Phase 11.5.5 progress

### References

- [DATASET_SPLIT_STRATEGY.md](../../../platform/docs/architecture/DATASET_SPLIT_STRATEGY.md) - Original 3-Level Priority System design
- [DATASET_MANAGEMENT_ARCHITECTURE.md](DATASET_MANAGEMENT_ARCHITECTURE.md) - Platform-Labeler separation
- [LABELER_DATASET_API_REQUIREMENTS.md](../integration/LABELER_DATASET_API_REQUIREMENTS.md) - Labeler API spec
