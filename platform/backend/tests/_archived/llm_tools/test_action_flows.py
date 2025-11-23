"""
Integration tests for Action Flows with Mocked LLM Responses

Tests the flow: User Message → (Mocked) Intent Parsing → Action Execution

This bypasses Gemini API and directly tests ActionHandlers with predefined
GeminiActionResponse objects, enabling fast feedback and comprehensive testing.
"""

import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy.orm import Session

from app.services.action_handlers import ActionHandlers
from app.models.conversation import (
    GeminiActionResponse,
    ActionType,
    ConversationState
)
from app.db.models import Session as SessionModel, TrainingJob


@pytest.fixture
def mock_session(db_session):
    """Create mock session with initial state"""
    session = SessionModel(
        state=ConversationState.GATHERING_CONFIG.value,
        temp_data={"config": {}}
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


@pytest.fixture
def action_handlers(db_session):
    """Create ActionHandlers instance"""
    return ActionHandlers(db_session)


class TestDatasetActionFlows:
    """Test Dataset action flows with mocked LLM responses"""

    @pytest.mark.asyncio
    async def test_analyze_dataset_success_flow(self, action_handlers, mock_session):
        """
        Flow: User requests dataset analysis → Tool executes → Results saved
        """
        # Given: Mocked LLM response for analyze_dataset
        mock_llm_response = GeminiActionResponse(
            action=ActionType.ANALYZE_DATASET,
            message="데이터셋을 분석하고 있습니다...",
            current_config={
                "framework": "ultralytics",
                "task_type": "object_detection",
                "dataset_path": "C:/test/dataset",
                "dataset_format": "yolo"
            }
        )

        # Mock the tool call
        with patch("app.utils.tool_registry.tool_registry.call_tool") as mock_call_tool:
            mock_call_tool.return_value = {
                "path": "C:/test/dataset",
                "format": "yolo",
                "num_classes": 8,
                "classes": ["person", "car", "dog", "cat", "bike", "bus", "truck", "motorcycle"],
                "total_images": 128,
                "class_distribution": {},
                "dataset_info": {},
                "suggestions": ["데이터셋이 균형적입니다"]
            }

            # When: Execute action
            result = await action_handlers.handle_action(
                mock_llm_response,
                mock_session,
                "데이터셋 분석해줘"
            )

            # Then: Analysis completed successfully
            assert result["new_state"] == ConversationState.ANALYZING_DATASET
            assert "dataset_analysis" in result["temp_data"]
            assert result["temp_data"]["dataset_analysis"]["num_classes"] == 8
            assert "person" in result["temp_data"]["dataset_analysis"]["classes"]
            assert "분석 결과" in result["message"]

            # Verify tool was called with correct params
            mock_call_tool.assert_called_once()
            call_args = mock_call_tool.call_args
            assert call_args[0][0] == "analyze_dataset"
            assert call_args[0][1]["dataset_path"] == "C:/test/dataset"

    @pytest.mark.asyncio
    async def test_analyze_dataset_no_path_error(self, action_handlers, mock_session):
        """
        Flow: User requests analysis without dataset_path → Error handling
        """
        # Given: LLM response without dataset_path
        mock_llm_response = GeminiActionResponse(
            action=ActionType.ANALYZE_DATASET,
            message="데이터셋을 분석하고 있습니다...",
            current_config={
                "framework": "ultralytics",
                "task_type": "object_detection"
            }
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            "데이터셋 분석해줘"
        )

        # Then: Returns error asking for path
        assert result["new_state"] == ConversationState.INITIAL
        assert "경로를 알려주세요" in result["message"]

    @pytest.mark.asyncio
    async def test_list_datasets_flow(self, action_handlers, mock_session):
        """
        Flow: User requests dataset list → Tool returns list → Formatted display
        """
        # Given: Mocked LLM response for list_datasets
        mock_llm_response = GeminiActionResponse(
            action=ActionType.LIST_DATASETS,
            message="데이터셋 목록을 조회합니다..."
        )

        # Mock the tool call
        with patch("app.utils.tool_registry.tool_registry.call_tool") as mock_call_tool:
            mock_call_tool.return_value = [
                {"name": "coco8", "path": "C:/datasets/coco8", "exists": True},
                {"name": "imagenet10", "path": "C:/datasets/imagenet10", "exists": True}
            ]

            # When: Execute action
            result = await action_handlers.handle_action(
                mock_llm_response,
                mock_session,
                "데이터셋 목록 보여줘"
            )

            # Then: Dataset list displayed
            assert "coco8" in result["message"]
            assert "imagenet10" in result["message"]
            assert len(result["temp_data"]["available_datasets"]) == 2


class TestModelActionFlows:
    """Test Model action flows with mocked LLM responses"""

    @pytest.mark.asyncio
    async def test_search_models_classification_flow(self, action_handlers, mock_session):
        """
        Flow: User searches for classification models → Tool returns matches
        """
        # Given: Mocked LLM response for search_models
        mock_llm_response = GeminiActionResponse(
            action=ActionType.SEARCH_MODELS,
            message="분류 모델을 검색합니다...",
            current_config={
                "task_type": "classification"
            }
        )

        # Mock the tool call
        with patch("app.utils.tool_registry.tool_registry.call_tool") as mock_call_tool:
            mock_call_tool.return_value = [
                {"name": "resnet18", "framework": "timm", "task_types": ["classification"]},
                {"name": "resnet50", "framework": "timm", "task_types": ["classification"]},
                {"name": "efficientnet_b0", "framework": "timm", "task_types": ["classification"]}
            ]

            # When: Execute action
            result = await action_handlers.handle_action(
                mock_llm_response,
                mock_session,
                "classification 모델 찾아줘"
            )

            # Then: Models listed
            assert result["new_state"] == ConversationState.SELECTING_MODEL
            assert "resnet18" in result["message"]
            assert "resnet50" in result["message"]
            assert len(result["temp_data"]["model_search_results"]) == 3

    @pytest.mark.asyncio
    async def test_recommend_models_with_dataset_analysis(self, action_handlers, mock_session):
        """
        Flow: User asks for recommendations → Uses dataset analysis → Recommends models
        """
        # Given: Session with dataset analysis
        mock_session.temp_data = {
            "config": {"task_type": "object_detection"},
            "dataset_analysis": {"num_classes": 10, "format": "yolo"}
        }

        mock_llm_response = GeminiActionResponse(
            action=ActionType.RECOMMEND_MODELS,
            message="모델을 추천합니다..."
        )

        # Mock the tool call
        with patch("app.utils.tool_registry.tool_registry.call_tool") as mock_call_tool:
            mock_call_tool.return_value = [
                {"name": "yolov8n", "framework": "ultralytics", "description": "Lightweight"},
                {"name": "yolov8s", "framework": "ultralytics", "description": "Balanced"},
                {"name": "yolo11n", "framework": "ultralytics", "description": "Latest"}
            ]

            # When: Execute action
            result = await action_handlers.handle_action(
                mock_llm_response,
                mock_session,
                "어떤 모델이 좋을까?"
            )

            # Then: Recommendations with dataset context
            assert result["new_state"] == ConversationState.SELECTING_MODEL
            assert "10개 클래스" in result["message"]
            assert "yolov8n" in result["message"]
            assert len(result["temp_data"]["recommended_models"]) == 3


class TestTrainingActionFlows:
    """Test Training action flows with mocked LLM responses"""

    @pytest.mark.asyncio
    async def test_show_training_status_flow(self, action_handlers, mock_session, db_session):
        """
        Flow: User asks for training status → Tool fetches job → Status displayed
        """
        # Given: Create a training job
        job = TrainingJob(
            session_id=mock_session.id,
            framework="ultralytics",
            model_name="yolov8n",
            task_type="object_detection",
            dataset_path="/test/dataset",
            output_dir="/test/output",
            epochs=50,
            batch_size=16,
            learning_rate=0.001,
            status="running"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        mock_llm_response = GeminiActionResponse(
            action=ActionType.SHOW_TRAINING_STATUS,
            message="학습 상태를 확인합니다..."
        )

        # Mock the tool call
        with patch("app.utils.tool_registry.tool_registry.call_tool") as mock_call_tool:
            mock_call_tool.return_value = {
                "job_id": job.id,
                "model": "yolov8n",
                "framework": "ultralytics",
                "status": "running",
                "current_epoch": 25,
                "total_epochs": 50,
                "progress_percent": 50.0,
                "latest_metrics": {
                    "epoch": 25,
                    "box_loss": 0.35,
                    "cls_loss": 0.28
                }
            }

            # When: Execute action
            result = await action_handlers.handle_action(
                mock_llm_response,
                mock_session,
                f"job {job.id} 상태 알려줘"
            )

            # Then: Status displayed
            assert result["new_state"] == ConversationState.MONITORING_TRAINING
            assert "50.0%" in result["message"]
            assert "yolov8n" in result["message"]

    @pytest.mark.asyncio
    async def test_stop_training_flow(self, action_handlers, mock_session, db_session):
        """
        Flow: User stops training → Tool stops job → Confirmation message
        """
        # Given: Running training job
        job = TrainingJob(
            session_id=mock_session.id,
            framework="timm",
            model_name="resnet50",
            task_type="classification",
            dataset_path="/test/dataset",
            output_dir="/test/output",
            epochs=100,
            batch_size=32,
            learning_rate=0.001,
            status="running"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        mock_llm_response = GeminiActionResponse(
            action=ActionType.STOP_TRAINING,
            message="학습을 중지합니다..."
        )

        # Mock the tool call
        with patch("app.utils.tool_registry.tool_registry.call_tool") as mock_call_tool:
            mock_call_tool.return_value = {
                "job_id": job.id,
                "status": "stopped",
                "message": "학습이 안전하게 중지되었습니다. 체크포인트가 저장되었습니다."
            }

            # When: Execute action
            result = await action_handlers.handle_action(
                mock_llm_response,
                mock_session,
                f"job {job.id} 중지해줘"
            )

            # Then: Stop confirmation
            assert result["new_state"] == ConversationState.MONITORING_TRAINING
            assert "중지" in result["message"]
            assert str(job.id) in result["message"]


class TestInferenceActionFlows:
    """Test Inference action flows with mocked LLM responses"""

    @pytest.mark.asyncio
    async def test_quick_inference_flow(self, action_handlers, mock_session, db_session):
        """
        Flow: User runs inference → Tool executes → Results displayed
        """
        # Given: Completed training job
        job = TrainingJob(
            session_id=mock_session.id,
            framework="timm",
            model_name="resnet50",
            task_type="classification",
            dataset_path="/test/dataset",
            output_dir="/test/output",
            epochs=50,
            batch_size=32,
            learning_rate=0.001,
            status="completed"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        mock_llm_response = GeminiActionResponse(
            action=ActionType.START_QUICK_INFERENCE,
            message="추론을 실행합니다..."
        )

        # Mock the tool call
        with patch("app.utils.tool_registry.tool_registry.call_tool") as mock_call_tool:
            mock_call_tool.return_value = {
                "job_id": job.id,
                "image_path": "C:/test/cat.jpg",
                "predictions": [
                    {"class": "cat", "confidence": 0.98},
                    {"class": "dog", "confidence": 0.01},
                    {"class": "bird", "confidence": 0.01}
                ],
                "message": "추론이 완료되었습니다."
            }

            # When: Execute action
            result = await action_handlers.handle_action(
                mock_llm_response,
                mock_session,
                f"job {job.id}로 C:/test/cat.jpg 추론해줘"
            )

            # Then: Inference results displayed
            assert result["new_state"] == ConversationState.RUNNING_INFERENCE
            assert "추론 결과" in result["message"]
            assert "cat" in result["message"]
            assert "0.98" in result["message"] or "98" in result["message"]


class TestErrorHandling:
    """Test error handling in action flows"""

    @pytest.mark.asyncio
    async def test_tool_execution_failure(self, action_handlers, mock_session):
        """
        Flow: Tool execution fails → Error handled gracefully
        """
        # Given: LLM response that will trigger failing tool
        mock_llm_response = GeminiActionResponse(
            action=ActionType.ANALYZE_DATASET,
            message="데이터셋을 분석합니다...",
            current_config={
                "dataset_path": "C:/nonexistent/dataset"
            }
        )

        # Mock tool failure
        with patch("app.utils.tool_registry.tool_registry.call_tool") as mock_call_tool:
            mock_call_tool.side_effect = FileNotFoundError("Dataset path not found")

            # When: Execute action
            result = await action_handlers.handle_action(
                mock_llm_response,
                mock_session,
                "데이터셋 분석해줘"
            )

            # Then: Error handled
            assert result["new_state"] == ConversationState.ERROR
            assert "오류" in result["message"]
            assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_missing_required_config(self, action_handlers, mock_session):
        """
        Flow: Action requires config field that's missing → Error message
        """
        # Given: LLM response without required field
        mock_llm_response = GeminiActionResponse(
            action=ActionType.SHOW_TRAINING_STATUS,
            message="학습 상태를 확인합니다..."
        )

        # When: Execute action (no job_id in message or session)
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            "학습 어떻게 돼?"
        )

        # Then: Asks for job_id
        assert "ID를 알려주세요" in result["message"] or "job" in result["message"].lower()


class TestRemainingToolFlows:
    """Test remaining Phase 1 tools that weren't covered yet"""

    @pytest.mark.asyncio
    async def test_list_training_jobs_flow(self, action_handlers, mock_session, db_session):
        """
        Flow: User requests training job list → Tool fetches jobs → List displayed
        """
        # Given: Create multiple training jobs
        jobs = [
            TrainingJob(
                session_id=mock_session.id,
                framework="timm",
                model_name="resnet50",
                task_type="classification",
                dataset_path="/test/dataset1",
                output_dir="/test/output1",
                epochs=50,
                batch_size=32,
                learning_rate=0.001,
                status="completed"
            ),
            TrainingJob(
                session_id=mock_session.id,
                framework="ultralytics",
                model_name="yolov8n",
                task_type="object_detection",
                dataset_path="/test/dataset2",
                output_dir="/test/output2",
                epochs=100,
                batch_size=16,
                learning_rate=0.001,
                status="running"
            )
        ]
        for job in jobs:
            db_session.add(job)
        db_session.commit()

        mock_llm_response = GeminiActionResponse(
            action=ActionType.LIST_TRAINING_JOBS,
            message="학습 작업 목록을 조회합니다..."
        )

        # Mock the tool call
        with patch("app.utils.tool_registry.tool_registry.call_tool") as mock_call_tool:
            mock_call_tool.return_value = [
                {
                    "job_id": jobs[0].id,
                    "model": "resnet50",
                    "task_type": "classification",
                    "status": "completed",
                    "created_at": "2025-01-01T00:00:00",
                    "final_metric": 0.95
                },
                {
                    "job_id": jobs[1].id,
                    "model": "yolov8n",
                    "task_type": "object_detection",
                    "status": "running",
                    "created_at": "2025-01-02T00:00:00",
                    "final_metric": None
                }
            ]

            # When: Execute action
            result = await action_handlers.handle_action(
                mock_llm_response,
                mock_session,
                "학습 작업 목록 보여줘"
            )

            # Then: Job list displayed
            assert "resnet50" in result["message"] or "training_jobs" in result["temp_data"]
            assert result["new_state"] == ConversationState.MONITORING_TRAINING

    @pytest.mark.asyncio
    async def test_compare_models_flow(self, action_handlers, mock_session):
        """
        Flow: User requests model comparison → Tool compares → Comparison displayed
        """
        # Given: Mocked LLM response for compare_models
        mock_llm_response = GeminiActionResponse(
            action=ActionType.COMPARE_MODELS,
            message="모델을 비교합니다...",
            current_config={
                "models_to_compare": [
                    {"framework": "timm", "name": "resnet50"},
                    {"framework": "timm", "name": "efficientnet_b0"}
                ]
            }
        )

        # Mock the tool call
        with patch("app.utils.tool_registry.tool_registry.call_tool") as mock_call_tool:
            mock_call_tool.return_value = {
                "models": [
                    {"framework": "timm", "name": "resnet50"},
                    {"framework": "timm", "name": "efficientnet_b0"}
                ],
                "comparison": "Model comparison feature coming soon"
            }

            # When: Execute action
            result = await action_handlers.handle_action(
                mock_llm_response,
                mock_session,
                "resnet50과 efficientnet_b0 비교해줘"
            )

            # Then: Comparison displayed
            assert result["new_state"] == ConversationState.COMPARING_MODELS
            assert "비교" in result["message"]

    @pytest.mark.asyncio
    async def test_get_model_guide_flow(self, action_handlers, mock_session):
        """
        Flow: User requests model guide → Tool fetches guide → Guide displayed
        """
        # Given: Mocked LLM response for get_model_guide
        mock_llm_response = GeminiActionResponse(
            action=ActionType.SHOW_MODEL_INFO,
            message="모델 가이드를 조회합니다...",
            current_config={
                "framework": "ultralytics",
                "model_name": "yolov8n"
            }
        )

        # Mock the tool call
        with patch("app.utils.tool_registry.tool_registry.call_tool") as mock_call_tool:
            mock_call_tool.return_value = {
                "framework": "ultralytics",
                "model_name": "yolov8n",
                "description": "Model guide for yolov8n",
                "available": True
            }

            # When: Execute action
            result = await action_handlers.handle_action(
                mock_llm_response,
                mock_session,
                "yolov8n 모델 정보 알려줘"
            )

            # Then: Guide displayed
            assert result["new_state"] == ConversationState.SELECTING_MODEL
            assert "yolov8n" in result["message"]


class TestProjectManagementFlows:
    """Test project management action flows"""

    @pytest.mark.asyncio
    async def test_show_project_options_flow(self, action_handlers, mock_session):
        """
        Flow: User starts conversation → Show project options
        """
        # Given: Mocked LLM response for show_project_options
        mock_llm_response = GeminiActionResponse(
            action=ActionType.SHOW_PROJECT_OPTIONS,
            message="프로젝트 설정 방식을 선택해주세요:\n\n1. 신규 프로젝트 생성\n2. 기존 프로젝트 선택\n3. 프로젝트 없이 진행"
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            "학습 시작하고 싶어"
        )

        # Then: Options displayed
        assert result["new_state"] == ConversationState.SELECTING_PROJECT
        assert "1️⃣" in result["message"] and "2️⃣" in result["message"]

    @pytest.mark.asyncio
    async def test_create_project_flow(self, action_handlers, mock_session, db_session):
        """
        Flow: User creates new project → Project created → Confirmation
        """
        # Given: Mocked LLM response for create_project
        mock_llm_response = GeminiActionResponse(
            action=ActionType.CREATE_PROJECT,
            message="프로젝트를 생성합니다...",
            project_name="이미지 분류 프로젝트",
            project_description="고양이/강아지 분류 실험"
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            "이미지 분류 프로젝트 - 고양이/강아지 분류 실험"
        )

        # Then: Project created and ready for confirmation
        assert result["new_state"] == ConversationState.CONFIRMING
        assert "생성" in result["message"]
        assert result["temp_data"]["selected_project_id"] is not None

    @pytest.mark.asyncio
    async def test_skip_project_flow(self, action_handlers, mock_session):
        """
        Flow: User skips project selection → Proceed without project
        """
        # Given: Mocked LLM response for skip_project
        mock_llm_response = GeminiActionResponse(
            action=ActionType.SKIP_PROJECT,
            message="프로젝트 없이 진행합니다."
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            "프로젝트 없이 진행"
        )

        # Then: Proceed without project to confirmation
        assert result["new_state"] == ConversationState.CONFIRMING
        assert "없이" in result["message"]


class TestTrainingLifecycleFlows:
    """Test training lifecycle action flows"""

    @pytest.mark.asyncio
    async def test_confirm_training_flow(self, action_handlers, mock_session):
        """
        Flow: User confirms training → Show confirmation → Wait for approval
        """
        # Given: Session with complete config
        mock_session.temp_data = {
            "config": {
                "framework": "timm",
                "model_name": "resnet50",
                "task_type": "classification",
                "dataset_path": "C:/datasets/test",
                "epochs": 50,
                "batch_size": 32,
                "learning_rate": 0.001
            }
        }

        mock_llm_response = GeminiActionResponse(
            action=ActionType.CONFIRM_TRAINING,
            message="다음 설정으로 학습을 시작하시겠습니까?\n\n모델: resnet50\n데이터셋: C:/datasets/test\n에폭: 50"
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            "설정 확인"
        )

        # Then: Confirmation shown
        assert result["new_state"] == ConversationState.CONFIRMING
        assert "시작하시겠습니까" in result["message"]

    @pytest.mark.asyncio
    async def test_start_training_flow(self, action_handlers, mock_session, db_session):
        """
        Flow: User starts training → Training job created → Job ID returned
        """
        # Given: Session in CONFIRMING state with complete config
        mock_session.state = ConversationState.CONFIRMING.value
        mock_session.temp_data = {
            "config": {
                "framework": "timm",
                "model_name": "resnet50",
                "task_type": "classification",
                "dataset_path": "C:/datasets/test",
                "dataset_format": "imagefolder",
                "num_classes": 10,
                "epochs": 50,
                "batch_size": 32,
                "learning_rate": 0.001
            }
        }

        mock_llm_response = GeminiActionResponse(
            action=ActionType.START_TRAINING,
            message="학습을 시작합니다..."
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            "시작"
        )

        # Then: Training started
        assert result["new_state"] == ConversationState.COMPLETE
        assert "training_job_id" in result
        assert "시작" in result["message"]

    @pytest.mark.asyncio
    async def test_resume_training_flow(self, action_handlers, mock_session, db_session):
        """
        Flow: User resumes stopped training → Training resumes → Confirmation
        """
        # Given: Stopped training job
        job = TrainingJob(
            session_id=mock_session.id,
            framework="ultralytics",
            model_name="yolov8n",
            task_type="object_detection",
            dataset_path="/test/dataset",
            output_dir="/test/output",
            epochs=100,
            batch_size=16,
            learning_rate=0.001,
            status="stopped"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        mock_llm_response = GeminiActionResponse(
            action=ActionType.RESUME_TRAINING,
            message="학습을 재개합니다...",
            current_config={"job_id": job.id}
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            f"job {job.id} 재개해줘"
        )

        # Then: Resume attempted (may not be fully implemented yet)
        assert result["new_state"] == ConversationState.MONITORING_TRAINING
        assert "재개" in result["message"] or "resume" in result["message"].lower()


class TestResultsAndBatchInferenceFlows:
    """Test results viewing and batch inference action flows"""

    @pytest.mark.asyncio
    async def test_show_validation_results_flow(self, action_handlers, mock_session, db_session):
        """
        Flow: User requests validation results → Results displayed
        """
        # Given: Completed training job
        job = TrainingJob(
            session_id=mock_session.id,
            framework="timm",
            model_name="resnet50",
            task_type="classification",
            dataset_path="/test/dataset",
            output_dir="/test/output",
            epochs=50,
            batch_size=32,
            learning_rate=0.001,
            status="completed"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        mock_llm_response = GeminiActionResponse(
            action=ActionType.SHOW_VALIDATION_RESULTS,
            message="검증 결과를 조회합니다...",
            current_config={"job_id": job.id}
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            f"job {job.id} 검증 결과 보여줘"
        )

        # Then: Results displayed
        assert result["new_state"] == ConversationState.VIEWING_RESULTS
        assert "검증" in result["message"] or "validation" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_start_batch_inference_flow(self, action_handlers, mock_session, db_session):
        """
        Flow: User starts batch inference → Batch processing → Status shown
        """
        # Given: Completed training job
        job = TrainingJob(
            session_id=mock_session.id,
            framework="ultralytics",
            model_name="yolov8n",
            task_type="object_detection",
            dataset_path="/test/dataset",
            output_dir="/test/output",
            epochs=50,
            batch_size=16,
            learning_rate=0.001,
            status="completed"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        mock_llm_response = GeminiActionResponse(
            action=ActionType.START_BATCH_INFERENCE,
            message="배치 추론을 시작합니다...",
            current_config={
                "job_id": job.id,
                "image_dir": "C:/test/images"
            }
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            f"job {job.id}로 C:/test/images 폴더 배치 추론해줘"
        )

        # Then: Batch inference started
        assert result["new_state"] == ConversationState.RUNNING_INFERENCE
        assert "배치" in result["message"] or "batch" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_show_inference_results_flow(self, action_handlers, mock_session):
        """
        Flow: User requests inference results → Results displayed
        """
        # Given: Session with inference results in temp_data
        mock_session.temp_data = {
            "inference_results": {
                "job_id": 1,
                "predictions": [
                    {"image": "cat.jpg", "class": "cat", "confidence": 0.98},
                    {"image": "dog.jpg", "class": "dog", "confidence": 0.95}
                ]
            }
        }

        mock_llm_response = GeminiActionResponse(
            action=ActionType.SHOW_INFERENCE_RESULTS,
            message="추론 결과를 표시합니다..."
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            "추론 결과 보여줘"
        )

        # Then: Results displayed
        assert result["new_state"] == ConversationState.VIEWING_RESULTS
        assert "추론 결과" in result["message"] or "inference_results" in result["temp_data"]

    @pytest.mark.asyncio
    async def test_show_confusion_matrix_flow(self, action_handlers, mock_session, db_session):
        """
        Flow: User requests confusion matrix → Matrix displayed
        """
        # Given: Completed classification job
        job = TrainingJob(
            session_id=mock_session.id,
            framework="timm",
            model_name="resnet50",
            task_type="classification",
            dataset_path="/test/dataset",
            output_dir="/test/output",
            epochs=50,
            batch_size=32,
            learning_rate=0.001,
            status="completed"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        mock_llm_response = GeminiActionResponse(
            action=ActionType.SHOW_CONFUSION_MATRIX,
            message="Confusion Matrix를 조회합니다...",
            current_config={"job_id": job.id}
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            f"job {job.id} confusion matrix 보여줘"
        )

        # Then: Matrix displayed
        assert result["new_state"] == ConversationState.VIEWING_RESULTS
        assert "confusion" in result["message"].lower() or "혼동" in result["message"]


class TestHelpAndUtilityFlows:
    """Test help and utility action flows"""

    @pytest.mark.asyncio
    async def test_show_help_flow(self, action_handlers, mock_session):
        """
        Flow: User requests help → Help message displayed
        """
        # Given: Mocked LLM response for show_help
        mock_llm_response = GeminiActionResponse(
            action=ActionType.SHOW_HELP,
            message="Vision AI Training Platform 도움말\n\n사용 가능한 명령어:\n- 데이터셋 분석\n- 모델 검색\n- 학습 시작"
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            "도움말"
        )

        # Then: Help displayed
        assert result["new_state"] == ConversationState.IDLE
        assert "도움말" in result["message"] or "명령어" in result["message"]

    @pytest.mark.asyncio
    async def test_reset_conversation_flow(self, action_handlers, mock_session):
        """
        Flow: User resets conversation → Session cleared → Initial state
        """
        # Given: Session with existing data
        mock_session.temp_data = {
            "config": {"model_name": "resnet50"},
            "dataset_analysis": {"num_classes": 10}
        }

        mock_llm_response = GeminiActionResponse(
            action=ActionType.RESET_CONVERSATION,
            message="대화를 초기화했습니다. 새로운 작업을 시작해주세요."
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            "초기화"
        )

        # Then: Session reset
        assert result["new_state"] == ConversationState.INITIAL
        assert result["temp_data"] == {} or "config" not in result["temp_data"]
        assert "초기화" in result["message"]

    @pytest.mark.asyncio
    async def test_show_dataset_analysis_flow(self, action_handlers, mock_session):
        """
        Flow: User requests to view previous dataset analysis → Analysis displayed
        """
        # Given: Session with dataset analysis in temp_data
        mock_session.temp_data = {
            "dataset_analysis": {
                "path": "C:/datasets/test",
                "format": "yolo",
                "num_classes": 8,
                "classes": ["person", "car", "dog", "cat", "bike", "bus", "truck", "motorcycle"],
                "total_images": 128
            }
        }

        mock_llm_response = GeminiActionResponse(
            action=ActionType.SHOW_DATASET_ANALYSIS,
            message="이전 데이터셋 분석 결과를 표시합니다..."
        )

        # When: Execute action
        result = await action_handlers.handle_action(
            mock_llm_response,
            mock_session,
            "데이터셋 분석 결과 다시 보여줘"
        )

        # Then: Analysis displayed
        assert result["new_state"] == ConversationState.ANALYZING_DATASET
        assert "dataset_analysis" in result["temp_data"]
        assert "8" in result["message"] or "클래스" in result["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
