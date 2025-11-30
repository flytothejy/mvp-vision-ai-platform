"""
Datasets API endpoints (Phase 11.5: Dataset Service Integration)

Architecture:
- Labeler: Dataset metadata, annotations, permissions (Single Source of Truth)
- Platform: Training orchestration, Snapshots

Endpoints:
- GET /available: List available datasets (Labeler proxy)
- GET /{dataset_id}/split: Get dataset default split (Labeler)
- POST /{dataset_id}/split: Update dataset default split (Labeler)
- POST /{dataset_id}/snapshot: Create snapshot (Platform)
- GET /{dataset_id}/snapshots: List snapshots (Platform)
- DELETE /snapshots/{snapshot_id}: Delete snapshot (Platform)
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
import logging
import httpx
import json
from datetime import datetime
from sqlalchemy.orm import Session

from app.clients.labeler_client import labeler_client
from app.services.snapshot_service import snapshot_service
from app.db.database import get_db
from app.db.models import User, DatasetSnapshot
from app.utils.dependencies import get_current_user
from app.utils.split_resolver import (
    load_annotations_from_r2,
    calculate_split_statistics,
    generate_auto_split,
    validate_manual_split
)
from app.schemas.dataset import (
    DatasetSplitCreateRequest,
    DatasetSplitResponse,
    DatasetSplitGetResponse,
    SplitConfig,
    SnapshotCreateRequest,
    SnapshotResponse,
    SnapshotListResponse,
    SnapshotInfo
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================================
# Dataset List (Labeler Proxy)
# ============================================================================

class SampleDatasetInfo(BaseModel):
    """Dataset info returned from Labeler"""
    id: str
    name: str
    format: str
    task_type: Optional[str] = None  # Phase 11.5: Labeler may not return task_type
    num_images: int
    num_classes: Optional[int] = None
    class_names: Optional[List[str]] = None
    storage_path: str
    visibility: str
    published_task_types: Optional[List[str]] = []  # Phase 16.6: Task types this dataset is published for
    created_at: str
    owner_id: int


@router.get("/available", response_model=List[SampleDatasetInfo])
async def list_sample_datasets(
    labeled: Optional[bool] = Query(default=None, description="Filter by labeled status (true=has annotations, false=unlabeled)"),
    task_type: Optional[str] = Query(default=None, description="Filter by task type (detection, segmentation, classification, etc.)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List available datasets from Labeler.

    Phase 11.5: This endpoint proxies to Labeler API.
    Phase 16.6: Added task_type filtering for task-specific statistics.
    - Labeler is Single Source of Truth for dataset metadata
    - Platform only manages snapshots for training
    - task_type returns task-specific num_images and annotation_path
    """
    try:
        # Query Labeler API for available datasets (Phase 16.6: with task_type)
        result = await labeler_client.list_datasets(
            requesting_user_id=current_user.id,
            labeled=labeled,
            task_type=task_type
        )

        datasets = result.get("datasets", [])
        logger.info(f"[DATASETS] Retrieved {len(datasets)} datasets from Labeler for user {current_user.id}")

        # DEBUG: Log first dataset to check field mapping
        if datasets:
            logger.info(f"[DATASETS] First dataset sample: {datasets[0]}")

        return datasets

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.warning("[DATASETS] Labeler returned 404")
            return []
        else:
            logger.error(f"[DATASETS] Labeler API error: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to query Labeler API: {e.response.text}"
            )
    except Exception as e:
        logger.error(f"[DATASETS] Error querying Labeler: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve dataset list: {str(e)}"
        )


# ============================================================================
# Dataset Split Endpoints (Labeler Integration)
# ============================================================================

@router.get("/{dataset_id}/split", response_model=DatasetSplitGetResponse)
async def get_dataset_split(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get dataset default split configuration from Labeler.

    This returns the split_config stored in annotations.json (Layer 1).
    Training jobs can override this with job-level split_strategy (Layer 2).

    Returns:
    - Dataset default split if configured
    - Message if no split configured (will use auto 80/20 during training)
    """
    try:
        # Get dataset metadata from Labeler
        dataset = await labeler_client.get_dataset(dataset_id)
        task_type = dataset.get('task_type', 'classification')

        # Construct annotations path
        storage_path = dataset['storage_path']
        annotations_path = f"{storage_path}/annotations_{task_type}.json"

        logger.info(f"[SPLIT] Loading annotations from: {annotations_path}")

        # Load annotations from R2
        annotations = await load_annotations_from_r2(annotations_path)

        # Check for split_config
        split_config = annotations.get('split_config')

        if not split_config:
            return DatasetSplitGetResponse(
                dataset_id=dataset_id,
                split_config=None,
                has_split=False,
                message="No default split configured. Training jobs will use auto-split (80/20) unless overridden."
            )

        # Calculate statistics
        stats = calculate_split_statistics(split_config)
        num_train = stats.get("train", 0)
        num_val = stats.get("val", 0)
        num_test = stats.get("test", 0)

        logger.info(f"[SPLIT] Found split: train={num_train}, val={num_val}, test={num_test}")

        return DatasetSplitGetResponse(
            dataset_id=dataset_id,
            split_config=SplitConfig(**split_config),
            has_split=True,
            message=f"Dataset split configured: {num_train} train, {num_val} val, {num_test} test"
        )

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(404, f"Dataset '{dataset_id}' not found in Labeler")
        elif e.response.status_code == 403:
            raise HTTPException(403, f"Access denied to dataset '{dataset_id}'")
        else:
            raise HTTPException(500, f"Labeler API error: {e.response.text}")

    except Exception as e:
        logger.error(f"[SPLIT] Failed to get dataset split: {e}")
        raise HTTPException(500, f"Failed to retrieve split configuration: {str(e)}")


@router.post("/{dataset_id}/split", response_model=DatasetSplitResponse)
async def create_or_update_dataset_split(
    dataset_id: str,
    request: DatasetSplitCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create or update dataset default split configuration.

    This updates split_config in annotations.json (Layer 1).
    Requires dataset owner permission.

    Updates:
    1. Load annotations.json from R2
    2. Generate or validate split assignments
    3. Update annotations.json with split_config
    4. Save back to R2

    Note: Individual training jobs can still override this with job-level split_strategy.
    """
    try:
        # Check permission (owner only)
        permission = await labeler_client.check_permission(dataset_id, current_user.id)
        if not permission.get('is_owner'):
            raise HTTPException(403, "Only dataset owner can update default split")

        # Get dataset metadata
        dataset = await labeler_client.get_dataset(dataset_id)
        task_type = dataset.get('task_type', 'classification')
        storage_path = dataset['storage_path']
        annotations_path = f"{storage_path}/annotations_{task_type}.json"

        logger.info(f"[SPLIT] Updating split for dataset {dataset_id}")

        # Load annotations from R2
        from app.storage.dual_storage import dual_storage

        annotations_content = dual_storage.get_file_content(annotations_path)
        annotations = json.loads(annotations_content.decode('utf-8'))

        # Get list of images
        images = annotations.get('images', [])
        if not images:
            raise HTTPException(400, "No images found in annotations.json")

        num_images = len(images)
        logger.info(f"[SPLIT] Found {num_images} images in dataset")

        # Generate splits based on method
        splits = {}

        if request.method == "manual":
            # Use provided splits
            if not request.splits:
                raise HTTPException(400, "Manual split requires 'splits' dictionary")
            splits = validate_manual_split(images, request.splits)

        elif request.method == "auto":
            # Auto-generate splits with specified ratio and seed
            splits = generate_auto_split(images, request.default_ratio, request.seed)

        elif request.method == "partial":
            # Mix of manual and auto
            if request.splits:
                # Start with manual splits
                splits = request.splits.copy()

            # Auto-assign remaining images
            assigned_ids = set(splits.keys())
            unassigned = [img for img in images if str(img['id']) not in assigned_ids]

            if unassigned:
                auto_splits = generate_auto_split(unassigned, request.default_ratio, request.seed)
                splits.update(auto_splits)

        # Update annotations with split_config
        annotations['split_config'] = {
            "method": request.method,
            "default_ratio": request.default_ratio,
            "seed": request.seed,
            "splits": splits,
            "created_at": datetime.utcnow().isoformat(),
            "created_by": current_user.id
        }

        # Save back to R2
        updated_content = json.dumps(annotations, indent=2).encode('utf-8')
        dual_storage.upload_file_content(annotations_path, updated_content)

        logger.info(f"[SPLIT] Updated annotations.json with split configuration")

        # Calculate statistics
        stats = calculate_split_statistics(annotations['split_config'])

        return DatasetSplitResponse(
            dataset_id=dataset_id,
            split_config=SplitConfig(**annotations['split_config']),
            num_splits=len(splits),
            num_train=stats.get("train", 0),
            num_val=stats.get("val", 0),
            message="Dataset split configured successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SPLIT] Failed to update dataset split: {e}")
        raise HTTPException(500, f"Failed to update split configuration: {str(e)}")


# ============================================================================
# Snapshot Endpoints (Platform Management)
# ============================================================================

@router.post("/{dataset_id}/snapshot", response_model=SnapshotResponse)
async def create_dataset_snapshot(
    dataset_id: str,
    request: SnapshotCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create an immutable snapshot of a dataset.

    Platform manages snapshots for training reproducibility.
    Snapshots are created automatically when training jobs start,
    but can also be created manually via this endpoint.

    Process:
    1. Query Labeler for dataset metadata
    2. Copy dataset from R2 (datasets/ → snapshots/)
    3. Store snapshot metadata in Platform DB

    Returns:
        Snapshot metadata with storage path
    """
    try:
        # Get dataset metadata from Labeler
        dataset = await labeler_client.get_dataset(dataset_id)

        # Check permission
        permission = await labeler_client.check_permission(dataset_id, current_user.id)
        if not permission.get('has_access'):
            raise HTTPException(403, "Access denied to dataset")

        # Create snapshot
        snapshot = await snapshot_service.create_snapshot(
            dataset_id=dataset_id,
            dataset_path=dataset['storage_path'],
            user_id=current_user.id,
            db=db,
            notes=request.description or f"Manual snapshot: {request.version_tag or 'no tag'}"
        )

        logger.info(f"[SNAPSHOT] Created snapshot {snapshot.id} for dataset {dataset_id}")

        # Build response
        snapshot_info = SnapshotInfo(
            id=snapshot.id,
            name=f"{dataset['name']} (Snapshot)",
            version_tag=request.version_tag,
            description=request.description,
            snapshot_created_at=snapshot.created_at.isoformat(),
            num_images=dataset.get('num_images', 0),
            num_classes=dataset.get('num_classes'),
            format=dataset.get('format', 'unknown'),
            storage_path=snapshot.storage_path
        )

        return SnapshotResponse(
            snapshot_id=snapshot.id,
            parent_dataset_id=dataset_id,
            snapshot_info=snapshot_info,
            message="Snapshot created successfully"
        )

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(404, f"Dataset '{dataset_id}' not found")
        elif e.response.status_code == 403:
            raise HTTPException(403, "Access denied to dataset")
        else:
            raise HTTPException(500, f"Labeler API error: {e.response.text}")

    except Exception as e:
        logger.error(f"[SNAPSHOT] Failed to create snapshot: {e}")
        raise HTTPException(500, f"Failed to create snapshot: {str(e)}")


@router.get("/{dataset_id}/snapshots", response_model=SnapshotListResponse)
async def list_dataset_snapshots(
    dataset_id: str,
    limit: int = Query(default=50, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all snapshots for a dataset.

    Returns snapshots ordered by creation time (newest first).
    """
    try:
        # Verify dataset exists and user has access
        dataset = await labeler_client.get_dataset(dataset_id)
        permission = await labeler_client.check_permission(dataset_id, current_user.id)
        if not permission.get('has_access'):
            raise HTTPException(403, "Access denied to dataset")

        # Query Platform DB for snapshots
        snapshots = snapshot_service.list_snapshots_by_dataset(dataset_id, db, limit=limit)

        # Build snapshot info list
        snapshot_infos = []
        for snap in snapshots:
            snapshot_infos.append(SnapshotInfo(
                id=snap.id,
                name=f"{dataset['name']} (Snapshot)",
                version_tag=None,  # Could extract from notes
                description=snap.notes,
                snapshot_created_at=snap.created_at.isoformat(),
                num_images=dataset.get('num_images', 0),
                num_classes=dataset.get('num_classes'),
                format=dataset.get('format', 'unknown'),
                storage_path=snap.storage_path
            ))

        logger.info(f"[SNAPSHOT] Found {len(snapshot_infos)} snapshots for dataset {dataset_id}")

        return SnapshotListResponse(
            dataset_id=dataset_id,
            snapshots=snapshot_infos,
            total=len(snapshot_infos),
            message=f"Retrieved {len(snapshot_infos)} snapshot(s)"
        )

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(404, f"Dataset '{dataset_id}' not found")
        elif e.response.status_code == 403:
            raise HTTPException(403, "Access denied to dataset")
        else:
            raise HTTPException(500, f"Labeler API error: {e.response.text}")

    except Exception as e:
        logger.error(f"[SNAPSHOT] Failed to list snapshots: {e}")
        raise HTTPException(500, f"Failed to list snapshots: {str(e)}")


@router.delete("/snapshots/{snapshot_id}")
async def delete_dataset_snapshot(
    snapshot_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a dataset snapshot.

    Removes snapshot from both Platform DB and R2 storage.
    Requires snapshot owner or dataset owner permission.
    """
    try:
        # Get snapshot from Platform DB
        snapshot = db.query(DatasetSnapshot).filter(DatasetSnapshot.id == snapshot_id).first()
        if not snapshot:
            raise HTTPException(404, "Snapshot not found")

        # Check permission
        if snapshot.created_by_user_id != current_user.id:
            # Also check if user is dataset owner
            try:
                permission = await labeler_client.check_permission(snapshot.dataset_id, current_user.id)
                if not permission.get('is_owner'):
                    raise HTTPException(403, "Only snapshot creator or dataset owner can delete snapshot")
            except:
                raise HTTPException(403, "Permission denied")

        # Delete from R2
        from app.storage.dual_storage import dual_storage

        try:
            # List all objects in snapshot folder
            response = dual_storage.external_client.list_objects_v2(
                Bucket=dual_storage.external_bucket_datasets,
                Prefix=snapshot.storage_path
            )

            objects = response.get('Contents', [])
            if objects:
                # Delete all objects
                dual_storage.external_client.delete_objects(
                    Bucket=dual_storage.external_bucket_datasets,
                    Delete={
                        'Objects': [{'Key': obj['Key']} for obj in objects]
                    }
                )
                logger.info(f"[SNAPSHOT] Deleted {len(objects)} objects from R2: {snapshot.storage_path}")

        except Exception as e:
            logger.warning(f"[SNAPSHOT] Failed to delete R2 objects: {e}")

        # Delete from Platform DB
        db.delete(snapshot)
        db.commit()

        logger.info(f"[SNAPSHOT] Deleted snapshot {snapshot_id}")

        return {
            "message": f"Snapshot {snapshot_id} deleted successfully",
            "snapshot_id": snapshot_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SNAPSHOT] Failed to delete snapshot: {e}")
        db.rollback()
        raise HTTPException(500, f"Failed to delete snapshot: {str(e)}")
