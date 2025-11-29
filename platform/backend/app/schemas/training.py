"""Training-related Pydantic schemas."""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List
from .configs import (
    OptimizerConfig,
    SchedulerConfig,
    AugmentationConfig,
    PreprocessConfig,
    ValidationConfig,
    TrainingConfigAdvanced,
)
from .dataset import SplitStrategy


class TrainingConfig(BaseModel):
    """Training configuration schema."""

    framework: str = Field("timm", description="Framework (timm, ultralytics, transformers)")
    model_name: str = Field(..., description="Model name (e.g., resnet50, yolov8n)")
    task_type: str = Field(..., description="Task type (e.g., image_classification, object_detection)")
    num_classes: Optional[int] = Field(None, ge=2, description="Number of classes (required for classification)")

    # Dataset specification (provide either dataset_id OR dataset_path)
    dataset_id: Optional[str] = Field(None, description="Dataset ID from database (preferred)")
    dataset_path: Optional[str] = Field(None, description="Direct path to dataset (legacy)")
    dataset_format: str = Field("imagefolder", description="Dataset format (imagefolder, coco, yolo, etc.)")

    # Dataset split configuration (optional - overrides dataset-level split)
    split_strategy: Optional[SplitStrategy] = Field(
        None,
        description="Train/val split strategy. If not provided, uses dataset's split_config or runtime auto-split (80/20)."
    )

    # Basic training parameters (backward compatible)
    epochs: int = Field(50, ge=1, le=1000, description="Number of epochs")
    batch_size: int = Field(32, ge=1, le=512, description="Batch size")
    learning_rate: float = Field(0.001, gt=0, lt=1, description="Learning rate")

    # Advanced configurations (optional)
    advanced_config: Optional[TrainingConfigAdvanced] = Field(
        None,
        description="Advanced training configuration (optimizer, scheduler, augmentation, etc.)"
    )

    # Primary metric configuration
    primary_metric: Optional[str] = Field(
        None,
        description="Primary metric to optimize (e.g., 'accuracy', 'mAP50', 'f1_score'). If None, uses framework default."
    )
    primary_metric_mode: Optional[str] = Field(
        "max",
        description="Optimization mode: 'max' to maximize metric, 'min' to minimize"
    )

    # Open-vocabulary / Zero-shot configuration (for YOLO-World, etc.)
    custom_prompts: Optional[List[str]] = Field(
        None,
        description="Custom text prompts for open-vocabulary/zero-shot detection (e.g., YOLO-World). Example: ['red apple', 'damaged box']"
    )
    prompt_mode: Optional[str] = Field(
        "offline",
        description="Prompt mode for open-vocabulary models: 'offline' (pre-computed embeddings) or 'dynamic' (runtime encoding)"
    )

    class Config:
        protected_namespaces = ()  # Allow model_name field


class TrainingJobCreate(BaseModel):
    """Schema for creating a training job."""

    session_id: Optional[int] = Field(None, description="Chat session ID (optional)")
    config: TrainingConfig
    project_id: Optional[int] = Field(None, description="Project ID to associate with")
    experiment_name: Optional[str] = Field(None, max_length=200, description="Experiment name")
    tags: Optional[list[str]] = Field(None, description="Tags for categorization")
    notes: Optional[str] = Field(None, description="User notes about this experiment")


class TrainingJobResponse(BaseModel):
    """Schema for training job response."""

    id: int
    session_id: Optional[int] = Field(None, description="Chat session ID (optional)")
    project_id: Optional[int] = None
    project_name: Optional[str] = None  # Project name for breadcrumb navigation

    # Experiment metadata
    experiment_name: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    mlflow_run_id: Optional[str] = None

    # Orchestration metadata (Phase 12)
    workflow_id: Optional[str] = Field(None, description="Temporal Workflow ID")
    dataset_snapshot_id: Optional[str] = Field(None, description="Dataset Snapshot ID (Phase 12.2)")

    framework: str
    model_name: str
    task_type: str
    num_classes: Optional[int] = None
    dataset_path: str
    dataset_format: str
    output_dir: str

    # Basic training parameters
    epochs: int
    batch_size: int
    learning_rate: float

    # Advanced configurations (optional)
    advanced_config: Optional[TrainingConfigAdvanced] = None

    status: str
    error_message: Optional[str] = None
    process_id: Optional[int] = None

    final_accuracy: Optional[float] = None
    best_checkpoint_path: Optional[str] = None
    last_checkpoint_path: Optional[str] = None

    # Primary metric configuration
    primary_metric: Optional[str] = None
    primary_metric_mode: Optional[str] = None

    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        protected_namespaces = ()  # Allow model_name field


class TrainingMetricResponse(BaseModel):
    """Schema for training metric response."""

    id: int
    job_id: int
    epoch: int
    step: Optional[int] = None
    loss: Optional[float] = None
    accuracy: Optional[float] = None
    learning_rate: Optional[float] = None
    extra_metrics: Optional[dict] = None
    checkpoint_path: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TrainingStatusResponse(BaseModel):
    """Schema for training status response."""

    job: TrainingJobResponse
    latest_metrics: list[TrainingMetricResponse]


class TrainingLogResponse(BaseModel):
    """Schema for training log response."""

    id: int
    job_id: int
    log_type: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Training Callback Schemas (Training Service → Backend)
# ============================================================================

class TrainingCallbackMetrics(BaseModel):
    """Metrics sent from Training Service to Backend."""

    loss: Optional[float] = None
    accuracy: Optional[float] = None
    learning_rate: Optional[float] = None

    # Extra metrics (framework-specific)
    extra_metrics: Optional[dict] = Field(
        default_factory=dict,
        description="Additional metrics (e.g., precision, recall, mAP, etc.)"
    )


class TrainingProgressCallback(BaseModel):
    """
    Progress update from Training Service to Backend.

    Sent periodically during training (every N epochs based on CALLBACK_INTERVAL).
    K8s Job compatible: Works for both long-running service and one-time job.
    """

    job_id: int = Field(..., description="Training job ID")
    status: str = Field(..., description="Job status: running, completed, failed")

    # Progress info
    current_epoch: int = Field(..., ge=0, description="Current epoch number")
    total_epochs: int = Field(..., gt=0, description="Total number of epochs")
    progress_percent: Optional[float] = Field(None, ge=0, le=100, description="Overall progress percentage")

    # Metrics
    metrics: Optional[TrainingCallbackMetrics] = Field(None, description="Current epoch metrics")

    # Checkpoints
    checkpoint_path: Optional[str] = Field(None, description="Path to saved checkpoint (if available)")
    best_checkpoint_path: Optional[str] = Field(None, description="Path to best checkpoint so far")

    # Timing
    epoch_duration_seconds: Optional[float] = Field(None, description="Duration of last epoch in seconds")
    estimated_time_remaining: Optional[float] = Field(None, description="Estimated time remaining in seconds")

    # Logs (optional)
    logs: Optional[str] = Field(None, description="Recent training logs")

    # Error info (for failed status)
    error_message: Optional[str] = Field(None, description="Error message if status=failed")
    traceback: Optional[str] = Field(None, description="Full traceback if status=failed")


class TrainingCompletionCallback(BaseModel):
    """
    Final completion callback from Training Service to Backend.

    Sent once when training finishes (success or failure).
    K8s Job compatible: Exit code determines success/failure.
    """

    job_id: int = Field(..., description="Training job ID")
    status: str = Field(..., description="Final status: completed or failed")

    # Final results
    total_epochs_completed: int = Field(..., ge=0, description="Total epochs completed")
    final_metrics: Optional[TrainingCallbackMetrics] = Field(None, description="Final validation metrics")
    best_metrics: Optional[TrainingCallbackMetrics] = Field(None, description="Best metrics achieved")
    best_epoch: Optional[int] = Field(None, description="Epoch with best metrics")

    # Artifacts
    final_checkpoint_path: Optional[str] = Field(None, description="Path to final checkpoint")
    best_checkpoint_path: Optional[str] = Field(None, description="Path to best checkpoint")
    last_checkpoint_path: Optional[str] = Field(None, description="Path to last checkpoint")
    model_artifacts_path: Optional[str] = Field(None, description="Path to exported model artifacts")

    # MLflow integration
    mlflow_run_id: Optional[str] = Field(None, description="MLflow run ID for experiment tracking")

    # Timing
    total_duration_seconds: Optional[float] = Field(None, description="Total training duration")

    # Error info (if failed)
    error_message: Optional[str] = Field(None, description="Error message if failed")
    traceback: Optional[str] = Field(None, description="Full traceback if failed")
    exit_code: Optional[int] = Field(None, description="Exit code (for K8s Job: 0=success, non-zero=failure)")


class TrainingCallbackResponse(BaseModel):
    """Response from Backend to Training Service after callback."""

    success: bool = Field(..., description="Whether callback was processed successfully")
    message: str = Field(..., description="Response message")
    job_status: Optional[str] = Field(None, description="Current job status in Backend DB")


class LogEventCallback(BaseModel):
    """
    Log event from Training Service to Backend.

    Backend forwards to Loki for centralized logging.
    """

    job_id: int = Field(..., description="Training job ID")
    event_type: str = Field(..., description="Event category (training, validation, checkpoint, error)")
    message: str = Field(..., description="Human-readable message")
    level: str = Field("INFO", description="Log level (DEBUG, INFO, WARNING, ERROR)")
    data: Optional[dict] = Field(None, description="Additional structured data")
    timestamp: Optional[str] = Field(None, description="Event timestamp (ISO format)")


class CheckpointUploadUrlRequest(BaseModel):
    """
    Request from Training Service to get presigned URL for checkpoint upload.
    """

    checkpoint_filename: str = Field(..., description="Checkpoint filename (e.g., 'epoch_10.pt')")
    content_type: Optional[str] = Field("application/octet-stream", description="MIME type")


class CheckpointUploadUrlResponse(BaseModel):
    """
    Response with presigned URL for checkpoint upload.
    """

    upload_url: str = Field(..., description="Presigned S3 upload URL")
    object_key: str = Field(..., description="S3 object key")
    expires_in: int = Field(..., description="URL expiration time in seconds")
