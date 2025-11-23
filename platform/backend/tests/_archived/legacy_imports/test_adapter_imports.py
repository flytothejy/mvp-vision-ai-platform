"""
Test for adapter imports and base.py availability.

Ensures that Docker container import issues are resolved.

Related Issue: ModuleNotFoundError: No module named 'adapters.base'
when running training in Docker containers.
"""

import sys
from pathlib import Path
import pytest

# Add training module to path
training_path = Path(__file__).parent.parent.parent.parent / "training"
sys.path.insert(0, str(training_path))


def _is_torch_available():
    """Check if torch is available (training environment)."""
    try:
        import torch
        return True
    except ImportError:
        return False


class TestAdapterImports:
    """Test adapter module imports."""

    def test_base_adapter_import(self):
        """Test that base adapter can be imported."""
        try:
            from platform_sdk import TrainingAdapter, InferenceResult, TaskType
            assert TrainingAdapter is not None
            assert InferenceResult is not None
            assert TaskType is not None
        except ImportError as e:
            pytest.fail(f"Failed to import base adapter: {e}")

    def test_ultralytics_adapter_import(self):
        """Test that ultralytics adapter can be imported."""
        try:
            from adapters.ultralytics_adapter import UltralyticsAdapter
            assert UltralyticsAdapter is not None
        except ImportError as e:
            pytest.fail(f"Failed to import UltralyticsAdapter: {e}")

    @pytest.mark.skipif(
        not _is_torch_available(),
        reason="torch not installed (training environment only)"
    )
    def test_timm_adapter_import(self):
        """Test that timm adapter can be imported."""
        try:
            from adapters.timm_adapter import TimmAdapter
            assert TimmAdapter is not None
        except ImportError as e:
            pytest.fail(f"Failed to import TimmAdapter: {e}")

    def test_ultralytics_adapter_uses_base(self):
        """Test that ultralytics adapter correctly inherits from base."""
        from platform_sdk import TrainingAdapter
        from adapters.ultralytics_adapter import UltralyticsAdapter

        # Assert: UltralyticsAdapter is subclass of TrainingAdapter
        assert issubclass(UltralyticsAdapter, TrainingAdapter)

    @pytest.mark.skipif(
        not _is_torch_available(),
        reason="torch not installed (training environment only)"
    )
    def test_timm_adapter_uses_base(self):
        """Test that timm adapter correctly inherits from base."""
        from platform_sdk import TrainingAdapter
        from adapters.timm_adapter import TimmAdapter

        # Assert: TimmAdapter is subclass of TrainingAdapter
        assert issubclass(TimmAdapter, TrainingAdapter)

    def test_base_adapter_has_infer_batch(self):
        """Test that base adapter has infer_batch method."""
        from platform_sdk import TrainingAdapter

        # Assert: infer_batch method exists
        assert hasattr(TrainingAdapter, 'infer_batch')
        assert callable(getattr(TrainingAdapter, 'infer_batch'))

    def test_base_adapter_has_infer_single(self):
        """Test that base adapter defines infer_single (abstract)."""
        from platform_sdk import TrainingAdapter

        # Assert: infer_single method exists (even if abstract)
        assert hasattr(TrainingAdapter, 'infer_single')

    def test_inference_result_dataclass(self):
        """Test that InferenceResult can be instantiated."""
        from platform_sdk import InferenceResult, TaskType

        # Create a sample result
        result = InferenceResult(
            image_path="/path/to/image.jpg",
            image_name="image.jpg",
            task_type=TaskType.OBJECT_DETECTION,
            inference_time_ms=100.0,
            preprocessing_time_ms=10.0,
            postprocessing_time_ms=5.0
        )

        assert result.image_name == "image.jpg"
        assert result.task_type == TaskType.OBJECT_DETECTION

    def test_task_type_enum(self):
        """Test that TaskType enum has all expected values."""
        from platform_sdk import TaskType

        # Assert: Expected task types exist
        assert hasattr(TaskType, 'IMAGE_CLASSIFICATION')
        assert hasattr(TaskType, 'OBJECT_DETECTION')
        assert hasattr(TaskType, 'INSTANCE_SEGMENTATION')
        assert hasattr(TaskType, 'POSE_ESTIMATION')
