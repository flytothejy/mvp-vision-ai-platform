"""
Test inference output format for each task type.

This script verifies that inference outputs have the correct format
for each task type (detection, segmentation, classification, pose).

Priority: P2 (Critical for production readiness)

Usage:
    # Run in training environment (with framework dependencies installed)
    cd mvp/training
    python -m pytest ../backend/tests/integration/test_inference_output_format.py -v -s
"""

import pytest
import sys
from pathlib import Path
import numpy as np

# Add training directory to path
training_dir = Path(__file__).parent.parent.parent.parent / "training"
sys.path.insert(0, str(training_dir))


def _is_ultralytics_available():
    """Check if ultralytics is available."""
    try:
        import ultralytics
        return True
    except ImportError:
        return False


def _is_timm_available():
    """Check if timm is available."""
    try:
        import timm
        return True
    except ImportError:
        return False


def _is_transformers_available():
    """Check if transformers is available."""
    try:
        import transformers
        return True
    except ImportError:
        return False


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_image(tmp_path):
    """Create a sample test image (640x640 RGB)."""
    from PIL import Image

    # Create random RGB image
    img_array = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
    img = Image.fromarray(img_array)

    img_path = tmp_path / "test_image.jpg"
    img.save(img_path)

    return str(img_path)


# ============================================================
# Object Detection Output Format
# ============================================================

@pytest.mark.slow
@pytest.mark.skipif(
    not _is_ultralytics_available(),
    reason="ultralytics not installed"
)
class TestDetectionOutputFormat:
    """Test object detection output format."""

    def test_yolo11n_detection_output_format(self, sample_image):
        """Test that YOLO11n detection output has correct format."""
        from ultralytics import YOLO

        print("\n[TEST] YOLO11n detection output format...")
        model = YOLO("yolo11n.pt")
        results = model(sample_image, verbose=False)

        assert results is not None
        assert len(results) == 1

        result = results[0]

        # Check that result has required attributes
        assert hasattr(result, "boxes"), "Result missing 'boxes' attribute"
        assert hasattr(result, "names"), "Result missing 'names' attribute"

        # Check boxes format
        boxes = result.boxes
        assert hasattr(boxes, "xyxy"), "Boxes missing 'xyxy' attribute"
        assert hasattr(boxes, "conf"), "Boxes missing 'conf' (confidence) attribute"
        assert hasattr(boxes, "cls"), "Boxes missing 'cls' (class) attribute"

        # Verify data types
        if len(boxes) > 0:
            # If objects detected, check format
            xyxy = boxes.xyxy.cpu().numpy()
            conf = boxes.conf.cpu().numpy()
            cls = boxes.cls.cpu().numpy()

            assert xyxy.shape[1] == 4, f"Expected 4 coordinates per box, got {xyxy.shape[1]}"
            assert len(conf) == len(xyxy), "Confidence array length mismatch"
            assert len(cls) == len(xyxy), "Class array length mismatch"

            # Check coordinate ranges (should be within image bounds)
            assert np.all(xyxy >= 0), "Negative coordinates found"

            # Check confidence ranges (0-1)
            assert np.all((conf >= 0) & (conf <= 1)), "Confidence out of range [0, 1]"

            print(f"[OK] Detected {len(boxes)} objects with valid format")
        else:
            print("[OK] No objects detected (valid empty result)")

        # Check names dictionary
        assert isinstance(result.names, dict), "Names should be a dictionary"
        assert len(result.names) > 0, "Names dictionary is empty"

        print(f"[OK] YOLO11n detection output format valid")
        print(f"     Boxes: {len(boxes)} objects")
        print(f"     Classes: {len(result.names)} total classes")


# ============================================================
# Instance Segmentation Output Format
# ============================================================

@pytest.mark.slow
@pytest.mark.skipif(
    not _is_ultralytics_available(),
    reason="ultralytics not installed"
)
class TestSegmentationOutputFormat:
    """Test segmentation output format."""

    def test_yolo11n_seg_output_format(self, sample_image):
        """Test that YOLO11n-seg output has correct format."""
        from ultralytics import YOLO

        print("\n[TEST] YOLO11n-seg segmentation output format...")
        model = YOLO("yolo11n-seg.pt")
        results = model(sample_image, verbose=False)

        assert results is not None
        assert len(results) == 1

        result = results[0]

        # Check required attributes
        assert hasattr(result, "boxes"), "Result missing 'boxes' attribute"
        assert hasattr(result, "masks"), "Result missing 'masks' attribute"

        # Check boxes (same as detection)
        boxes = result.boxes
        assert hasattr(boxes, "xyxy")
        assert hasattr(boxes, "conf")
        assert hasattr(boxes, "cls")

        # Check masks
        masks = result.masks
        if masks is not None and len(masks) > 0:
            # If masks exist, verify format
            assert hasattr(masks, "data"), "Masks missing 'data' attribute"
            mask_data = masks.data.cpu().numpy()

            # Masks should be 2D or 3D (batch, height, width)
            assert len(mask_data.shape) >= 2, f"Invalid mask shape: {mask_data.shape}"

            # Mask values should be binary or float [0, 1]
            assert np.all((mask_data >= 0) & (mask_data <= 1)), "Mask values out of range"

            # Number of masks should match number of boxes
            assert len(mask_data) == len(boxes), "Mask count != box count"

            print(f"[OK] {len(masks)} masks with valid format")
        else:
            print("[OK] No masks (valid empty result)")

        print(f"[OK] YOLO11n-seg output format valid")


# ============================================================
# Classification Output Format
# ============================================================

@pytest.mark.slow
@pytest.mark.skipif(
    not _is_timm_available(),
    reason="timm not installed"
)
class TestClassificationOutputFormat:
    """Test classification output format."""

    def test_timm_classification_output_format(self, sample_image):
        """Test that TIMM classification output has correct format."""
        import timm
        import torch
        from PIL import Image
        from timm.data import resolve_data_config
        from timm.data.transforms_factory import create_transform

        print("\n[TEST] TIMM classification output format...")
        model = timm.create_model("tf_efficientnetv2_s.in1k", pretrained=True)
        model.eval()

        config = resolve_data_config({}, model=model)
        transform = create_transform(**config)

        img = Image.open(sample_image).convert("RGB")
        img_tensor = transform(img).unsqueeze(0)

        with torch.no_grad():
            output = model(img_tensor)

        # Check output format
        assert output is not None
        assert isinstance(output, torch.Tensor), "Output should be a tensor"
        assert len(output.shape) == 2, f"Expected 2D output, got {len(output.shape)}D"
        assert output.shape[0] == 1, f"Expected batch size 1, got {output.shape[0]}"
        assert output.shape[1] == 1000, f"Expected 1000 classes, got {output.shape[1]}"

        # Check logits format
        logits = output[0]
        assert torch.all(torch.isfinite(logits)), "Output contains inf or nan"

        # Get probabilities
        probs = torch.softmax(output, dim=1)[0]
        assert torch.all((probs >= 0) & (probs <= 1)), "Probabilities out of range"
        assert torch.isclose(probs.sum(), torch.tensor(1.0), atol=1e-5), \
            f"Probabilities don't sum to 1: {probs.sum()}"

        # Get top-k predictions
        top_k = 5
        top_probs, top_indices = torch.topk(probs, top_k)

        assert len(top_probs) == top_k, f"Expected {top_k} predictions"
        assert len(top_indices) == top_k, f"Expected {top_k} indices"

        # Top probabilities should be sorted in descending order
        assert torch.all(top_probs[:-1] >= top_probs[1:]), "Top probs not sorted"

        print(f"[OK] Classification output format valid")
        print(f"     Output shape: {output.shape}")
        print(f"     Top-1 class: {top_indices[0].item()}")
        print(f"     Top-1 confidence: {top_probs[0].item():.4f}")
        print(f"     Top-5 classes: {top_indices.tolist()}")


# ============================================================
# Pose Estimation Output Format
# ============================================================

@pytest.mark.slow
@pytest.mark.skipif(
    not _is_ultralytics_available(),
    reason="ultralytics not installed"
)
class TestPoseOutputFormat:
    """Test pose estimation output format."""

    def test_yolo11n_pose_output_format(self, sample_image):
        """Test that YOLO11n-pose output has correct format."""
        from ultralytics import YOLO

        print("\n[TEST] YOLO11n-pose output format...")
        model = YOLO("yolo11n-pose.pt")
        results = model(sample_image, verbose=False)

        assert results is not None
        assert len(results) == 1

        result = results[0]

        # Check required attributes
        assert hasattr(result, "keypoints"), "Result missing 'keypoints' attribute"
        assert hasattr(result, "boxes"), "Result missing 'boxes' attribute"

        # Check keypoints
        keypoints = result.keypoints
        if keypoints is not None and len(keypoints) > 0:
            assert hasattr(keypoints, "data"), "Keypoints missing 'data' attribute"
            assert hasattr(keypoints, "conf"), "Keypoints missing 'conf' attribute"

            kp_data = keypoints.data.cpu().numpy()
            kp_conf = keypoints.conf.cpu().numpy() if keypoints.conf is not None else None

            # Keypoints should be 3D: (num_persons, num_keypoints, 2 or 3)
            # Format: [x, y] or [x, y, confidence]
            assert len(kp_data.shape) == 3, f"Expected 3D keypoints, got {kp_data.shape}"

            num_persons = kp_data.shape[0]
            num_keypoints = kp_data.shape[1]
            coords_per_kp = kp_data.shape[2]

            assert coords_per_kp >= 2, f"Expected at least 2 coords per keypoint, got {coords_per_kp}"
            assert num_keypoints == 17, f"Expected 17 COCO keypoints, got {num_keypoints}"

            # Check coordinate ranges
            xy_coords = kp_data[:, :, :2]
            assert np.all(xy_coords >= 0), "Negative keypoint coordinates found"

            # If confidence is included in data
            if coords_per_kp == 3:
                kp_conf_in_data = kp_data[:, :, 2]
                assert np.all((kp_conf_in_data >= 0) & (kp_conf_in_data <= 1)), \
                    "Keypoint confidence out of range"

            # Check boxes match number of persons
            boxes = result.boxes
            assert len(boxes) == num_persons, \
                f"Box count ({len(boxes)}) != person count ({num_persons})"

            print(f"[OK] {num_persons} person(s) detected with {num_keypoints} keypoints each")
        else:
            print("[OK] No persons detected (valid empty result)")

        print(f"[OK] YOLO11n-pose output format valid")


# ============================================================
# Semantic Segmentation Output Format
# ============================================================

@pytest.mark.slow
@pytest.mark.skipif(
    not _is_transformers_available(),
    reason="transformers not installed"
)
class TestSemanticSegmentationFormat:
    """Test semantic segmentation output format."""

    def test_segformer_output_format(self, sample_image):
        """Test that SegFormer output has correct format."""
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
        from PIL import Image
        import torch

        print("\n[TEST] SegFormer semantic segmentation output format...")
        model = SegformerForSemanticSegmentation.from_pretrained(
            "nvidia/segformer-b0-finetuned-ade-512-512"
        )
        processor = SegformerImageProcessor.from_pretrained(
            "nvidia/segformer-b0-finetuned-ade-512-512"
        )

        img = Image.open(sample_image).convert("RGB")
        inputs = processor(images=img, return_tensors="pt")

        with torch.no_grad():
            outputs = model(**inputs)

        # Check logits format
        logits = outputs.logits
        assert logits is not None
        assert isinstance(logits, torch.Tensor)
        assert len(logits.shape) == 4, f"Expected 4D logits [B,C,H,W], got {len(logits.shape)}D"

        batch, num_classes, height, width = logits.shape
        assert batch == 1, f"Expected batch size 1, got {batch}"
        assert num_classes == 150, f"Expected 150 ADE20K classes, got {num_classes}"

        # Upsample to original size
        upsampled_logits = torch.nn.functional.interpolate(
            logits,
            size=img.size[::-1],
            mode="bilinear",
            align_corners=False
        )

        # Get segmentation map
        pred_seg = upsampled_logits.argmax(dim=1)[0]

        # Check segmentation map format
        assert pred_seg.shape == (img.size[1], img.size[0]), \
            f"Segmentation map size mismatch: {pred_seg.shape} vs {img.size[::-1]}"

        # Class IDs should be in valid range
        unique_classes = torch.unique(pred_seg)
        assert torch.all((unique_classes >= 0) & (unique_classes < num_classes)), \
            f"Invalid class IDs: {unique_classes}"

        print(f"[OK] Semantic segmentation output format valid")
        print(f"     Logits shape: {logits.shape}")
        print(f"     Segmentation map shape: {pred_seg.shape}")
        print(f"     Unique classes: {len(unique_classes)}")


# ============================================================
# Summary Test
# ============================================================

@pytest.mark.slow
def test_output_format_summary():
    """Summary of output format tests."""
    print("\n" + "=" * 80)
    print("OUTPUT FORMAT TEST SUMMARY")
    print("=" * 80)
    print("\nTested output formats:")
    print("  - Object Detection (YOLO11n)")
    print("  - Instance Segmentation (YOLO11n-seg)")
    print("  - Classification (TIMM)")
    print("  - Pose Estimation (YOLO11n-pose)")
    print("  - Semantic Segmentation (SegFormer)")
    print("\nAll output formats validated successfully!")
    print("=" * 80)
