"""Training Workflow Definition.

Phase 12: Temporal Orchestration & Backend Modernization

This module defines the TrainingWorkflow and its Activities for orchestrating
the entire training pipeline using Temporal.
"""

import logging
from datetime import timedelta
from typing import Dict, Any, Optional

from temporalio import workflow, activity
from temporalio.common import RetryPolicy

logger = logging.getLogger(__name__)


# ========== Workflow Input/Output Models ==========

class TrainingWorkflowInput:
    """Input parameters for TrainingWorkflow."""

    def __init__(self, job_id: int):
        self.job_id = job_id


class TrainingWorkflowResult:
    """Result of TrainingWorkflow execution."""

    def __init__(
        self,
        success: bool,
        job_id: int,
        final_metrics: Optional[Dict[str, Any]] = None,
        model_path: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        self.success = success
        self.job_id = job_id
        self.final_metrics = final_metrics
        self.model_path = model_path
        self.error_message = error_message


# ========== Activity Definitions ==========

@activity.defn(name="validate_dataset")
async def validate_dataset(job_id: int) -> Dict[str, Any]:
    """
    Validate dataset existence and format.

    Args:
        job_id: TrainingJob ID

    Returns:
        Dict containing validation results and dataset metadata

    Raises:
        ValueError: If dataset is invalid or not found
    """
    logger.info(f"[Activity] validate_dataset - job_id={job_id}")

    from app.db.database import SessionLocal
    from app.db import models
    from pathlib import Path

    db = SessionLocal()
    try:
        # 1. Load TrainingJob from database
        job = db.query(models.TrainingJob).filter(
            models.TrainingJob.id == job_id
        ).first()

        if not job:
            raise ValueError(f"TrainingJob {job_id} not found")

        # 2. Check dataset exists
        if job.dataset_id:
            # New dataset reference approach
            dataset = db.query(models.Dataset).filter(
                models.Dataset.id == job.dataset_id
            ).first()

            if not dataset:
                raise ValueError(f"Dataset {job.dataset_id} not found")

            dataset_path = dataset.local_path
            logger.info(f"[validate_dataset] Using Dataset ID: {dataset.id}, path: {dataset_path}")
        elif job.dataset_path:
            # Legacy dataset_path approach
            dataset_path = job.dataset_path
            logger.info(f"[validate_dataset] Using legacy dataset_path: {dataset_path}")
        else:
            raise ValueError(f"Job {job_id} has no dataset_id or dataset_path")

        # 3. Check dataset path exists
        dataset_dir = Path(dataset_path)
        if not dataset_dir.exists():
            raise ValueError(f"Dataset path does not exist: {dataset_path}")

        # 4. Basic format validation (simplified - full validation in Training Service)
        dataset_format = job.dataset_format or "imagefolder"
        logger.info(f"[validate_dataset] Dataset format: {dataset_format}")

        # 5. Return metadata
        return {
            "valid": True,
            "dataset_path": str(dataset_path),
            "dataset_format": dataset_format,
            "job_id": job_id,
        }

    finally:
        db.close()


@activity.defn(name="create_clearml_task")
async def create_clearml_task(job_id: int) -> str:
    """
    Create ClearML Task for experiment tracking.

    Args:
        job_id: TrainingJob ID

    Returns:
        ClearML Task ID

    Note:
        This will be implemented in Phase 12.2 (ClearML Migration).
        For now, returns empty string to maintain workflow structure.
    """
    logger.info(f"[Activity] create_clearml_task - job_id={job_id}")

    # TODO: Implement ClearML Task creation (Phase 12.2)
    # 1. Initialize ClearML Task
    # 2. Set task parameters from TrainingJob
    # 3. Link to project
    # 4. Return task ID

    return ""  # Placeholder


@activity.defn(name="execute_training")
async def execute_training(job_id: int, clearml_task_id: str) -> Dict[str, Any]:
    """
    Execute actual training using TrainingManager.

    This is the core activity that runs the training process.
    It delegates to TrainingManager which handles subprocess/kubernetes execution.

    Args:
        job_id: TrainingJob ID
        clearml_task_id: ClearML Task ID (empty if not using ClearML yet)

    Returns:
        Dict containing training results (metrics, checkpoint paths, etc.)

    Raises:
        RuntimeError: If training fails
    """
    logger.info(f"[Activity] execute_training - job_id={job_id}, clearml_task_id={clearml_task_id}")

    from app.db.database import SessionLocal
    from app.db import models
    from app.core.training_manager import get_training_manager

    db = SessionLocal()
    try:
        # 1. Load TrainingJob from database
        job = db.query(models.TrainingJob).filter(
            models.TrainingJob.id == job_id
        ).first()

        if not job:
            raise ValueError(f"TrainingJob {job_id} not found")

        logger.info(f"[execute_training] Loaded job {job_id}: {job.model_name} on {job.framework}")

        # 2. Get TrainingManager instance (based on TRAINING_MODE)
        manager = get_training_manager()
        logger.info(f"[execute_training] Using TrainingManager: {type(manager).__name__}")

        # 3. Start training
        training_metadata = await manager.start_training(job)
        logger.info(f"[execute_training] Training started: {training_metadata}")

        # 4. Monitor training progress and send heartbeats
        import asyncio
        import time

        start_time = time.time()
        while True:
            # Refresh job status from database
            db.refresh(job)

            # Check if training completed/failed
            if job.status in ["completed", "failed", "cancelled"]:
                logger.info(f"[execute_training] Training {job.status}: job_id={job_id}")
                break

            # Send heartbeat to Temporal
            elapsed = int(time.time() - start_time)
            if job.current_epoch and job.epochs:
                progress_msg = f"Epoch {job.current_epoch}/{job.epochs} (elapsed: {elapsed}s)"
            else:
                progress_msg = f"Training in progress (elapsed: {elapsed}s)"

            activity.heartbeat(progress_msg)
            logger.debug(f"[execute_training] Heartbeat: {progress_msg}")

            # Wait 60 seconds before next check
            await asyncio.sleep(60)

        # 5. Return final result
        if job.status == "completed":
            return {
                "status": "completed",
                "final_metrics": {
                    "accuracy": job.final_accuracy,
                    "loss": getattr(job, "final_loss", None),
                },
                "best_checkpoint": job.best_checkpoint_path,
                "last_checkpoint": job.last_checkpoint_path,
            }
        else:
            # Training failed
            raise RuntimeError(f"Training failed: {job.error_message}")

    finally:
        db.close()


@activity.defn(name="upload_final_model")
async def upload_final_model(job_id: int, checkpoint_path: str) -> str:
    """
    Upload final model to storage (MinIO/S3).

    Args:
        job_id: TrainingJob ID
        checkpoint_path: Local path to best checkpoint

    Returns:
        Storage URL of uploaded model
    """
    logger.info(f"[Activity] upload_final_model - job_id={job_id}, checkpoint={checkpoint_path}")

    # TODO: Implement model upload
    # 1. Load checkpoint file
    # 2. Upload to MinIO (model-weights bucket)
    # 3. Update TrainingJob.best_checkpoint_path with storage URL
    # 4. Return storage URL

    return "s3://model-weights/job-123/best.pth"


@activity.defn(name="cleanup_training_resources")
async def cleanup_training_resources(job_id: int) -> None:
    """
    Clean up temporary training resources.

    Args:
        job_id: TrainingJob ID
    """
    logger.info(f"[Activity] cleanup_training_resources - job_id={job_id}")

    from app.core.training_manager import get_training_manager

    try:
        # Get TrainingManager and cleanup resources
        manager = get_training_manager()
        manager.cleanup_resources(job_id)

        logger.info(f"[cleanup_training_resources] Cleanup completed for job {job_id}")

    except Exception as e:
        logger.error(f"[cleanup_training_resources] Cleanup failed for job {job_id}: {e}")
        # Don't raise - cleanup failures should not fail the workflow
        pass


# ========== Workflow Definition ==========

@workflow.defn(name="TrainingWorkflow")
class TrainingWorkflow:
    """
    Main training workflow orchestrating the entire training pipeline.

    Workflow Steps:
    1. Validate dataset
    2. Create ClearML task (optional, Phase 12.2)
    3. Execute training
    4. Upload final model
    5. Cleanup resources

    Timeouts:
    - Execution: 24 hours (max training time)
    - Run: No limit (workflow can be long-lived)

    Retry Policy:
    - Activities have individual retry policies
    - Workflow itself does not retry (let caller handle)
    """

    @workflow.run
    async def run(self, input: TrainingWorkflowInput) -> TrainingWorkflowResult:
        """
        Execute the training workflow.

        Args:
            input: Workflow input containing job_id

        Returns:
            TrainingWorkflowResult with final status and metrics
        """
        job_id = input.job_id
        workflow.logger.info(f"Starting TrainingWorkflow for job_id={job_id}")

        try:
            # Step 1: Validate Dataset
            workflow.logger.info(f"[Step 1/5] Validating dataset for job {job_id}")
            dataset_info = await workflow.execute_activity(
                validate_dataset,
                job_id,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                )
            )
            workflow.logger.info(f"Dataset validation completed: {dataset_info}")

            # Step 2: Create ClearML Task (Phase 12.2 - currently placeholder)
            workflow.logger.info(f"[Step 2/5] Creating ClearML task for job {job_id}")
            clearml_task_id = await workflow.execute_activity(
                create_clearml_task,
                job_id,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                )
            )
            workflow.logger.info(f"ClearML task created: {clearml_task_id}")

            # Step 3: Execute Training (longest step)
            workflow.logger.info(f"[Step 3/5] Executing training for job {job_id}")
            training_result = await workflow.execute_activity(
                execute_training,
                args=[job_id, clearml_task_id],
                start_to_close_timeout=timedelta(hours=24),  # Max 24h training
                heartbeat_timeout=timedelta(minutes=5),       # 5min heartbeat
                retry_policy=RetryPolicy(
                    maximum_attempts=1,  # Don't auto-retry training failures
                    non_retryable_error_types=["ValueError", "RuntimeError"],
                )
            )
            workflow.logger.info(f"Training completed: {training_result}")

            # Step 4: Upload Final Model
            workflow.logger.info(f"[Step 4/5] Uploading final model for job {job_id}")
            best_checkpoint = training_result.get("best_checkpoint")
            model_url = await workflow.execute_activity(
                upload_final_model,
                args=[job_id, best_checkpoint],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    maximum_attempts=5,  # Retry uploads
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=30),
                    backoff_coefficient=2.0,
                )
            )
            workflow.logger.info(f"Model uploaded to: {model_url}")

            # Step 5: Cleanup Resources
            workflow.logger.info(f"[Step 5/5] Cleaning up resources for job {job_id}")
            await workflow.execute_activity(
                cleanup_training_resources,
                job_id,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                )
            )

            workflow.logger.info(f"TrainingWorkflow completed successfully for job {job_id}")

            return TrainingWorkflowResult(
                success=True,
                job_id=job_id,
                final_metrics=training_result.get("final_metrics"),
                model_path=model_url,
                error_message=None
            )

        except Exception as e:
            error_msg = f"TrainingWorkflow failed for job {job_id}: {str(e)}"
            workflow.logger.error(error_msg)

            return TrainingWorkflowResult(
                success=False,
                job_id=job_id,
                final_metrics=None,
                model_path=None,
                error_message=error_msg
            )
