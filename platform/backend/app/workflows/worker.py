"""Temporal Worker for Training Workflows.

Phase 12: Temporal Orchestration & Backend Modernization

This worker processes training workflows from the Temporal task queue.

Usage:
    python -m app.workflows.worker

The worker connects to Temporal server and polls for:
- TrainingWorkflow executions
- Activity tasks (validate_dataset, execute_training, etc.)
"""

import asyncio
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file before anything else
backend_dir = Path(__file__).parent.parent.parent
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"[WORKER] Loaded .env from: {env_path}")
else:
    print(f"[WORKER] No .env file found at {env_path}, using environment variables")

# Add project root to path for imports
project_root = backend_dir.parent
sys.path.insert(0, str(project_root))

from temporalio.client import Client
from temporalio.worker import Worker

from app.core.config import settings
from app.workflows.training_workflow import (
    TrainingWorkflow,
    validate_dataset,
    create_clearml_task,
    execute_training,
    upload_final_model,
    cleanup_training_resources,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


async def main():
    """
    Start the Temporal worker.

    This worker will:
    1. Connect to Temporal server
    2. Poll the task queue for work
    3. Execute workflows and activities
    4. Report results back to Temporal
    """
    logger.info("=" * 80)
    logger.info("Starting Temporal Training Worker")
    logger.info("=" * 80)
    logger.info(f"Temporal Host: {settings.TEMPORAL_HOST}")
    logger.info(f"Temporal Namespace: {settings.TEMPORAL_NAMESPACE}")
    logger.info(f"Task Queue: {settings.TEMPORAL_TASK_QUEUE}")
    logger.info(f"Training Mode: {settings.TRAINING_MODE}")
    logger.info("=" * 80)

    # Connect to Temporal
    logger.info("Connecting to Temporal server...")
    client = await Client.connect(
        settings.TEMPORAL_HOST,
        namespace=settings.TEMPORAL_NAMESPACE
    )
    logger.info("Connected to Temporal server successfully")

    # Create and run worker
    logger.info(f"Creating worker for task queue: {settings.TEMPORAL_TASK_QUEUE}")
    worker = Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[TrainingWorkflow],
        activities=[
            validate_dataset,
            create_clearml_task,
            execute_training,
            upload_final_model,
            cleanup_training_resources,
        ],
    )

    logger.info("Worker created successfully")
    logger.info("=" * 80)
    logger.info("Worker is now polling for tasks...")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 80)

    # Run the worker
    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("\nReceived shutdown signal (Ctrl+C)")
        logger.info("Stopping worker gracefully...")
    except Exception as e:
        logger.error(f"Worker encountered an error: {e}", exc_info=True)
        raise
    finally:
        logger.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
