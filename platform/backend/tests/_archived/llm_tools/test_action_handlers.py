"""
Unit tests for Action Handlers

Tests Phase 1 action handlers (Dataset, Model, Training, Inference).
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from sqlalchemy.orm import Session

from app.services.action_handlers import ActionHandlers
from app.models.conversation import (
    GeminiActionResponse,
    ActionType,
    ConversationState
)
from app.db.models import Session as SessionModel, TrainingJob


class TestDatasetHandlers:
    """Test dataset-related action handlers"""

    @pytest.fixture
    def action_handlers(self, db_session):
        """Create ActionHandlers instance"""
        return ActionHandlers(db_session)

    @pytest.fixture
    def mock_session(self):
        """Create mock session"""
        session = Mock(spec=SessionModel)
        session.id = 1
        session.state = ConversationState.INITIAL
        session.temp_data = {}
        return session

    @pytest.mark.asyncio
    async def test_handle_analyze_dataset_success(self, action_handlers, mock_session):
        """Test analyze_dataset handler with valid dataset path"""
        # Setup
        action_response = GeminiActionResponse(
            action=ActionType.ANALYZE_DATASET,
            message="데이터셋을 분석합니다."
        )
        mock_session.temp_data = {"config": {"dataset_path": "C:/test/dataset"}}

        # Mock tool_registry
        with patch("app.services.action_handlers.tool_registry") as mock_registry:
            mock_registry.call_tool = AsyncMock(return_value={
                "path": "C:/test/dataset",
                "format": "imagefolder",
                "num_classes": 5,
                "classes": ["cat", "dog", "bird", "fish", "hamster"],
                "total_images": 1000,
                "class_distribution": {},
                "dataset_info": {},
                "suggestions": []
            })

            # Execute
            result = await action_handlers._handle_analyze_dataset(
                action_response,
                mock_session,
                "데이터셋 분석해줘"
            )

            # Assert
            assert result["new_state"] == ConversationState.ANALYZING_DATASET
            assert "데이터셋 분석 결과" in result["message"]
            assert result["temp_data"]["dataset_analysis"]["num_classes"] == 5
            assert mock_registry.call_tool.called

    @pytest.mark.asyncio
    async def test_handle_analyze_dataset_no_path(self, action_handlers, mock_session):
        """Test analyze_dataset handler without dataset path"""
        action_response = GeminiActionResponse(
            action=ActionType.ANALYZE_DATASET,
            message="데이터셋을 분석합니다."
        )
        mock_session.temp_data = {}

        result = await action_handlers._handle_analyze_dataset(
            action_response,
            mock_session,
            "데이터셋 분석해줘"
        )

        assert result["new_state"] == ConversationState.INITIAL
        assert "경로를 알려주세요" in result["message"]

    @pytest.mark.asyncio
    async def test_handle_list_datasets(self, action_handlers, mock_session):
        """Test list_datasets handler"""
        action_response = GeminiActionResponse(
            action=ActionType.LIST_DATASETS,
            message="데이터셋 목록을 조회합니다."
        )

        with patch("app.services.action_handlers.tool_registry") as mock_registry:
            mock_registry.call_tool = AsyncMock(return_value=[
                {"name": "dataset1", "path": "C:/datasets/dataset1", "exists": True},
                {"name": "dataset2", "path": "C:/datasets/dataset2", "exists": True}
            ])

            result = await action_handlers._handle_list_datasets(
                action_response,
                mock_session,
                "데이터셋 목록 보여줘"
            )

            assert "dataset1" in result["message"]
            assert "dataset2" in result["message"]
            assert len(result["temp_data"]["available_datasets"]) == 2


class TestModelHandlers:
    """Test model-related action handlers"""

    @pytest.fixture
    def action_handlers(self, db_session):
        return ActionHandlers(db_session)

    @pytest.fixture
    def mock_session(self):
        session = Mock(spec=SessionModel)
        session.id = 1
        session.state = ConversationState.SELECTING_MODEL
        session.temp_data = {"config": {"task_type": "classification"}}
        return session

    @pytest.mark.asyncio
    async def test_handle_search_models(self, action_handlers, mock_session):
        """Test search_models handler"""
        action_response = GeminiActionResponse(
            action=ActionType.SEARCH_MODELS,
            message="모델을 검색합니다."
        )

        with patch("app.services.action_handlers.tool_registry") as mock_registry:
            mock_registry.call_tool = AsyncMock(return_value=[
                {"name": "resnet50", "framework": "timm", "task_types": ["classification"]},
                {"name": "efficientnet_b0", "framework": "timm", "task_types": ["classification"]}
            ])

            result = await action_handlers._handle_search_models(
                action_response,
                mock_session,
                "classification 모델 찾아줘"
            )

            assert result["new_state"] == ConversationState.SELECTING_MODEL
            assert "resnet50" in result["message"]
            assert len(result["temp_data"]["model_search_results"]) == 2

    @pytest.mark.asyncio
    async def test_handle_recommend_models(self, action_handlers, mock_session):
        """Test recommend_models handler with dataset analysis"""
        action_response = GeminiActionResponse(
            action=ActionType.RECOMMEND_MODELS,
            message="모델을 추천합니다."
        )

        mock_session.temp_data = {
            "config": {"task_type": "classification"},
            "dataset_analysis": {"num_classes": 10}
        }

        with patch("app.services.action_handlers.tool_registry") as mock_registry:
            mock_registry.call_tool = AsyncMock(return_value=[
                {"name": "resnet18", "framework": "timm", "description": "Lightweight model"},
                {"name": "resnet50", "framework": "timm", "description": "Balanced model"},
                {"name": "efficientnet_b0", "framework": "timm", "description": "Efficient model"}
            ])

            result = await action_handlers._handle_recommend_models(
                action_response,
                mock_session,
                "어떤 모델이 좋을까?"
            )

            assert result["new_state"] == ConversationState.SELECTING_MODEL
            assert "10개 클래스" in result["message"]
            assert len(result["temp_data"]["recommended_models"]) == 3


class TestTrainingHandlers:
    """Test training-related action handlers"""

    @pytest.fixture
    def action_handlers(self, db_session):
        return ActionHandlers(db_session)

    @pytest.fixture
    def mock_session(self):
        session = Mock(spec=SessionModel)
        session.id = 1
        session.state = ConversationState.MONITORING_TRAINING
        session.temp_data = {}
        return session

    @pytest.fixture
    def sample_training_job(self, db_session):
        """Create sample training job"""
        job = TrainingJob(
            session_id=1,
            framework="timm",
            model_name="resnet50",
            task_type="classification",
            dataset_path="/test/path",
            epochs=50,
            batch_size=32,
            learning_rate=0.001,
            status="running",
            current_epoch=25
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        return job

    @pytest.mark.asyncio
    async def test_handle_show_training_status(
        self,
        action_handlers,
        mock_session,
        sample_training_job
    ):
        """Test show_training_status handler"""
        action_response = GeminiActionResponse(
            action=ActionType.SHOW_TRAINING_STATUS,
            message="학습 상태를 확인합니다."
        )

        with patch("app.services.action_handlers.tool_registry") as mock_registry:
            mock_registry.call_tool = AsyncMock(return_value={
                "job_id": sample_training_job.id,
                "status": "running",
                "model": "resnet50",
                "framework": "timm",
                "current_epoch": 25,
                "total_epochs": 50,
                "progress_percent": 50.0,
                "latest_metrics": {
                    "epoch": 25,
                    "loss": 0.35,
                    "accuracy": 0.92
                }
            })

            result = await action_handlers._handle_show_training_status(
                action_response,
                mock_session,
                f"job {sample_training_job.id} 상태 알려줘"
            )

            assert result["new_state"] == ConversationState.MONITORING_TRAINING
            assert "학습 상태" in result["message"]
            assert "50.0%" in result["message"]

    @pytest.mark.asyncio
    async def test_handle_list_training_jobs(
        self,
        action_handlers,
        mock_session,
        sample_training_job
    ):
        """Test list_training_jobs handler"""
        action_response = GeminiActionResponse(
            action=ActionType.LIST_TRAINING_JOBS,
            message="학습 작업 목록을 조회합니다."
        )

        with patch("app.services.action_handlers.tool_registry") as mock_registry:
            mock_registry.call_tool = AsyncMock(return_value=[
                {
                    "job_id": sample_training_job.id,
                    "model": "resnet50",
                    "status": "running",
                    "task_type": "classification",
                    "created_at": "2025-11-01T12:00:00"
                }
            ])

            result = await action_handlers._handle_list_training_jobs(
                action_response,
                mock_session,
                "학습 목록 보여줘"
            )

            assert result["new_state"] == ConversationState.MONITORING_TRAINING
            assert "resnet50" in result["message"]
            assert f"Job #{sample_training_job.id}" in result["message"]


class TestInferenceHandlers:
    """Test inference-related action handlers"""

    @pytest.fixture
    def action_handlers(self, db_session):
        return ActionHandlers(db_session)

    @pytest.fixture
    def mock_session(self):
        session = Mock(spec=SessionModel)
        session.id = 1
        session.state = ConversationState.RUNNING_INFERENCE
        session.temp_data = {}
        return session

    @pytest.mark.asyncio
    async def test_handle_start_quick_inference(self, action_handlers, mock_session):
        """Test start_quick_inference handler"""
        action_response = GeminiActionResponse(
            action=ActionType.START_QUICK_INFERENCE,
            message="추론을 실행합니다."
        )

        with patch("app.services.action_handlers.tool_registry") as mock_registry:
            mock_registry.call_tool = AsyncMock(return_value={
                "job_id": 1,
                "image_path": "C:/test/image.jpg",
                "predictions": [
                    {"class": "cat", "confidence": 0.95},
                    {"class": "dog", "confidence": 0.03}
                ],
                "message": "추론이 완료되었습니다."
            })

            result = await action_handlers._handle_start_quick_inference(
                action_response,
                mock_session,
                "job 1으로 C:/test/image.jpg 추론해줘"
            )

            assert result["new_state"] == ConversationState.RUNNING_INFERENCE
            assert "추론 결과" in result["message"]
            assert "cat" in result["message"]
            assert "0.95" in result["message"] or "95%" in result["message"]


class TestFormattingHelpers:
    """Test formatting helper methods"""

    @pytest.fixture
    def action_handlers(self, db_session):
        return ActionHandlers(db_session)

    def test_format_dataset_analysis(self, action_handlers):
        """Test _format_dataset_analysis helper"""
        analysis = {
            "path": "C:/test/dataset",
            "format": "imagefolder",
            "total_images": 1000,
            "num_classes": 5,
            "classes": ["cat", "dog", "bird", "fish", "hamster"],
            "class_distribution": {"cat": 200, "dog": 200, "bird": 200, "fish": 200, "hamster": 200},
            "dataset_info": {},
            "suggestions": ["데이터셋이 균형적입니다."]
        }

        result = action_handlers._format_dataset_analysis(analysis)

        assert "데이터셋 분석 결과" in result
        assert "C:/test/dataset" in result
        assert "imagefolder" in result
        assert "1,000개" in result
        assert "5개" in result
        assert "cat" in result
        assert "균형적" in result

    def test_format_training_status(self, action_handlers):
        """Test _format_training_status helper"""
        status = {
            "job_id": 123,
            "model": "resnet50",
            "framework": "timm",
            "status": "running",
            "current_epoch": 25,
            "total_epochs": 50,
            "progress_percent": 50.0,
            "latest_metrics": {
                "epoch": 25,
                "loss": 0.35,
                "accuracy": 0.92,
                "val_loss": 0.42,
                "val_accuracy": 0.88
            }
        }

        result = action_handlers._format_training_status(status)

        assert "학습 상태" in result
        assert "123" in result
        assert "resnet50" in result
        assert "50.0%" in result
        assert "25/50" in result
        assert "0.35" in result
        assert "92%" in result or "0.92" in result

    def test_format_model_list(self, action_handlers):
        """Test _format_model_list helper"""
        models = [
            {"name": "resnet50", "framework": "timm", "task_types": ["classification"]},
            {"name": "yolov8n", "framework": "ultralytics", "task_types": ["object_detection"]}
        ]
        search_params = {"task_type": "classification"}

        result = action_handlers._format_model_list(models, search_params)

        assert "모델 검색 결과" in result
        assert "2개" in result
        assert "resnet50" in result
        assert "yolov8n" in result
        assert "classification" in result
