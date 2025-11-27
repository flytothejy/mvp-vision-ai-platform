"""
ClearML Service

Provides ClearML integration for experiment tracking, metrics logging,
and model management. Replaces MLflow in Phase 12.2.

Key Features:
- Task creation and lifecycle management
- Real-time metrics logging
- Artifact and model management
- Integration with Temporal Workflows
"""

from typing import Optional, Dict, List, Any
import logging
import os
from pathlib import Path

from clearml import Task, Model, OutputModel
from sqlalchemy.orm import Session

from app.db import models
from app.core.config import settings

logger = logging.getLogger(__name__)


class ClearMLService:
    """ClearML integration service for experiment tracking"""

    def __init__(self, db: Session):
        """
        Initialize ClearML Service

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

        # Ensure ClearML is configured
        self._configure_clearml()

    def _configure_clearml(self):
        """Configure ClearML SDK with environment variables"""
        if hasattr(settings, 'CLEARML_API_HOST'):
            os.environ['CLEARML_API_HOST'] = settings.CLEARML_API_HOST
            os.environ['CLEARML_WEB_HOST'] = settings.CLEARML_WEB_HOST
            os.environ['CLEARML_FILES_HOST'] = settings.CLEARML_FILES_HOST

            # Set credentials if provided (empty for open-source server)
            os.environ['CLEARML_API_ACCESS_KEY'] = getattr(settings, 'CLEARML_API_ACCESS_KEY', '')
            os.environ['CLEARML_API_SECRET_KEY'] = getattr(settings, 'CLEARML_API_SECRET_KEY', '')

    # ========================================
    # 1. Task Management
    # ========================================

    def create_task(
        self,
        job_id: int,
        task_name: str,
        task_type: str = "training",
        project_name: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        Create ClearML task for training job

        Args:
            job_id: Training job ID from database
            task_name: Human-readable task name
            task_type: Type of task (training, testing, inference)
            project_name: ClearML project name (default: "Platform Training")
            tags: Optional tags for task organization

        Returns:
            ClearML task ID (str) or None on failure
        """
        try:
            # Get training job from database
            training_job = self.db.query(models.TrainingJob).filter(
                models.TrainingJob.id == job_id
            ).first()

            if not training_job:
                logger.error(f"Training job {job_id} not found")
                return None

            # Use default project if not specified
            if not project_name:
                project_name = getattr(settings, 'CLEARML_DEFAULT_PROJECT', 'Platform Training')

            # Create ClearML task
            task = Task.init(
                project_name=project_name,
                task_name=task_name,
                task_type=task_type,
                reuse_last_task_id=False,
                auto_connect_frameworks=False,  # Manual control
                tags=tags or []
            )

            # Connect configuration parameters
            task.connect_configuration(
                name="training_config",
                configuration={
                    "job_id": job_id,
                    "model_name": training_job.model_name,
                    "framework": training_job.framework,
                    "task_type": training_job.task_type,
                    "dataset_format": training_job.dataset_format,
                    "num_epochs": training_job.num_epochs,
                    "batch_size": training_job.batch_size,
                    "learning_rate": training_job.learning_rate,
                    "image_size": training_job.image_size,
                }
            )

            task_id = task.id

            # Update training job with ClearML task ID
            training_job.clearml_task_id = task_id
            self.db.commit()

            logger.info(f"Created ClearML task {task_id} for job {job_id}")
            logger.info(f"  Web UI: {settings.CLEARML_WEB_HOST}/projects/*/experiments/{task_id}")

            return task_id

        except Exception as e:
            logger.error(f"Failed to create ClearML task for job {job_id}: {e}")
            self.db.rollback()
            return None

    def get_task(self, task_id: str) -> Optional[Task]:
        """
        Get ClearML task by ID

        Args:
            task_id: ClearML task ID

        Returns:
            ClearML Task object or None if not found
        """
        try:
            task = Task.get_task(task_id=task_id)
            return task
        except Exception as e:
            logger.error(f"Failed to get ClearML task {task_id}: {e}")
            return None

    # ========================================
    # 2. Metrics Logging
    # ========================================

    def log_metrics(
        self,
        task_id: str,
        metrics: Dict[str, float],
        iteration: int,
        title: str = "metrics"
    ):
        """
        Log metrics to ClearML task

        Args:
            task_id: ClearML task ID
            metrics: Dictionary of metric name → value
            iteration: Iteration/epoch number
            title: Metric group title
        """
        try:
            task = self.get_task(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found, skipping metrics logging")
                return

            logger = task.get_logger()

            # Log each metric as a scalar
            for metric_name, metric_value in metrics.items():
                logger.report_scalar(
                    title=title,
                    series=metric_name,
                    value=metric_value,
                    iteration=iteration
                )

            logger.info(f"Logged {len(metrics)} metrics to task {task_id} at iteration {iteration}")

        except Exception as e:
            logger.error(f"Failed to log metrics to task {task_id}: {e}")

    def log_scalar(
        self,
        task_id: str,
        title: str,
        series: str,
        value: float,
        iteration: int
    ):
        """
        Log single scalar metric to ClearML

        Args:
            task_id: ClearML task ID
            title: Metric group title (e.g., "loss", "accuracy")
            series: Metric series name (e.g., "train", "val")
            value: Metric value
            iteration: Iteration/epoch number
        """
        try:
            task = self.get_task(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found, skipping scalar logging")
                return

            task_logger = task.get_logger()
            task_logger.report_scalar(
                title=title,
                series=series,
                value=value,
                iteration=iteration
            )

        except Exception as e:
            logger.error(f"Failed to log scalar to task {task_id}: {e}")

    # ========================================
    # 3. Artifact Management
    # ========================================

    def upload_artifact(
        self,
        task_id: str,
        artifact_name: str,
        artifact_path: str,
        metadata: Optional[Dict] = None
    ):
        """
        Upload artifact (checkpoint, config, etc.) to ClearML

        Args:
            task_id: ClearML task ID
            artifact_name: Name of artifact
            artifact_path: Local path to artifact file
            metadata: Optional metadata dictionary
        """
        try:
            task = self.get_task(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found, skipping artifact upload")
                return

            # Upload artifact
            task.upload_artifact(
                name=artifact_name,
                artifact_object=artifact_path,
                metadata=metadata
            )

            logger.info(f"Uploaded artifact '{artifact_name}' to task {task_id}")

        except Exception as e:
            logger.error(f"Failed to upload artifact to task {task_id}: {e}")

    def upload_checkpoint(
        self,
        task_id: str,
        checkpoint_path: str,
        epoch: int,
        metrics: Optional[Dict[str, float]] = None
    ):
        """
        Upload training checkpoint

        Args:
            task_id: ClearML task ID
            checkpoint_path: Path to checkpoint file
            epoch: Epoch number
            metrics: Optional metrics at this checkpoint
        """
        metadata = {
            "epoch": epoch,
            "metrics": metrics or {}
        }

        artifact_name = f"checkpoint_epoch_{epoch}"
        self.upload_artifact(task_id, artifact_name, checkpoint_path, metadata)

    # ========================================
    # 4. Task Status Management
    # ========================================

    def mark_completed(self, task_id: str, status_message: Optional[str] = None):
        """
        Mark task as completed

        Args:
            task_id: ClearML task ID
            status_message: Optional completion message
        """
        try:
            task = self.get_task(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found, skipping completion")
                return

            task.mark_completed(status_message=status_message)
            logger.info(f"Marked task {task_id} as completed")

        except Exception as e:
            logger.error(f"Failed to mark task {task_id} as completed: {e}")

    def mark_failed(self, task_id: str, status_reason: str):
        """
        Mark task as failed

        Args:
            task_id: ClearML task ID
            status_reason: Failure reason message
        """
        try:
            task = self.get_task(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found, skipping failure marking")
                return

            task.mark_failed(status_reason=status_reason)
            logger.error(f"Marked task {task_id} as failed: {status_reason}")

        except Exception as e:
            logger.error(f"Failed to mark task {task_id} as failed: {e}")

    def mark_stopped(self, task_id: str, status_message: Optional[str] = None):
        """
        Mark task as stopped (user requested stop)

        Args:
            task_id: ClearML task ID
            status_message: Optional stop message
        """
        try:
            task = self.get_task(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found, skipping stop")
                return

            task.mark_stopped(status_message=status_message)
            logger.info(f"Marked task {task_id} as stopped")

        except Exception as e:
            logger.error(f"Failed to mark task {task_id} as stopped: {e}")

    # ========================================
    # 5. Model Registry
    # ========================================

    def register_model(
        self,
        task_id: str,
        model_path: str,
        model_name: str,
        tags: Optional[List[str]] = None,
        comment: Optional[str] = None
    ) -> Optional[str]:
        """
        Register model in ClearML Model Repository

        Args:
            task_id: ClearML task ID
            model_path: Path to model file
            model_name: Model name for registration
            tags: Optional model tags
            comment: Optional model description

        Returns:
            Model ID (str) or None on failure
        """
        try:
            task = self.get_task(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found, skipping model registration")
                return None

            # Create output model
            output_model = OutputModel(
                task=task,
                name=model_name,
                tags=tags or [],
                comment=comment
            )

            # Update model file
            output_model.update_weights(
                weights_filename=model_path,
                auto_delete_file=False
            )

            model_id = output_model.id

            logger.info(f"Registered model '{model_name}' (ID: {model_id}) for task {task_id}")
            logger.info(f"  Model URL: {settings.CLEARML_WEB_HOST}/models/*/models/{model_id}")

            return model_id

        except Exception as e:
            logger.error(f"Failed to register model for task {task_id}: {e}")
            return None

    # ========================================
    # 6. Query Methods
    # ========================================

    def get_task_by_job_id(self, job_id: int) -> Optional[Task]:
        """
        Get ClearML task associated with training job

        Args:
            job_id: Training job ID

        Returns:
            ClearML Task object or None
        """
        try:
            training_job = self.db.query(models.TrainingJob).filter(
                models.TrainingJob.id == job_id
            ).first()

            if not training_job or not training_job.clearml_task_id:
                return None

            return self.get_task(training_job.clearml_task_id)

        except Exception as e:
            logger.error(f"Failed to get task for job {job_id}: {e}")
            return None

    def get_task_metrics(self, task_id: str) -> Dict[str, Any]:
        """
        Get all metrics for a task

        Args:
            task_id: ClearML task ID

        Returns:
            Dictionary of metrics data
        """
        try:
            task = self.get_task(task_id)
            if not task:
                return {}

            # Get scalars (metrics)
            scalars = task.get_last_scalar_metrics()

            return {
                "scalars": scalars,
                "task_status": task.status,
                "task_url": f"{settings.CLEARML_WEB_HOST}/projects/*/experiments/{task_id}"
            }

        except Exception as e:
            logger.error(f"Failed to get metrics for task {task_id}: {e}")
            return {}


# ========================================
# Dependency Injection Helper
# ========================================

def get_clearml_service(db: Session) -> ClearMLService:
    """
    Dependency for FastAPI endpoints

    Usage:
        @app.get("/...")
        async def endpoint(clearml: ClearMLService = Depends(get_clearml_service)):
            ...
    """
    return ClearMLService(db)
