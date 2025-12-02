"""
ClearMLAdapter for Phase 13.1

Adapter for ClearML observability backend.
Wraps the existing ClearMLService to conform to ObservabilityAdapter interface.
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from clearml import Task
from .base import ObservabilityAdapter, MetricsResult
from app.services.clearml_service import ClearMLService


logger = logging.getLogger(__name__)


class ClearMLAdapter(ObservabilityAdapter):
    """
    ClearML-based observability adapter.

    Wraps ClearMLService to provide ObservabilityAdapter interface.
    Enables experiment tracking, metrics logging, and artifact management via ClearML.

    Design Principles:
    - Wrapper pattern: Delegates to ClearMLService
    - Graceful degradation: Failures don't stop training
    - External service: Requires ClearML server configuration
    """

    def __init__(self, db: Session):
        """
        Initialize ClearMLAdapter.

        Args:
            db: SQLAlchemy database session
        """
        super().__init__(name="clearml")
        self.db = db
        self.clearml_service: Optional[ClearMLService] = None

    def initialize(self, config: Dict[str, Any]) -> None:
        """
        Initialize ClearML service.

        Args:
            config: Configuration dictionary containing:
                - api_host: ClearML API server URL (optional, uses env vars)
                - web_host: ClearML Web UI URL (optional)
                - access_key: API access key (optional)
                - secret_key: API secret key (optional)

        Raises:
            Exception: If ClearML initialization fails
        """
        try:
            # Create ClearML service (handles configuration internally)
            self.clearml_service = ClearMLService(self.db)

            logger.info("[ClearMLAdapter] Initialized successfully")

        except Exception as e:
            logger.error(f"[ClearMLAdapter] Initialization failed: {e}")
            self.disable()
            raise

    def create_experiment(
        self,
        job_id: int,
        project_name: str,
        experiment_name: str,
        tags: Optional[List[str]] = None,
        hyperparameters: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create ClearML task for experiment.

        Args:
            job_id: Training job ID
            project_name: ClearML project name
            experiment_name: Task name
            tags: Optional tags for the task
            hyperparameters: Hyperparameters (logged via connect_configuration)

        Returns:
            task_id: ClearML task ID

        Raises:
            Exception: If task creation fails
        """
        if not self.clearml_service:
            raise RuntimeError("ClearMLAdapter not initialized")

        try:
            # Create ClearML task
            task_id = self.clearml_service.create_task(
                job_id=job_id,
                task_name=experiment_name,
                task_type="training",
                project_name=project_name,
                tags=tags
            )

            if not task_id:
                raise RuntimeError(f"Failed to create ClearML task for job {job_id}")

            # Log hyperparameters if provided
            if hyperparameters:
                task = self.clearml_service.get_task(task_id)
                if task:
                    task.connect_configuration(
                        name="hyperparameters",
                        configuration=hyperparameters
                    )

            logger.info(f"[ClearMLAdapter] Created task {task_id} for job {job_id}")
            return task_id

        except Exception as e:
            logger.error(f"[ClearMLAdapter] Failed to create experiment: {e}")
            raise

    def log_metrics(
        self,
        experiment_id: str,
        metrics: Dict[str, float],
        step: int
    ) -> None:
        """
        Log metrics to ClearML task.

        Args:
            experiment_id: ClearML task ID
            metrics: Dictionary of metric names to values
            step: Training step/epoch number

        Raises:
            Exception: If logging fails
        """
        if not self.clearml_service:
            raise RuntimeError("ClearMLAdapter not initialized")

        try:
            self.clearml_service.log_metrics(
                task_id=experiment_id,
                metrics=metrics,
                iteration=step,
                title="training_metrics"
            )

            logger.debug(
                f"[ClearMLAdapter] Logged metrics for task {experiment_id}, step {step}"
            )

        except Exception as e:
            logger.error(f"[ClearMLAdapter] Failed to log metrics: {e}")
            raise

    def log_hyperparameters(
        self,
        experiment_id: str,
        params: Dict[str, Any]
    ) -> None:
        """
        Log hyperparameters to ClearML task.

        Args:
            experiment_id: ClearML task ID
            params: Hyperparameters dictionary

        Raises:
            Exception: If logging fails
        """
        if not self.clearml_service:
            raise RuntimeError("ClearMLAdapter not initialized")

        try:
            task = self.clearml_service.get_task(experiment_id)
            if not task:
                raise RuntimeError(f"Task {experiment_id} not found")

            # Connect hyperparameters to task
            task.connect_configuration(
                name="hyperparameters",
                configuration=params
            )

            logger.info(f"[ClearMLAdapter] Logged hyperparameters for task {experiment_id}")

        except Exception as e:
            logger.error(f"[ClearMLAdapter] Failed to log hyperparameters: {e}")
            raise

    def get_metrics(
        self,
        experiment_id: str,
        metric_names: Optional[List[str]] = None
    ) -> MetricsResult:
        """
        Retrieve metrics from ClearML task.

        Note: ClearML API provides limited historical metrics retrieval.
        For full metrics history, use DatabaseAdapter as primary source.

        Args:
            experiment_id: ClearML task ID
            metric_names: Optional list of specific metrics

        Returns:
            MetricsResult: Metrics data (may be incomplete)

        Raises:
            Exception: If retrieval fails
        """
        if not self.clearml_service:
            raise RuntimeError("ClearMLAdapter not initialized")

        try:
            task = self.clearml_service.get_task(experiment_id)
            if not task:
                raise RuntimeError(f"Task {experiment_id} not found")

            # Get last scalar metrics from ClearML
            scalars = task.get_last_scalar_metrics()

            # ClearML's get_last_scalar_metrics() returns:
            # {
            #   "title": {
            #     "series": {"last": value, "min": value, "max": value}
            #   }
            # }

            # Convert to MetricsResult format
            metrics_dict: Dict[str, List[float]] = {}
            steps: List[int] = []

            # Extract metrics (only last values available)
            for title, series_dict in scalars.items():
                for series_name, values in series_dict.items():
                    metric_key = f"{title}/{series_name}"
                    if metric_names and metric_key not in metric_names:
                        continue

                    # Only last value available from ClearML API
                    last_value = values.get("last")
                    if last_value is not None:
                        metrics_dict[metric_key] = [last_value]

            # ClearML doesn't provide step history via this API
            # Use iteration 0 as placeholder
            if metrics_dict:
                steps = [0] * len(next(iter(metrics_dict.values())))

            logger.warning(
                f"[ClearMLAdapter] Retrieved limited metrics for task {experiment_id}. "
                "ClearML API only provides last values. Use DatabaseAdapter for full history."
            )

            return MetricsResult(
                metrics=metrics_dict,
                steps=steps,
                total_count=len(steps)
            )

        except Exception as e:
            logger.error(f"[ClearMLAdapter] Failed to retrieve metrics: {e}")
            raise

    def finalize_experiment(
        self,
        experiment_id: str,
        status: str,
        final_metrics: Optional[Dict[str, float]] = None
    ) -> None:
        """
        Mark ClearML task as completed/failed/stopped.

        Args:
            experiment_id: ClearML task ID
            status: Final status ("completed", "failed", "stopped")
            final_metrics: Optional final metrics to log

        Raises:
            Exception: If finalization fails
        """
        if not self.clearml_service:
            raise RuntimeError("ClearMLAdapter not initialized")

        try:
            # Log final metrics if provided
            if final_metrics:
                task = self.clearml_service.get_task(experiment_id)
                if task:
                    # Get last iteration number
                    last_iteration = task.get_last_iteration() or 0
                    self.log_metrics(
                        experiment_id=experiment_id,
                        metrics=final_metrics,
                        step=last_iteration + 1
                    )

            # Mark task with appropriate status
            if status == "completed":
                self.clearml_service.mark_completed(
                    task_id=experiment_id,
                    status_message="Training completed successfully"
                )
            elif status == "failed":
                self.clearml_service.mark_failed(
                    task_id=experiment_id,
                    status_reason="Training failed"
                )
            elif status == "stopped":
                self.clearml_service.mark_stopped(
                    task_id=experiment_id,
                    status_message="Training stopped by user"
                )
            else:
                logger.warning(f"[ClearMLAdapter] Unknown status '{status}', marking as stopped")
                self.clearml_service.mark_stopped(
                    task_id=experiment_id,
                    status_message=f"Training ended with status: {status}"
                )

            logger.info(
                f"[ClearMLAdapter] Finalized task {experiment_id} with status '{status}'"
            )

        except Exception as e:
            logger.error(f"[ClearMLAdapter] Failed to finalize experiment: {e}")
            # Don't raise - finalization failure shouldn't stop training

    def get_experiment_url(self, experiment_id: str) -> Optional[str]:
        """
        Get ClearML Web UI URL for the task.

        Args:
            experiment_id: ClearML task ID

        Returns:
            URL string for ClearML task UI
        """
        if not self.clearml_service:
            return None

        try:
            task = self.clearml_service.get_task(experiment_id)
            if not task:
                return None

            # Get ClearML web host from settings
            from app.core.config import settings
            web_host = getattr(settings, 'CLEARML_WEB_HOST', 'http://localhost:8080')

            # ClearML URL format: {web_host}/projects/*/experiments/{task_id}
            url = f"{web_host}/projects/*/experiments/{experiment_id}"

            logger.debug(f"[ClearMLAdapter] Experiment URL: {url}")
            return url

        except Exception as e:
            logger.error(f"[ClearMLAdapter] Failed to get experiment URL: {e}")
            return None
