"""
Model Export and Deployment API endpoints.

Provides endpoints for:
- Export: Converting trained checkpoints to production formats
- Deployment: Deploying exported models to various targets
- Platform Inference: Running inference on deployed models
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import json
import logging
from datetime import datetime
from pathlib import Path

from app.db.database import get_db
from app.db import models
import asyncio
from app.schemas import export as export_schemas
from app.core.training_managers.subprocess_manager import get_training_subprocess_manager
from app.utils.dual_storage import dual_storage
from app.services.websocket_manager import get_websocket_manager

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/export", tags=["export"])


# ========== Export Capabilities ==========

# Framework capability matrix (static for now, can be loaded from trainer services later)
EXPORT_CAPABILITIES = {
    "ultralytics": {
        "object_detection": {
            "supported_formats": [
                {
                    "format": "onnx",
                    "supported": True,
                    "native_support": True,
                    "requires_conversion": False,
                    "optimization_options": ["dynamic_quantization"]
                },
                {
                    "format": "tensorrt",
                    "supported": True,
                    "native_support": True,
                    "requires_conversion": False,
                    "optimization_options": ["fp16", "int8"]
                },
                {
                    "format": "coreml",
                    "supported": True,
                    "native_support": True,
                    "requires_conversion": False,
                    "optimization_options": []
                },
                {
                    "format": "torchscript",
                    "supported": True,
                    "native_support": True,
                    "requires_conversion": False,
                    "optimization_options": []
                },
                {
                    "format": "openvino",
                    "supported": True,
                    "native_support": True,
                    "requires_conversion": False,
                    "optimization_options": []
                }
            ],
            "default_format": "onnx"
        },
        "instance_segmentation": {
            "supported_formats": [
                {
                    "format": "onnx",
                    "supported": True,
                    "native_support": True,
                    "requires_conversion": False,
                    "optimization_options": ["dynamic_quantization"]
                },
                {
                    "format": "tensorrt",
                    "supported": True,
                    "native_support": True,
                    "requires_conversion": False,
                    "optimization_options": ["fp16"]
                }
            ],
            "default_format": "onnx"
        },
        "pose_estimation": {
            "supported_formats": [
                {
                    "format": "onnx",
                    "supported": True,
                    "native_support": True,
                    "requires_conversion": False,
                    "optimization_options": ["dynamic_quantization"]
                }
            ],
            "default_format": "onnx"
        }
    },
    "timm": {
        "image_classification": {
            "supported_formats": [
                {
                    "format": "onnx",
                    "supported": True,
                    "native_support": False,
                    "requires_conversion": True,
                    "optimization_options": ["dynamic_quantization"]
                },
                {
                    "format": "torchscript",
                    "supported": True,
                    "native_support": False,
                    "requires_conversion": True,
                    "optimization_options": []
                }
            ],
            "default_format": "onnx"
        }
    }
}

# Task type aliases for backward compatibility
# Maps short names used in TrainingJob to canonical names in EXPORT_CAPABILITIES
TASK_TYPE_ALIASES = {
    "detection": "object_detection",
    "segmentation": "instance_segmentation",
    "pose": "pose_estimation",
    "classification": "image_classification",
}


def normalize_task_type(task_type: str) -> str:
    """Normalize task_type to canonical form used in EXPORT_CAPABILITIES."""
    return TASK_TYPE_ALIASES.get(task_type, task_type)


@router.get("/capabilities", response_model=export_schemas.ExportCapabilitiesResponse)
async def get_export_capabilities(
    training_job_id: Optional[int] = Query(None, description="Training job ID (preferred, will look up framework/task_type)"),
    framework: Optional[str] = Query(None, description="Framework name (ultralytics, timm, etc.)"),
    task_type: Optional[str] = Query(None, description="Task type (object_detection, image_classification, etc.)"),
    db: Session = Depends(get_db)
):
    """
    Get export capabilities for a specific framework and task type.

    Returns supported export formats, optimization options, and recommended defaults.

    You can provide either:
    - training_job_id: Will look up framework and task_type from the training job
    - framework + task_type: Direct specification

    Args:
        training_job_id: Training job ID (will look up framework/task_type)
        framework: Framework name (if not using training_job_id)
        task_type: Task type (if not using training_job_id)
        db: Database session

    Returns:
        ExportCapabilitiesResponse with supported formats and options
    """
    # If training_job_id is provided, look up framework and task_type
    if training_job_id is not None:
        training_job = db.query(models.TrainingJob).filter(
            models.TrainingJob.id == training_job_id
        ).first()

        if not training_job:
            raise HTTPException(
                status_code=404,
                detail=f"Training job {training_job_id} not found"
            )

        framework = training_job.framework
        task_type = training_job.task_type
    elif framework is None or task_type is None:
        raise HTTPException(
            status_code=422,
            detail="Either training_job_id or both framework and task_type must be provided"
        )

    # Check if framework is supported
    if framework not in EXPORT_CAPABILITIES:
        raise HTTPException(
            status_code=404,
            detail=f"Framework '{framework}' not supported. Supported: {list(EXPORT_CAPABILITIES.keys())}"
        )

    # Normalize task_type (e.g., "detection" -> "object_detection")
    normalized_task_type = normalize_task_type(task_type)

    # Check if task type is supported for this framework
    if normalized_task_type not in EXPORT_CAPABILITIES[framework]:
        raise HTTPException(
            status_code=404,
            detail=f"Task type '{task_type}' not supported for framework '{framework}'. "
                   f"Supported: {list(EXPORT_CAPABILITIES[framework].keys())}"
        )

    capabilities = EXPORT_CAPABILITIES[framework][normalized_task_type]

    return export_schemas.ExportCapabilitiesResponse(
        framework=framework,
        task_type=task_type,  # Return original task_type for backward compatibility
        supported_formats=[
            export_schemas.ExportFormatCapability(**fmt)
            for fmt in capabilities["supported_formats"]
        ],
        default_format=capabilities["default_format"]
    )


# ========== Export Job Endpoints ==========

@router.post("/jobs", response_model=export_schemas.ExportJobResponse, status_code=201)
async def create_export_job(
    request: export_schemas.ExportJobRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Create a new export job to convert a trained checkpoint to production format.

    Supports ONNX, TensorRT, CoreML, TFLite, TorchScript, OpenVINO formats
    with optional optimizations (quantization, pruning) and validation.

    Args:
        request: Export job configuration
        background_tasks: FastAPI background tasks
        db: Database session

    Returns:
        ExportJobResponse with job metadata
    """
    # Check if training job exists
    training_job = db.query(models.TrainingJob).filter(
        models.TrainingJob.id == request.training_job_id
    ).first()

    if not training_job:
        raise HTTPException(
            status_code=404,
            detail=f"Training job {request.training_job_id} not found"
        )

    # Determine checkpoint path
    checkpoint_path = request.checkpoint_path
    if not checkpoint_path:
        # Use best checkpoint from training job
        checkpoint_path = training_job.best_checkpoint_path
        if not checkpoint_path:
            raise HTTPException(
                status_code=400,
                detail="No checkpoint specified and training job has no best checkpoint"
            )

    # Check if checkpoint exists (skip validation for now - will be validated in subprocess)
    # checkpoint_file = Path(checkpoint_path)
    # if not checkpoint_file.exists():
    #     raise HTTPException(
    #         status_code=404,
    #         detail=f"Checkpoint not found: {checkpoint_path}"
    #     )

    # Determine next version number
    existing_exports = db.query(models.ExportJob).filter(
        models.ExportJob.training_job_id == request.training_job_id
    ).all()
    next_version = len(existing_exports) + 1

    # If set_as_default, unset any existing default
    if request.set_as_default:
        db.query(models.ExportJob).filter(
            models.ExportJob.training_job_id == request.training_job_id,
            models.ExportJob.is_default == True
        ).update({"is_default": False})

    # Create export job record
    export_job = models.ExportJob(
        training_job_id=request.training_job_id,
        export_format=request.export_format,
        checkpoint_path=checkpoint_path,
        version=next_version,
        is_default=request.set_as_default or (next_version == 1),  # First export is default
        framework=training_job.framework,
        task_type=training_job.task_type,
        model_name=training_job.model_name,
        export_config=request.export_config.model_dump() if request.export_config else None,
        optimization_config=request.optimization_config.model_dump() if request.optimization_config else None,
        validation_config=request.validation_config.model_dump() if request.validation_config else None,
        status=models.ExportJobStatus.PENDING,
        created_at=datetime.utcnow()
    )

    db.add(export_job)
    db.commit()
    db.refresh(export_job)

    # Broadcast WebSocket event for new export job
    try:
        ws_manager = get_websocket_manager()
        ws_message = {
            "type": "export_status_change",
            "job_id": request.training_job_id,
            "export_job_id": export_job.id,
            "old_status": "",
            "new_status": "pending",
            "timestamp": datetime.utcnow().isoformat()
        }
        asyncio.create_task(ws_manager.broadcast_to_job(request.training_job_id, ws_message))
        logger.info(f"[EXPORT] WebSocket broadcast sent for new export job {export_job.id}")
    except Exception as e:
        logger.warning(f"[EXPORT] Failed to send WebSocket broadcast: {e}")

    # Launch background task to run export
    async def run_export_task(job_id: int):
        """Background task to run export subprocess"""
        try:
            # Get fresh export job from DB
            from app.db.database import SessionLocal
            db_session = SessionLocal()
            job = db_session.query(models.ExportJob).filter(models.ExportJob.id == job_id).first()

            if not job:
                logger.error(f"Export job {job_id} not found")
                return

            # Update status to running
            job.status = models.ExportJobStatus.RUNNING
            job.started_at = datetime.utcnow()
            db_session.commit()

            # Get training subprocess manager
            manager = get_training_subprocess_manager()

            # Prepare export config
            export_config = job.export_config or {}
            if job.optimization_config:
                export_config.update(job.optimization_config)
            if job.validation_config:
                export_config.update(job.validation_config)

            # Add task_type to config
            export_config['task_type'] = job.task_type

            # Start export subprocess
            await manager.start_export(
                export_job_id=job.id,
                training_job_id=job.training_job_id,
                framework=job.framework,
                checkpoint_s3_uri=job.checkpoint_path,
                export_format=job.export_format.value,  # Enum to string
                callback_url=f"{request.callback_url if hasattr(request, 'callback_url') else 'http://localhost:8000/api/v1'}",
                config=export_config
            )

            logger.info(f"Export subprocess started for job {job_id}")

        except Exception as e:
            logger.error(f"Failed to start export subprocess for job {job_id}: {e}")
            # Update job status to failed
            try:
                from app.db.database import SessionLocal
                db_session = SessionLocal()
                job = db_session.query(models.ExportJob).filter(models.ExportJob.id == job_id).first()
                if job:
                    job.status = models.ExportJobStatus.FAILED
                    job.error_message = str(e)
                    db_session.commit()
            except:
                pass
        finally:
            if 'db_session' in locals():
                db_session.close()

    background_tasks.add_task(run_export_task, export_job.id)

    logger.info(f"Created export job {export_job.id} for training job {request.training_job_id}")

    return export_schemas.ExportJobResponse.model_validate(export_job)


@router.get("/training/{training_job_id}/exports", response_model=export_schemas.ExportJobListResponse)
async def get_export_jobs(
    training_job_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """
    Get all export jobs for a training job.

    Returns export jobs ordered by version (descending).

    Args:
        training_job_id: Training job ID
        skip: Number of results to skip (pagination)
        limit: Maximum number of results to return
        db: Database session

    Returns:
        ExportJobListResponse with all export jobs
    """
    # Check if training job exists
    training_job = db.query(models.TrainingJob).filter(
        models.TrainingJob.id == training_job_id
    ).first()

    if not training_job:
        raise HTTPException(
            status_code=404,
            detail=f"Training job {training_job_id} not found"
        )

    # Query export jobs
    query = db.query(models.ExportJob).filter(
        models.ExportJob.training_job_id == training_job_id
    ).order_by(models.ExportJob.version.desc())

    total_count = query.count()
    export_jobs = query.offset(skip).limit(limit).all()

    export_jobs_data = [
        export_schemas.ExportJobResponse.model_validate(job)
        for job in export_jobs
    ]

    return export_schemas.ExportJobListResponse(
        training_job_id=training_job_id,
        total_count=total_count,
        export_jobs=export_jobs_data
    )


@router.get("/jobs/{export_job_id}", response_model=export_schemas.ExportJobResponse)
async def get_export_job(
    export_job_id: int,
    db: Session = Depends(get_db)
):
    """
    Get a specific export job.

    Returns export job details including status, results, and file size.

    Args:
        export_job_id: Export job ID
        db: Database session

    Returns:
        ExportJobResponse with job details
    """
    export_job = db.query(models.ExportJob).filter(
        models.ExportJob.id == export_job_id
    ).first()

    if not export_job:
        raise HTTPException(
            status_code=404,
            detail=f"Export job {export_job_id} not found"
        )

    return export_schemas.ExportJobResponse.model_validate(export_job)




@router.get("/{export_job_id}/download")
async def get_export_download_url(
    export_job_id: int,
    db: Session = Depends(get_db)
):
    """
    Get presigned download URL for exported model.

    Returns a temporary URL (1 hour expiration) to download the exported model file.

    Args:
        export_job_id: Export job ID
        db: Database session

    Returns:
        JSON with download_url field
    """
    export_job = db.query(models.ExportJob).filter(
        models.ExportJob.id == export_job_id
    ).first()

    if not export_job:
        raise HTTPException(
            status_code=404,
            detail=f"Export job {export_job_id} not found"
        )

    if export_job.status != models.ExportJobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Export job {export_job_id} is not completed (status: {export_job.status})"
        )

    if not export_job.export_path:
        raise HTTPException(
            status_code=404,
            detail=f"Export job {export_job_id} has no export path"
        )

    # Extract object_key from S3 URI (s3://bucket/key -> key)
    export_path = export_job.export_path
    if export_path.startswith("s3://"):
        # Remove s3://bucket/ prefix
        parts = export_path.replace("s3://", "").split("/", 1)
        object_key = parts[1] if len(parts) > 1 else ""
    else:
        object_key = export_path

    # Generate presigned URL from internal storage (checkpoints)
    try:
        download_url = dual_storage.internal_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": dual_storage.internal_bucket_checkpoints,
                "Key": object_key
            },
            ExpiresIn=3600  # 1 hour
        )
    except Exception as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate download URL: {str(e)}"
        )

    if not download_url:
        raise HTTPException(
            status_code=500,
            detail="Failed to generate download URL"
        )

    return {"download_url": download_url}

# ========== Deployment Endpoints (Placeholder) ==========

@router.post("/deployments", response_model=export_schemas.DeploymentResponse, status_code=201)
async def create_deployment(
    request: export_schemas.DeploymentRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Create a new deployment for an exported model.

    Supports deployment types: download, platform_endpoint, edge_package, container.

    Args:
        request: Deployment configuration
        background_tasks: FastAPI background tasks
        db: Database session

    Returns:
        DeploymentResponse with deployment metadata
    """
    # Check if export job exists
    export_job = db.query(models.ExportJob).filter(
        models.ExportJob.id == request.export_job_id
    ).first()

    if not export_job:
        raise HTTPException(
            status_code=404,
            detail=f"Export job {request.export_job_id} not found"
        )

    # Check if export is completed
    if export_job.status != models.ExportJobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Export job {request.export_job_id} is not completed (status: {export_job.status})"
        )

    # Create deployment record
    deployment = models.DeploymentTarget(
        export_job_id=request.export_job_id,
        training_job_id=export_job.training_job_id,
        deployment_type=request.deployment_type,
        deployment_name=request.deployment_name,
        deployment_config=request.deployment_config.model_dump() if request.deployment_config else None,
        cpu_limit=request.cpu_limit,
        memory_limit=request.memory_limit,
        gpu_enabled=request.gpu_enabled,
        status=models.DeploymentStatus.PENDING,
        created_at=datetime.utcnow()
    )

    db.add(deployment)
    db.commit()
    db.refresh(deployment)

    # TODO: Launch background task to deploy
    # background_tasks.add_task(deploy_task, deployment.id)

    logger.info(f"Created deployment {deployment.id} for export job {request.export_job_id}")

    return export_schemas.DeploymentResponse.model_validate(deployment)


@router.get("/deployments", response_model=export_schemas.DeploymentListResponse)
async def list_deployments(
    training_job_id: Optional[int] = Query(None, description="Filter by training job ID"),
    export_job_id: Optional[int] = Query(None, description="Filter by export job ID"),
    deployment_type: Optional[str] = Query(None, description="Filter by deployment type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """
    List deployments with optional filters.

    Args:
        training_job_id: Filter by training job ID
        export_job_id: Filter by export job ID
        deployment_type: Filter by deployment type
        status: Filter by status
        skip: Number of results to skip (pagination)
        limit: Maximum number of results to return
        db: Database session

    Returns:
        DeploymentListResponse with matching deployments
    """
    query = db.query(models.DeploymentTarget)

    if training_job_id:
        query = query.filter(models.DeploymentTarget.training_job_id == training_job_id)

    if export_job_id:
        query = query.filter(models.DeploymentTarget.export_job_id == export_job_id)

    if deployment_type:
        query = query.filter(models.DeploymentTarget.deployment_type == deployment_type)

    if status:
        query = query.filter(models.DeploymentTarget.status == status)

    query = query.order_by(models.DeploymentTarget.created_at.desc())

    total_count = query.count()
    deployments = query.offset(skip).limit(limit).all()

    deployments_data = [
        export_schemas.DeploymentResponse.model_validate(dep)
        for dep in deployments
    ]

    return export_schemas.DeploymentListResponse(
        total_count=total_count,
        deployments=deployments_data
    )


@router.get("/deployments/{deployment_id}", response_model=export_schemas.DeploymentResponse)
async def get_deployment(
    deployment_id: int,
    db: Session = Depends(get_db)
):
    """
    Get a specific deployment.

    Returns deployment details including endpoint URL, usage stats, and status.

    Args:
        deployment_id: Deployment ID
        db: Database session

    Returns:
        DeploymentResponse with deployment details
    """
    deployment = db.query(models.DeploymentTarget).filter(
        models.DeploymentTarget.id == deployment_id
    ).first()

    if not deployment:
        raise HTTPException(
            status_code=404,
            detail=f"Deployment {deployment_id} not found"
        )

    return export_schemas.DeploymentResponse.model_validate(deployment)


# ========== Export Callback Endpoint ==========

@router.post("/jobs/{export_job_id}/callback/started", status_code=200)
async def export_started_callback(
    export_job_id: int,
    callback_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Receive export started callback from export subprocess.

    Called by export.py when export job starts.

    Args:
        export_job_id: Export job ID
        callback_data: Callback payload
        db: Database session

    Returns:
        Success message
    """
    logger.info(f"[EXPORT CALLBACK] Received started callback for job {export_job_id}")

    # Get export job
    export_job = db.query(models.ExportJob).filter(
        models.ExportJob.id == export_job_id
    ).first()

    if not export_job:
        logger.error(f"[EXPORT CALLBACK] Export job {export_job_id} not found")
        raise HTTPException(
            status_code=404,
            detail=f"Export job {export_job_id} not found"
        )

    # Update status to running if still pending
    if export_job.status == models.ExportJobStatus.PENDING:
        export_job.status = models.ExportJobStatus.RUNNING
        export_job.started_at = datetime.utcnow()
        db.commit()
        logger.info(f"[EXPORT CALLBACK] Job {export_job_id} status updated to RUNNING")

    # Broadcast WebSocket event
    try:
        ws_manager = get_websocket_manager()
        ws_message = {
            "type": "export_status_change",
            "job_id": export_job.training_job_id,
            "export_job_id": export_job_id,
            "old_status": "pending",
            "new_status": "running",
            "timestamp": datetime.utcnow().isoformat()
        }
        asyncio.create_task(ws_manager.broadcast_to_job(export_job.training_job_id, ws_message))
        logger.info(f"[EXPORT CALLBACK] WebSocket broadcast sent for job {export_job_id}")
    except Exception as e:
        logger.warning(f"[EXPORT CALLBACK] Failed to send WebSocket broadcast: {e}")

    return {
        "message": "Started callback received",
        "export_job_id": export_job_id,
        "status": "running"
    }


@router.post("/jobs/{export_job_id}/callback/completion", status_code=200)
async def export_completion_callback(
    export_job_id: int,
    callback_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Receive export completion callback from export subprocess.

    Called by export.py when export job completes (success or failure).

    Args:
        export_job_id: Export job ID
        callback_data: Callback payload with status and results
        db: Database session

    Returns:
        Success message
    """
    logger.info(f"[EXPORT CALLBACK] Received completion callback for job {export_job_id}")
    logger.info(f"[EXPORT CALLBACK] Status: {callback_data.get('status')}")

    # Get export job
    export_job = db.query(models.ExportJob).filter(
        models.ExportJob.id == export_job_id
    ).first()

    if not export_job:
        logger.error(f"[EXPORT CALLBACK] Export job {export_job_id} not found")
        raise HTTPException(
            status_code=404,
            detail=f"Export job {export_job_id} not found"
        )

    # Update export job status
    status = callback_data.get('status', 'unknown')

    if status == 'completed':
        export_job.status = models.ExportJobStatus.COMPLETED
        export_job.completed_at = datetime.utcnow()

        # SDK format only (no legacy fallback)
        export_job.export_path = callback_data.get('output_s3_uri')
        
        file_size_bytes = callback_data.get('file_size_bytes')
        export_job.file_size_mb = file_size_bytes / (1024 * 1024) if file_size_bytes else None
        
        export_job.export_results = callback_data.get('metadata', {})

        logger.info(f"[EXPORT CALLBACK] Job {export_job_id} completed successfully")
        logger.info(f"[EXPORT CALLBACK]   Export path: {export_job.export_path}")
        if export_job.file_size_mb:
            logger.info(f"[EXPORT CALLBACK]   File size: {export_job.file_size_mb:.2f} MB")

    elif status == 'failed':
        export_job.status = models.ExportJobStatus.FAILED
        export_job.error_message = callback_data.get('error_message')
        export_job.completed_at = datetime.utcnow()

        logger.error(f"[EXPORT CALLBACK] Job {export_job_id} failed: {export_job.error_message}")

    else:
        logger.warning(f"[EXPORT CALLBACK] Unknown status: {status}")
        export_job.error_message = f"Unknown status from callback: {status}"

    db.commit()

    logger.info(f"[EXPORT CALLBACK] Export job {export_job_id} updated in database")

    # Broadcast WebSocket event for real-time updates
    try:
        ws_manager = get_websocket_manager()
        ws_message = {
            "type": "export_status_change",
            "job_id": export_job.training_job_id,
            "export_job_id": export_job_id,
            "old_status": "running",
            "new_status": status,
            "timestamp": datetime.utcnow().isoformat()
        }
        asyncio.create_task(ws_manager.broadcast_to_job(export_job.training_job_id, ws_message))
        logger.info(f"[EXPORT CALLBACK] WebSocket broadcast sent for training job {export_job.training_job_id}")
    except Exception as e:
        logger.warning(f"[EXPORT CALLBACK] Failed to send WebSocket broadcast: {e}")

    return {
        "message": "Callback received",
        "export_job_id": export_job_id,
        "status": status
    }
