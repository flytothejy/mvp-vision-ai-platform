"""Pytest configuration and fixtures."""

import os
import sys
from pathlib import Path

# Set minimal environment variables for testing BEFORE importing app modules
os.environ.setdefault("GOOGLE_API_KEY", "test_google_api_key_for_testing")
os.environ.setdefault("JWT_SECRET", "test_jwt_secret_for_testing")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")  # Use different DB for tests
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test_access_key")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test_secret_key")
os.environ.setdefault("S3_ENDPOINT", "http://localhost:9000")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.db.database import Base, get_db
from app.main import app


# Test database
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database for each test."""
    # Create tables
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        # Drop tables after test
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client with database dependency override."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    test_client = TestClient(app)
    yield test_client
    test_client.close()

    # Clear overrides
    app.dependency_overrides.clear()


@pytest.fixture
def sample_training_config():
    """Sample training configuration for tests."""
    return {
        "framework": "ultralytics",
        "model_name": "yolo11n",
        "task_type": "object_detection",
        "dataset_path": "C:\\datasets\\det-coco8",
        "dataset_format": "yolo",
        "num_classes": 80,
        "epochs": 5,
        "batch_size": 16,
        "learning_rate": 0.01,
    }


@pytest.fixture
def sample_image_path(tmp_path):
    """Create a sample test image."""
    from PIL import Image
    import numpy as np

    # Create a simple test image
    img = Image.fromarray(np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8))
    img_path = tmp_path / "test_image.jpg"
    img.save(img_path)

    return str(img_path)


@pytest.fixture
def sample_image_batch(tmp_path):
    """Create multiple test images for batch inference."""
    from PIL import Image
    import numpy as np

    image_paths = []
    for i in range(3):
        img = Image.fromarray(np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8))
        img_path = tmp_path / f"test_image_{i}.jpg"
        img.save(img_path)
        image_paths.append(str(img_path))

    return image_paths


@pytest.fixture
def api_url():
    """Base API URL for E2E tests."""
    return os.getenv("API_URL", "http://localhost:8000/api/v1")


@pytest.fixture(scope="function")
async def redis_manager():
    """Create a RedisManager instance for testing.

    Uses Redis DB 15 for tests (separate from production).
    Flushes the test database before and after each test.
    """
    from app.services.redis_manager import RedisManager

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/15")
    manager = RedisManager(redis_url=redis_url)

    try:
        await manager.connect()
        await manager.flushdb()  # Clean before test
        yield manager
    finally:
        await manager.flushdb()  # Clean after test
        await manager.close()


@pytest.fixture(scope="function", autouse=True)
def mock_model_capabilities(monkeypatch):
    """
    Mock dual_storage.get_capabilities() to return sample model capabilities.

    This is autouse=True so all tests automatically get mocked capabilities
    without needing to call Training Services.
    """
    import json

    # Sample capabilities for ultralytics
    ultralytics_capabilities = {
        "framework": "ultralytics",
        "models": [
            {
                "model_name": "yolo11n",
                "display_name": "YOLOv11 Nano",
                "task_types": ["object_detection"],
                "pretrained_available": True,
                "status": "active"
            },
            {
                "model_name": "yolo11m",
                "display_name": "YOLOv11 Medium",
                "task_types": ["object_detection"],
                "pretrained_available": True,
                "status": "active"
            },
            {
                "model_name": "yolo11l",
                "display_name": "YOLOv11 Large",
                "task_types": ["object_detection"],
                "pretrained_available": True,
                "status": "active"
            }
        ],
        "task_types": ["object_detection", "instance_segmentation", "pose_estimation"]
    }

    # Sample capabilities for timm
    timm_capabilities = {
        "framework": "timm",
        "models": [
            {
                "model_name": "resnet50",
                "display_name": "ResNet-50",
                "task_types": ["classification"],
                "pretrained_available": True,
                "status": "active"
            }
        ],
        "task_types": ["classification"]
    }

    def mock_get_capabilities(framework: str):
        """Mock get_capabilities to return sample data."""
        if framework == "ultralytics":
            return json.dumps(ultralytics_capabilities).encode('utf-8')
        elif framework == "timm":
            return json.dumps(timm_capabilities).encode('utf-8')
        elif framework == "huggingface":
            return None  # Not implemented yet
        else:
            return None

    # Patch dual_storage.get_capabilities
    from app.utils import dual_storage as ds_module
    monkeypatch.setattr(ds_module.dual_storage, "get_capabilities", mock_get_capabilities)

    yield

    # Cleanup happens automatically with monkeypatch
