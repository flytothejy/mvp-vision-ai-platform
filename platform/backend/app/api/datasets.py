"""
Datasets API endpoints for dataset analysis and management.
"""
from fastapi import APIRouter, HTTPException, Query, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path
from typing import Optional, Dict, List, Any
import logging
import os
import tempfile
import zipfile
import shutil
import json
import uuid
import random
from datetime import datetime
from sqlalchemy.orm import Session

from app.utils.dataset_analyzer import DatasetAnalyzer
from app.utils.dual_storage import dual_storage
from app.db.database import get_db
from app.db.models import Dataset, User
from app.utils.dependencies import get_current_user
from app.schemas.dataset import (
    DatasetSplitCreateRequest,
    DatasetSplitResponse,
    DatasetSplitGetResponse,
    SplitConfig,
    SnapshotCreateRequest,
    SnapshotResponse,
    SnapshotListResponse,
    SnapshotInfo,
    DatasetCompareResponse
)

router = APIRouter()
logger = logging.getLogger(__name__)


class DatasetAnalyzeRequest(BaseModel):
    """Request model for dataset analysis"""
    path: str
    format_hint: Optional[str] = None  # 'imagefolder', 'yolo', 'coco', or None for auto-detect


class DatasetAnalyzeResponse(BaseModel):
    """Response model for dataset analysis"""
    status: str  # 'success' or 'error'
    dataset_info: Optional[Dict[str, Any]] = None
    error_type: Optional[str] = None
    message: Optional[str] = None
    suggestions: Optional[List[str]] = None


def _get_dataset_metadata_from_db(dataset_id: str, db: Session) -> Optional[DatasetAnalyzeResponse]:
    """
    Check if dataset_id exists in database and return metadata.

    Works for all public datasets (including platform samples).
    """
    # Query dataset from database
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.visibility == 'public').first()

    if not dataset:
        return None

    logger.info(f"Found dataset in database: {dataset_id}")

    # Build response from database record
    dataset_info = {
        "format": dataset.format,
        "confidence": 1.0,  # DB datasets are pre-validated
        "labeled": dataset.labeled,  # Whether dataset has annotations
        "structure": {
            "num_classes": dataset.num_classes,
            "num_images": dataset.num_images,
            "classes": dataset.class_names[:10] if dataset.class_names else [],  # First 10 classes
        },
        "statistics": {
            "total_images": dataset.num_images,
            "source": dataset.storage_type,
            "validated": True,
        },
        "samples_per_class": {},  # Not detailed for DB datasets
        "quality_checks": {
            "corrupted_files": [],
            "missing_labels": [],
            "class_imbalance": False,
            "resolution_variance": "uniform",
            "overall_status": "excellent",
        },
        "preview_images": [],  # No preview for DB datasets
    }

    return DatasetAnalyzeResponse(
        status="success",
        dataset_info=dataset_info
    )


@router.post("/analyze", response_model=DatasetAnalyzeResponse)
async def analyze_dataset(request: DatasetAnalyzeRequest, db: Session = Depends(get_db)):
    """
    Analyze a dataset and return structure, statistics, and quality checks.

    - Automatically detects format (ImageFolder, YOLO, COCO)
    - Counts classes and samples
    - Calculates statistics (resolution, size, etc.)
    - Performs quality checks (corrupted files, class imbalance, etc.)
    - Supports public datasets from database (pre-validated metadata)
    """
    try:
        # Check if this is a public dataset in database
        db_dataset = _get_dataset_metadata_from_db(request.path, db)
        if db_dataset:
            logger.info(f"Found public dataset in database: {request.path}")
            return db_dataset

        # Validate path exists
        path = Path(request.path)
        if not path.exists():
            return DatasetAnalyzeResponse(
                status="error",
                error_type="path_not_found",
                message=f"경로를 찾을 수 없습니다: {request.path}",
                suggestions=[
                    "경로가 올바른지 확인하세요",
                    "절대 경로를 사용하세요 (예: C:\\datasets\\imagenet-10)",
                    "네트워크 드라이브의 경우 연결 상태를 확인하세요"
                ]
            )

        if not path.is_dir():
            return DatasetAnalyzeResponse(
                status="error",
                error_type="not_a_directory",
                message=f"경로가 디렉토리가 아닙니다: {request.path}",
                suggestions=[
                    "데이터셋 폴더 경로를 입력하세요",
                    "파일이 아닌 폴더를 선택하세요"
                ]
            )

        # Initialize analyzer
        analyzer = DatasetAnalyzer(path)

        # Detect format
        logger.info(f"Analyzing dataset at: {path}")
        detected_format = analyzer.detect_format(hint=request.format_hint)
        logger.info(f"[DEBUG] detected_format = {detected_format}")

        if detected_format['format'] == 'unknown':
            return DatasetAnalyzeResponse(
                status="error",
                error_type="unknown_format",
                message="데이터셋 형식을 인식할 수 없습니다",
                suggestions=[
                    "지원 형식: ImageFolder, YOLO, COCO",
                    "ImageFolder: dataset/class1/img1.jpg",
                    "YOLO: images/*.jpg + labels/*.txt",
                    "COCO: annotations/*.json + images/"
                ]
            )

        # Collect statistics
        logger.info(f"Collecting statistics for {detected_format['format']} format")
        stats = analyzer.collect_statistics(detected_format['format'])

        # Perform quality checks
        logger.info("Performing quality checks")
        quality_checks = analyzer.check_quality(stats)

        # Build response
        dataset_info = {
            "format": detected_format['format'],
            "confidence": detected_format['confidence'],
            "task_type": detected_format.get('task_type'),
            "structure": stats.get('structure', {}),
            "statistics": stats.get('statistics', {}),
            "samples_per_class": stats.get('samples_per_class', {}),
            "quality_checks": quality_checks,
            "preview_images": stats.get('preview_images', [])
        }

        return DatasetAnalyzeResponse(
            status="success",
            dataset_info=dataset_info
        )

    except PermissionError:
        return DatasetAnalyzeResponse(
            status="error",
            error_type="permission_denied",
            message="경로에 대한 접근 권한이 없습니다",
            suggestions=[
                "폴더의 권한을 확인하세요",
                "관리자 권한으로 실행해보세요"
            ]
        )
    except Exception as e:
        logger.error(f"Error analyzing dataset: {str(e)}", exc_info=True)
        return DatasetAnalyzeResponse(
            status="error",
            error_type="analysis_error",
            message=f"데이터셋 분석 중 오류가 발생했습니다: {str(e)}",
            suggestions=[
                "데이터셋 구조가 올바른지 확인하세요",
                "일부 파일이 손상되었을 수 있습니다"
            ]
        )


class SampleDatasetInfo(BaseModel):
    """Sample dataset information"""
    id: str
    name: str
    description: str
    format: str
    labeled: bool  # Changed from task_type - indicates if dataset has annotations
    num_items: int
    size_mb: Optional[float] = None
    source: str
    path: str
    visibility: str  # 'public', 'private', 'organization'
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    owner_badge_color: Optional[str] = None


class DatasetListItem(BaseModel):
    """Dataset list item"""
    name: str
    path: str
    size_mb: Optional[float] = None
    num_items: Optional[int] = None


class DatasetListResponse(BaseModel):
    """Response model for dataset list"""
    base_path: str
    datasets: List[DatasetListItem]


@router.get("/available", response_model=List[SampleDatasetInfo])
async def list_sample_datasets(
    labeled: Optional[bool] = Query(default=None, description="Filter by labeled status (true=has annotations, false=unlabeled)"),
    tags: Optional[str] = Query(default=None, description="Filter by tags (comma-separated)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List available datasets for the current user.

    Phase 11.5: Dataset Service Integration - Queries Labeler API instead of Platform DB.

    Returns:
    - User's own datasets (where owner_id == user_id)
    - Public datasets (visibility == 'public')

    Args:
        labeled: Optional filter by labeled status
        tags: Optional filter by tags (comma-separated, e.g., "platform-sample,coco")
        current_user: Current authenticated user
        db: Database session

    Returns:
        List of datasets with metadata from Labeler
    """
    from app.clients.labeler_client import labeler_client
    import httpx

    try:
        # Query Labeler API for datasets
        tag_list = [t.strip() for t in tags.split(',')] if tags else None

        result = await labeler_client.list_datasets(
            user_id=current_user.id,
            labeled=labeled,
            tags=tag_list,
            page=1,
            limit=100  # Get all datasets (adjust if needed)
        )

        datasets = result.get("datasets", [])
        logger.info(
            f"User {current_user.id} ({current_user.email}) querying datasets: "
            f"found {len(datasets)} datasets from Labeler API"
        )

        # Convert Labeler response to Platform format
        response_list = []
        for ds in datasets:
            response_list.append({
                "id": ds["id"],
                "name": ds["name"],
                "description": ds.get("description", f"Dataset - {ds['format']} format"),
                "format": ds["format"],
                "labeled": ds["labeled"],
                "num_items": ds.get("num_images", 0),
                "size_mb": None,  # Labeler doesn't return size yet
                "source": ds.get("storage_type", "r2"),
                "path": ds["id"],  # Use ID as path
                "visibility": ds.get("visibility", "public"),
                "owner_id": ds.get("owner_id"),
                "owner_name": None,  # Labeler doesn't return owner details
                "owner_email": None,
                "owner_badge_color": None,
            })

        return response_list

    except httpx.HTTPError as e:
        logger.error(f"Failed to query Labeler API: {e}")
        # Fallback to empty list on error
        raise HTTPException(
            status_code=503,
            detail="Dataset service temporarily unavailable. Please try again later."
        )


@router.get("/list", response_model=DatasetListResponse)
async def list_datasets(
    base_path: str = Query(default="C:\\datasets", description="Base directory to scan for datasets")
):
    """
    List available datasets in the specified base directory.

    Scans for subdirectories that appear to be datasets based on their structure.
    """
    try:
        base = Path(base_path)

        if not base.exists():
            # Try common dataset locations
            alternative_paths = [
                Path("C:\\datasets"),
                Path("D:\\datasets"),
                Path.home() / "datasets",
                Path.cwd() / "datasets"
            ]

            for alt_path in alternative_paths:
                if alt_path.exists():
                    base = alt_path
                    break
            else:
                # None found, return empty list
                return DatasetListResponse(
                    base_path=str(base),
                    datasets=[]
                )

        if not base.is_dir():
            return DatasetListResponse(
                base_path=str(base),
                datasets=[]
            )

        datasets = []

        # Scan subdirectories
        try:
            for item in base.iterdir():
                if not item.is_dir():
                    continue

                # Skip hidden directories
                if item.name.startswith('.'):
                    continue

                # Calculate directory size and item count
                size_bytes = 0
                num_items = 0

                try:
                    for root, dirs, files in os.walk(item):
                        # Count image files
                        image_files = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'))]
                        num_items += len(image_files)

                        # Calculate size
                        for file in files:
                            try:
                                size_bytes += os.path.getsize(os.path.join(root, file))
                            except:
                                pass
                except:
                    pass

                size_mb = round(size_bytes / (1024 * 1024), 2) if size_bytes > 0 else None

                datasets.append(DatasetListItem(
                    name=item.name,
                    path=str(item),
                    size_mb=size_mb,
                    num_items=num_items if num_items > 0 else None
                ))

        except PermissionError:
            logger.warning(f"Permission denied accessing {base}")

        # Sort by name
        datasets.sort(key=lambda x: x.name.lower())

        return DatasetListResponse(
            base_path=str(base),
            datasets=datasets
        )

    except Exception as e:
        logger.error(f"Error listing datasets: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list datasets: {str(e)}")


class CreateDatasetRequest(BaseModel):
    """Request model for creating a new dataset"""
    name: str
    description: Optional[str] = None
    visibility: str = "private"  # 'public', 'private', 'organization'


class CreateDatasetResponse(BaseModel):
    """Response model for dataset creation"""
    status: str
    dataset_id: Optional[str] = None
    message: str
    dataset: Optional[Dict[str, Any]] = None


@router.post("", response_model=CreateDatasetResponse)
async def create_dataset(
    request: CreateDatasetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new empty dataset (metadata only).

    Images can be uploaded later via the folder upload endpoint.

    Args:
        request: Dataset creation request with name, description, visibility
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created dataset information
    """
    try:
        # Generate unique dataset ID
        dataset_id = str(uuid.uuid4())

        # Create dataset record (empty, no images yet)
        new_dataset = Dataset(
            id=dataset_id,
            name=request.name,
            description=request.description or f"Dataset: {request.name}",
            format="dice",  # Default format
            labeled=False,  # No annotations yet
            storage_type=dual_storage.external_storage_type,  # Auto-detect from environment (r2, minio, s3)
            storage_path=f"datasets/{dataset_id}/",  # Reserve storage path
            visibility=request.visibility,
            owner_id=current_user.id,  # Set owner to current user
            num_classes=0,
            num_images=0,  # Empty dataset
            class_names=[],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(new_dataset)
        db.commit()
        db.refresh(new_dataset)

        logger.info(f"Created empty dataset: {dataset_id} - {request.name}")

        return CreateDatasetResponse(
            status="success",
            dataset_id=dataset_id,
            message=f"Dataset '{request.name}' created successfully",
            dataset={
                "id": dataset_id,
                "name": request.name,
                "description": new_dataset.description,
                "visibility": request.visibility,
                "num_images": 0,
                "created_at": new_dataset.created_at.isoformat()
            }
        )

    except Exception as e:
        logger.error(f"Error creating dataset: {str(e)}", exc_info=True)
        return CreateDatasetResponse(
            status="error",
            message=f"Failed to create dataset: {str(e)}"
        )


class DeleteDatasetResponse(BaseModel):
    """Response model for dataset deletion"""
    status: str
    message: str


@router.delete("/{dataset_id}", response_model=DeleteDatasetResponse)
async def delete_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a dataset and all its associated data.

    Only the dataset owner can delete it.

    This will:
    1. Delete all images from R2 storage
    2. Delete the dataset record from database

    Args:
        dataset_id: Dataset ID to delete
        current_user: Current authenticated user
        db: Database session

    Returns:
        Deletion status
    """
    try:
        # Find dataset in database
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()

        if not dataset:
            return DeleteDatasetResponse(
                status="error",
                message=f"Dataset not found: {dataset_id}"
            )

        # Check if user has permission to delete (must be owner)
        if dataset.owner_id != current_user.id:
            logger.warning(f"User {current_user.id} attempted to delete dataset {dataset_id} owned by {dataset.owner_id}")
            return DeleteDatasetResponse(
                status="error",
                message="Permission denied: You can only delete your own datasets"
            )

        # Delete all images from storage
        try:
            storage = dual_storage
            prefix = f"datasets/{dataset_id}/"
            deleted_count = storage.delete_all_with_prefix(prefix)
            logger.info(f"Deleted {deleted_count} objects from storage with prefix: {prefix}")
        except Exception as e:
            logger.warning(f"Error deleting storage objects for dataset {dataset_id}: {str(e)}")
            # Continue with database deletion even if storage deletion fails

        # Delete dataset record from database
        db.delete(dataset)
        db.commit()

        logger.info(f"Deleted dataset: {dataset_id} - {dataset.name}")

        return DeleteDatasetResponse(
            status="success",
            message=f"Dataset '{dataset.name}' deleted successfully"
        )

    except Exception as e:
        logger.error(f"Error deleting dataset: {str(e)}", exc_info=True)
        db.rollback()
        return DeleteDatasetResponse(
            status="error",
            message=f"Failed to delete dataset: {str(e)}"
        )


@router.get("/{dataset_id}/file/{filename}")
async def get_dataset_file(
    dataset_id: str,
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific file from dataset (e.g., annotations.json).

    This endpoint allows downloading dataset metadata files like annotations.json
    to check which images have labels without downloading all images.
    """
    try:
        # Verify dataset exists and user has access
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")

        # Check user ownership or public access
        if dataset.owner_id != current_user.id and dataset.visibility != 'public':
            raise HTTPException(status_code=403, detail="Access denied")

        # Construct storage key for the file
        storage_key = f"datasets/{dataset_id}/{filename}"

        logger.info(f"Fetching file from storage: {storage_key}")

        # Get file content from storage
        storage = dual_storage
        file_content = storage.get_file_content(storage_key)

        if file_content is None:
            raise HTTPException(
                status_code=404,
                detail=f"File '{filename}' not found in dataset"
            )

        # Parse JSON if it's a JSON file
        if filename.endswith('.json'):
            try:
                # Decode bytes to string, then parse JSON
                json_str = file_content.decode('utf-8')
                json_data = json.loads(json_str)
                return JSONResponse(content=json_data)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                logger.error(f"Failed to parse JSON file {filename}: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to parse JSON file: {str(e)}"
                )

        # For non-JSON files, return raw content as base64
        import base64
        encoded_content = base64.b64encode(file_content).decode('utf-8')
        return JSONResponse(content={"content": encoded_content})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching dataset file: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch file: {str(e)}"
        )


# ============================================================================
# Dataset Split API
# ============================================================================

@router.post("/{dataset_id}/split", response_model=DatasetSplitResponse)
async def create_or_update_dataset_split(
    dataset_id: str,
    request: DatasetSplitCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create or update dataset split configuration.

    This will:
    1. Load annotations.json from storage
    2. Generate or validate split assignments
    3. Update annotations.json with split_config
    4. Cache split_config in datasets table
    """
    import random

    # Check if dataset exists and user has access
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Check ownership or permissions
    if dataset.owner_id != current_user.id:
        # TODO: Check dataset permissions
        raise HTTPException(status_code=403, detail="You don't have permission to modify this dataset")

    # Check if dataset has annotations
    if not dataset.labeled or not dataset.annotation_path:
        raise HTTPException(
            status_code=400,
            detail="Dataset must have annotations.json to configure splits"
        )

    try:
        # Load annotations.json from storage
        storage_client = dual_storage
        annotations_key = dataset.annotation_path

        logger.info(f"Loading annotations from: {annotations_key}")
        annotations_data = storage_client.get_file_content(annotations_key)
        annotations = json.loads(annotations_data.decode('utf-8'))

        # Get list of images
        images = annotations.get('images', [])
        if not images:
            raise HTTPException(status_code=400, detail="No images found in annotations.json")

        num_images = len(images)
        logger.info(f"Found {num_images} images in dataset")

        # Generate splits based on method
        splits = {}

        if request.method == "manual":
            # Use provided splits
            if not request.splits:
                raise HTTPException(
                    status_code=400,
                    detail="Manual split requires 'splits' dictionary"
                )
            splits = request.splits

        elif request.method == "auto":
            # Auto-generate splits with specified ratio and seed
            random.seed(request.seed)
            image_ids = [img['id'] for img in images]
            shuffled = image_ids.copy()
            random.shuffle(shuffled)

            # Calculate split index
            train_ratio = request.default_ratio[0]
            split_idx = int(len(shuffled) * train_ratio)

            # Assign splits (ensure img_id is string for Pydantic validation)
            for idx, img_id in enumerate(shuffled):
                if idx < split_idx:
                    splits[str(img_id)] = 'train'
                else:
                    splits[str(img_id)] = 'val'

        elif request.method == "partial":
            # Use provided splits and auto-fill the rest
            if request.splits:
                splits = request.splits.copy()

            # Find images without split assignment
            unassigned = [
                img['id'] for img in images
                if str(img['id']) not in splits or splits.get(str(img['id'])) is None
            ]

            if unassigned:
                # Auto-assign remaining images
                random.seed(request.seed)
                random.shuffle(unassigned)

                train_ratio = request.default_ratio[0]
                split_idx = int(len(unassigned) * train_ratio)

                for idx, img_id in enumerate(unassigned):
                    splits[str(img_id)] = 'train' if idx < split_idx else 'val'

        # Count train/val images
        num_train = sum(1 for split in splits.values() if split == 'train')
        num_val = sum(1 for split in splits.values() if split == 'val')

        logger.info(f"Split result: {num_train} train, {num_val} val")

        # Create split_config
        split_config = {
            "method": request.method,
            "default_ratio": request.default_ratio,
            "seed": request.seed,
            "splits": splits,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": current_user.id
        }

        # Update annotations.json
        annotations['split_config'] = split_config

        # Save back to storage
        updated_annotations = json.dumps(annotations, indent=2).encode('utf-8')
        storage_client.upload_bytes(updated_annotations, annotations_key, content_type='application/json')
        logger.info(f"Updated annotations.json with split config")

        # Update database cache
        dataset.split_config = split_config
        db.commit()
        logger.info(f"Cached split config in database")

        return DatasetSplitResponse(
            dataset_id=dataset_id,
            split_config=SplitConfig(**split_config),
            num_splits=len(splits),
            num_train=num_train,
            num_val=num_val,
            message="Dataset split configured successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating dataset split: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create dataset split: {str(e)}"
        )


@router.get("/{dataset_id}/split", response_model=DatasetSplitGetResponse)
async def get_dataset_split(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get dataset split configuration.

    Returns the split configuration if exists, or null if not configured.
    """
    # Check if dataset exists and user has access
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Check access (public datasets are accessible to everyone)
    if dataset.visibility == 'private' and dataset.owner_id != current_user.id:
        # TODO: Check dataset permissions
        raise HTTPException(status_code=403, detail="You don't have permission to access this dataset")

    # Return split config from database cache
    if dataset.split_config:
        return DatasetSplitGetResponse(
            dataset_id=dataset_id,
            split_config=SplitConfig(**dataset.split_config),
            has_split=True,
            message="Dataset split configuration retrieved"
        )
    else:
        return DatasetSplitGetResponse(
            dataset_id=dataset_id,
            split_config=None,
            has_split=False,
            message="Dataset has no split configuration"
        )


# ============================================================================
# Snapshot Management Endpoints
# ============================================================================

@router.post("/{dataset_id}/snapshot", response_model=SnapshotResponse)
async def create_dataset_snapshot(
    dataset_id: str,
    request: SnapshotCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a snapshot of a dataset.

    Snapshots are immutable copies of datasets at a specific point in time.
    They are stored separately and can be used for training to ensure reproducibility.

    Args:
        dataset_id: Parent dataset ID
        request: Snapshot creation request (version_tag, description)
        current_user: Current authenticated user
        db: Database session

    Returns:
        SnapshotResponse with created snapshot information
    """
    # Check if parent dataset exists
    parent_dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not parent_dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Check permissions (owner or editor can create snapshots)
    if parent_dataset.visibility == 'private' and parent_dataset.owner_id != current_user.id:
        # TODO: Check dataset permissions for editor role
        raise HTTPException(status_code=403, detail="You don't have permission to create snapshots for this dataset")

    # Cannot snapshot a snapshot
    if parent_dataset.is_snapshot:
        raise HTTPException(status_code=400, detail="Cannot create snapshot of a snapshot")

    # Generate snapshot ID
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    snapshot_id = f"{dataset_id}-snapshot-{timestamp}"

    # Generate snapshot name
    snapshot_name = f"{parent_dataset.name} (Snapshot"
    if request.version_tag:
        snapshot_name += f" {request.version_tag}"
    snapshot_name += f" - {timestamp})"

    # Copy dataset files in storage
    storage_client = dual_storage
    parent_storage_path = parent_dataset.storage_path.rstrip('/')
    snapshot_storage_path = f"datasets/snapshots/{snapshot_id}/"

    try:
        # List all files in parent dataset
        logger.info(f"Creating snapshot: copying from {parent_storage_path} to {snapshot_storage_path}")

        # Copy all files from parent to snapshot
        # NOTE: This is a simplified implementation. In production, use storage provider's native copy/clone
        files = storage_client.list_files(parent_storage_path)
        logger.info(f"Found {len(files)} files to copy")

        for file_path in files:
            # Get relative path
            relative_path = file_path.replace(parent_storage_path, '').lstrip('/')
            if not relative_path:
                continue

            # Download and re-upload (inefficient but works across storage providers)
            file_content = storage_client.get_file_content(file_path)
            target_path = f"{snapshot_storage_path}{relative_path}"

            # Determine content type
            content_type = 'application/octet-stream'
            if relative_path.endswith('.json'):
                content_type = 'application/json'
            elif relative_path.endswith('.yaml') or relative_path.endswith('.yml'):
                content_type = 'application/x-yaml'
            elif relative_path.lower().endswith(('.jpg', '.jpeg')):
                content_type = 'image/jpeg'
            elif relative_path.lower().endswith('.png'):
                content_type = 'image/png'

            storage_client.upload_bytes(file_content, target_path, content_type=content_type)

        logger.info(f"Snapshot files copied successfully")

    except Exception as e:
        logger.error(f"Failed to copy dataset files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to copy dataset files: {str(e)}")

    # Create snapshot database record
    snapshot_dataset = Dataset(
        id=snapshot_id,
        name=snapshot_name,
        description=request.description or f"Snapshot of {parent_dataset.name}",
        owner_id=current_user.id,
        visibility=parent_dataset.visibility,  # Inherit visibility
        tags=parent_dataset.tags,  # Copy tags
        storage_path=snapshot_storage_path,
        storage_type=parent_dataset.storage_type,
        format=parent_dataset.format,
        labeled=parent_dataset.labeled,
        annotation_path=snapshot_storage_path + "annotations.json" if parent_dataset.annotation_path else None,
        num_classes=parent_dataset.num_classes,
        num_images=parent_dataset.num_images,
        class_names=parent_dataset.class_names,
        split_config=parent_dataset.split_config,  # Copy split config
        is_snapshot=True,
        parent_dataset_id=dataset_id,
        snapshot_created_at=datetime.utcnow(),
        version_tag=request.version_tag,
        status='active',
        integrity_status='valid',
        version=1,
        content_hash=parent_dataset.content_hash,  # Copy content hash
        last_modified_at=parent_dataset.last_modified_at,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.add(snapshot_dataset)
    db.commit()
    db.refresh(snapshot_dataset)

    logger.info(f"Snapshot created: {snapshot_id} from parent {dataset_id}")

    # Build response
    snapshot_info = SnapshotInfo(
        id=snapshot_dataset.id,
        name=snapshot_dataset.name,
        version_tag=snapshot_dataset.version_tag,
        description=snapshot_dataset.description,
        snapshot_created_at=snapshot_dataset.snapshot_created_at.isoformat() + "Z",
        num_images=snapshot_dataset.num_images,
        num_classes=snapshot_dataset.num_classes,
        format=snapshot_dataset.format,
        storage_path=snapshot_dataset.storage_path
    )

    return SnapshotResponse(
        snapshot_id=snapshot_id,
        parent_dataset_id=dataset_id,
        snapshot_info=snapshot_info,
        message="Snapshot created successfully"
    )


@router.get("/{dataset_id}/snapshots", response_model=SnapshotListResponse)
async def list_dataset_snapshots(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all snapshots of a dataset.

    Returns snapshots in reverse chronological order (most recent first).

    Args:
        dataset_id: Parent dataset ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SnapshotListResponse with list of snapshots
    """
    # Check if parent dataset exists
    parent_dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not parent_dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Check permissions
    if parent_dataset.visibility == 'private' and parent_dataset.owner_id != current_user.id:
        # TODO: Check dataset permissions
        raise HTTPException(status_code=403, detail="You don't have permission to access this dataset")

    # Query snapshots (children with parent_dataset_id = dataset_id)
    snapshots = db.query(Dataset).filter(
        Dataset.parent_dataset_id == dataset_id,
        Dataset.is_snapshot == True,
        Dataset.status == 'active'
    ).order_by(Dataset.snapshot_created_at.desc()).all()

    # Build snapshot info list
    snapshot_infos = []
    for snapshot in snapshots:
        snapshot_infos.append(SnapshotInfo(
            id=snapshot.id,
            name=snapshot.name,
            version_tag=snapshot.version_tag,
            description=snapshot.description,
            snapshot_created_at=snapshot.snapshot_created_at.isoformat() + "Z" if snapshot.snapshot_created_at else "",
            num_images=snapshot.num_images,
            num_classes=snapshot.num_classes,
            format=snapshot.format,
            storage_path=snapshot.storage_path
        ))

    return SnapshotListResponse(
        dataset_id=dataset_id,
        snapshots=snapshot_infos,
        total=len(snapshot_infos),
        message=f"Retrieved {len(snapshot_infos)} snapshot(s)"
    )


@router.delete("/{snapshot_id}")
async def delete_dataset_snapshot(
    snapshot_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a dataset snapshot.

    Only snapshots (is_snapshot=True) can be deleted via this endpoint.
    Parent datasets must use the regular dataset deletion endpoint.

    Args:
        snapshot_id: Snapshot dataset ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Success message
    """
    # Check if snapshot exists
    snapshot = db.query(Dataset).filter(Dataset.id == snapshot_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    # Verify it's actually a snapshot
    if not snapshot.is_snapshot:
        raise HTTPException(
            status_code=400,
            detail="This is not a snapshot. Use the regular dataset deletion endpoint for parent datasets."
        )

    # Check permissions (only owner can delete)
    if snapshot.owner_id != current_user.id:
        # TODO: Check dataset permissions
        raise HTTPException(status_code=403, detail="You don't have permission to delete this snapshot")

    # Delete from storage
    storage_client = dual_storage
    try:
        # Delete all files in snapshot storage path
        files = storage_client.list_files(snapshot.storage_path.rstrip('/'))
        logger.info(f"Deleting {len(files)} files from snapshot {snapshot_id}")

        for file_path in files:
            storage_client.delete_file(file_path)

        logger.info(f"Snapshot files deleted successfully")
    except Exception as e:
        logger.error(f"Failed to delete snapshot files: {e}")
        # Continue with database deletion even if storage deletion fails

    # Delete from database
    db.delete(snapshot)
    db.commit()

    logger.info(f"Snapshot deleted: {snapshot_id}")

    return JSONResponse(
        status_code=200,
        content={
            "message": "Snapshot deleted successfully",
            "snapshot_id": snapshot_id
        }
    )


@router.get("/compare", response_model=DatasetCompareResponse)
async def compare_datasets(
    dataset_a: str = Query(..., description="First dataset ID"),
    dataset_b: str = Query(..., description="Second dataset ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Compare two datasets to identify differences.

    Useful for comparing a parent dataset with its snapshot to see what changed,
    or comparing two different versions of a dataset.

    Args:
        dataset_a: First dataset ID
        dataset_b: Second dataset ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        DatasetCompareResponse with comparison results
    """
    # Check if both datasets exist
    dataset_a_obj = db.query(Dataset).filter(Dataset.id == dataset_a).first()
    dataset_b_obj = db.query(Dataset).filter(Dataset.id == dataset_b).first()

    if not dataset_a_obj:
        raise HTTPException(status_code=404, detail=f"Dataset A '{dataset_a}' not found")
    if not dataset_b_obj:
        raise HTTPException(status_code=404, detail=f"Dataset B '{dataset_b}' not found")

    # Check permissions for both datasets
    for dataset in [dataset_a_obj, dataset_b_obj]:
        if dataset.visibility == 'private' and dataset.owner_id != current_user.id:
            # TODO: Check dataset permissions
            raise HTTPException(status_code=403, detail=f"You don't have permission to access dataset {dataset.id}")

    # Simple comparison based on database metadata
    # For deep comparison, would need to load and compare annotations.json

    images_added = max(0, dataset_b_obj.num_images - dataset_a_obj.num_images)
    images_removed = max(0, dataset_a_obj.num_images - dataset_b_obj.num_images)
    images_unchanged = min(dataset_a_obj.num_images, dataset_b_obj.num_images)

    # Compare class names
    classes_a = set(dataset_a_obj.class_names or [])
    classes_b = set(dataset_b_obj.class_names or [])

    classes_added = list(classes_b - classes_a)
    classes_removed = list(classes_a - classes_b)

    # For annotation changes, would need deep comparison of annotations.json
    # Placeholder: assume 0 for now
    annotation_changes = 0

    return DatasetCompareResponse(
        dataset_a_id=dataset_a,
        dataset_b_id=dataset_b,
        images_added=images_added,
        images_removed=images_removed,
        images_unchanged=images_unchanged,
        classes_added=classes_added,
        classes_removed=classes_removed,
        annotation_changes=annotation_changes,
        message="Comparison completed (metadata-based)"
    )
