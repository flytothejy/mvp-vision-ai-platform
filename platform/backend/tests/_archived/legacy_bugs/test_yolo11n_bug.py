"""
Test for yolo11n → yolov8n bug fix.

This test ensures that when a user selects yolo11n, it is correctly saved
to the database as yolo11n (not yolov8n).

Related Issue: Frontend useEffect was resetting model_name based on hardcoded array.
"""

import pytest
from app.db.models import TrainingJob


class TestYolo11nBugFix:
    """Test yolo11n model selection and persistence."""

    def test_yolo11n_job_creation(self, client, sample_training_config):
        """Test that yolo11n is correctly saved to database."""
        # Arrange: Use yolo11n in config
        config = sample_training_config.copy()
        config["model_name"] = "yolo11n"

        # Act: Create training job
        response = client.post(
            "/api/v1/training/jobs",
            json={"config": config}
        )

        # Assert: Job created successfully
        assert response.status_code == 200
        job_data = response.json()

        # Assert: model_name is yolo11n (NOT yolov8n)
        assert job_data["model_name"] == "yolo11n", \
            f"Expected 'yolo11n' but got '{job_data['model_name']}'"
        assert job_data["framework"] == "ultralytics"
        assert job_data["task_type"] == "object_detection"

    def test_yolo11m_job_creation(self, client, sample_training_config):
        """Test that yolo11m is correctly saved to database."""
        # Arrange: Use yolo11m in config
        config = sample_training_config.copy()
        config["model_name"] = "yolo11m"

        # Act: Create training job
        response = client.post(
            "/api/v1/training/jobs",
            json={"config": config}
        )

        # Assert
        assert response.status_code == 200
        job_data = response.json()
        assert job_data["model_name"] == "yolo11m"

    def test_yolo11l_job_creation(self, client, sample_training_config):
        """Test that yolo11l is correctly saved to database."""
        # Arrange: Use yolo11l in config
        config = sample_training_config.copy()
        config["model_name"] = "yolo11l"

        # Act: Create training job
        response = client.post(
            "/api/v1/training/jobs",
            json={"config": config}
        )

        # Assert
        assert response.status_code == 200
        job_data = response.json()
        assert job_data["model_name"] == "yolo11l"

    def test_yolo8_models_still_work(self, client, sample_training_config):
        """Test that yolov8 models are not affected by the fix."""
        # Test yolov8n, yolov8s, yolov8m
        for model_name in ["yolov8n", "yolov8s", "yolov8m"]:
            config = sample_training_config.copy()
            config["model_name"] = model_name

            response = client.post(
                "/api/v1/training/jobs",
                json={"config": config}
            )

            assert response.status_code == 200
            job_data = response.json()
            assert job_data["model_name"] == model_name

    def test_database_persistence(self, client, db_session, sample_training_config):
        """Test that yolo11n is correctly persisted to database."""
        # Arrange
        config = sample_training_config.copy()
        config["model_name"] = "yolo11n"

        # Act: Create job via API
        response = client.post(
            "/api/v1/training/jobs",
            json={"config": config}
        )
        assert response.status_code == 200
        job_id = response.json()["id"]

        # Assert: Query database directly
        db_job = db_session.query(TrainingJob).filter(TrainingJob.id == job_id).first()
        assert db_job is not None
        assert db_job.model_name == "yolo11n", \
            f"DB contains '{db_job.model_name}' instead of 'yolo11n'"
