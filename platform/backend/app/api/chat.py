"""
Chat API endpoints (Phase 1+2 Refactored)

Uses ConversationManager with state machine + structured actions
"""

import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.db.database import get_db
from app.db.models import Session as SessionModel, Message as MessageModel, TrainingJob, User
from app.schemas import chat
from app.services.conversation_manager import ConversationManager
from app.utils.dependencies import get_current_user
from app.core.config import settings

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/capabilities")
async def get_capabilities():
    """
    Get platform capabilities including supported models and parameters.

    Dynamically fetches model information from Training Services.

    Returns information about:
    - Available frameworks
    - Available models per framework (from Training Service APIs)
    - Supported task types
    - Configurable parameters
    - Default values
    """
    # Framework configuration
    # Note: Service URLs removed - subprocess mode doesn't use HTTP APIs
    frameworks_config = {
        "timm": {
            "name": "timm",
            "display_name": "PyTorch Image Models (timm)",
            "description": "Image classification with pretrained models",
            "supported": True
        },
        "ultralytics": {
            "name": "ultralytics",
            "display_name": "Ultralytics YOLO",
            "description": "Object detection, segmentation, and pose estimation",
            "supported": True
        },
        "huggingface": {
            "name": "transformers",
            "display_name": "HuggingFace Transformers",
            "description": "Vision transformers for classification, detection, segmentation, and super-resolution",
            "supported": False  # Not yet implemented
        }
    }

    # Static frameworks info (without URL)
    frameworks = []
    for framework in frameworks_config.values():
        frameworks.append({
            "name": framework["name"],
            "display_name": framework["display_name"],
            "description": framework["description"],
            "supported": framework["supported"]
        })

    # Dynamically fetch models from Training Services
    all_models = []

    async with httpx.AsyncClient(timeout=5.0) as client:
        for framework_key, framework in frameworks_config.items():
            if not framework["supported"]:
                continue

            try:
                response = await client.get(f"{framework['url']}/models/list")
                if response.status_code == 200:
                    models_data = response.json()
                    # Add to all_models list
                    all_models.extend(models_data)
                    logger.info(f"Fetched {len(models_data)} models from {framework['name']} service")
                else:
                    logger.warning(f"Failed to fetch models from {framework['name']} service: {response.status_code}")
            except Exception as e:
                logger.error(f"Error fetching models from {framework['name']} service: {str(e)}")
                # Continue with other services

    # Static task types (these are defined by the platform)
    task_types = [
        {
            "name": "image_classification",
            "display_name": "이미지 분류",
            "description": "이미지를 여러 클래스 중 하나로 분류",
            "frameworks": ["timm", "ultralytics"],
            "supported": True
        },
        {
            "name": "object_detection",
            "display_name": "객체 탐지",
            "description": "이미지 내 객체의 위치와 클래스 탐지",
            "frameworks": ["ultralytics"],
            "supported": True
        },
        {
            "name": "instance_segmentation",
            "display_name": "인스턴스 분할",
            "description": "이미지 내 각 객체를 픽셀 단위로 분할",
            "frameworks": ["ultralytics"],
            "supported": True
        },
        {
            "name": "pose_estimation",
            "display_name": "자세 추정",
            "description": "이미지 내 사람의 자세 키포인트 탐지",
            "frameworks": ["ultralytics"],
            "supported": True
        },
        {
            "name": "semantic_segmentation",
            "display_name": "시맨틱 분할",
            "description": "이미지의 모든 픽셀을 클래스별로 분할",
            "frameworks": ["transformers"],
            "supported": False  # Not yet implemented
        },
        {
            "name": "super_resolution",
            "display_name": "초해상화",
            "description": "저해상도 이미지를 고해상도로 업스케일",
            "frameworks": ["transformers"],
            "supported": False  # Not yet implemented
        }
    ]

    # Static dataset formats
    dataset_formats = [
        {
            "name": "imagefolder",
            "display_name": "ImageFolder",
            "description": "PyTorch ImageFolder 형식 (class/image.jpg)",
            "task_types": ["image_classification"],
            "supported": True
        },
        {
            "name": "yolo",
            "display_name": "YOLO Format",
            "description": "Ultralytics YOLO 형식 (images/, labels/, data.yaml)",
            "task_types": ["object_detection", "instance_segmentation", "pose_estimation"],
            "supported": True
        },
        {
            "name": "coco",
            "display_name": "COCO Format",
            "description": "MS COCO JSON 형식",
            "task_types": ["object_detection", "instance_segmentation"],
            "supported": False
        }
    ]

    # Static parameters
    parameters = [
        {
            "name": "framework",
            "display_name": "프레임워크",
            "description": "사용할 딥러닝 프레임워크",
            "type": "string",
            "required": True,
            "options": ["timm", "ultralytics", "transformers"],
            "default": "timm"
        },
        {
            "name": "task_type",
            "display_name": "작업 유형",
            "description": "수행할 작업의 종류",
            "type": "string",
            "required": True,
            "options": ["image_classification", "object_detection", "instance_segmentation", "pose_estimation", "semantic_segmentation", "super_resolution"],
            "default": "image_classification"
        },
        {
            "name": "model_name",
            "display_name": "모델 이름",
            "description": "사용할 모델",
            "type": "string",
            "required": True,
            "default": None
        },
        {
            "name": "num_classes",
            "display_name": "클래스 수",
            "description": "분류할 클래스의 개수 (classification 작업에만 필요)",
            "type": "integer",
            "required": False,
            "min": 2,
            "max": 1000,
            "default": None
        },
        {
            "name": "dataset_format",
            "display_name": "데이터셋 형식",
            "description": "데이터셋의 저장 형식",
            "type": "string",
            "required": False,
            "options": ["imagefolder", "yolo", "coco"],
            "default": "imagefolder"
        },
        {
            "name": "epochs",
            "display_name": "에포크",
            "description": "학습 반복 횟수",
            "type": "integer",
            "required": False,
            "min": 1,
            "max": 1000,
            "default": 50
        },
        {
            "name": "batch_size",
            "display_name": "배치 크기",
            "description": "한 번에 처리할 이미지 수",
            "type": "integer",
            "required": False,
            "min": 1,
            "max": 256,
            "default": 32
        },
        {
            "name": "learning_rate",
            "display_name": "학습률",
            "description": "모델 가중치 업데이트 비율",
            "type": "float",
            "required": False,
            "min": 0.00001,
            "max": 0.1,
            "default": 0.001
        },
        {
            "name": "dataset_path",
            "display_name": "데이터셋 경로",
            "description": "학습 데이터가 있는 폴더 경로",
            "type": "string",
            "required": True,
            "default": None
        }
    ]

    return {
        "frameworks": frameworks,
        "models": all_models,  # Dynamically fetched from Training Services
        "task_types": task_types,
        "dataset_formats": dataset_formats,
        "parameters": parameters
    }


@router.post("/sessions", response_model=chat.SessionResponse)
async def create_session(db: DBSession = Depends(get_db)):
    """Create a new chat session."""
    manager = ConversationManager(db)
    session = await manager.create_new_session()
    return session


@router.get("/sessions/{session_id}", response_model=chat.SessionResponse)
async def get_session(session_id: int, db: DBSession = Depends(get_db)):
    """Get a chat session by ID."""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions/{session_id}/messages", response_model=list[chat.MessageResponse])
async def get_messages(session_id: int, db: DBSession = Depends(get_db)):
    """Get all messages in a session."""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = (
        db.query(MessageModel)
        .filter(MessageModel.session_id == session_id)
        .order_by(MessageModel.created_at)
        .all()
    )
    return messages


@router.get("/sessions/{session_id}/export")
async def export_chat_log(session_id: int, db: DBSession = Depends(get_db)):
    """
    Export chat session as a downloadable text file.

    This endpoint returns the entire chat conversation in a human-readable format.
    """
    from fastapi.responses import PlainTextResponse
    from datetime import datetime

    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = (
        db.query(MessageModel)
        .filter(MessageModel.session_id == session_id)
        .order_by(MessageModel.created_at)
        .all()
    )

    # Build chat log text
    log_lines = []
    log_lines.append("=" * 80)
    log_lines.append(f"Chat Session Log - Session ID: {session_id}")
    log_lines.append(f"Created: {session.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    log_lines.append(f"Total Messages: {len(messages)}")
    log_lines.append("=" * 80)
    log_lines.append("")

    for msg in messages:
        timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
        role_label = "USER" if msg.role == "user" else "ASSISTANT"

        log_lines.append(f"[{timestamp}] {role_label}:")
        log_lines.append(msg.content)
        log_lines.append("")
        log_lines.append("-" * 80)
        log_lines.append("")

    log_text = "\n".join(log_lines)

    # Return as downloadable text file
    filename = f"chat_session_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    return PlainTextResponse(
        content=log_text,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.post("/message", response_model=chat.ChatResponse)
async def send_message(
    request: chat.ChatRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Authentication required
):
    """
    Send a message and get AI response.

    This endpoint (Phase 1+2 Refactored):
    1. Creates or retrieves a session
    2. Delegates to ConversationManager for processing
    3. Returns response with state information

    Requires authentication: User must be logged in.
    """
    logger.debug(f"Received chat request: session_id={request.session_id}, message={request.message[:50]}...")

    # Get authenticated user ID
    user_id = current_user.id

    try:
        # Create manager
        manager = ConversationManager(db)

        # Create or get session
        if request.session_id:
            session = db.query(SessionModel).filter(SessionModel.id == request.session_id).first()
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            session_id = session.id
        else:
            session = await manager.create_new_session()
            session_id = session.id

        logger.debug(f"Using session ID: {session_id}")

        # Process message through ConversationManager
        result = await manager.process_message(
            session_id=session_id,
            user_message=request.message,
            user_id=user_id  # Pass authenticated user ID
        )

        # Get the latest messages
        messages = (
            db.query(MessageModel)
            .filter(MessageModel.session_id == session_id)
            .order_by(MessageModel.created_at.desc())
            .limit(2)
            .all()
        )

        # Safely get assistant and user messages
        if len(messages) < 2:
            raise HTTPException(status_code=500, detail="Failed to retrieve messages")

        assistant_message = messages[0] if messages[0].role == "assistant" else messages[1]
        user_message = messages[1] if messages[0].role == "assistant" else messages[0]

        # Build response
        response = chat.ChatResponse(
            session_id=session_id,
            user_message=user_message,
            assistant_message=assistant_message,
            parsed_intent=None  # Will be populated if training started
        )

        # If training started, add training info to parsed_intent
        if result.get("training_job_id"):
            training_job = db.query(TrainingJob).filter(
                TrainingJob.id == result["training_job_id"]
            ).first()

            if training_job:
                response.parsed_intent = {
                    "status": "complete",
                    "config": {
                        "framework": training_job.framework,
                        "model_name": training_job.model_name,
                        "task_type": training_job.task_type,
                        "dataset_path": training_job.dataset_path,
                        "dataset_format": training_job.dataset_format,
                        "num_classes": training_job.num_classes,
                        "epochs": training_job.epochs,
                        "batch_size": training_job.batch_size,
                        "learning_rate": training_job.learning_rate,
                    },
                    "metadata": {
                        "project_id": training_job.project_id,
                        "experiment_name": training_job.experiment_name,
                        "tags": training_job.tags,
                        "notes": training_job.notes,
                    }
                }

        # Phase 1: Populate action-specific fields from ConversationManager result
        if result.get("dataset_analysis"):
            response.dataset_analysis = result["dataset_analysis"]
        if result.get("model_search_results"):
            response.model_search_results = result["model_search_results"]
        if result.get("recommended_models"):
            response.model_recommendations = result["recommended_models"]
        if result.get("available_datasets"):
            response.available_datasets = result["available_datasets"]
        if result.get("training_status"):
            response.training_status = result["training_status"]
        if result.get("inference_results"):
            response.inference_results = result["inference_results"]

        logger.debug(f"Response sent for session {session_id}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/sessions/{session_id}/reset")
async def reset_session(session_id: int, db: DBSession = Depends(get_db)):
    """
    Reset a session to initial state.

    Clears conversation state and temp_data.
    """
    manager = ConversationManager(db)
    success = manager.reset_session(session_id)

    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"message": "Session reset successfully", "session_id": session_id}


@router.get("/sessions/{session_id}/info")
async def get_session_info(session_id: int, db: DBSession = Depends(get_db)):
    """
    Get session information including state and temp_data.
    """
    manager = ConversationManager(db)
    info = manager.get_session_info(session_id)

    if not info:
        raise HTTPException(status_code=404, detail="Session not found")

    return info
