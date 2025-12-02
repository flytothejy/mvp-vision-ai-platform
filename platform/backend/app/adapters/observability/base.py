"""
ObservabilityAdapter Base Class (Phase 13.1)

Abstract base class defining the interface for all observability adapters.
Each observability tool (ClearML, MLflow, TensorBoard, Database) implements this interface.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class MetricsResult:
    """
    Standardized metrics result format returned by all adapters.

    Attributes:
        metrics: Dictionary of metric name to values {metric_name: [value1, value2, ...]}
        steps: List of step numbers corresponding to metric values
        total_count: Total number of metric entries
    """
    metrics: Dict[str, List[float]]
    steps: List[int]
    total_count: int


class ObservabilityAdapter(ABC):
    """
    Abstract base class for observability adapters.

    Each adapter provides a unified interface for logging and retrieving metrics
    from different observability tools (ClearML, MLflow, TensorBoard, Database).

    Design Principles:
    - Single Responsibility: Each adapter handles one observability tool
    - Open/Closed: Easy to add new adapters without modifying existing code
    - Liskov Substitution: All adapters can be used interchangeably
    - Graceful Degradation: Adapter failures don't stop training
    """

    def __init__(self, name: str):
        """
        Initialize adapter with a unique name.

        Args:
            name: Unique identifier for this adapter (e.g., "database", "clearml")
        """
        self.name = name
        self._enabled = True

    @abstractmethod
    def initialize(self, config: Dict[str, Any]) -> None:
        """
        Initialize the adapter with configuration.

        Args:
            config: Configuration dictionary specific to this adapter
                    (e.g., API keys, endpoints, credentials)

        Raises:
            Exception: If initialization fails, adapter will be disabled
        """
        pass

    @abstractmethod
    def create_experiment(
        self,
        job_id: int,
        project_name: str,
        experiment_name: str,
        tags: Optional[List[str]] = None,
        hyperparameters: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a new experiment/run in the observability tool.

        Args:
            job_id: Training job ID (unique identifier)
            project_name: Project name for grouping experiments
            experiment_name: Human-readable experiment name
            tags: Optional list of tags for the experiment
            hyperparameters: Optional hyperparameters to log

        Returns:
            experiment_id: Unique identifier for the created experiment
                           (format depends on the tool, e.g., ClearML task_id, MLflow run_id)

        Raises:
            Exception: If experiment creation fails
        """
        pass

    @abstractmethod
    def log_metrics(
        self,
        experiment_id: str,
        metrics: Dict[str, float],
        step: int
    ) -> None:
        """
        Log metrics for a specific step.

        Args:
            experiment_id: Experiment identifier returned by create_experiment()
            metrics: Dictionary of metric name to value {metric_name: value}
                     (e.g., {"loss": 0.234, "accuracy": 0.89})
            step: Training step/epoch number

        Raises:
            Exception: If logging fails
        """
        pass

    @abstractmethod
    def log_hyperparameters(
        self,
        experiment_id: str,
        params: Dict[str, Any]
    ) -> None:
        """
        Log hyperparameters for an experiment.

        Args:
            experiment_id: Experiment identifier
            params: Dictionary of hyperparameter names to values
                    (e.g., {"learning_rate": 0.001, "batch_size": 32})

        Raises:
            Exception: If logging fails
        """
        pass

    @abstractmethod
    def get_metrics(
        self,
        experiment_id: str,
        metric_names: Optional[List[str]] = None
    ) -> MetricsResult:
        """
        Retrieve metrics for an experiment.

        Args:
            experiment_id: Experiment identifier
            metric_names: Optional list of specific metrics to retrieve.
                          If None, retrieve all metrics.

        Returns:
            MetricsResult: Standardized metrics result with values and steps

        Raises:
            Exception: If retrieval fails
        """
        pass

    @abstractmethod
    def finalize_experiment(
        self,
        experiment_id: str,
        status: str,
        final_metrics: Optional[Dict[str, float]] = None
    ) -> None:
        """
        Mark an experiment as completed and log final metrics.

        Args:
            experiment_id: Experiment identifier
            status: Final status ("completed", "failed", "stopped")
            final_metrics: Optional final metrics to log

        Raises:
            Exception: If finalization fails
        """
        pass

    @abstractmethod
    def get_experiment_url(self, experiment_id: str) -> Optional[str]:
        """
        Get the web UI URL for viewing the experiment.

        Args:
            experiment_id: Experiment identifier

        Returns:
            URL string for the experiment UI, or None if not available
        """
        pass

    def is_enabled(self) -> bool:
        """
        Check if this adapter is enabled and operational.

        Returns:
            True if adapter is enabled, False otherwise
        """
        return self._enabled

    def disable(self) -> None:
        """
        Disable this adapter (typically called after initialization failure).
        Disabled adapters will be skipped by ObservabilityManager.
        """
        self._enabled = False

    def enable(self) -> None:
        """
        Enable this adapter.
        """
        self._enabled = True

    def __repr__(self) -> str:
        status = "enabled" if self._enabled else "disabled"
        return f"{self.__class__.__name__}(name='{self.name}', status={status})"
