"""FastAPI application entry point."""

import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file before anything else (only for local development)
# Railway provides environment variables directly, no .env file needed
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"[STARTUP] Loaded .env from: {env_path}")
else:
    print(f"[STARTUP] No .env file found at {env_path}, using environment variables")

# Add parent directory to sys.path for training module access
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.core.config import settings
from app.api import auth, chat, training, projects, debug, datasets, admin, validation, test_inference, models, image_tools, internal, invitations, export, inference, websocket
# Temporarily disabled: datasets_images, datasets_folder (Phase 11.5 Dataset model cleanup)

# Redis integration (Phase 5)
from app.services.redis_manager import RedisManager
from app.services.redis_session_store import RedisSessionStore

# Global instances for Redis
redis_manager: RedisManager = None
session_store: RedisSessionStore = None

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
)

# Log CORS origins for debugging
print(f"[CORS] Allowed origins: {settings.BACKEND_CORS_ORIGINS}")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup event to run migrations and initialize Redis
@app.on_event("startup")
async def startup_event():
    """Run startup tasks."""
    global redis_manager, session_store

    # Initialize Redis connection
    print("[STARTUP] Connecting to Redis...")
    try:
        redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
        redis_manager = RedisManager(redis_url=redis_url)
        await redis_manager.connect()

        # Initialize Session Store
        session_store = RedisSessionStore(redis_manager)

        print(f"[STARTUP] Redis connected: {redis_url}")
    except Exception as e:
        print(f"[STARTUP] WARNING: Redis connection failed: {e}")
        print("[STARTUP] Application will continue without Redis (graceful degradation)")
        redis_manager = None
        session_store = None

    # Initialize Temporal client (Phase 12: Workflow Orchestration)
    print("[STARTUP] Connecting to Temporal...")
    try:
        from app.core.temporal_client import get_temporal_client
        temporal_client = await get_temporal_client()
        print(f"[STARTUP] Temporal connected: {settings.TEMPORAL_HOST}")
    except Exception as e:
        print(f"[STARTUP] Temporal connection failed: {e}")
        print("[STARTUP] Application will continue without Temporal (workflows disabled)")


    print("[STARTUP] Running database migrations...")
    try:
        from sqlalchemy import create_engine, text, inspect

        db_url = settings.DATABASE_URL
        engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {}
        )

        inspector = inspect(engine)

        # Check if training_jobs table exists
        if 'training_jobs' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('training_jobs')]

            # Add dataset_id if missing
            if 'dataset_id' not in columns:
                print("[MIGRATION] Adding dataset_id column to training_jobs...")
                with engine.begin() as conn:
                    if db_url.startswith("sqlite"):
                        conn.execute(text("ALTER TABLE training_jobs ADD COLUMN dataset_id TEXT"))
                    else:
                        conn.execute(text("ALTER TABLE training_jobs ADD COLUMN dataset_id VARCHAR(100)"))

                    conn.execute(text("CREATE INDEX ix_training_jobs_dataset_id ON training_jobs(dataset_id)"))
                print("[MIGRATION] dataset_id column added successfully")
            else:
                print("[MIGRATION] dataset_id column already exists, skipping")

            # Add dataset_snapshot_id if missing
            if 'dataset_snapshot_id' not in columns:
                print("[MIGRATION] Adding dataset_snapshot_id column to training_jobs...")
                with engine.begin() as conn:
                    if db_url.startswith("sqlite"):
                        conn.execute(text("ALTER TABLE training_jobs ADD COLUMN dataset_snapshot_id TEXT"))
                    else:
                        conn.execute(text("ALTER TABLE training_jobs ADD COLUMN dataset_snapshot_id VARCHAR(100)"))

                    conn.execute(text("CREATE INDEX ix_training_jobs_dataset_snapshot_id ON training_jobs(dataset_snapshot_id)"))
                print("[MIGRATION] dataset_snapshot_id column added successfully")
            else:
                print("[MIGRATION] dataset_snapshot_id column already exists, skipping")

            # Add dataset_version if missing (deprecated but needed for backward compatibility)
            if 'dataset_version' not in columns:
                print("[MIGRATION] Adding dataset_version column to training_jobs...")
                with engine.begin() as conn:
                    if db_url.startswith("sqlite"):
                        conn.execute(text("ALTER TABLE training_jobs ADD COLUMN dataset_version INTEGER"))
                    else:
                        conn.execute(text("ALTER TABLE training_jobs ADD COLUMN dataset_version INTEGER"))
                print("[MIGRATION] dataset_version column added successfully")
            else:
                print("[MIGRATION] dataset_version column already exists, skipping")
        else:
            print("[MIGRATION] training_jobs table not found, skipping migration")
    except Exception as e:
        print(f"[WARNING] Migration failed: {e}")
        print("[INFO] Continuing with startup...")

# Shutdown event to cleanup resources
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources on application shutdown."""
    global redis_manager

    # Close Temporal client
    print("[SHUTDOWN] Closing Temporal client connection...")
    try:
        from app.core.temporal_client import close_temporal_client
        await close_temporal_client()
        print("[SHUTDOWN] Temporal client closed")
    except Exception as e:
        print(f"[SHUTDOWN] Error closing Temporal client: {e}")

    # Close Redis if initialized
    if redis_manager:
        print("[SHUTDOWN] Closing Redis connection...")
        try:
            await redis_manager.close()
            print("[SHUTDOWN] Redis connection closed")
        except Exception as e:
            print(f"[SHUTDOWN] Error closing Redis: {e}")

# Include routers
app.include_router(auth.router, prefix=f"{settings.API_V1_PREFIX}/auth", tags=["auth"])
app.include_router(chat.router, prefix=f"{settings.API_V1_PREFIX}/chat", tags=["chat"])
app.include_router(training.router, prefix=f"{settings.API_V1_PREFIX}/training", tags=["training"])
app.include_router(validation.router, prefix=f"{settings.API_V1_PREFIX}", tags=["validation"])
app.include_router(test_inference.router, prefix=f"{settings.API_V1_PREFIX}", tags=["test_inference"])
app.include_router(image_tools.router, prefix=f"{settings.API_V1_PREFIX}", tags=["image_tools"])  # Image tools
app.include_router(projects.router, prefix=f"{settings.API_V1_PREFIX}/projects", tags=["projects"])
# experiments.router removed - MLflow experiments replaced by ClearML Projects (Phase 12.2)
app.include_router(invitations.router, prefix=f"{settings.API_V1_PREFIX}", tags=["invitations"])
app.include_router(datasets.router, prefix=f"{settings.API_V1_PREFIX}/datasets", tags=["datasets"])
# Phase 11.5: Temporarily disabled until Dataset model cleanup complete
# app.include_router(datasets_images.router, prefix=f"{settings.API_V1_PREFIX}/datasets", tags=["datasets-images"])
# app.include_router(datasets_folder.router, prefix=f"{settings.API_V1_PREFIX}/datasets", tags=["datasets-folder"])
app.include_router(admin.router, prefix=f"{settings.API_V1_PREFIX}/admin", tags=["admin"])
app.include_router(debug.router, prefix=f"{settings.API_V1_PREFIX}/debug", tags=["debug"])
app.include_router(models.router, prefix=f"{settings.API_V1_PREFIX}", tags=["models"])  # Model registry
app.include_router(internal.router, prefix=f"{settings.API_V1_PREFIX}", tags=["internal"])  # Internal API for Training Services
app.include_router(export.router, prefix=f"{settings.API_V1_PREFIX}", tags=["export"])  # Export & Deployment
app.include_router(inference.router, tags=["inference"])  # Platform Inference (no API_V1_PREFIX - uses /v1 directly)
app.include_router(websocket.router, prefix=f"{settings.API_V1_PREFIX}", tags=["websocket"])  # WebSocket for real-time updates


@app.get("/health")
async def health_check():
    """Health check endpoint with Redis status."""
    health_status = {
        "status": "healthy",
        "service": "vision-ai-mvp-backend",
        "database": "connected",
        "redis": "unknown"
    }

    # Check Redis connection
    if redis_manager and redis_manager.is_connected:
        redis_healthy = await redis_manager.ping()
        health_status["redis"] = "connected" if redis_healthy else "disconnected"
    else:
        health_status["redis"] = "not_configured"

    # Overall status: healthy if DB connected (Redis optional)
    health_status["status"] = "healthy"

    return health_status


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Vision AI Training Platform - MVP",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ========== Background Tasks ==========

@app.on_event("startup")
async def start_background_tasks():
    """Start background tasks on application startup."""
    import asyncio
    from datetime import datetime, timedelta
    import shutil

    # Initialize database tables (Phase 11: Separate Platform and User DBs)
    print("[STARTUP] Initializing database tables...")
    from app.db.database import init_db, init_user_db, UserSessionLocal
    from app.db.models import User, UserRole
    from app.core.security import get_password_hash

    try:
        # Initialize Platform DB (projects, datasets, training jobs, etc.)
        init_db()
        print("[STARTUP] Platform DB tables initialized")

        # Initialize Shared User DB (users, organizations, invitations, etc.)
        init_user_db()
        print("[STARTUP] Shared User DB tables initialized")
    except Exception as e:
        print(f"[STARTUP] Database initialization error: {e}")
        # Don't crash the app if tables already exist

    # Create default admin user if no users exist (Phase 11: Use User DB)
    try:
        user_db = UserSessionLocal()
        user_count = user_db.query(User).count()

        if user_count == 0:
            admin_email = "admin@example.com"
            admin_password = "admin123"

            admin_user = User(
                email=admin_email,
                hashed_password=get_password_hash(admin_password),
                full_name="Admin User",
                system_role=UserRole.ADMIN,
                is_active=True
            )
            user_db.add(admin_user)
            user_db.commit()
            print(f"[STARTUP] Created default admin user in Shared User DB: {admin_email} / {admin_password}")
            print("[STARTUP] WARNING: IMPORTANT: Change the default password after first login!")
        else:
            print(f"[STARTUP] Found {user_count} existing user(s) in Shared User DB")

        user_db.close()
    except Exception as e:
        print(f"[STARTUP] Error creating admin user: {e}")

    async def cleanup_old_inference_sessions():
        """
        Periodically clean up old inference session directories.

        Runs every hour and deletes sessions where all files are older than 2 hours.
        Cleans up both inference_temp and image_tools_temp directories.
        """
        while True:
            try:
                await asyncio.sleep(3600)  # Run every 1 hour

                # Cleanup both inference_temp and image_tools_temp
                temp_dirs = [
                    Path(settings.UPLOAD_DIR) / "inference_temp",
                    Path(settings.UPLOAD_DIR) / "image_tools_temp"
                ]

                cutoff_time = datetime.now() - timedelta(hours=2)

                for temp_dir in temp_dirs:
                    if not temp_dir.exists():
                        continue

                    for session_dir in temp_dir.iterdir():
                        if not session_dir.is_dir():
                            continue

                        try:
                            # Check if all files in session are older than cutoff
                            files = list(session_dir.iterdir())

                            if not files:
                                # Empty directory - delete it
                                session_dir.rmdir()
                                print(f"[CLEANUP] Removed empty session: {session_dir.name}")
                                continue

                            all_old = all(
                                datetime.fromtimestamp(f.stat().st_mtime) < cutoff_time
                                for f in files
                            )

                            if all_old:
                                shutil.rmtree(session_dir)
                                print(f"[CLEANUP] Removed old session: {session_dir.name} ({len(files)} files)")

                        except Exception as e:
                            print(f"[CLEANUP] Error processing session {session_dir.name}: {e}")
                            continue

            except Exception as e:
                print(f"[CLEANUP] Background cleanup task error: {e}")
                # Continue running even if there's an error

    # Start the cleanup task
    asyncio.create_task(cleanup_old_inference_sessions())
    print("[STARTUP] Background cleanup task started (runs every 1 hour)")
