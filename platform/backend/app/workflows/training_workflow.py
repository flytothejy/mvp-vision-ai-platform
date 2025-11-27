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

    # TODO: Implement dataset validation logic
    # 1. Load TrainingJob from database
    # 2. Check dataset_id or dataset_path exists
    # 3. Validate dataset format (imagefolder, yolo, coco)
    # 4. Check required files exist
    # 5. Return metadata (num_images, num_classes, etc.)

    return {
        "valid": True,
        "dataset_path": "/path/to/dataset",
        "num_images": 1000,
        "num_classes": 10
    }


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

    # TODO: Implement training execution (Phase 12.1)
    # 1. Load TrainingJob from database
    # 2. Get TrainingManager instance (based on TRAINING_MODE)
    # 3. Call manager.start_training(job)
    # 4. Monitor training progress (via callbacks or polling)
    # 5. Wait for completion
    # 6. Return final metrics and checkpoint paths

    return {
        "status": "completed",
        "final_metrics": {
            "accuracy": 0.95,
            "loss": 0.15
        },
        "best_checkpoint": "/path/to/best.pth",
        "last_checkpoint": "/path/to/last.pth"
    }


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

    # TODO: Implement cleanup
    # 1. Delete temporary training directories
    # 2. Remove intermediate checkpoints (keep only best/last)
    # 3. Clean up any kubernetes pods (if TRAINING_MODE=kubernetes)
    # 4. Release GPU resources

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
