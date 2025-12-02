"""
DatabaseAdapter for Phase 13.1

Default observability adapter that stores metrics in the platform's own database.
Requires no external dependencies and always works.
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from .base import ObservabilityAdapter, MetricsResult
from app.db.models import TrainingMetric, TrainingJob


logger = logging.getLogger(__name__)


class DatabaseAdapter(ObservabilityAdapter):
    """
    Database-based observability adapter (default).

    Stores training metrics in the platform's TrainingMetric table.
    Requires no external services - always available.

    Design Principles:
    - Self-contained: No external dependencies
    - Always available: Primary fallback when other tools fail
    - Simple: Direct DB queries via SQLAlchemy
    """

    def __init__(self, db: Session):
        """
        Initialize DatabaseAdapter.

        Args:
            db: SQLAlchemy database session
        """
        super().__init__(name="database")
        self.db = db

    def initialize(self, config: Dict[str, Any]) -> None:
        """
        Initialize the adapter (no-op for database).

        Database is always available through the injected session.

        Args:
            config: Configuration (unused for database)
        """
        logger.info("[DatabaseAdapter] Initialized (always available)")

    def create_experiment(
        self,
        job_id: int,
        project_name: str,
        experiment_name: str,
        tags: Optional[List[str]] = None,
        hyperparameters: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create experiment (no-op for database, returns job_id as experiment_id).

        For DatabaseAdapter, the experiment is the TrainingJob itself.
        Hyperparameters are logged if provided.

        Args:
            job_id: Training job ID
            project_name: Project name (unused)
            experiment_name: Experiment name (unused)
            tags: Tags (unused)
            hyperparameters: Hyperparameters to log in TrainingJob

        Returns:
            experiment_id: String representation of job_id
        """
        experiment_id = str(job_id)

        # Log hyperparameters if provided
        if hyperparameters:
            try:
                job = self.db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
                if job:
                    # Store hyperparameters in job's config if not already set
                    if not job.config:
                        job.config = {}
                    if "hyperparameters" not in job.config:
                        job.config["hyperparameters"] = hyperparameters
                        self.db.commit()
                        logger.info(f"[DatabaseAdapter] Logged hyperparameters for job {job_id}")
            except Exception as e:
                logger.error(f"[DatabaseAdapter] Failed to log hyperparameters: {e}")
                self.db.rollback()

        logger.info(f"[DatabaseAdapter] Created experiment for job_id={job_id}")
        return experiment_id

    def log_metrics(
        self,
        experiment_id: str,
        metrics: Dict[str, float],
        step: int
    ) -> None:
        """
        Log metrics to the database.

        Args:
            experiment_id: String representation of job_id
            metrics: Dictionary of metric names to values
            step: Training step/epoch number

        Raises:
            Exception: If database insert fails
        """
        try:
            job_id = int(experiment_id)

            # Extract standard metrics
            loss = metrics.get("loss")
            accuracy = metrics.get("accuracy")
            learning_rate = metrics.get("learning_rate") or metrics.get("lr")

            # Put remaining metrics in extra_metrics
            extra_metrics = {
                k: v for k, v in metrics.items()
                if k not in ["loss", "accuracy", "learning_rate", "lr"]
            }

            # Create TrainingMetric record
            metric = TrainingMetric(
                job_id=job_id,
                epoch=step,  # Use step as epoch
                step=step,
                loss=loss,
                accuracy=accuracy,
                learning_rate=learning_rate,
                extra_metrics=extra_metrics if extra_metrics else None
            )

            self.db.add(metric)
            self.db.commit()

            logger.debug(
                f"[DatabaseAdapter] Logged metrics for job {job_id}, step {step}: "
                f"{list(metrics.keys())}"
            )

        except Exception as e:
            self.db.rollback()
            logger.error(f"[DatabaseAdapter] Failed to log metrics: {e}")
            raise

    def log_hyperparameters(
        self,
        experiment_id: str,
        params: Dict[str, Any]
    ) -> None:
        """
        Log hyperparameters to the database.

        Args:
            experiment_id: String representation of job_id
            params: Hyperparameters dictionary

        Raises:
            Exception: If database update fails
        """
        try:
            job_id = int(experiment_id)
            job = self.db.query(TrainingJob).filter(TrainingJob.id == job_id).first()

            if not job:
                raise ValueError(f"TrainingJob {job_id} not found")

            # Update config with hyperparameters
            if not job.config:
                job.config = {}

            job.config["hyperparameters"] = params
            self.db.commit()

            logger.info(f"[DatabaseAdapter] Logged hyperparameters for job {job_id}")

        except Exception as e:
            self.db.rollback()
            logger.error(f"[DatabaseAdapter] Failed to log hyperparameters: {e}")
            raise

    def get_metrics(
        self,
        experiment_id: str,
        metric_names: Optional[List[str]] = None
    ) -> MetricsResult:
        """
        Retrieve metrics from the database.

        Args:
            experiment_id: String representation of job_id
            metric_names: Optional list of specific metrics to retrieve

        Returns:
            MetricsResult: Standardized metrics result

        Raises:
            Exception: If database query fails
        """
        try:
            job_id = int(experiment_id)

            # Query all metrics for this job, ordered by step
            metrics_records = (
                self.db.query(TrainingMetric)
                .filter(TrainingMetric.job_id == job_id)
                .order_by(TrainingMetric.step)
                .all()
            )

            # Build result
            metrics_dict: Dict[str, List[float]] = {}
            steps: List[int] = []

            for record in metrics_records:
                steps.append(record.step or record.epoch)

                # Add standard metrics
                if record.loss is not None:
                    if "loss" not in metrics_dict:
                        metrics_dict["loss"] = []
                    metrics_dict["loss"].append(record.loss)

                if record.accuracy is not None:
                    if "accuracy" not in metrics_dict:
                        metrics_dict["accuracy"] = []
                    metrics_dict["accuracy"].append(record.accuracy)

                if record.learning_rate is not None:
                    if "learning_rate" not in metrics_dict:
                        metrics_dict["learning_rate"] = []
                    metrics_dict["learning_rate"].append(record.learning_rate)

                # Add extra metrics
                if record.extra_metrics:
                    for key, value in record.extra_metrics.items():
                        if key not in metrics_dict:
                            metrics_dict[key] = []
                        metrics_dict[key].append(float(value))

            # Filter by metric_names if provided
            if metric_names:
                metrics_dict = {
                    k: v for k, v in metrics_dict.items()
                    if k in metric_names
                }

            logger.debug(
                f"[DatabaseAdapter] Retrieved {len(steps)} metric entries for job {job_id}"
            )

            return MetricsResult(
                metrics=metrics_dict,
                steps=steps,
                total_count=len(steps)
            )

        except Exception as e:
            logger.error(f"[DatabaseAdapter] Failed to retrieve metrics: {e}")
            raise

    def finalize_experiment(
        self,
        experiment_id: str,
        status: str,
        final_metrics: Optional[Dict[str, float]] = None
    ) -> None:
        """
        Finalize experiment (no-op for database).

        Database doesn't need explicit finalization.
        Final metrics are logged if provided.

        Args:
            experiment_id: String representation of job_id
            status: Final status ("completed", "failed", "stopped")
            final_metrics: Optional final metrics to log

        Raises:
            Exception: If logging final metrics fails
        """
        try:
            job_id = int(experiment_id)

            # Log final metrics if provided
            if final_metrics:
                # Get the last step number
                last_metric = (
                    self.db.query(TrainingMetric)
                    .filter(TrainingMetric.job_id == job_id)
                    .order_by(desc(TrainingMetric.step))
                    .first()
                )

                final_step = (last_metric.step + 1) if last_metric else 0

                self.log_metrics(
                    experiment_id=experiment_id,
                    metrics=final_metrics,
                    step=final_step
                )

            logger.info(
                f"[DatabaseAdapter] Finalized experiment for job {job_id} with status '{status}'"
            )

        except Exception as e:
            logger.error(f"[DatabaseAdapter] Failed to finalize experiment: {e}")
            # Don't raise - finalization failure shouldn't stop training

    def get_experiment_url(self, experiment_id: str) -> Optional[str]:
        """
        Get experiment URL (returns frontend URL for database).

        Args:
            experiment_id: String representation of job_id

        Returns:
            Frontend URL for viewing the training job
        """
        job_id = experiment_id
        # Return frontend URL (this will be constructed by the frontend)
        # Format: /training/{job_id}
        url = f"/training/{job_id}"
        logger.debug(f"[DatabaseAdapter] Experiment URL: {url}")
        return url
