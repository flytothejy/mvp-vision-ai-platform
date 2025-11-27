"""Dataset and Split schemas."""

from typing import Optional, Dict, List, Literal
from pydantic import BaseModel, Field
from datetime import datetime


# ============================================================================
# Split Schemas (for train/val/test split configuration)
# ============================================================================

class SplitConfig(BaseModel):
    """Dataset-level split configuration.

    Stored in annotations.json and cached in datasets.split_config column.
    Defines default split for this dataset that will be used by all training jobs
    unless overridden at job level.
    """
    method: Literal["manual", "auto", "partial"] = Field(
        description="Split method: 'manual' (user-defined), 'auto' (random with seed), 'partial' (mix of both)"
    )
    default_ratio: List[float] = Field(
        default=[0.8, 0.2],
        description="Default train/val split ratio, e.g., [0.8, 0.2] for 80/20"
    )
    seed: int = Field(
        default=42,
        description="Random seed for reproducible auto-splits"
    )
    splits: Optional[Dict[str, str]] = Field(
        default=None,
        description="Image ID to split mapping: {'image_001': 'train', 'image_002': 'val', ...}"
    )
    created_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 datetime when split was created"
    )
    created_by: Optional[int] = Field(
        default=None,
        description="User ID who created this split configuration"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "method": "auto",
                "default_ratio": [0.8, 0.2],
                "seed": 42,
                "splits": {
                    "image_001": "train",
                    "image_002": "train",
                    "image_003": "val",
                    "image_004": "train",
                    "image_005": "val"
                },
                "created_at": "2025-01-10T10:00:00Z",
                "created_by": 1
            }
        }


class SplitStrategy(BaseModel):
    """Job-level split strategy (overrides dataset-level split).

    Specified when creating a training job to override the dataset's default split.
    This allows different experiments to use different splits on the same dataset.

    Phase 11.5.5: Split Integration
    - Implements 3-Level Priority System for split resolution
    """
    method: Literal["use_dataset", "auto", "custom"] = Field(
        description=(
            "'use_dataset': Use dataset.split_config from Labeler annotations.json, "
            "'auto': Random split with specified ratio/seed, "
            "'custom': Provide explicit split mapping per image"
        )
    )
    ratio: Optional[List[float]] = Field(
        default=None,
        description="Train/val/test ratio for 'auto' method, e.g., [0.8, 0.2] or [0.7, 0.2, 0.1]"
    )
    seed: Optional[int] = Field(
        default=42,
        description="Random seed for 'auto' method reproducibility"
    )
    custom_splits: Optional[Dict[str, str]] = Field(
        default=None,
        description="Custom split mapping for 'custom' method: {'image_id': 'train'|'val'|'test'}"
    )
    exclude_images: Optional[List[str]] = Field(
        default=None,
        description="List of image IDs to exclude from training (e.g., corrupted images)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "method": "auto",
                "ratio": [0.7, 0.3],
                "seed": 123
            }
        }


class SplitInfo(BaseModel):
    """Split information returned when querying split status."""
    source: Literal["dataset", "job", "runtime"] = Field(
        description="Where the split came from: 'dataset' (dataset.split_config), 'job' (job.split_strategy), 'runtime' (auto-generated)"
    )
    method: str = Field(description="Split method used")
    ratio: List[float] = Field(description="Actual train/val ratio")
    seed: int = Field(description="Random seed used")
    num_train: int = Field(description="Number of training images")
    num_val: int = Field(description="Number of validation images")
    num_total: int = Field(description="Total number of images")

    class Config:
        json_schema_extra = {
            "example": {
                "source": "dataset",
                "method": "auto",
                "ratio": [0.8, 0.2],
                "seed": 42,
                "num_train": 800,
                "num_val": 200,
                "num_total": 1000
            }
        }


# ============================================================================
# Dataset Split API Schemas
# ============================================================================

class DatasetSplitCreateRequest(BaseModel):
    """Request to create or update dataset split configuration."""
    method: Literal["manual", "auto", "partial"] = Field(
        description="Split method"
    )
    default_ratio: List[float] = Field(
        default=[0.8, 0.2],
        description="Train/val split ratio"
    )
    seed: int = Field(
        default=42,
        description="Random seed for reproducibility"
    )
    splits: Optional[Dict[str, str]] = Field(
        default=None,
        description="Manual split mapping (for 'manual' or 'partial' methods)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "method": "auto",
                "default_ratio": [0.8, 0.2],
                "seed": 42
            }
        }


class DatasetSplitResponse(BaseModel):
    """Response after creating/updating dataset split."""
    dataset_id: str
    split_config: SplitConfig
    num_splits: int = Field(description="Number of images with split assignments")
    num_train: int = Field(description="Number of training images")
    num_val: int = Field(description="Number of validation images")
    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "dataset_id": "dataset-abc123",
                "split_config": {
                    "method": "auto",
                    "default_ratio": [0.8, 0.2],
                    "seed": 42,
                    "splits": {},
                    "created_at": "2025-01-10T10:00:00Z",
                    "created_by": 1
                },
                "num_splits": 1000,
                "num_train": 800,
                "num_val": 200,
                "message": "Dataset split configured successfully"
            }
        }


class DatasetSplitGetResponse(BaseModel):
    """Response when getting dataset split configuration."""
    dataset_id: str
    split_config: Optional[SplitConfig] = Field(
        default=None,
        description="Split configuration if exists, None otherwise"
    )
    has_split: bool = Field(description="Whether dataset has split configuration")
    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "dataset_id": "dataset-abc123",
                "split_config": {
                    "method": "auto",
                    "default_ratio": [0.8, 0.2],
                    "seed": 42,
                    "splits": {},
                    "created_at": "2025-01-10T10:00:00Z",
                    "created_by": 1
                },
                "has_split": True,
                "message": "Dataset split configuration retrieved"
            }
        }


# ============================================================================
# Snapshot API Schemas
# ============================================================================

class SnapshotCreateRequest(BaseModel):
    """Request to create a dataset snapshot."""
    version_tag: Optional[str] = Field(
        default=None,
        description="Optional version tag for the snapshot (e.g., 'v1.0', 'stable')"
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional description of this snapshot"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "version_tag": "v1.0",
                "description": "Initial stable version for production training"
            }
        }


class SnapshotInfo(BaseModel):
    """Snapshot metadata information."""
    id: str = Field(description="Snapshot dataset ID")
    name: str = Field(description="Snapshot dataset name")
    version_tag: Optional[str] = Field(description="Version tag")
    description: Optional[str] = Field(description="Snapshot description")
    snapshot_created_at: str = Field(description="When snapshot was created (ISO 8601)")
    num_images: int = Field(description="Number of images in snapshot")
    num_classes: Optional[int] = Field(description="Number of classes")
    format: str = Field(description="Dataset format")
    storage_path: str = Field(description="Storage path")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "dataset-abc123-snapshot-20250113",
                "name": "My Dataset (Snapshot v1.0)",
                "version_tag": "v1.0",
                "description": "Initial stable version",
                "snapshot_created_at": "2025-01-13T10:30:00Z",
                "num_images": 1000,
                "num_classes": 10,
                "format": "yolo",
                "storage_path": "datasets/snapshots/dataset-abc123-snapshot-20250113/"
            }
        }


class SnapshotResponse(BaseModel):
    """Response after creating a snapshot."""
    snapshot_id: str = Field(description="Created snapshot dataset ID")
    parent_dataset_id: str = Field(description="Parent dataset ID")
    snapshot_info: SnapshotInfo
    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "snapshot_id": "dataset-abc123-snapshot-20250113",
                "parent_dataset_id": "dataset-abc123",
                "snapshot_info": {
                    "id": "dataset-abc123-snapshot-20250113",
                    "name": "My Dataset (Snapshot v1.0)",
                    "version_tag": "v1.0",
                    "description": "Initial stable version",
                    "snapshot_created_at": "2025-01-13T10:30:00Z",
                    "num_images": 1000,
                    "num_classes": 10,
                    "format": "yolo",
                    "storage_path": "datasets/snapshots/dataset-abc123-snapshot-20250113/"
                },
                "message": "Snapshot created successfully"
            }
        }


class SnapshotListResponse(BaseModel):
    """Response for listing dataset snapshots."""
    dataset_id: str = Field(description="Parent dataset ID")
    snapshots: List[SnapshotInfo] = Field(description="List of snapshots")
    total: int = Field(description="Total number of snapshots")
    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "dataset_id": "dataset-abc123",
                "snapshots": [
                    {
                        "id": "dataset-abc123-snapshot-20250113",
                        "name": "My Dataset (Snapshot v1.0)",
                        "version_tag": "v1.0",
                        "description": "Initial stable version",
                        "snapshot_created_at": "2025-01-13T10:30:00Z",
                        "num_images": 1000,
                        "num_classes": 10,
                        "format": "yolo",
                        "storage_path": "datasets/snapshots/dataset-abc123-snapshot-20250113/"
                    }
                ],
                "total": 1,
                "message": "Retrieved 1 snapshot(s)"
            }
        }


class DatasetCompareResponse(BaseModel):
    """Response for comparing two datasets."""
    dataset_a_id: str
    dataset_b_id: str
    images_added: int = Field(description="Number of images added in B compared to A")
    images_removed: int = Field(description="Number of images removed in B compared to A")
    images_unchanged: int = Field(description="Number of unchanged images")
    classes_added: List[str] = Field(description="New classes in B")
    classes_removed: List[str] = Field(description="Removed classes from A")
    annotation_changes: int = Field(description="Number of images with annotation changes")
    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "dataset_a_id": "dataset-abc123-snapshot-v1",
                "dataset_b_id": "dataset-abc123",
                "images_added": 50,
                "images_removed": 5,
                "images_unchanged": 945,
                "classes_added": ["bicycle", "motorcycle"],
                "classes_removed": [],
                "annotation_changes": 12,
                "message": "Comparison completed"
            }
        }
