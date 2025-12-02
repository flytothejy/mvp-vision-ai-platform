"""Application configuration."""

import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    """Application settings."""

    # API Settings
    API_V1_PREFIX: str = "/api/v1"
    API_BASE_URL: str = "http://localhost:8000"  # Base URL for callbacks (override in production)
    PROJECT_NAME: str = "Vision AI Training Platform - MVP"
    BACKEND_PORT: int = 8000

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def BACKEND_CORS_ORIGINS(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    # Database (set via DATABASE_URL environment variable)
    # If not set, will use local SQLite in __init__
    DATABASE_URL: Optional[str] = None

    # Shared User Database (Phase 11: Microservice Separation)
    # Shared between Platform and Labeler for user authentication
    # If not set, will use separate SQLite in __init__
    USER_DATABASE_URL: Optional[str] = None

    # Redis (Phase 5: Multi-backend state management)
    # If not set, will default to localhost in main.py
    REDIS_URL: Optional[str] = "redis://localhost:6379/0"

    # LLM
    GOOGLE_API_KEY: str
    LLM_MODEL: str = "gemini-2.0-flash-exp"
    LLM_TEMPERATURE: float = 0.0
    # Security & Authentication
    JWT_SECRET: str = "your-secret-key-change-this-in-production-use-openssl-rand-hex-32"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Service-to-Service Authentication (Phase 11.5.6: Hybrid JWT)
    # Separate secret for inter-service JWTs (different from user JWT_SECRET)
    # Generated with: openssl rand -hex 32
    SERVICE_JWT_SECRET: str = "service-jwt-secret-change-in-production-use-openssl-rand-hex-32"

    # Storage Paths (will be converted to absolute paths)
    # Note: Paths are relative to project root (mvp-vision-ai-platform/)
    UPLOAD_DIR: str = "./data/uploads"
    OUTPUT_DIR: str = "./data/outputs"
    MODEL_DIR: str = "./data/models"
    LOG_DIR: str = "./data/logs"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Convert relative paths to absolute paths based on mvp directory
        # __file__ = mvp/backend/app/core/config.py
        # parent x3 = mvp/backend -> mvp/
        project_root = Path(__file__).parent.parent.parent.absolute()

        for attr in ['UPLOAD_DIR', 'OUTPUT_DIR', 'MODEL_DIR', 'LOG_DIR']:
            path_value = getattr(self, attr)
            if not os.path.isabs(path_value):
                # Convert relative path to absolute
                abs_path = project_root / path_value.lstrip('./')
                setattr(self, attr, str(abs_path))

        # Handle DATABASE_URL
        if not self.DATABASE_URL:
            # No DATABASE_URL set - use local SQLite
            db_path = project_root / 'data' / 'db' / 'vision_platform.db'
            self.DATABASE_URL = f'sqlite:///{db_path}'
            print(f"[CONFIG] Using local SQLite database: {db_path}")
        elif self.DATABASE_URL.startswith('sqlite:///./'):
            # Relative SQLite path - convert to absolute
            rel_path = self.DATABASE_URL.replace('sqlite:///./', '')
            abs_path = project_root / rel_path
            self.DATABASE_URL = f'sqlite:///{abs_path}'
            print(f"[CONFIG] Using SQLite database: {abs_path}")
        elif 'postgresql' in self.DATABASE_URL or 'postgres' in self.DATABASE_URL:
            # PostgreSQL URL from Railway - use as-is
            # Mask password for logging
            masked_url = self.DATABASE_URL.split('@')[0].split(':')[0] + ':***@' + self.DATABASE_URL.split('@')[1] if '@' in self.DATABASE_URL else self.DATABASE_URL
            print(f"[CONFIG] Using PostgreSQL database: {masked_url}")
        else:
            # Unknown database URL format
            print(f"[CONFIG] Using database URL: {self.DATABASE_URL}")

        # Handle USER_DATABASE_URL (Phase 11: Shared User DB)
        if not self.USER_DATABASE_URL:
            # No USER_DATABASE_URL set - use local SQLite (Tier 1)
            # Windows: C:\temp\shared_users.db
            # Linux/Mac: /tmp/shared_users.db
            import platform
            if platform.system() == 'Windows':
                user_db_path = Path('C:/temp/shared_users.db')
            else:
                user_db_path = Path('/tmp/shared_users.db')

            self.USER_DATABASE_URL = f'sqlite:///{user_db_path}'
            print(f"[CONFIG] Using shared SQLite User DB (Tier 1): {user_db_path}")
        elif self.USER_DATABASE_URL.startswith('sqlite:///./'):
            # Relative SQLite path - convert to absolute
            rel_path = self.USER_DATABASE_URL.replace('sqlite:///./', '')
            abs_path = project_root / rel_path
            self.USER_DATABASE_URL = f'sqlite:///{abs_path}'
            print(f"[CONFIG] Using shared SQLite User DB: {abs_path}")
        elif 'postgresql' in self.USER_DATABASE_URL or 'postgres' in self.USER_DATABASE_URL:
            # PostgreSQL URL (Tier 2: Railway or Tier 3: K8s)
            masked_url = self.USER_DATABASE_URL.split('@')[0].split(':')[0] + ':***@' + self.USER_DATABASE_URL.split('@')[1] if '@' in self.USER_DATABASE_URL else self.USER_DATABASE_URL
            print(f"[CONFIG] Using shared PostgreSQL User DB: {masked_url}")
        else:
            print(f"[CONFIG] Using shared User DB URL: {self.USER_DATABASE_URL}")

    # Training Service URLs (DEPRECATED - now using subprocess execution)
    # These URLs are kept for backward compatibility but are not actively used
    TIMM_SERVICE_URL: str = "http://localhost:8001"  # UNUSED
    # ULTRALYTICS_SERVICE_URL removed - using subprocess CLI execution
    HUGGINGFACE_SERVICE_URL: str = "http://localhost:8003"  # UNUSED

    # Labeler Service (Phase 11.5: Dataset Service Integration)
    # Labeler Backend is the Single Source of Truth for dataset metadata
    # Platform queries Labeler API for dataset information
    LABELER_API_URL: str = "http://localhost:8011"
    LABELER_SERVICE_KEY: str = "dev-labeler-service-key-change-in-production"

    # Training Defaults
    DEFAULT_BATCH_SIZE: int = 32
    DEFAULT_EPOCHS: int = 50
    DEFAULT_LEARNING_RATE: float = 0.001


    # Temporal Workflow Orchestration (Phase 12)
    TEMPORAL_HOST: str = "localhost:7233"
    TEMPORAL_NAMESPACE: str = "default"
    TEMPORAL_TASK_QUEUE: str = "training-tasks"

    # Training Execution Mode (Phase 12: TrainingManager)
    TRAINING_MODE: str = "subprocess"  # Options: "subprocess" (Tier 0), "kubernetes" (Tier 1+)

    # ClearML Configuration (Phase 12.2: Replaces MLflow)
    CLEARML_API_HOST: str = "http://localhost:8008"
    CLEARML_WEB_HOST: str = "http://localhost:8080"
    CLEARML_FILES_HOST: str = "http://localhost:8081"
    CLEARML_API_ACCESS_KEY: str = ""  # Empty for open-source server
    CLEARML_API_SECRET_KEY: str = ""  # Empty for open-source server
    CLEARML_DEFAULT_PROJECT: str = "Platform Training"

    # Observability Configuration (Phase 13: Multi-tool support)
    # Comma-separated list of observability backends to enable
    # Options: "database", "clearml", "mlflow", "tensorboard"
    # Example: "database,clearml" to use both Database and ClearML
    OBSERVABILITY_BACKENDS: str = "database"  # Default: database only

    # MLflow Configuration (optional, Phase 13)
    MLFLOW_TRACKING_URI: str = "http://localhost:5000"
    MLFLOW_ENABLED: bool = False

    # TensorBoard Configuration (optional, Phase 13)
    TENSORBOARD_LOG_DIR: str = "./data/tensorboard"
    TENSORBOARD_ENABLED: bool = False

    class Config:
        # Don't load .env file - use environment variables directly
        # Railway provides environment variables, not .env files
        # For local development, use .env file loaded by main.py
        case_sensitive = True
        extra = "ignore"


settings = Settings()
