"""Training API endpoints."""

import os
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import httpx

from app.db.database import get_db
from app.db import models
from app.schemas import training
from app.core.config import settings
from app.services.websocket_manager import get_websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter()


async def auto_create_snapshot_if_needed(dataset_id: str, job_id: int, db: Session) -> str:
    """
    Automatically create a snapshot of the dataset before training starts.

    This ensures reproducibility by freezing the dataset state at the time of training.
    If the dataset hasn't changed since the last snapshot, the existing snapshot is reused.

    Args:
        dataset_id: Dataset ID to snapshot
        job_id: Training job ID (used in version tag)
        db: Database session

    Returns:
        Snapshot dataset ID (either newly created or existing)
    """
    from app.db.models import Dataset
    from app.utils.dual_storage import dual_storage
    import json

    # Get parent dataset
    parent_dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not parent_dataset:
        logger.warning(f"[SNAPSHOT] Dataset {dataset_id} not found, skipping snapshot")
        return None

    # Cannot snapshot a snapshot
    if parent_dataset.is_snapshot:
        logger.info(f"[SNAPSHOT] Dataset {dataset_id} is already a snapshot, skipping")
        return dataset_id

    # Check if we have existing snapshots
    existing_snapshots = db.query(Dataset).filter(
        Dataset.parent_dataset_id == dataset_id,
        Dataset.is_snapshot == True,
        Dataset.status == 'active'
    ).order_by(Dataset.snapshot_created_at.desc()).all()

    # Check if latest snapshot has same content_hash (dataset unchanged)
    if existing_snapshots and existing_snapshots[0].content_hash == parent_dataset.content_hash:
        logger.info(f"[SNAPSHOT] Dataset {dataset_id} unchanged, reusing snapshot {existing_snapshots[0].id}")
        return existing_snapshots[0].id

    # Need to create new snapshot
    logger.info(f"[SNAPSHOT] Creating new snapshot for dataset {dataset_id} (job {job_id})")

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    snapshot_id = f"{dataset_id}-snapshot-job{job_id}-{timestamp}"
    version_tag = f"training-job-{job_id}"

    snapshot_name = f"{parent_dataset.name} (Training Snapshot - Job {job_id})"
    snapshot_storage_path = f"datasets/snapshots/{snapshot_id}/"

    # Copy dataset files in storage
    storage_client = dual_storage
    parent_storage_path = parent_dataset.storage_path.rstrip('/')

    try:
        # List and copy all files
        files = storage_client.list_files(parent_storage_path)
        logger.info(f"[SNAPSHOT] Copying {len(files)} files from {parent_storage_path} to {snapshot_storage_path}")

        for file_path in files:
            relative_path = file_path.replace(parent_storage_path, '').lstrip('/')
            if not relative_path:
                continue

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

        logger.info(f"[SNAPSHOT] Files copied successfully")

    except Exception as e:
        logger.error(f"[SNAPSHOT] Failed to copy dataset files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create snapshot: {str(e)}")

    # Create snapshot database record
    snapshot_dataset = Dataset(
        id=snapshot_id,
        name=snapshot_name,
        description=f"Automatic snapshot created for training job {job_id}",
        owner_id=parent_dataset.owner_id,
        visibility=parent_dataset.visibility,
        tags=parent_dataset.tags,
        storage_path=snapshot_storage_path,
        storage_type=parent_dataset.storage_type,
        format=parent_dataset.format,
        labeled=parent_dataset.labeled,
        annotation_path=snapshot_storage_path + "annotations.json" if parent_dataset.annotation_path else None,
        num_classes=parent_dataset.num_classes,
        num_images=parent_dataset.num_images,
        class_names=parent_dataset.class_names,
        split_config=parent_dataset.split_config,
        is_snapshot=True,
        parent_dataset_id=dataset_id,
        snapshot_created_at=datetime.utcnow(),
        version_tag=version_tag,
        status='active',
        integrity_status='valid',
        version=1,
        content_hash=parent_dataset.content_hash,
        last_modified_at=parent_dataset.last_modified_at,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.add(snapshot_dataset)
    db.commit()
    db.refresh(snapshot_dataset)

    logger.info(f"[SNAPSHOT] Created snapshot {snapshot_id} for job {job_id}")
    return snapshot_id


@router.post("/jobs", response_model=training.TrainingJobResponse)
async def create_training_job(
    job_request: training.TrainingJobCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new training job.

    This endpoint creates a training job but does not start it immediately.
    Use the /jobs/{job_id}/start endpoint to start training.
    """
    # DEBUG: Log what we received
    logger.info(f"[DEBUG] Received training job request:")
    logger.info(f"[DEBUG]   framework: {job_request.config.framework}")
    logger.info(f"[DEBUG]   model_name: {job_request.config.model_name}")
    logger.info(f"[DEBUG]   task_type: {job_request.config.task_type}")

    # Validate required fields
    config = job_request.config

    # Must provide either dataset_id or dataset_path
    if not config.dataset_id and not config.dataset_path:
        raise HTTPException(
            status_code=400,
            detail="Either dataset_id or dataset_path must be provided"
        )

    # Resolve dataset from database if dataset_id provided
    dataset = None
    dataset_id = None
    dataset_path = None
    dataset_format = config.dataset_format

    if config.dataset_id:
        # Look up dataset in database
        dataset = db.query(models.Dataset).filter(models.Dataset.id == config.dataset_id).first()
        if not dataset:
            raise HTTPException(
                status_code=404,
                detail=f"Dataset with id '{config.dataset_id}' not found"
            )

        # Check access permissions (for now, only public datasets allowed)
        if dataset.visibility != 'public':
            raise HTTPException(
                status_code=403,
                detail=f"Dataset '{config.dataset_id}' is not publicly accessible"
            )

        # Use dataset information from DB
        dataset_id = dataset.id
        dataset_path = config.dataset_id  # Use ID as path for Training Service
        dataset_format = dataset.format
        logger.info(f"[DATASET] Using dataset from DB: {dataset_id} (format: {dataset_format})")

        # Get split configuration from dataset (if exists)
        dataset_split_config = dataset.split_config if dataset.split_config else None
        if dataset_split_config:
            logger.info(f"[DATASET] Found split configuration: {dataset_split_config.get('method')}")
        else:
            logger.info(f"[DATASET] No split configuration found, will use defaults")

    elif config.dataset_path:
        # Legacy: direct path provided
        dataset_path = config.dataset_path
        dataset_split_config = None  # No split config for legacy path
        logger.info(f"[DATASET] Using direct path (legacy): {dataset_path}")

    if not config.model_name:
        raise HTTPException(
            status_code=400,
            detail="model_name is required"
        )

    if not config.task_type:
        raise HTTPException(
            status_code=400,
            detail="task_type is required"
        )

    # For classification tasks, use num_classes from Dataset if available (optional optimization)
    if config.task_type == "image_classification" and not config.num_classes:
        if dataset is not None and dataset.num_classes and dataset.num_classes > 0:
            # Use pre-computed num_classes from Dataset (faster)
            config.num_classes = dataset.num_classes
            logger.info(f"[training] Using num_classes from Dataset: {config.num_classes}")
        else:
            # num_classes will be auto-detected by Training Service during dataset loading
            logger.info(f"[training] num_classes not provided - will be auto-detected by Training Service")

    # Verify session exists (if provided)
    if job_request.session_id:
        session = db.query(models.Session).filter(models.Session.id == job_request.session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

    # Verify project exists if provided
    if job_request.project_id:
        project = db.query(models.Project).filter(models.Project.id == job_request.project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

    # Create output directory
    job_output_dir = os.path.join(
        settings.OUTPUT_DIR,
        f"job_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
    )
    os.makedirs(job_output_dir, exist_ok=True)

    # Determine primary metric based on framework/task if not provided
    primary_metric = config.primary_metric
    primary_metric_mode = config.primary_metric_mode or "max"

    if not primary_metric:
        # Framework-specific defaults
        if config.task_type == "image_classification":
            primary_metric = "accuracy"
            primary_metric_mode = "max"
        elif config.task_type in ["object_detection", "instance_segmentation"]:
            primary_metric = "mAP50"
            primary_metric_mode = "max"
        elif config.task_type == "pose_estimation":
            primary_metric = "mAP50"
            primary_metric_mode = "max"
        else:
            # Fallback to loss
            primary_metric = "loss"
            primary_metric_mode = "min"

    # Prepare advanced_config with split_config
    advanced_config_dict = job_request.config.advanced_config.model_dump() if job_request.config.advanced_config else {}

    # Add dataset split_config to advanced_config if available
    if dataset_split_config:
        advanced_config_dict['split_config'] = dataset_split_config
        logger.info(f"[CONFIG] Added split_config to advanced_config")

    # Create training job
    job = models.TrainingJob(
        session_id=job_request.session_id,
        project_id=job_request.project_id,
        experiment_name=job_request.experiment_name,
        tags=job_request.tags,  # Will be stored as JSON
        notes=job_request.notes,
        framework=job_request.config.framework,
        model_name=job_request.config.model_name,
        task_type=job_request.config.task_type,
        num_classes=job_request.config.num_classes,
        dataset_id=dataset_id,  # Store dataset ID if from DB
        dataset_path=dataset_path,  # Use resolved path
        dataset_format=dataset_format,  # Use format from DB or config
        output_dir=job_output_dir,
        epochs=job_request.config.epochs,
        batch_size=job_request.config.batch_size,
        learning_rate=job_request.config.learning_rate,
        advanced_config=advanced_config_dict if advanced_config_dict else None,
        primary_metric=primary_metric,
        primary_metric_mode=primary_metric_mode,
        status="pending",
    )

    db.add(job)
    db.commit()
    db.refresh(job)
    # Add project_name for breadcrumb navigation
    if job.project_id and job.project:
        job.project_name = job.project.name
    else:
        job.project_name = None


    return job


@router.get("/jobs/{job_id}", response_model=training.TrainingJobResponse)
async def get_training_job(job_id: int, db: Session = Depends(get_db)):
    """Get a training job by ID."""
    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    # Auto-link MLflow run_id if not already linked and job is running/completed
    if not job.mlflow_run_id and job.status in ["running", "completed"]:
        try:
            from app.services.mlflow_service import MLflowService
            mlflow_service = MLflowService(db)
            mlflow_run = mlflow_service.get_run_by_job_id(job_id)
            if mlflow_run:
                job.mlflow_run_id = mlflow_run.info.run_id
                db.commit()
                db.refresh(job)
                print(f"[INFO] Linked MLflow run_id {job.mlflow_run_id} to job {job_id}")
        except Exception as e:
            # Don't fail the request if MLflow linking fails
            print(f"[WARNING] Failed to link MLflow run for job {job_id}: {e}")
    # Add project_name for breadcrumb navigation
    if job.project_id and job.project:
        job.project_name = job.project.name
    else:
        job.project_name = None


    return job


@router.get("/jobs/{job_id}/status", response_model=training.TrainingStatusResponse)
async def get_training_status(job_id: int, db: Session = Depends(get_db)):
    """Get training job status with latest metrics."""
    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    # Get latest metrics (last 10)
    latest_metrics = (
        db.query(models.TrainingMetric)
        .filter(models.TrainingMetric.job_id == job_id)
        .order_by(models.TrainingMetric.created_at.desc())
        .limit(10)
        .all()
    )

    return training.TrainingStatusResponse(
        job=job,
        latest_metrics=list(reversed(latest_metrics)),
    )


@router.get("/jobs/{job_id}/metrics", response_model=list[training.TrainingMetricResponse])
async def get_training_metrics(
    job_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Get training metrics for a job."""
    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    metrics = (
        db.query(models.TrainingMetric)
        .filter(models.TrainingMetric.job_id == job_id)
        .order_by(models.TrainingMetric.created_at)
        .limit(limit)
        .all()
    )

    return metrics


@router.get("/jobs/{job_id}/metric-schema")
async def get_metric_schema(job_id: int, db: Session = Depends(get_db)):
    """
    Get available metric columns for a training job.

    Returns a schema describing available metrics, their types,
    and the primary metric configuration.
    """
    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    # Get a sample metric to extract available columns
    sample_metric = (
        db.query(models.TrainingMetric)
        .filter(models.TrainingMetric.job_id == job_id)
        .order_by(models.TrainingMetric.created_at.desc())
        .first()
    )

    available_metrics = []

    if sample_metric and sample_metric.extra_metrics:
        # Extract all metric names from extra_metrics
        for key in sample_metric.extra_metrics.keys():
            # Skip internal/debugging metrics
            if key not in ['batch', 'total_batches', 'epoch_time']:
                available_metrics.append(key)

    # Add standard columns if they have values
    if sample_metric:
        if sample_metric.loss is not None:
            available_metrics.insert(0, 'loss')
        if sample_metric.accuracy is not None:
            available_metrics.insert(1, 'accuracy')
        if sample_metric.learning_rate is not None:
            available_metrics.append('learning_rate')

    return {
        "job_id": job_id,
        "framework": job.framework,
        "task_type": job.task_type,
        "primary_metric": job.primary_metric or "loss",
        "primary_metric_mode": job.primary_metric_mode or "min",
        "available_metrics": available_metrics,
        "metric_count": len(available_metrics)
    }


@router.post("/jobs/{job_id}/start", response_model=training.TrainingJobResponse)
async def start_training_job(
    job_id: int,
    checkpoint_path: str = None,
    resume: bool = False,
    db: Session = Depends(get_db)
):
    """
    Start a training job.

    This endpoint starts the actual training process by calling the Training Service HTTP API.

    Args:
        job_id: Training job ID
        checkpoint_path: Optional path to checkpoint file to load
        resume: If True, resume training from checkpoint (restore optimizer/scheduler state).
                If False, only load model weights.
    """
    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    if job.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start job with status '{job.status}'",
        )

    # Auto-create snapshot before training starts (if dataset_id provided)
    if job.dataset_id:
        try:
            snapshot_id = await auto_create_snapshot_if_needed(job.dataset_id, job_id, db)
            if snapshot_id:
                job.dataset_snapshot_id = snapshot_id
                db.commit()
                logger.info(f"[JOB {job_id}] Using dataset snapshot: {snapshot_id}")
            else:
                logger.info(f"[JOB {job_id}] No snapshot created (dataset not found or already snapshot)")
        except Exception as e:
            logger.error(f"[JOB {job_id}] Failed to create snapshot: {e}")
            # Don't fail the training if snapshot creation fails
            logger.warning(f"[JOB {job_id}] Continuing training without snapshot")

    # Phase 12: Start training via Temporal Workflow
    try:
        from app.core.temporal_client import get_temporal_client
        from app.workflows.training_workflow import TrainingWorkflow, TrainingWorkflowInput

        # Get Temporal client
        client = await get_temporal_client()
        logger.info(f"[JOB {job_id}] Temporal client ready")

        # Generate workflow ID
        workflow_id = f"training-job-{job_id}"

        # Start TrainingWorkflow
        workflow_handle = await client.start_workflow(
            TrainingWorkflow.run,
            TrainingWorkflowInput(job_id=job_id),
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )

        logger.info(f"[JOB {job_id}] TrainingWorkflow started: {workflow_id}")

        # Update job status
        job.status = "running"
        job.started_at = datetime.utcnow()
        job.workflow_id = workflow_id
        db.commit()
        db.refresh(job)

        logger.info(
            f"[JOB {job_id}] Training orchestration started "
            f"(workflow_id: {workflow_id}, mode: {settings.TRAINING_MODE})"
        )

    except Exception as e:
        logger.error(f"[JOB {job_id}] Failed to start training workflow: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start training workflow: {str(e)}"
        )

    return job


@router.post("/jobs/{job_id}/cancel", response_model=training.TrainingJobResponse)
async def cancel_training_job(job_id: int, db: Session = Depends(get_db)):
    """
    Cancel a running training job.
    """
    from app.core.training_managers.subprocess_manager import get_training_subprocess_manager

    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    if job.status not in ["pending", "running"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status '{job.status}'",
        )

    # Stop training subprocess
    manager = get_training_subprocess_manager()
    if manager.stop_training(job_id):
        job.status = "cancelled"
        job.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        return job
    else:
        # Fallback if process not found
        job.status = "cancelled"
        job.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        return job


@router.post("/jobs/{job_id}/restart", response_model=training.TrainingJobResponse)
async def restart_training_job(job_id: int, db: Session = Depends(get_db)):
    """
    Restart a completed or cancelled training job.

    Resets the job status to 'pending' and clears previous training data.
    The job configuration remains the same.
    """
    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    if job.status not in ["completed", "cancelled", "failed"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot restart job with status '{job.status}'. Only completed, cancelled, or failed jobs can be restarted.",
        )

    # Reset job status
    job.status = "pending"
    job.started_at = None
    job.completed_at = None
    job.error_message = None
    job.final_accuracy = None
    job.process_id = None
    job.mlflow_run_id = None

    # Clear previous metrics
    db.query(models.TrainingMetric).filter(models.TrainingMetric.job_id == job_id).delete()

    # Clear previous logs
    db.query(models.TrainingLog).filter(models.TrainingLog.job_id == job_id).delete()

    db.commit()
    db.refresh(job)

    # Add project_name for breadcrumb navigation
    if job.project_id and job.project:
        job.project_name = job.project.name
    else:
        job.project_name = None

    return job


@router.get("/jobs/{job_id}/logs", response_model=list[training.TrainingLogResponse])
async def get_training_logs(
    job_id: int,
    limit: int = 500,
    log_type: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Get training logs for a job.

    Returns the most recent logs up to the limit, ordered chronologically.

    Args:
        job_id: Training job ID
        limit: Maximum number of log entries to return (default: 500)
        log_type: Filter by log type ('stdout' or 'stderr'), optional
    """
    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    # Build query
    query = db.query(models.TrainingLog).filter(models.TrainingLog.job_id == job_id)

    # Apply log type filter if specified
    if log_type in ["stdout", "stderr"]:
        query = query.filter(models.TrainingLog.log_type == log_type)

    # Get most recent logs (newest first), then reverse to show chronologically
    logs = query.order_by(models.TrainingLog.created_at.desc()).limit(limit).all()

    # Reverse to show oldest first (chronological order)
    return list(reversed(logs))


@router.get("/jobs/{job_id}/logs/loki")
async def get_training_logs_from_loki(
    job_id: int,
    limit: int = 1000,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Get training logs from Loki log aggregation system.

    This endpoint queries Loki directly for training logs, providing
    real-time log access without relying on database storage.

    Args:
        job_id: Training job ID
        limit: Maximum number of log lines to return (default: 1000)
        start: Start time (ISO 8601 or relative like "1h", "30m")
        end: End time (ISO 8601 or relative)

    Returns:
        JSON with log entries from Loki
    """
    import requests
    from datetime import datetime, timedelta

    # Verify job exists
    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    # Loki URL from environment
    loki_url = os.getenv("LOKI_URL", "http://localhost:3100")

    # Build LogQL query
    logql_query = f'{{job="training", job_id="{job_id}"}}'

    # Default time range: last 24 hours
    if not start:
        start_time = datetime.utcnow() - timedelta(hours=24)
        start = start_time.isoformat() + "Z"
    if not end:
        end_time = datetime.utcnow()
        end = end_time.isoformat() + "Z"

    # Query Loki
    try:
        response = requests.get(
            f"{loki_url}/loki/api/v1/query_range",
            params={
                "query": logql_query,
                "limit": limit,
                "start": start,
                "end": end,
                "direction": "forward",  # Chronological order
            },
            timeout=10,
        )
        response.raise_for_status()

        loki_data = response.json()

        # Extract log lines from Loki response
        logs = []
        if loki_data.get("status") == "success":
            for stream in loki_data.get("data", {}).get("result", []):
                for entry in stream.get("values", []):
                    timestamp_ns, log_line = entry
                    # Convert nanosecond timestamp to datetime
                    timestamp = datetime.fromtimestamp(int(timestamp_ns) / 1e9)
                    logs.append({
                        "timestamp": timestamp.isoformat(),
                        "log": log_line,
                        "labels": stream.get("stream", {}),
                    })

        return {
            "job_id": job_id,
            "total": len(logs),
            "logs": logs,
            "source": "loki",
            "query": logql_query,
        }

    except requests.exceptions.ConnectionError:
        raise HTTPException(
            status_code=503,
            detail="Loki service unavailable. Ensure Loki is running."
        )
    except requests.exceptions.Timeout:
        raise HTTPException(
            status_code=504,
            detail="Loki query timeout"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error querying Loki: {str(e)}"
        )


@router.get("/jobs/{job_id}/mlflow/metrics")
async def get_mlflow_metrics(job_id: int, db: Session = Depends(get_db)):
    """
    Get MLflow metrics for a training job.

    Returns all metrics with their history from MLflow tracking server,
    plus primary metric information.
    """
    # Verify job exists
    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    try:
        from app.services.mlflow_service import MLflowService
        mlflow_service = MLflowService(db)
        metrics_data = mlflow_service.get_job_run_metrics(job_id)

        # Add primary metric information
        metrics_data['primary_metric'] = job.primary_metric or 'loss'
        metrics_data['primary_metric_mode'] = job.primary_metric_mode or 'min'
        metrics_data['task_type'] = job.task_type
        metrics_data['framework'] = job.framework

        return metrics_data
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch MLflow metrics: {str(e)}"
        )


@router.get("/jobs/{job_id}/mlflow/summary")
async def get_mlflow_summary(job_id: int, db: Session = Depends(get_db)):
    """
    Get MLflow run summary for a training job.

    Returns summary information including best metrics, parameters, and run status.
    """
    # Verify job exists
    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    try:
        from app.services.mlflow_service import MLflowService
        mlflow_service = MLflowService(db)
        summary = mlflow_service.get_job_run_summary(job_id)
        return summary
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch MLflow summary: {str(e)}"
        )


# ==================== Advanced Configuration Endpoints ====================


@router.get("/config/schema")
async def get_config_schema():
    """
    Get the JSON schema for advanced training configuration.

    Returns the complete schema including:
    - Optimizer options and parameters
    - Scheduler options and parameters
    - Augmentation options and parameters
    - Preprocessing options and parameters
    - Validation options and parameters

    This schema can be used by the frontend to dynamically generate configuration forms.
    """
    from app.schemas.configs import (
        OptimizerConfig,
        SchedulerConfig,
        AugmentationConfig,
        PreprocessConfig,
        ValidationConfig,
        TrainingConfigAdvanced,
    )

    return {
        "optimizer": OptimizerConfig.model_json_schema(),
        "scheduler": SchedulerConfig.model_json_schema(),
        "augmentation": AugmentationConfig.model_json_schema(),
        "preprocessing": PreprocessConfig.model_json_schema(),
        "validation": ValidationConfig.model_json_schema(),
        "complete": TrainingConfigAdvanced.model_json_schema(),
    }


@router.get("/config/defaults")
async def get_config_defaults():
    """
    Get default values for advanced training configuration.

    Returns sensible default values for all configuration options.
    """
    from app.schemas.configs import (
        OptimizerConfig,
        SchedulerConfig,
        AugmentationConfig,
        PreprocessConfig,
        ValidationConfig,
        TrainingConfigAdvanced,
    )

    return {
        "optimizer": OptimizerConfig().model_dump(),
        "scheduler": SchedulerConfig().model_dump(),
        "augmentation": AugmentationConfig().model_dump(),
        "preprocessing": PreprocessConfig().model_dump(),
        "validation": ValidationConfig().model_dump(),
        "complete": TrainingConfigAdvanced().model_dump(),
    }


@router.get("/config/presets")
async def get_config_presets():
    """
    Get pre-defined configuration presets.

    Returns preset configurations for common use cases:
    - basic: Simple training with minimal augmentation
    - standard: Balanced configuration for general use
    - aggressive: Heavy augmentation for small datasets
    - fine_tuning: Optimized for fine-tuning pre-trained models
    """
    from app.schemas.configs import (
        OptimizerConfig,
        SchedulerConfig,
        AugmentationConfig,
        PreprocessConfig,
        ValidationConfig,
        TrainingConfigAdvanced,
    )

    presets = {
        "basic": TrainingConfigAdvanced(
            optimizer=OptimizerConfig(
                type="adam",
                learning_rate=1e-3,
                weight_decay=0.0
            ),
            scheduler=SchedulerConfig(type="none"),
            augmentation=AugmentationConfig(
                enabled=True,
                random_flip=True,
                random_flip_prob=0.5
            ),
            preprocessing=PreprocessConfig(
                image_size=224,
                resize_mode="resize"
            ),
            validation=ValidationConfig(
                enabled=True,
                val_interval=1,
                save_best=True,
                metrics=["accuracy"]
            )
        ),

        "standard": TrainingConfigAdvanced(
            optimizer=OptimizerConfig(
                type="adamw",
                learning_rate=3e-4,
                weight_decay=0.01,
                betas=(0.9, 0.999)
            ),
            scheduler=SchedulerConfig(
                type="cosine",
                T_max=100,
                eta_min=1e-6,
                warmup_epochs=5,
                warmup_lr=1e-6
            ),
            augmentation=AugmentationConfig(
                enabled=True,
                random_flip=True,
                random_flip_prob=0.5,
                color_jitter=True,
                brightness=0.2,
                contrast=0.2,
                saturation=0.2,
                hue=0.1
            ),
            preprocessing=PreprocessConfig(
                image_size=224,
                resize_mode="resize_crop"
            ),
            validation=ValidationConfig(
                enabled=True,
                val_interval=1,
                save_best=True,
                metrics=["accuracy", "precision", "recall", "f1"],
                early_stopping=True,
                early_stopping_patience=10
            ),
            mixed_precision=True
        ),

        "aggressive": TrainingConfigAdvanced(
            optimizer=OptimizerConfig(
                type="adamw",
                learning_rate=1e-3,
                weight_decay=0.05
            ),
            scheduler=SchedulerConfig(
                type="cosine_warm_restarts",
                T_0=10,
                T_mult=2,
                warmup_epochs=3
            ),
            augmentation=AugmentationConfig(
                enabled=True,
                random_flip=True,
                random_rotation=True,
                rotation_degrees=15,
                random_crop=True,
                crop_scale=(0.7, 1.0),
                color_jitter=True,
                brightness=0.3,
                contrast=0.3,
                saturation=0.3,
                hue=0.15,
                random_erasing=True,
                erasing_prob=0.5,
                mixup=True,
                mixup_alpha=0.2,
                cutmix=True,
                cutmix_alpha=1.0
            ),
            preprocessing=PreprocessConfig(
                image_size=224,
                resize_mode="resize_crop"
            ),
            validation=ValidationConfig(
                enabled=True,
                val_interval=1,
                save_best=True,
                metrics=["accuracy", "precision", "recall", "f1"],
                early_stopping=True,
                early_stopping_patience=15
            ),
            mixed_precision=True,
            gradient_clip_value=1.0
        ),

        "fine_tuning": TrainingConfigAdvanced(
            optimizer=OptimizerConfig(
                type="sgd",
                learning_rate=1e-4,
                momentum=0.9,
                weight_decay=1e-4,
                nesterov=True
            ),
            scheduler=SchedulerConfig(
                type="step",
                step_size=10,
                gamma=0.1
            ),
            augmentation=AugmentationConfig(
                enabled=True,
                random_flip=True,
                random_flip_prob=0.5,
                color_jitter=True,
                brightness=0.1,
                contrast=0.1,
                saturation=0.1
            ),
            preprocessing=PreprocessConfig(
                image_size=224,
                resize_mode="resize"
            ),
            validation=ValidationConfig(
                enabled=True,
                val_interval=1,
                save_best=True,
                save_best_metric="accuracy",
                metrics=["accuracy"],
                early_stopping=True,
                early_stopping_patience=5,
                early_stopping_min_delta=0.001
            )
        )
    }

    return {
        name: preset.model_dump()
        for name, preset in presets.items()
    }


@router.post("/config/validate")
async def validate_config(config: training.TrainingConfigAdvanced):
    """
    Validate an advanced training configuration.

    Validates the provided configuration against the schema and returns
    validation results and any warnings.

    Args:
        config: Advanced training configuration to validate

    Returns:
        Dictionary with validation status and any warnings/suggestions
    """
    from pydantic import ValidationError

    warnings = []
    suggestions = []

    # Check for common issues
    if config.optimizer.learning_rate > 0.1:
        warnings.append("Learning rate is very high (>0.1). Consider using a lower value.")

    if config.optimizer.learning_rate < 1e-6:
        warnings.append("Learning rate is very low (<1e-6). Training may be very slow.")

    if config.scheduler.type != "none" and config.scheduler.warmup_epochs > 0:
        if config.scheduler.warmup_lr >= config.optimizer.learning_rate:
            warnings.append("Warmup LR is higher than or equal to initial LR. Warmup may not work as expected.")

    if config.augmentation.enabled:
        aug_count = sum([
            config.augmentation.random_flip,
            config.augmentation.random_rotation,
            config.augmentation.random_crop,
            config.augmentation.color_jitter,
            config.augmentation.random_erasing,
            config.augmentation.mixup,
            config.augmentation.cutmix,
            config.augmentation.autoaugment
        ])

        if aug_count == 0:
            warnings.append("Augmentation is enabled but no augmentation techniques are selected.")
        elif aug_count > 6:
            suggestions.append("Many augmentation techniques are enabled. This may slow down training significantly.")

    if config.validation.early_stopping and config.validation.early_stopping_patience < 3:
        suggestions.append("Early stopping patience is very low (<3). Training may stop prematurely.")

    if config.mixed_precision and config.gradient_clip_value and config.gradient_clip_value > 10:
        suggestions.append("Gradient clipping value is high (>10) with mixed precision. Consider using a lower value.")

    return {
        "valid": True,
        "warnings": warnings,
        "suggestions": suggestions,
        "config": config.model_dump()
    }


@router.get("/config-schema")
async def get_config_schema(framework: str, task_type: str = None):
    """
    Get configuration schema for a specific framework and task type.

    This endpoint returns the configuration schema that can be used to dynamically
    generate UI forms for advanced training configuration.

    Schemas are uploaded to S3/R2 by GitHub Actions workflow (.github/workflows/upload-config-schemas.yml)
    and dynamically loaded by the Frontend without requiring Backend redeployment.

    Args:
        framework: Framework name ('ultralytics', 'timm', etc.)
        task_type: Optional task type for framework-specific schemas (currently unused)

    Returns:
        Configuration schema with fields, types, defaults, and presets

    Example Response:
        {
            "framework": "ultralytics",
            "description": "Ultralytics YOLO Training Configuration",
            "version": "1.0",
            "fields": [
                {
                    "name": "optimizer_type",
                    "type": "select",
                    "default": "Adam",
                    "options": ["Adam", "AdamW", "SGD"],
                    "description": "Optimizer algorithm",
                    "group": "optimizer",
                    "required": false,
                    "advanced": false
                },
                ...
            ],
            "presets": {
                "easy": { "mosaic": 1.0, "fliplr": 0.5, "amp": true },
                "medium": { "mosaic": 1.0, "mixup": 0.1, ... },
                "advanced": { "mosaic": 1.0, "mixup": 0.15, "copy_paste": 0.1, ... }
            }
        }
    """
    logger.info(f"[config-schema] Requested framework={framework}, task_type={task_type}")

    # Load schema from Internal Storage (Results MinIO)
    # Uploaded by GitHub Actions workflow (.github/workflows/upload-config-schemas.yml)
    # This maintains complete dependency isolation between Backend and Training Services
    from app.utils.dual_storage import dual_storage
    import json

    try:
        logger.info(f"[config-schema] Loading schema from Internal Storage: {framework}.json")

        # Get schema from Internal Storage (config-schemas bucket)
        schema_bytes = dual_storage.get_schema(framework)

        if not schema_bytes:
            logger.warning(f"[config-schema] Schema not found: {framework}")
            raise HTTPException(
                status_code=404,
                detail=f"Configuration schema for framework '{framework}' not found. "
                       f"Available frameworks: ultralytics, timm, huggingface. "
                       f"Schemas are uploaded via GitHub Actions from platform/trainers/*/config_schema.py"
            )

        # Parse JSON
        schema_dict = json.loads(schema_bytes.decode('utf-8'))

        logger.info(f"[config-schema] Schema loaded: {len(schema_dict.get('fields', []))} fields, "
                   f"{len(schema_dict.get('presets', {}))} presets")

        return schema_dict

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error(f"[config-schema] Invalid JSON in schema file: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Schema file is corrupted. Please re-upload via GitHub Actions."
        )
    except Exception as e:
        logger.error(f"[config-schema] Error loading schema: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load configuration schema: {str(e)}"
        )


@router.get("/datasets/list")
async def list_available_datasets():
    """
    List available datasets in the default datasets directory.

    Scans the mvp/data/datasets folder and returns a list of available
    datasets with their paths and detected formats.

    Returns:
        List of dataset info objects with:
        - name: Dataset folder name
        - path: Absolute path
        - format: Detected format (imagefolder, yolo, coco, or unknown)
        - size: Number of files (approximate)
    """
    try:
        import os
        from pathlib import Path

        # Get datasets directory (mvp/data/datasets)
        backend_dir = Path(__file__).parent.parent.parent
        mvp_dir = backend_dir.parent
        datasets_dir = mvp_dir / 'data' / 'datasets'

        logger.info(f"[list-datasets] Scanning directory: {datasets_dir}")

        datasets = []

        # Create datasets directory if it doesn't exist
        if not datasets_dir.exists():
            datasets_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"[list-datasets] Created datasets directory: {datasets_dir}")
            return {"datasets": []}

        # Scan for dataset folders
        for item in datasets_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                dataset_info = {
                    "name": item.name,
                    "path": str(item.absolute()),
                    "format": "unknown",
                    "size": 0
                }

                # Detect format by folder structure
                if (item / 'train').exists() and (item / 'val').exists():
                    # Could be ImageFolder or YOLO
                    if (item / 'labels').exists():
                        dataset_info["format"] = "yolo"
                    else:
                        # Check if train has class subfolders (ImageFolder)
                        train_dir = item / 'train'
                        subdirs = [d for d in train_dir.iterdir() if d.is_dir()]
                        if subdirs:
                            dataset_info["format"] = "imagefolder"
                        else:
                            dataset_info["format"] = "yolo"

                elif (item / 'annotations').exists():
                    # Likely COCO format
                    dataset_info["format"] = "coco"

                # Count total files (approximate)
                try:
                    file_count = sum(1 for _ in item.rglob('*') if _.is_file())
                    dataset_info["size"] = file_count
                except Exception as e:
                    logger.warning(f"Failed to count files in {item}: {e}")

                datasets.append(dataset_info)

        logger.info(f"[list-datasets] Found {len(datasets)} datasets")

        return {
            "datasets": datasets,
            "datasets_dir": str(datasets_dir.absolute())
        }

    except Exception as e:
        import traceback
        logger.error(f"[list-datasets] Error: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list datasets: {str(e)}"
        )


@router.get("/jobs/{job_id}/checkpoints")
async def get_job_checkpoints(
    job_id: int,
    db: Session = Depends(get_db),
):
    """
    Get available checkpoints for a training job.

    Returns a list of checkpoints with epoch numbers and file paths.
    """
    try:
        # Get training job
        job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Training job not found")

        checkpoints = []

        # Check if output directory exists
        if not job.output_dir:
            return {"checkpoints": []}

        from pathlib import Path
        output_path = Path(job.output_dir)

        if not output_path.exists():
            return {"checkpoints": []}

        # Scan for checkpoint files
        # Common patterns: best.pt, last.pt, epoch_*.pt, checkpoint_*.pth
        checkpoint_files = []

        # Look for .pt files (PyTorch/YOLO) - direct children
        checkpoint_files.extend(list(output_path.glob("*.pt")))
        # Look for .pth files (PyTorch) - direct children
        checkpoint_files.extend(list(output_path.glob("*.pth")))

        # Look in weights subdirectory (YOLO format)
        weights_dir = output_path / "weights"
        if weights_dir.exists():
            checkpoint_files.extend(list(weights_dir.glob("*.pt")))

        # Recursively search for checkpoints in subdirectories (YOLO job_X/weights structure)
        # This handles cases like: output_dir/job_3/weights/best.pt
        for weights_subdir in output_path.glob("*/weights"):
            if weights_subdir.is_dir():
                checkpoint_files.extend(list(weights_subdir.glob("*.pt")))
                checkpoint_files.extend(list(weights_subdir.glob("*.pth")))

        # Parse checkpoint information
        for ckpt_file in checkpoint_files:
            checkpoint_info = {
                "path": str(ckpt_file.absolute()),
                "filename": ckpt_file.name,
                "is_best": False,
                "epoch": None
            }

            # Determine if it's the best checkpoint
            if ckpt_file.name in ["best.pt", "best.pth", "model_best.pth"]:
                checkpoint_info["is_best"] = True
                # Try to get epoch from metrics
                metrics = db.query(models.TrainingMetric).filter(
                    models.TrainingMetric.job_id == job_id
                ).order_by(models.TrainingMetric.accuracy.desc()).first()
                if metrics:
                    checkpoint_info["epoch"] = metrics.epoch

            # Try to extract epoch from filename
            elif "epoch" in ckpt_file.name.lower():
                import re
                match = re.search(r'epoch[_-]?(\d+)', ckpt_file.name, re.IGNORECASE)
                if match:
                    checkpoint_info["epoch"] = int(match.group(1))

            elif ckpt_file.name == "last.pt":
                # Get last epoch from metrics
                metrics = db.query(models.TrainingMetric).filter(
                    models.TrainingMetric.job_id == job_id
                ).order_by(models.TrainingMetric.epoch.desc()).first()
                if metrics:
                    checkpoint_info["epoch"] = metrics.epoch

            checkpoints.append(checkpoint_info)

        # Sort by epoch (None values at end)
        checkpoints.sort(key=lambda x: (x["epoch"] is None, x["epoch"] or 0))

        logger.info(f"[get-checkpoints] Found {len(checkpoints)} checkpoints for job {job_id}")

        return {"checkpoints": checkpoints}

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[get-checkpoints] Error: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get checkpoints: {str(e)}"
        )


@router.post("/stop/{job_id}")
async def stop_training_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    """
    Stop a running training job.

    This endpoint stops the training process and updates the job status.
    """
    try:
        # Get training job
        job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()

        if not job:
            raise HTTPException(
                status_code=404,
                detail=f"Training job {job_id} not found"
            )

        # Check if job is running
        if job.status not in ["pending", "running"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot stop job with status '{job.status}'. Job must be 'pending' or 'running'."
            )

        logger.info(f"[stop-training] Stopping job {job_id} (status: {job.status})")

        # Stop training subprocess
        from app.core.training_managers.subprocess_manager import get_training_subprocess_manager
        manager = get_training_subprocess_manager()

        # Stop the training job
        success = manager.stop_training(job_id)

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to stop training job"
            )

        # Update job status
        job.status = "stopped"
        job.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(job)

        logger.info(f"[stop-training] Successfully stopped job {job_id}")

        return {
            "job_id": job_id,
            "status": job.status,
            "message": "Training job stopped successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[stop-training] Error: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop training job: {str(e)}"
        )


# ============================================================================
# Training Service Callbacks (K8s Job Compatible)
# ============================================================================


@router.post(
    "/jobs/{job_id}/callback/progress",
    response_model=training.TrainingCallbackResponse
)
async def training_progress_callback(
    job_id: int,
    callback: training.TrainingProgressCallback,
    db: Session = Depends(get_db)
):
    """
    Receive progress updates from Training Service.

    K8s Job Compatible: Works for both long-running service and one-time job.
    Training Service sends periodic updates (every N epochs based on CALLBACK_INTERVAL).

    Args:
        job_id: Training job ID
        callback: Progress update data
        db: Database session

    Returns:
        Acknowledgment response
    """
    from app.services.training_callback_service import TrainingCallbackService

    service = TrainingCallbackService(db)
    return await service.handle_progress(job_id, callback)


@router.post(
    "/jobs/{job_id}/callback/completion",
    response_model=training.TrainingCallbackResponse
)
async def training_completion_callback(
    job_id: int,
    callback: training.TrainingCompletionCallback,
    db: Session = Depends(get_db)
):
    """
    Receive final completion callback from Training Service.

    K8s Job Compatible: Handles exit_code for K8s Job success/failure detection.
    Training Service sends this once when training finishes (success or failure).

    Args:
        job_id: Training job ID
        callback: Completion data with final results
        db: Database session

    Returns:
        Acknowledgment response
    """
    from app.services.training_callback_service import TrainingCallbackService

    service = TrainingCallbackService(db)
    return await service.handle_completion(job_id, callback)


@router.post(
    "/jobs/{job_id}/callback/logs",
    response_model=training.TrainingCallbackResponse
)
async def training_log_callback(
    job_id: int,
    callback: training.LogEventCallback,
    db: Session = Depends(get_db)
):
    """
    Receive log events from Training Service.

    Backend forwards logs to Loki for centralized logging.
    This provides structured logging from trainers without requiring
    direct Loki access.

    Args:
        job_id: Training job ID
        callback: Log event data
        db: Database session

    Returns:
        Acknowledgment response
    """
    from app.services.training_callback_service import TrainingCallbackService

    service = TrainingCallbackService(db)
    return await service.handle_log(job_id, callback)


@router.post(
    "/jobs/{job_id}/checkpoints/upload-url",
    response_model=training.CheckpointUploadUrlResponse
)
async def get_checkpoint_upload_url(
    job_id: int,
    request: training.CheckpointUploadUrlRequest,
    db: Session = Depends(get_db)
):
    """
    Generate presigned S3 URL for checkpoint upload.

    This endpoint implements the Backend-Proxied storage pattern:
    - Training Service requests upload URL from Backend
    - Backend generates presigned S3 URL
    - Training Service uploads directly to S3 using presigned URL
    - No direct S3 credentials needed in Training Service

    Args:
        job_id: Training job ID
        request: Upload request with filename and content type
        db: Database session

    Returns:
        Presigned upload URL and object key
    """
    try:
        # Verify job exists
        job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
        if not job:
            logger.error(f"[CHECKPOINT] Job {job_id} not found")
            raise HTTPException(status_code=404, detail="Training job not found")

        logger.info(
            f"[CHECKPOINT] Generating upload URL for job {job_id}: {request.checkpoint_filename}"
        )

        # Generate S3 object key: checkpoints/{job_id}/{filename}
        object_key = f"checkpoints/job-{job_id}/{request.checkpoint_filename}"

        # Generate presigned upload URL
        from app.utils.dual_storage import dual_storage

        # Use boto3 client's generate_presigned_url
        upload_url = dual_storage.internal_client.generate_presigned_url(
            ClientMethod='put_object',
            Params={
                'Bucket': dual_storage.internal_bucket_checkpoints,
                'Key': object_key,
                'ContentType': request.content_type
            },
            ExpiresIn=3600  # 1 hour
        )

        if not upload_url:
            logger.error(f"[CHECKPOINT] Failed to generate presigned URL for job {job_id}")
            raise HTTPException(
                status_code=500,
                detail="Failed to generate upload URL. S3 storage may not be configured."
            )

        logger.info(f"[CHECKPOINT] Generated upload URL for job {job_id}: {object_key}")

        return training.CheckpointUploadUrlResponse(
            upload_url=upload_url,
            object_key=object_key,
            expires_in=3600
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[CHECKPOINT] Error generating upload URL: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate upload URL: {str(e)}"
        )
