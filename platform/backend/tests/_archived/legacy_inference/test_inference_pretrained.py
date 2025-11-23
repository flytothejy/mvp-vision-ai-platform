"""
Test pretrained model inference.

This script tests that all active pretrained models can successfully
run inference on sample images.

Priority: P2 (Critical for production readiness)

Usage:
    # Run in training environment (with framework dependencies installed)
    cd mvp/training
    python -m pytest ../backend/tests/integration/test_inference_pretrained.py -v -s
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


@pytest.fixture
def sample_images_batch(tmp_path):
    """Create a batch of sample test images."""
    from PIL import Image

    image_paths = []
    for i in range(3):
        img_array = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
        img = Image.fromarray(img_array)

        img_path = tmp_path / f"test_image_{i}.jpg"
        img.save(img_path)
        image_paths.append(str(img_path))

    return image_paths


# ============================================================
# Ultralytics Models (5 models)
# ============================================================

@pytest.mark.slow
@pytest.mark.skipif(
    not _is_ultralytics_available(),
    reason="ultralytics not installed"
)
class TestUltralyticsInference:
    """Test Ultralytics pretrained model inference."""

    def test_yolo11n_detection_inference(self, sample_image):
        """Test YOLO11n detection inference."""
        from ultralytics import YOLO

        print("\n[TEST] Running YOLO11n detection inference...")
        model = YOLO("yolo11n.pt")

        # Run inference
        results = model(sample_image, verbose=False)

        assert results is not None
        assert len(results) == 1

        # Check results structure
        result = results[0]
        assert hasattr(result, "boxes")
        assert hasattr(result, "names")

        print(f"[OK] YOLO11n detection inference successful")
        print(f"     Detected {len(result.boxes)} objects")

    def test_yolo11n_seg_inference(self, sample_image):
        """Test YOLO11n-seg instance segmentation inference."""
        from ultralytics import YOLO

        print("\n[TEST] Running YOLO11n-seg segmentation inference...")
        model = YOLO("yolo11n-seg.pt")

        results = model(sample_image, verbose=False)

        assert results is not None
        assert len(results) == 1

        result = results[0]
        assert hasattr(result, "boxes")
        assert hasattr(result, "masks")

        print(f"[OK] YOLO11n-seg inference successful")

    def test_yolo11n_pose_inference(self, sample_image):
        """Test YOLO11n-pose keypoint detection inference."""
        from ultralytics import YOLO

        print("\n[TEST] Running YOLO11n-pose inference...")
        model = YOLO("yolo11n-pose.pt")

        results = model(sample_image, verbose=False)

        assert results is not None
        assert len(results) == 1

        result = results[0]
        assert hasattr(result, "keypoints")

        print(f"[OK] YOLO11n-pose inference successful")

    def test_yolo_world_v2_inference(self, sample_image):
        """Test YOLO-World v2 zero-shot detection inference."""
        from ultralytics import YOLO

        print("\n[TEST] Running YOLO-World v2 inference...")
        model = YOLO("yolov8s-worldv2.pt")

        # Set custom classes for zero-shot detection
        model.set_classes(["person", "car", "dog"])

        results = model(sample_image, verbose=False)

        assert results is not None
        assert len(results) == 1

        print(f"[OK] YOLO-World v2 inference successful")

    def test_sam2_inference(self, sample_image):
        """Test SAM2 zero-shot segmentation inference."""
        from ultralytics import SAM

        print("\n[TEST] Running SAM2 inference...")
        model = SAM("sam2_t.pt")

        results = model(sample_image, verbose=False)

        assert results is not None
        assert len(results) == 1

        print(f"[OK] SAM2 inference successful")

    def test_batch_inference(self, sample_images_batch):
        """Test batch inference with multiple images."""
        from ultralytics import YOLO

        print("\n[TEST] Running batch inference...")
        model = YOLO("yolo11n.pt")

        results = model(sample_images_batch, verbose=False)

        assert results is not None
        assert len(results) == len(sample_images_batch)

        print(f"[OK] Batch inference successful ({len(results)} images)")


# ============================================================
# TIMM Models (3 models)
# ============================================================

@pytest.mark.slow
@pytest.mark.skipif(
    not _is_timm_available(),
    reason="timm not installed"
)
class TestTIMMInference:
    """Test TIMM pretrained model inference."""

    def test_efficientnetv2_inference(self, sample_image):
        """Test EfficientNetV2-S classification inference."""
        import timm
        import torch
        from PIL import Image
        from timm.data import resolve_data_config
        from timm.data.transforms_factory import create_transform

        print("\n[TEST] Running EfficientNetV2-S inference...")
        model = timm.create_model("tf_efficientnetv2_s.in1k", pretrained=True)
        model.eval()

        # Prepare image
        config = resolve_data_config({}, model=model)
        transform = create_transform(**config)

        img = Image.open(sample_image).convert("RGB")
        img_tensor = transform(img).unsqueeze(0)

        # Run inference
        with torch.no_grad():
            output = model(img_tensor)

        assert output is not None
        assert output.shape[0] == 1
        assert output.shape[1] == 1000  # ImageNet classes

        # Get top prediction
        probs = torch.softmax(output, dim=1)
        top_prob, top_class = torch.max(probs, dim=1)

        print(f"[OK] EfficientNetV2-S inference successful")
        print(f"     Top class: {top_class.item()}, Confidence: {top_prob.item():.4f}")

    def test_convnext_inference(self, sample_image):
        """Test ConvNeXt Tiny classification inference."""
        import timm
        import torch
        from PIL import Image
        from timm.data import resolve_data_config
        from timm.data.transforms_factory import create_transform

        print("\n[TEST] Running ConvNeXt Tiny inference...")
        model = timm.create_model("convnext_tiny.in12k_ft_in1k", pretrained=True)
        model.eval()

        config = resolve_data_config({}, model=model)
        transform = create_transform(**config)

        img = Image.open(sample_image).convert("RGB")
        img_tensor = transform(img).unsqueeze(0)

        with torch.no_grad():
            output = model(img_tensor)

        assert output is not None
        assert output.shape[0] == 1
        assert output.shape[1] == 1000

        probs = torch.softmax(output, dim=1)
        top_prob, top_class = torch.max(probs, dim=1)

        print(f"[OK] ConvNeXt Tiny inference successful")
        print(f"     Top class: {top_class.item()}, Confidence: {top_prob.item():.4f}")

    def test_vit_inference(self, sample_image):
        """Test Vision Transformer Base inference."""
        import timm
        import torch
        from PIL import Image
        from timm.data import resolve_data_config
        from timm.data.transforms_factory import create_transform

        print("\n[TEST] Running ViT-Base inference...")
        model = timm.create_model("vit_base_patch16_224.augreg_in21k_ft_in1k", pretrained=True)
        model.eval()

        config = resolve_data_config({}, model=model)
        transform = create_transform(**config)

        img = Image.open(sample_image).convert("RGB")
        img_tensor = transform(img).unsqueeze(0)

        with torch.no_grad():
            output = model(img_tensor)

        assert output is not None
        assert output.shape[0] == 1
        assert output.shape[1] == 1000

        probs = torch.softmax(output, dim=1)
        top_prob, top_class = torch.max(probs, dim=1)

        print(f"[OK] ViT-Base inference successful")
        print(f"     Top class: {top_class.item()}, Confidence: {top_prob.item():.4f}")


# ============================================================
# HuggingFace Models (2 models)
# ============================================================

@pytest.mark.slow
@pytest.mark.skipif(
    not _is_transformers_available(),
    reason="transformers not installed"
)
class TestHuggingFaceInference:
    """Test HuggingFace pretrained model inference."""

    def test_segformer_inference(self, sample_image):
        """Test SegFormer-B0 semantic segmentation inference."""
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
        from PIL import Image
        import torch

        print("\n[TEST] Running SegFormer-B0 inference...")
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

        # Get segmentation map
        logits = outputs.logits
        assert logits is not None
        assert len(logits.shape) == 4  # [batch, classes, height, width]

        # Upsample to original image size
        upsampled_logits = torch.nn.functional.interpolate(
            logits,
            size=img.size[::-1],
            mode="bilinear",
            align_corners=False
        )

        pred_seg = upsampled_logits.argmax(dim=1)[0]

        print(f"[OK] SegFormer-B0 inference successful")
        print(f"     Segmentation map shape: {pred_seg.shape}")
        print(f"     Unique classes: {torch.unique(pred_seg).numel()}")

    def test_swin2sr_inference(self, sample_image):
        """Test Swin2SR super-resolution inference."""
        from transformers import Swin2SRForImageSuperResolution, Swin2SRImageProcessor
        from PIL import Image
        import torch

        print("\n[TEST] Running Swin2SR inference...")
        model = Swin2SRForImageSuperResolution.from_pretrained(
            "caidas/swin2SR-classical-sr-x2-64"
        )
        processor = Swin2SRImageProcessor.from_pretrained(
            "caidas/swin2SR-classical-sr-x2-64"
        )

        img = Image.open(sample_image).convert("RGB")
        # Resize to smaller size for faster testing
        img = img.resize((128, 128))

        inputs = processor(images=img, return_tensors="pt")

        with torch.no_grad():
            outputs = model(**inputs)

        # Get reconstructed image
        output_tensor = outputs.reconstruction
        assert output_tensor is not None

        # Swin2SR processor pads the input, then upscales by 2x
        # Check that output is approximately 2x the processed input size
        processed_size = inputs.pixel_values.shape[2]
        actual_output_size = output_tensor.shape[2]

        # Output should be 2x the processed input (after padding)
        expected_output = processed_size * 2
        assert actual_output_size == expected_output, \
            f"Expected {expected_output} (2x processed), got {actual_output_size}"

        print(f"[OK] Swin2SR inference successful")
        print(f"     Original input: {img.size}")
        print(f"     Processed input: {processed_size}x{processed_size}")
        print(f"     Output size: {actual_output_size}x{actual_output_size}")
        print(f"     Upscaling ratio: 2x (of processed input)")


# ============================================================
# Summary Test
# ============================================================

@pytest.mark.slow
def test_inference_summary():
    """Summary of inference tests."""
    print("\n" + "=" * 80)
    print("INFERENCE TEST SUMMARY")
    print("=" * 80)
    print("\nTarget: 10 models across 3 frameworks")
    print("\nFrameworks:")
    print("  - Ultralytics: 5 models + batch inference")
    print("  - TIMM: 3 models")
    print("  - HuggingFace: 2 models")
    print("\nNote: All inference tests use randomly generated sample images")
    print("=" * 80)
