"""
Integration tests for Phase 1 user scenarios

Tests realistic user conversation flows with natural language.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

from app.services.conversation_manager import ConversationManager
from app.models.conversation import ConversationState, ActionType
from app.db.models import TrainingJob, Project


class TestDatasetExplorationScenario:
    """
    시나리오 1: 데이터셋 분석부터 시작하는 사용자

    사용자 발화:
    1. "내 데이터셋 분석해줘"
    2. "C:/datasets/my_images"
    3. "어떤 모델이 좋을까?"
    4. "resnet50으로 학습해줘"
    """

    @pytest.fixture
    def conv_manager(self, db_session):
        return ConversationManager(db_session)

    @pytest.mark.asyncio
    async def test_dataset_first_exploration(self, conv_manager, db_session):
        """데이터셋 분석 → 모델 추천 → 학습 설정 플로우"""

        # Step 1: 사용자가 데이터셋 분석 요청
        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser:
            # LLM이 데이터셋 경로를 물어봄
            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.ASK_CLARIFICATION,
                message="데이터셋을 분석하시겠습니까? 데이터셋 경로를 알려주세요.",
                missing_fields=["dataset_path"],
                current_config={}
            ))

            response = await conv_manager.process_message(
                session_id=1,
                message="내 데이터셋 분석해줘"
            )

            assert "경로" in response["message"]
            assert response["state"] in [ConversationState.INITIAL, ConversationState.GATHERING_CONFIG]

        # Step 2: 사용자가 데이터셋 경로 제공
        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser, \
             patch("app.services.action_handlers.tool_registry") as mock_registry:

            # LLM이 analyze_dataset 액션 반환
            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.ANALYZE_DATASET,
                message="데이터셋을 분석하겠습니다.",
                current_config={"dataset_path": "C:/datasets/my_images"}
            ))

            # Tool Registry가 분석 결과 반환
            mock_registry.call_tool = AsyncMock(return_value={
                "path": "C:/datasets/my_images",
                "format": "imagefolder",
                "num_classes": 5,
                "classes": ["cat", "dog", "bird", "fish", "hamster"],
                "total_images": 500,
                "class_distribution": {"cat": 100, "dog": 100, "bird": 100, "fish": 100, "hamster": 100},
                "dataset_info": {},
                "suggestions": ["데이터셋이 균형적으로 구성되어 있습니다."]
            })

            response = await conv_manager.process_message(
                session_id=1,
                message="C:/datasets/my_images"
            )

            assert "5개" in response["message"]  # 클래스 수
            assert "500" in response["message"] or "500개" in response["message"]  # 이미지 수
            assert response["state"] == ConversationState.ANALYZING_DATASET

        # Step 3: 모델 추천 요청
        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser, \
             patch("app.services.action_handlers.tool_registry") as mock_registry:

            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.RECOMMEND_MODELS,
                message="모델을 추천해드리겠습니다."
            ))

            mock_registry.call_tool = AsyncMock(return_value=[
                {"name": "resnet18", "framework": "timm", "description": "경량 모델"},
                {"name": "resnet50", "framework": "timm", "description": "균형잡힌 모델"},
                {"name": "efficientnet_b0", "framework": "timm", "description": "효율적인 모델"}
            ])

            response = await conv_manager.process_message(
                session_id=1,
                message="어떤 모델이 좋을까?"
            )

            assert "resnet" in response["message"].lower()
            assert response["state"] == ConversationState.SELECTING_MODEL

        # Step 4: 모델 선택하고 학습 시작
        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser:
            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.ASK_CLARIFICATION,
                message="ResNet-50을 선택하셨습니다. 나머지 설정을 입력해주세요.",
                missing_fields=["epochs", "batch_size", "learning_rate"],
                current_config={
                    "framework": "timm",
                    "model_name": "resnet50",
                    "task_type": "image_classification",
                    "dataset_path": "C:/datasets/my_images"
                }
            ))

            response = await conv_manager.process_message(
                session_id=1,
                message="resnet50으로 학습해줘"
            )

            assert "resnet50" in response["message"].lower() or "resnet" in response["message"].lower()


class TestQuickStartScenario:
    """
    시나리오 2: 숙련된 사용자 - 한 번에 모든 정보 제공

    사용자 발화:
    "ResNet-50으로 C:/datasets/imagenet-10 데이터셋을 50 에포크, 배치 32, lr 0.001로 학습해줘"
    """

    @pytest.fixture
    def conv_manager(self, db_session):
        return ConversationManager(db_session)

    @pytest.mark.asyncio
    async def test_experienced_user_quick_start(self, conv_manager, db_session):
        """한 번에 모든 정보를 제공하는 숙련 사용자"""

        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser:
            # LLM이 모든 정보를 한 번에 파싱
            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.SHOW_PROJECT_OPTIONS,
                message="설정이 완료되었습니다. 프로젝트를 선택해주세요.",
                config={
                    "framework": "timm",
                    "model_name": "resnet50",
                    "task_type": "image_classification",
                    "dataset_path": "C:/datasets/imagenet-10",
                    "dataset_format": "imagefolder",
                    "epochs": 50,
                    "batch_size": 32,
                    "learning_rate": 0.001
                }
            ))

            response = await conv_manager.process_message(
                session_id=1,
                message="ResNet-50으로 C:/datasets/imagenet-10 데이터셋을 50 에포크, 배치 32, lr 0.001로 학습해줘"
            )

            assert response["state"] == ConversationState.SELECTING_PROJECT
            assert "프로젝트" in response["message"]


class TestTrainingMonitoringScenario:
    """
    시나리오 3: 학습 모니터링 및 제어

    사용자 발화:
    1. "학습 상태 알려줘"
    2. "학습 목록 보여줘"
    3. "실행중인 학습만 보여줘"
    4. "job 5 중지해줘"
    """

    @pytest.fixture
    def conv_manager(self, db_session):
        return ConversationManager(db_session)

    @pytest.fixture
    def running_job(self, db_session):
        """실행 중인 학습 작업 생성"""
        job = TrainingJob(
            session_id=1,
            framework="timm",
            model_name="resnet50",
            task_type="image_classification",
            dataset_path="/test/path",
            epochs=50,
            batch_size=32,
            learning_rate=0.001,
            status="running"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        return job

    @pytest.mark.asyncio
    async def test_check_training_status(self, conv_manager, db_session, running_job):
        """학습 상태 확인"""

        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser, \
             patch("app.services.action_handlers.tool_registry") as mock_registry:

            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.SHOW_TRAINING_STATUS,
                message="학습 상태를 확인하겠습니다."
            ))

            mock_registry.call_tool = AsyncMock(return_value={
                "job_id": running_job.id,
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

            response = await conv_manager.process_message(
                session_id=1,
                message="학습 상태 알려줘"
            )

            assert "학습 상태" in response["message"]
            assert response["state"] == ConversationState.MONITORING_TRAINING

    @pytest.mark.asyncio
    async def test_list_running_jobs(self, conv_manager, db_session, running_job):
        """실행 중인 학습 목록 조회"""

        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser, \
             patch("app.services.action_handlers.tool_registry") as mock_registry:

            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.LIST_TRAINING_JOBS,
                message="실행중인 학습 목록을 조회합니다."
            ))

            mock_registry.call_tool = AsyncMock(return_value=[
                {
                    "job_id": running_job.id,
                    "model": "resnet50",
                    "status": "running",
                    "task_type": "image_classification",
                    "created_at": "2025-11-01T12:00:00"
                }
            ])

            response = await conv_manager.process_message(
                session_id=1,
                message="실행중인 학습만 보여줘"
            )

            assert "resnet50" in response["message"]
            assert response["state"] == ConversationState.MONITORING_TRAINING


class TestInferenceScenario:
    """
    시나리오 4: 추론 실행

    사용자 발화:
    1. "job 3으로 이미지 추론해줘"
    2. "C:/test/cat.jpg"
    """

    @pytest.fixture
    def conv_manager(self, db_session):
        return ConversationManager(db_session)

    @pytest.mark.asyncio
    async def test_quick_inference(self, conv_manager, db_session):
        """빠른 추론 실행"""

        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser, \
             patch("app.services.action_handlers.tool_registry") as mock_registry:

            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.START_QUICK_INFERENCE,
                message="추론을 실행합니다."
            ))

            mock_registry.call_tool = AsyncMock(return_value={
                "job_id": 3,
                "image_path": "C:/test/cat.jpg",
                "predictions": [
                    {"class": "cat", "confidence": 0.98},
                    {"class": "dog", "confidence": 0.01},
                    {"class": "bird", "confidence": 0.01}
                ],
                "message": "추론이 완료되었습니다."
            })

            response = await conv_manager.process_message(
                session_id=1,
                message="job 3으로 C:/test/cat.jpg 추론해줘"
            )

            assert "cat" in response["message"]
            assert response["state"] == ConversationState.RUNNING_INFERENCE


class TestNaturalLanguageVariations:
    """
    시나리오 5: 자연어 변형 테스트 - 같은 의도를 다양하게 표현
    """

    @pytest.fixture
    def conv_manager(self, db_session):
        return ConversationManager(db_session)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_message,expected_keywords", [
        # 데이터셋 분석 요청의 다양한 표현
        ("내 데이터셋 좀 분석해줘", ["데이터셋", "경로"]),
        ("데이터셋 어떤지 확인해줄래?", ["데이터셋", "경로"]),
        ("이 데이터로 학습할 수 있을까?", ["데이터셋", "경로"]),

        # 모델 추천 요청
        ("뭐가 좋을까?", ["모델"]),
        ("추천해줘", ["모델"]),
        ("어떤 거 쓰면 되지?", ["모델"]),

        # 학습 상태 확인
        ("학습 어떻게 되고 있어?", ["학습", "상태"]),
        ("지금 학습 진행률 알려줘", ["학습", "상태"]),
        ("얼마나 됐어?", ["학습", "상태"]),

        # 학습 중지
        ("그만 학습해", ["중지"]),
        ("학습 멈춰줘", ["중지"]),
        ("stop", ["중지"]),
    ])
    async def test_natural_language_variations(
        self,
        conv_manager,
        db_session,
        user_message,
        expected_keywords
    ):
        """다양한 자연어 표현 테스트"""

        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser:
            # Mock LLM response (실제로는 LLM이 intent를 파싱)
            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.ASK_CLARIFICATION,
                message=f"알겠습니다. {user_message}에 대한 응답입니다.",
                missing_fields=[],
                current_config={}
            ))

            response = await conv_manager.process_message(
                session_id=1,
                message=user_message
            )

            # 응답이 정상적으로 반환되는지 확인
            assert response is not None
            assert "message" in response


class TestConversationalContext:
    """
    시나리오 6: 대화 맥락 유지 테스트

    사용자가 이전 대화를 참조하는 경우
    """

    @pytest.fixture
    def conv_manager(self, db_session):
        return ConversationManager(db_session)

    @pytest.mark.asyncio
    async def test_context_maintained_across_messages(self, conv_manager, db_session):
        """
        대화 맥락 유지 테스트

        User: "ResNet으로 학습하고 싶어"
        Bot: "ResNet 모델을 선택하셨습니다. 어떤 버전을 사용하시겠어요?"
        User: "50"  <- 이전 맥락(ResNet)을 유지하고 있어야 함
        """

        # Step 1: 첫 번째 메시지
        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser:
            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.ASK_CLARIFICATION,
                message="ResNet 모델을 선택하셨습니다. 어떤 버전을 사용하시겠어요? (resnet18, resnet50)",
                missing_fields=["model_name"],
                current_config={
                    "framework": "timm",
                    "task_type": "image_classification"
                }
            ))

            response1 = await conv_manager.process_message(
                session_id=1,
                message="ResNet으로 학습하고 싶어"
            )

            assert "resnet" in response1["message"].lower()

        # Step 2: 두 번째 메시지 (맥락 참조)
        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser:
            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.ASK_CLARIFICATION,
                message="ResNet-50을 선택했습니다. 데이터셋 경로를 알려주세요.",
                missing_fields=["dataset_path", "epochs", "batch_size", "learning_rate"],
                current_config={
                    "framework": "timm",
                    "model_name": "resnet50",
                    "task_type": "image_classification"
                }
            ))

            response2 = await conv_manager.process_message(
                session_id=1,
                message="50"
            )

            # 이전 맥락(ResNet)이 유지되어 resnet50으로 인식되어야 함
            assert "resnet" in response2["message"].lower() or "50" in response2["message"]


class TestErrorRecovery:
    """
    시나리오 7: 에러 복구 및 재시도

    사용자가 잘못된 정보를 제공하거나 경로가 없는 경우
    """

    @pytest.fixture
    def conv_manager(self, db_session):
        return ConversationManager(db_session)

    @pytest.mark.asyncio
    async def test_invalid_dataset_path_recovery(self, conv_manager, db_session):
        """존재하지 않는 데이터셋 경로 처리"""

        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser, \
             patch("app.services.action_handlers.tool_registry") as mock_registry:

            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.ANALYZE_DATASET,
                message="데이터셋을 분석하겠습니다."
            ))

            # Tool Registry가 에러 발생
            mock_registry.call_tool = AsyncMock(
                side_effect=ValueError("Dataset path does not exist: C:/invalid/path")
            )

            response = await conv_manager.process_message(
                session_id=1,
                message="C:/invalid/path 분석해줘"
            )

            # 에러 상태로 전환되고 사용자에게 안내
            assert response["state"] == ConversationState.ERROR
            assert "오류" in response["message"] or "경로" in response["message"]


class TestMixedIntentScenario:
    """
    시나리오 8: 복합 의도 - 여러 작업을 한 번에 요청

    "데이터셋 분석하고 모델 추천해줘"
    """

    @pytest.fixture
    def conv_manager(self, db_session):
        return ConversationManager(db_session)

    @pytest.mark.asyncio
    async def test_multiple_intents_in_one_message(self, conv_manager, db_session):
        """한 메시지에 여러 의도가 포함된 경우"""

        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser:
            # LLM이 먼저 데이터셋 분석을 요청
            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.ASK_CLARIFICATION,
                message="데이터셋을 먼저 분석하겠습니다. 데이터셋 경로를 알려주세요.",
                missing_fields=["dataset_path"],
                current_config={}
            ))

            response = await conv_manager.process_message(
                session_id=1,
                message="데이터셋 분석하고 모델 추천해줘"
            )

            # LLM이 단계적으로 처리하도록 유도
            assert "데이터셋" in response["message"] or "경로" in response["message"]


class TestCasualConversation:
    """
    시나리오 9: 일상적인 대화 패턴

    사용자가 격식 없이 편하게 대화하는 경우
    """

    @pytest.fixture
    def conv_manager(self, db_session):
        return ConversationManager(db_session)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("casual_message", [
        "ㅇㅇ",  # 동의
        "ㄱㄱ",  # 고고
        "ㅇㅋ",  # 오케이
        "어 그래",  # 동의
        "알겠어",  # 이해
        "1번",  # 선택
        "2",  # 선택
    ])
    async def test_casual_conversation_style(self, conv_manager, db_session, casual_message):
        """격식 없는 대화 스타일 처리"""

        with patch("app.services.conversation_manager.structured_intent_parser") as mock_parser:
            mock_parser.parse_intent = AsyncMock(return_value=MagicMock(
                action=ActionType.ASK_CLARIFICATION,
                message="알겠습니다.",
                missing_fields=[],
                current_config={}
            ))

            response = await conv_manager.process_message(
                session_id=1,
                message=casual_message
            )

            # 응답이 정상적으로 반환되는지만 확인
            assert response is not None
            assert "message" in response
