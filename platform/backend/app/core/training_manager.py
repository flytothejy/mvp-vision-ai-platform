"""Training Manager Abstraction.

Phase 12: Temporal Orchestration & Backend Modernization

This module provides an abstract base class for training execution,
allowing seamless switching between subprocess (Tier 0) and Kubernetes (Tier 1+)
based on the TRAINING_MODE environment variable.

Architecture:
- TrainingManager: Abstract base class defining the interface
- SubprocessTrainingManager: Executes training in local subprocess (Tier 0)
- KubernetesTrainingManager: Executes training in K8s Job (Tier 1+)
- get_training_manager(): Factory function selecting implementation based on TRAINING_MODE
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from app.db import models

logger = logging.getLogger(__name__)


class TrainingManager(ABC):
    """
    Abstract base class for training execution.

    Implementations:
    - SubprocessTrainingManager: Local subprocess execution (Tier 0)
    - KubernetesTrainingManager: K8s Job execution (Tier 1+)

    This abstraction allows the same code to work across different deployment tiers
    by simply changing the TRAINING_MODE environment variable.
    """

    @abstractmethod
    async def start_training(
        self,
        job: models.TrainingJob,
        callback_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Start a training job.

        Args:
            job: TrainingJob model instance
            callback_url: Optional URL for training callbacks (status updates)

        Returns:
            Dict containing execution metadata (process_id, job_id, status, etc.)

        Raises:
            RuntimeError: If training fails to start
            FileNotFoundError: If required files/resources not found
        """
        pass

    @abstractmethod
    def stop_training(self, job_id: int) -> bool:
        """
        Stop a running training job.

        Args:
            job_id: TrainingJob ID

        Returns:
            True if successfully stopped, False otherwise
        """
        pass

    @abstractmethod
    def get_training_status(self, job_id: int) -> Optional[Dict[str, Any]]:
        """
        Get current status of a training job.

        Args:
            job_id: TrainingJob ID

        Returns:
            Dict with status information, or None if job not found

        Example return:
            {
                "job_id": 123,
                "status": "running",  # pending, running, completed, failed
                "process_id": "12345",
                "started_at": "2025-01-27T10:00:00Z",
                "runtime_seconds": 3600,
                "current_epoch": 25,
                "total_epochs": 50
            }
        """
        pass

    @abstractmethod
    async def start_evaluation(
        self,
        job_id: int,
        checkpoint_path: str,
        dataset_path: str
    ) -> Dict[str, Any]:
        """
        Start model evaluation.

        Args:
            job_id: TrainingJob ID (for logging context)
            checkpoint_path: Path to model checkpoint
            dataset_path: Path to evaluation dataset

        Returns:
            Dict containing evaluation results

        Raises:
            RuntimeError: If evaluation fails to start
        """
        pass

    @abstractmethod
    async def start_inference(
        self,
        job_id: int,
        checkpoint_path: str,
        input_data: Any
    ) -> Dict[str, Any]:
        """
        Run inference with trained model.

        Args:
            job_id: TrainingJob ID (for logging context)
            checkpoint_path: Path to model checkpoint
            input_data: Input data for inference

        Returns:
            Dict containing inference results

        Raises:
            RuntimeError: If inference fails
        """
        pass

    @abstractmethod
    async def start_export(
        self,
        job_id: int,
        checkpoint_path: str,
        export_format: str,
        export_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Export trained model to different format.

        Args:
            job_id: TrainingJob ID (for logging context)
            checkpoint_path: Path to model checkpoint
            export_format: Target format (onnx, tensorrt, coreml, etc.)
            export_config: Optional export configuration

        Returns:
            Dict containing export results (output_path, metadata, etc.)

        Raises:
            RuntimeError: If export fails
        """
        pass

    @abstractmethod
    def cleanup_resources(self, job_id: int) -> None:
        """
        Clean up resources for a training job.

        This includes:
        - Temporary files
        - Running processes/pods
        - GPU allocations

        Args:
            job_id: TrainingJob ID
        """
        pass


def get_training_manager() -> TrainingManager:
    """
    Factory function to get TrainingManager implementation.

    Returns appropriate implementation based on TRAINING_MODE environment variable:
    - "subprocess": SubprocessTrainingManager (Tier 0)
    - "kubernetes": KubernetesTrainingManager (Tier 1+)

    Returns:
        TrainingManager instance

    Raises:
        ValueError: If TRAINING_MODE is invalid

    Example:
        >>> from app.core.config import settings
        >>> manager = get_training_manager()
        >>> # Returns SubprocessTrainingManager if settings.TRAINING_MODE == "subprocess"
        >>> # Returns KubernetesTrainingManager if settings.TRAINING_MODE == "kubernetes"
    """
    from app.core.config import settings

    mode = settings.TRAINING_MODE.lower()

    if mode == "subprocess":
        from app.core.training_managers.subprocess_manager import SubprocessTrainingManager
        logger.info("[TrainingManager] Using SubprocessTrainingManager (Tier 0)")
        return SubprocessTrainingManager()

    elif mode == "kubernetes":
        from app.core.training_managers.kubernetes_manager import KubernetesTrainingManager
        logger.info("[TrainingManager] Using KubernetesTrainingManager (Tier 1+)")
        return KubernetesTrainingManager()

    else:
        raise ValueError(
            f"Invalid TRAINING_MODE: {mode}. "
            f"Expected 'subprocess' or 'kubernetes'"
        )
