"""
ObservabilityManager for Phase 13.2

Manages multiple observability adapters and coordinates metrics logging.
Provides graceful degradation when individual adapters fail.
"""

import logging
from typing import Any, Dict, List, Optional

from app.adapters.observability import ObservabilityAdapter, MetricsResult


logger = logging.getLogger(__name__)


class ObservabilityManager:
    """
    Manages multiple observability adapters.

    Coordinates metrics logging across multiple backends (Database, ClearML, MLflow, etc.).
    Provides graceful degradation - individual adapter failures don't stop training.

    Design Principles:
    - Coordinator: Manages multiple adapters
    - Graceful Degradation: Adapter errors are logged but don't stop execution
    - Primary Source: DatabaseAdapter is primary for metrics retrieval
    - Flexible: Easy to add/remove adapters at runtime
    """

    def __init__(self):
        """
        Initialize ObservabilityManager with empty adapter registry.
        """
        self._adapters: Dict[str, ObservabilityAdapter] = {}
        self._primary_adapter: Optional[str] = None

    def add_adapter(self, name: str, adapter: ObservabilityAdapter) -> None:
        """
        Register an observability adapter.

        Args:
            name: Unique adapter name (e.g., "database", "clearml")
            adapter: ObservabilityAdapter instance

        Raises:
            ValueError: If adapter with same name already exists
        """
        if name in self._adapters:
            raise ValueError(f"Adapter '{name}' already registered")

        self._adapters[name] = adapter

        # Set first adapter as primary (typically "database")
        if not self._primary_adapter:
            self._primary_adapter = name

        logger.info(f"[ObservabilityManager] Registered adapter '{name}'")

    def remove_adapter(self, name: str) -> None:
        """
        Remove an adapter from registry.

        Args:
            name: Adapter name to remove
        """
        if name in self._adapters:
            del self._adapters[name]
            logger.info(f"[ObservabilityManager] Removed adapter '{name}'")

            # Update primary if removed
            if self._primary_adapter == name:
                self._primary_adapter = next(iter(self._adapters.keys()), None)

    def set_primary_adapter(self, name: str) -> None:
        """
        Set primary adapter for metrics retrieval.

        Args:
            name: Adapter name to set as primary

        Raises:
            ValueError: If adapter not found
        """
        if name not in self._adapters:
            raise ValueError(f"Adapter '{name}' not found")

        self._primary_adapter = name
        logger.info(f"[ObservabilityManager] Set primary adapter to '{name}'")

    def get_adapter(self, name: str) -> Optional[ObservabilityAdapter]:
        """
        Get adapter by name.

        Args:
            name: Adapter name

        Returns:
            ObservabilityAdapter instance or None
        """
        return self._adapters.get(name)

    def list_adapters(self) -> List[str]:
        """
        Get list of registered adapter names.

        Returns:
            List of adapter names
        """
        return list(self._adapters.keys())

    def list_enabled_adapters(self) -> List[str]:
        """
        Get list of enabled adapter names.

        Returns:
            List of enabled adapter names
        """
        return [
            name for name, adapter in self._adapters.items()
            if adapter.is_enabled()
        ]

    # ========================================
    # Experiment Lifecycle
    # ========================================

    def create_experiment(
        self,
        job_id: int,
        project_name: str,
        experiment_name: str,
        tags: Optional[List[str]] = None,
        hyperparameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        Create experiment in all enabled adapters.

        Args:
            job_id: Training job ID
            project_name: Project name for grouping
            experiment_name: Human-readable experiment name
            tags: Optional tags
            hyperparameters: Optional hyperparameters

        Returns:
            experiment_ids: Dictionary mapping adapter name to experiment_id
                            {adapter_name: experiment_id}
                            Example: {"database": "123", "clearml": "abc-def-ghi"}
        """
        experiment_ids: Dict[str, str] = {}

        for name, adapter in self._adapters.items():
            if not adapter.is_enabled():
                logger.warning(f"[ObservabilityManager] Skipping disabled adapter '{name}'")
                continue

            try:
                experiment_id = adapter.create_experiment(
                    job_id=job_id,
                    project_name=project_name,
                    experiment_name=experiment_name,
                    tags=tags,
                    hyperparameters=hyperparameters
                )

                experiment_ids[name] = experiment_id

                logger.info(
                    f"[ObservabilityManager] Created experiment in '{name}': {experiment_id}"
                )

            except Exception as e:
                logger.error(
                    f"[ObservabilityManager] Failed to create experiment in '{name}': {e}",
                    exc_info=True
                )
                # Disable adapter on failure
                adapter.disable()
                logger.warning(f"[ObservabilityManager] Disabled adapter '{name}' due to error")

        if not experiment_ids:
            logger.error("[ObservabilityManager] Failed to create experiment in any adapter!")
            # This is critical - at least database should work

        return experiment_ids

    def log_metrics(
        self,
        experiment_ids: Dict[str, str],
        metrics: Dict[str, float],
        step: int
    ) -> None:
        """
        Log metrics to all enabled adapters.

        Args:
            experiment_ids: Dictionary mapping adapter name to experiment_id
            metrics: Dictionary of metric names to values
            step: Training step/epoch number
        """
        for name, adapter in self._adapters.items():
            if not adapter.is_enabled():
                continue

            experiment_id = experiment_ids.get(name)
            if not experiment_id:
                logger.warning(
                    f"[ObservabilityManager] No experiment_id for adapter '{name}', skipping"
                )
                continue

            try:
                adapter.log_metrics(
                    experiment_id=experiment_id,
                    metrics=metrics,
                    step=step
                )

                logger.debug(
                    f"[ObservabilityManager] Logged metrics to '{name}' (step {step})"
                )

            except Exception as e:
                logger.error(
                    f"[ObservabilityManager] Failed to log metrics to '{name}': {e}",
                    exc_info=True
                )
                # Don't disable adapter for metrics logging failures
                # (might be transient network issues)

    def log_hyperparameters(
        self,
        experiment_ids: Dict[str, str],
        params: Dict[str, Any]
    ) -> None:
        """
        Log hyperparameters to all enabled adapters.

        Args:
            experiment_ids: Dictionary mapping adapter name to experiment_id
            params: Hyperparameters dictionary
        """
        for name, adapter in self._adapters.items():
            if not adapter.is_enabled():
                continue

            experiment_id = experiment_ids.get(name)
            if not experiment_id:
                logger.warning(
                    f"[ObservabilityManager] No experiment_id for adapter '{name}', skipping"
                )
                continue

            try:
                adapter.log_hyperparameters(
                    experiment_id=experiment_id,
                    params=params
                )

                logger.info(f"[ObservabilityManager] Logged hyperparameters to '{name}'")

            except Exception as e:
                logger.error(
                    f"[ObservabilityManager] Failed to log hyperparameters to '{name}': {e}",
                    exc_info=True
                )

    def get_metrics(
        self,
        experiment_ids: Dict[str, str],
        metric_names: Optional[List[str]] = None,
        adapter_name: Optional[str] = None
    ) -> MetricsResult:
        """
        Retrieve metrics from primary adapter (or specified adapter).

        Args:
            experiment_ids: Dictionary mapping adapter name to experiment_id
            metric_names: Optional list of specific metrics to retrieve
            adapter_name: Optional specific adapter to query (default: primary)

        Returns:
            MetricsResult: Metrics data

        Raises:
            RuntimeError: If primary/specified adapter not available
        """
        # Determine which adapter to query
        source_adapter = adapter_name or self._primary_adapter

        if not source_adapter:
            raise RuntimeError("No primary adapter configured")

        adapter = self._adapters.get(source_adapter)
        if not adapter or not adapter.is_enabled():
            raise RuntimeError(f"Adapter '{source_adapter}' not available")

        experiment_id = experiment_ids.get(source_adapter)
        if not experiment_id:
            raise RuntimeError(f"No experiment_id for adapter '{source_adapter}'")

        try:
            metrics_result = adapter.get_metrics(
                experiment_id=experiment_id,
                metric_names=metric_names
            )

            logger.debug(
                f"[ObservabilityManager] Retrieved metrics from '{source_adapter}': "
                f"{metrics_result.total_count} entries"
            )

            return metrics_result

        except Exception as e:
            logger.error(
                f"[ObservabilityManager] Failed to retrieve metrics from '{source_adapter}': {e}",
                exc_info=True
            )
            raise

    def finalize_experiment(
        self,
        experiment_ids: Dict[str, str],
        status: str,
        final_metrics: Optional[Dict[str, float]] = None
    ) -> None:
        """
        Finalize experiment in all enabled adapters.

        Args:
            experiment_ids: Dictionary mapping adapter name to experiment_id
            status: Final status ("completed", "failed", "stopped")
            final_metrics: Optional final metrics to log
        """
        for name, adapter in self._adapters.items():
            if not adapter.is_enabled():
                continue

            experiment_id = experiment_ids.get(name)
            if not experiment_id:
                logger.warning(
                    f"[ObservabilityManager] No experiment_id for adapter '{name}', skipping"
                )
                continue

            try:
                adapter.finalize_experiment(
                    experiment_id=experiment_id,
                    status=status,
                    final_metrics=final_metrics
                )

                logger.info(
                    f"[ObservabilityManager] Finalized experiment in '{name}' "
                    f"with status '{status}'"
                )

            except Exception as e:
                logger.error(
                    f"[ObservabilityManager] Failed to finalize experiment in '{name}': {e}",
                    exc_info=True
                )
                # Don't raise - finalization failures shouldn't stop training

    def get_experiment_urls(self, experiment_ids: Dict[str, str]) -> Dict[str, Optional[str]]:
        """
        Get experiment URLs from all adapters.

        Args:
            experiment_ids: Dictionary mapping adapter name to experiment_id

        Returns:
            Dictionary mapping adapter name to experiment URL
            Example: {"database": "/training/123", "clearml": "http://..."}
        """
        urls: Dict[str, Optional[str]] = {}

        for name, adapter in self._adapters.items():
            if not adapter.is_enabled():
                continue

            experiment_id = experiment_ids.get(name)
            if not experiment_id:
                continue

            try:
                url = adapter.get_experiment_url(experiment_id)
                urls[name] = url

            except Exception as e:
                logger.error(
                    f"[ObservabilityManager] Failed to get URL from '{name}': {e}"
                )
                urls[name] = None

        return urls

    # ========================================
    # Statistics
    # ========================================

    def get_stats(self) -> Dict[str, Any]:
        """
        Get ObservabilityManager statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "total_adapters": len(self._adapters),
            "enabled_adapters": len(self.list_enabled_adapters()),
            "primary_adapter": self._primary_adapter,
            "adapters": {
                name: {
                    "enabled": adapter.is_enabled(),
                    "type": adapter.__class__.__name__
                }
                for name, adapter in self._adapters.items()
            }
        }

    def __repr__(self) -> str:
        enabled = len(self.list_enabled_adapters())
        total = len(self._adapters)
        return (
            f"ObservabilityManager(adapters={enabled}/{total}, "
            f"primary='{self._primary_adapter}')"
        )
