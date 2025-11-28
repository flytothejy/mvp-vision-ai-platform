"""
Split Configuration Resolution Utility

Implements the 3-Level Priority System for dataset split resolution:
- Priority 1: Job-Level Override (TrainingJob.split_strategy)
- Priority 2: Dataset-Level Metadata (Labeler's annotations.json)
- Priority 3: Runtime Auto-Split (80/20, seed=42)

Reference: platform/docs/architecture/SPLIT_INTEGRATION_DESIGN.md
"""

import json
import logging
from typing import Optional, Dict, Any
import httpx

from app.clients.labeler_client import labeler_client
from app.utils.dual_storage import dual_storage

logger = logging.getLogger(__name__)


async def load_annotations_from_r2(annotations_path: str) -> Dict[str, Any]:
    """
    Load annotations.json from R2 storage.

    Args:
        annotations_path: R2 path to annotations file
                         e.g., "datasets/dataset_abc123/annotations_classification.json"

    Returns:
        Parsed annotations dictionary

    Raises:
        Exception: If file not found or parsing fails
    """
    try:
        # Load from R2 via dual_storage
        content = dual_storage.get_file_content(annotations_path)
        annotations = json.loads(content.decode('utf-8'))
        return annotations
    except Exception as e:
        logger.error(f"Failed to load annotations from {annotations_path}: {e}")
        raise


def calculate_split_statistics(split_config: Dict[str, Any]) -> Dict[str, int]:
    """
    Calculate split statistics from split configuration.

    Args:
        split_config: Split configuration dict with "splits" key

    Returns:
        Statistics dict with counts per split
        Example: {"train": 800, "val": 200, "test": 0}
    """
    splits = split_config.get("splits", {})
    stats = {"train": 0, "val": 0, "test": 0}

    for img_id, split_name in splits.items():
        if split_name in stats:
            stats[split_name] += 1

    return stats


async def resolve_split_configuration(
    dataset_id: str,
    job_split_strategy: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Resolve split configuration using 3-Level Priority System.

    Priority 1: Job-Level Override (TrainingJob.split_strategy)
        ↓ (if None or method="use_default")
    Priority 2: Dataset-Level Metadata (Labeler annotations.json)
        ↓ (if None)
    Priority 3: Runtime Auto-Split (80/20, seed=42)

    Args:
        dataset_id: Labeler dataset UUID
        job_split_strategy: Optional job-level split override from TrainingJob

    Returns:
        Resolved split configuration dict with source information:
        {
            "source": "job_override" | "dataset_default" | "auto",
            "method": "auto" | "manual",
            "ratio": [0.8, 0.2],
            "seed": 42,
            "splits": {...}  # if manual method
        }

    Example Usage:
        # Priority 1: Custom 70/30 split
        resolved = await resolve_split_configuration(
            "dataset_123",
            {"method": "auto", "ratio": [0.7, 0.3], "seed": 99}
        )
        # Returns: {"source": "job_override", "method": "auto", ...}

        # Priority 2: Use dataset default
        resolved = await resolve_split_configuration(
            "dataset_123",
            None  # or {"method": "use_default"}
        )
        # Returns: {"source": "dataset_default", ...}

        # Priority 3: Auto-fallback
        resolved = await resolve_split_configuration(
            "dataset_without_split",
            None
        )
        # Returns: {"source": "auto", "method": "auto", "ratio": [0.8, 0.2], ...}
    """

    # Priority 1: Job-Level Override
    if job_split_strategy is not None:
        method = job_split_strategy.get("method")

        # Check if explicitly requesting dataset default
        # Handle both "use_dataset" (schema) and "use_default" (design doc) naming
        if method in ("use_dataset", "use_default"):
            logger.info("[SPLIT] Job explicitly requested dataset default, falling to Priority 2")
        else:
            # Custom split strategy provided
            logger.info(f"[SPLIT] Priority 1: Using job-level override (method={method})")

            # Normalize "custom" to "manual" for internal consistency
            normalized_strategy = job_split_strategy.copy()
            if method == "custom":
                normalized_strategy["method"] = "manual"
                # Rename custom_splits to splits if present
                if "custom_splits" in normalized_strategy:
                    normalized_strategy["splits"] = normalized_strategy.pop("custom_splits")

            return {
                "source": "job_override",
                **normalized_strategy
            }

    # Priority 2: Dataset-Level Metadata (from Labeler)
    try:
        logger.info(f"[SPLIT] Priority 2: Querying Labeler for dataset {dataset_id} default split")

        # Get dataset metadata from Labeler
        dataset = await labeler_client.get_dataset(dataset_id)
        task_type = dataset.get('task_type', 'classification')

        # Construct annotations path
        storage_path = dataset['storage_path']  # e.g., "datasets/dataset_abc123"
        annotations_path = f"{storage_path}/annotations_{task_type}.json"

        # Load annotations from R2
        annotations = await load_annotations_from_r2(annotations_path)

        # Check for split_config
        split_config = annotations.get('split_config')

        if split_config:
            logger.info("[SPLIT] Found dataset default split configuration")
            stats = calculate_split_statistics(split_config)
            logger.info(f"[SPLIT] Split statistics: {stats}")

            return {
                "source": "dataset_default",
                **split_config
            }
        else:
            logger.info("[SPLIT] No split_config found in annotations.json")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.warning(f"[SPLIT] Dataset {dataset_id} not found in Labeler")
        elif e.response.status_code == 403:
            logger.warning(f"[SPLIT] Permission denied for dataset {dataset_id}")
        else:
            logger.warning(f"[SPLIT] Labeler API error: {e}")
    except Exception as e:
        logger.warning(f"[SPLIT] Failed to get dataset default split: {e}")

    # Priority 3: Runtime Auto-Split (fallback)
    logger.info("[SPLIT] Priority 3: Using auto-split fallback (80/20)")
    return {
        "source": "auto",
        "method": "auto",
        "ratio": [0.8, 0.2],
        "seed": 42
    }


def validate_split_strategy(split_strategy: Optional[Dict[str, Any]]) -> bool:
    """
    Validate split strategy dictionary.

    Args:
        split_strategy: Split strategy to validate

    Returns:
        True if valid, raises ValueError if invalid

    Raises:
        ValueError: If split strategy is invalid
    """
    if split_strategy is None:
        return True

    if not isinstance(split_strategy, dict):
        raise ValueError("split_strategy must be a dictionary")

    method = split_strategy.get("method")
    if method not in ["auto", "manual", "use_default"]:
        raise ValueError(f"Invalid method: {method}. Must be 'auto', 'manual', or 'use_default'")

    if method == "auto":
        ratio = split_strategy.get("ratio")
        if ratio is None:
            raise ValueError("'auto' method requires 'ratio' field")
        if not isinstance(ratio, list) or len(ratio) < 2:
            raise ValueError("'ratio' must be a list with at least 2 elements")
        if not all(isinstance(r, (int, float)) for r in ratio):
            raise ValueError("'ratio' must contain numbers")
        if not (0.99 <= sum(ratio) <= 1.01):  # Allow small floating-point errors
            raise ValueError(f"'ratio' must sum to 1.0, got {sum(ratio)}")

    if method == "manual":
        splits = split_strategy.get("splits")
        if not splits:
            raise ValueError("'manual' method requires 'splits' dictionary")
        if not isinstance(splits, dict):
            raise ValueError("'splits' must be a dictionary")

    return True


def generate_auto_split(
    images: list,
    ratio: list,
    seed: int = 42
) -> Dict[str, str]:
    """
    Generate automatic split assignments.

    Args:
        images: List of image dicts with 'id' field
        ratio: Split ratios (e.g., [0.8, 0.2] or [0.7, 0.2, 0.1])
        seed: Random seed for reproducibility

    Returns:
        Split assignments dict: {image_id: "train"|"val"|"test"}

    Example:
        images = [{"id": "img_001"}, {"id": "img_002"}, ...]
        splits = generate_auto_split(images, [0.8, 0.2], seed=42)
        # Returns: {"img_001": "train", "img_002": "val", ...}
    """
    import random
    random.seed(seed)

    # Shuffle image IDs
    image_ids = [str(img['id']) for img in images]
    shuffled = image_ids.copy()
    random.shuffle(shuffled)

    # Calculate split indices
    num_images = len(shuffled)
    split_names = ["train", "val", "test"]
    splits = {}

    cumulative_ratio = 0
    start_idx = 0

    for i, r in enumerate(ratio):
        cumulative_ratio += r
        end_idx = int(num_images * cumulative_ratio)

        # Assign split
        split_name = split_names[i] if i < len(split_names) else "test"
        for img_id in shuffled[start_idx:end_idx]:
            splits[img_id] = split_name

        start_idx = end_idx

    # Handle any remaining images (due to rounding)
    for img_id in shuffled[start_idx:]:
        splits[img_id] = split_names[-1] if ratio else "test"

    logger.info(f"[SPLIT] Generated auto-split: {calculate_split_statistics({'splits': splits})}")
    return splits


def validate_manual_split(
    images: list,
    splits: Dict[str, str]
) -> Dict[str, str]:
    """
    Validate manual split assignments.

    Args:
        images: List of image dicts with 'id' field
        splits: Manual split assignments {image_id: "train"|"val"|"test"}

    Returns:
        Validated splits (same as input if valid)

    Raises:
        ValueError: If split assignments are invalid
    """
    image_ids = {str(img['id']) for img in images}
    split_ids = set(splits.keys())

    # Check for missing images
    missing = image_ids - split_ids
    if missing:
        logger.warning(f"[SPLIT] {len(missing)} images have no split assignment (will use 'train')")

    # Check for unknown images
    unknown = split_ids - image_ids
    if unknown:
        logger.warning(f"[SPLIT] {len(unknown)} split assignments for unknown images (will be ignored)")

    # Validate split values
    valid_splits = {"train", "val", "test"}
    for img_id, split_name in splits.items():
        if split_name not in valid_splits:
            raise ValueError(f"Invalid split name '{split_name}' for image '{img_id}'. Must be one of: {valid_splits}")

    return splits
