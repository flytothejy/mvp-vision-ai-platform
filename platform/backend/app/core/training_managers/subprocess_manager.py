"""
Subprocess Training Manager

Phase 12: Temporal Orchestration & Backend Modernization

Manages training jobs by executing Training Service CLI via subprocess (Tier 0).
This approach maintains consistency between local dev and K8s Job production.

Architecture:
- Backend executes Training Service's train.py using its dedicated venv
- Training Service has its own dependencies (ultralytics, torch, etc.)
- Same execution model for both local subprocess and K8s Job
- Implements TrainingManager abstract interface
"""

import asyncio
import io
import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

# Optional Loki integration (disabled on Windows due to query issues)
try:
    from logging_loki import LokiHandler
    LOKI_AVAILABLE = True
except ImportError:
    LOKI_AVAILABLE = False

from app.db.database import SessionLocal
from app.db import models
from app.core.training_manager import TrainingManager

logger = logging.getLogger(__name__)


class SubprocessTrainingManager(TrainingManager):
    """
    Manages training subprocesses for local development.

    Each framework (ultralytics, timm, huggingface) has its own Training Service
    with dedicated venv and dependencies.
    """

    def __init__(self):
        # Get Trainers base directory
        # __file__ = app/core/training_managers/subprocess_manager.py
        # parent x4 = app/core/training_managers -> app/core -> app -> backend
        self.backend_dir = Path(__file__).parent.parent.parent.parent
        self.platform_dir = self.backend_dir.parent
        self.trainers_dir = self.platform_dir / "trainers"

        logger.info(f"[TrainingSubprocess] Trainers directory: {self.trainers_dir}")

        # Store running processes
        self.processes: Dict[int, subprocess.Popen] = {}

        # Initialize Loki handler (optional - only if LOKI_URL is set)
        self.loki_url = os.getenv('LOKI_URL', 'http://localhost:3100')
        self.loki_enabled = os.getenv('LOKI_ENABLED', 'true').lower() == 'true'

        if self.loki_enabled:
            logger.info(f"[TrainingSubprocess] Loki logging enabled: {self.loki_url}")
        else:
            logger.info(f"[TrainingSubprocess] Loki logging disabled (using DB only)")

    def get_python_executable(self, framework: str) -> Path:
        """
        Get Python executable for a specific framework's Trainer.

        Args:
            framework: Framework name (ultralytics, timm, huggingface)

        Returns:
            Path to Python executable in Trainer's venv

        Raises:
            FileNotFoundError: If Trainer venv not found
        """
        trainer_dir = self.trainers_dir / framework

        # Check Windows path first
        python_exe = trainer_dir / "venv" / "Scripts" / "python.exe"
        if python_exe.exists():
            return python_exe

        # Check Linux/macOS path
        python_exe = trainer_dir / "venv" / "bin" / "python"
        if python_exe.exists():
            return python_exe

        raise FileNotFoundError(
            f"Trainer venv not found for {framework}. "
            f"Expected at: {trainer_dir / 'venv'}. "
            f"Please create venv: cd {trainer_dir} && python -m venv venv && venv/Scripts/pip install -r requirements.txt"
        )

    def get_trainer_directory(self, framework: str) -> Path:
        """Get Trainer directory for a framework."""
        trainer_dir = self.trainers_dir / framework

        if not trainer_dir.exists():
            raise FileNotFoundError(
                f"Trainer directory not found for {framework}: {trainer_dir}"
            )

        return trainer_dir

    async def start_training(
        self,
        job_id: int,
        framework: str,
        model_name: str,
        dataset_s3_uri: str,
        callback_url: str,
        config: Dict[str, Any],
        snapshot_id: str = None,
        dataset_version_hash: str = None,
    ) -> subprocess.Popen:
        """
        Start training subprocess.

        Args:
            job_id: Training job ID
            framework: Framework name (ultralytics, timm, huggingface)
            model_name: Model name to train
            dataset_s3_uri: S3 URI of dataset
            callback_url: Backend API callback URL
            config: Training configuration dictionary

        Returns:
            subprocess.Popen instance

        Raises:
            FileNotFoundError: If Training Service not found
            subprocess.CalledProcessError: If subprocess fails to start
        """
        try:
            # Get paths
            python_exe = self.get_python_executable(framework)
            trainer_dir = self.get_trainer_directory(framework)

            logger.info(f"[TrainingSubprocess] Starting job {job_id}")
            logger.info(f"[TrainingSubprocess]   Framework: {framework}")
            logger.info(f"[TrainingSubprocess]   Trainer dir: {trainer_dir}")
            logger.info(f"[TrainingSubprocess]   Python: {python_exe}")
            logger.info(f"[TrainingSubprocess]   Model: {model_name}")

            # Prepare command (K8s Job style - use env vars instead of CLI args)
            cmd = [
                str(python_exe),
                "train.py",
                "--log-level", "INFO",  # Only keep log-level as CLI arg for quick override
            ]

            logger.info(f"[TrainingSubprocess] Command: {' '.join(cmd)}")

            # Prepare environment (K8s Job style - all config via env vars)
            env = os.environ.copy()

            # Extract dataset_id from S3 URI (format: s3://bucket/datasets/{dataset_id}/)
            import re
            dataset_id_match = re.search(r'/datasets/([^/]+)/?$', dataset_s3_uri)
            dataset_id = dataset_id_match.group(1) if dataset_id_match else ""

            # ===== Environment Variables: Simple, Common Values =====
            env['JOB_ID'] = str(job_id)
            env['CALLBACK_URL'] = callback_url
            env['MODEL_NAME'] = model_name
            env['TASK_TYPE'] = config.get('task', 'detection')
            env['FRAMEWORK'] = framework
            env['DATASET_ID'] = dataset_id
            env['DATASET_S3_URI'] = dataset_s3_uri

            # Phase 12.9: Dataset caching parameters
            if snapshot_id:
                env['SNAPSHOT_ID'] = snapshot_id
            if dataset_version_hash:
                env['DATASET_VERSION_HASH'] = dataset_version_hash

            # Basic training parameters
            env['EPOCHS'] = str(config.get('epochs', 100))
            env['BATCH_SIZE'] = str(config.get('batch', 16))
            env['LEARNING_RATE'] = str(config.get('learning_rate', 0.01))
            env['IMGSZ'] = str(config.get('imgsz', 640))
            env['DEVICE'] = str(config.get('device', '0'))

            # ===== CONFIG JSON: Complex, Trainer-specific Settings =====
            advanced_config_json = {
                'advanced_config': config.get('advanced_config', {}),
                'primary_metric': config.get('primary_metric'),
                'primary_metric_mode': config.get('primary_metric_mode', 'max'),
                'split_config': config.get('split_config'),
            }
            # Remove None values
            advanced_config_json = {k: v for k, v in advanced_config_json.items() if v is not None}
            env['CONFIG'] = json.dumps(advanced_config_json)

            # Explicitly inject MinIO/Storage environment variables (for DualStorageClient)
            # These should already be in os.environ from Backend's .env, but we ensure they're passed
            storage_env_vars = [
                'EXTERNAL_STORAGE_ENDPOINT',
                'EXTERNAL_STORAGE_ACCESS_KEY',
                'EXTERNAL_STORAGE_SECRET_KEY',
                'EXTERNAL_BUCKET_DATASETS',
                'INTERNAL_STORAGE_ENDPOINT',
                'INTERNAL_STORAGE_ACCESS_KEY',
                'INTERNAL_STORAGE_SECRET_KEY',
                'INTERNAL_BUCKET_CHECKPOINTS',
            ]
            for var in storage_env_vars:
                if var in os.environ:
                    env[var] = os.environ[var]

            logger.info(f"[TrainingSubprocess] Environment variables set: JOB_ID={job_id}, MODEL_NAME={model_name}")

            # Start subprocess in background
            process = subprocess.Popen(
                cmd,
                cwd=str(trainer_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",  # Replace decode errors instead of failing
            )

            # Store process
            self.processes[job_id] = process

            logger.info(f"[TrainingSubprocess] Job {job_id} started (PID: {process.pid})")

            # Start async log monitoring (non-blocking)
            asyncio.create_task(self._monitor_process_logs(job_id, process))

            return process

        except FileNotFoundError as e:
            logger.error(f"[TrainingSubprocess] Setup error: {e}")
            raise
        except Exception as e:
            logger.error(f"[TrainingSubprocess] Failed to start job {job_id}: {e}")
            raise

    async def _monitor_process_logs(self, job_id: int, process: subprocess.Popen):
        """
        Monitor subprocess logs in background.

        This is a simple implementation that logs to console.
        For production, you should store logs in database or forward to Loki.
        """
        try:
            # Wrap stdout/stderr with explicit UTF-8 encoding to avoid Windows cp949 issues
            # Even though we set encoding="utf-8" on Popen, iteration over the stream
            # still uses system default encoding, so we need to wrap it explicitly
            stdout_reader = io.TextIOWrapper(
                process.stdout.buffer,
                encoding='utf-8',
                errors='replace'  # Replace undecodable bytes instead of failing
            )
            stderr_reader = io.TextIOWrapper(
                process.stderr.buffer,
                encoding='utf-8',
                errors='replace'
            )

            # IMPORTANT: Use asyncio.to_thread to avoid blocking the event loop
            # Reading from pipes is blocking I/O and should not be done directly in async functions

            async def read_stream_async(reader, prefix):
                """Read stream line by line and save to DB in real-time"""
                loop = asyncio.get_event_loop()
                batch = []
                batch_size = 10  # Save every 10 lines for efficiency

                def read_one_line():
                    """Read one line from stream (blocking)"""
                    try:
                        return reader.readline()
                    except Exception:
                        return None

                while True:
                    # Read line in thread pool to avoid blocking event loop
                    line = await loop.run_in_executor(None, read_one_line)

                    if not line:  # EOF
                        break

                    line = line.rstrip()
                    if not line.strip():
                        continue

                    # Log to console
                    if prefix == "stdout":
                        logger.info(f"[JOB {job_id}] {line}")
                    else:
                        logger.error(f"[JOB {job_id}] {line}")

                    # Add to batch
                    batch.append(line)

                    # Save batch to DB when full
                    if len(batch) >= batch_size:
                        await self._save_logs_to_db(job_id, batch, prefix)
                        batch = []

                # Save remaining logs
                if batch:
                    await self._save_logs_to_db(job_id, batch, prefix)

            # Read both streams concurrently (but in threads to avoid blocking)
            await asyncio.gather(
                read_stream_async(stdout_reader, "stdout"),
                read_stream_async(stderr_reader, "stderr")
            )

            # Wait for process to complete (also blocking, so run in thread)
            loop = asyncio.get_event_loop()
            exit_code = await loop.run_in_executor(None, process.wait)

            logger.info(f"[TrainingSubprocess] Job {job_id} finished (exit code: {exit_code})")

            # Remove from active processes
            if job_id in self.processes:
                del self.processes[job_id]

        except Exception as e:
            logger.error(f"[TrainingSubprocess] Error monitoring job {job_id}: {e}")

    async def _save_logs_to_db(self, job_id: int, lines: list[str], log_type: str):
        """
        Save log lines to database AND Loki (dual storage).

        Args:
            job_id: Training job ID
            lines: List of log lines
            log_type: "stdout" or "stderr"
        """
        try:
            # Run DB operations in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()

            def save_to_db():
                # Skip DB save for non-training jobs (export_, inference_, eval_)
                # These are short-lived tasks and report results via callbacks
                if not isinstance(job_id, int):
                    return
                    
                db = SessionLocal()
                try:
                    # Create log entries
                    log_entries = [
                        models.TrainingLog(
                            job_id=job_id,
                            log_type=log_type,
                            content=line,
                            created_at=datetime.utcnow()
                        )
                        for line in lines
                    ]

                    # Bulk insert for efficiency
                    db.bulk_save_objects(log_entries)
                    db.commit()

                except Exception as e:
                    logger.error(f"[TrainingSubprocess] Failed to save logs to DB: {e}")
                    db.rollback()
                finally:
                    db.close()

            # Save to DB
            await loop.run_in_executor(None, save_to_db)

            # Also send to Loki if enabled
            if self.loki_enabled:
                await self._send_logs_to_loki(job_id, lines, log_type)

        except Exception as e:
            logger.error(f"[TrainingSubprocess] Error in _save_logs_to_db: {e}")

    async def _send_logs_to_loki(self, job_id: int, lines: list[str], log_type: str):
        """
        Send log lines to Loki for real-time log aggregation.

        Args:
            job_id: Training job ID
            lines: List of log lines
            log_type: "stdout" or "stderr"
        """
        try:
            import requests

            # Loki Push API endpoint
            url = f"{self.loki_url}/loki/api/v1/push"

            # Build Loki streams payload
            # Loki uses nanosecond timestamps
            # Use single stream with multiple values for efficiency
            base_timestamp_ns = int(datetime.utcnow().timestamp() * 1_000_000_000)

            # Create values array with incrementing timestamps
            # This ensures each log line has a unique timestamp
            values = []
            for i, line in enumerate(lines):
                # Add microseconds to ensure uniqueness
                timestamp_ns = str(base_timestamp_ns + i * 1000)  # Add 1μs per line
                values.append([timestamp_ns, line])

            # Single stream for efficiency (Loki batches by stream)
            stream = {
                "stream": {
                    "job": "training",
                    "job_id": str(job_id),
                    "log_type": log_type,
                    "source": "backend"
                },
                "values": values
            }

            payload = {"streams": [stream]}

            # Send to Loki (async)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: requests.post(url, json=payload, timeout=5)
            )

        except Exception as e:
            # Don't fail if Loki is down - logs are still saved in DB
            logger.warning(f"[TrainingSubprocess] Failed to send logs to Loki: {e}")

    def stop_training(self, job_id: int) -> bool:
        """
        Stop a running training subprocess.

        Args:
            job_id: Training job ID to stop

        Returns:
            True if stopped successfully, False if not found or already stopped
        """
        try:
            if job_id not in self.processes:
                logger.warning(f"[TrainingSubprocess] Job {job_id} not found in active processes")
                return False

            process = self.processes[job_id]

            if process.poll() is None:
                # Process still running
                logger.info(f"[TrainingSubprocess] Terminating job {job_id} (PID: {process.pid})")
                process.terminate()

                # Wait up to 5 seconds for graceful shutdown
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"[TrainingSubprocess] Job {job_id} didn't terminate gracefully, killing")
                    process.kill()
                    process.wait()

                logger.info(f"[TrainingSubprocess] Job {job_id} stopped")
            else:
                logger.info(f"[TrainingSubprocess] Job {job_id} already finished")

            # Remove from active processes
            del self.processes[job_id]
            return True

        except Exception as e:
            logger.error(f"[TrainingSubprocess] Error stopping job {job_id}: {e}")
            return False

    def get_training_status(self, job_id: int) -> Optional[Dict[str, Any]]:
        """
        Get status of a training subprocess.

        Implements TrainingManager.get_training_status()

        Args:
            job_id: Training job ID

        Returns:
            Status dictionary or None if not found
        """
        if job_id not in self.processes:
            return None

        process = self.processes[job_id]
        exit_code = process.poll()

        return {
            "job_id": job_id,
            "pid": process.pid,
            "running": exit_code is None,
            "exit_code": exit_code,
        }

    async def start_evaluation(
        self,
        test_run_id: int,
        training_job_id: Optional[int],
        framework: str,
        checkpoint_s3_uri: str,
        dataset_s3_uri: str,
        callback_url: str,
        config: Dict[str, Any],
    ) -> subprocess.Popen:
        """
        Start evaluation subprocess (evaluate.py).

        Args:
            test_run_id: Test run ID
            training_job_id: Original training job ID (optional)
            framework: Framework name (ultralytics, timm, huggingface)
            checkpoint_s3_uri: S3 URI to checkpoint
            dataset_s3_uri: S3 URI to test dataset
            callback_url: Backend API callback URL
            config: Evaluation configuration dictionary

        Returns:
            subprocess.Popen instance

        Raises:
            FileNotFoundError: If Training Service not found
            subprocess.CalledProcessError: If subprocess fails to start
        """
        try:
            # Get paths
            python_exe = self.get_python_executable(framework)
            trainer_dir = self.get_trainer_directory(framework)

            logger.info(f"[EvaluationSubprocess] Starting test run {test_run_id}")
            logger.info(f"[EvaluationSubprocess]   Framework: {framework}")
            logger.info(f"[EvaluationSubprocess]   Trainer dir: {trainer_dir}")
            logger.info(f"[EvaluationSubprocess]   Python: {python_exe}")
            logger.info(f"[EvaluationSubprocess]   Checkpoint: {checkpoint_s3_uri}")

            # Prepare command (K8s Job style - use env vars instead of CLI args)
            cmd = [
                str(python_exe),
                "evaluate.py",
                "--log-level", "INFO",  # Only keep log-level as CLI arg for quick override
            ]

            logger.info(f"[EvaluationSubprocess] Command: {' '.join(cmd)}")

            # Prepare environment (K8s Job style - all config via env vars)
            env = os.environ.copy()

            # Evaluation job configuration (K8s Job compatible)
            env['TEST_RUN_ID'] = str(test_run_id)
            env['CHECKPOINT_S3_URI'] = checkpoint_s3_uri
            env['DATASET_S3_URI'] = dataset_s3_uri
            env['CALLBACK_URL'] = callback_url
            env['CONFIG'] = json.dumps(config)

            # Add training_job_id if provided
            if training_job_id:
                env['TRAINING_JOB_ID'] = str(training_job_id)

            # Inject MinIO/Storage environment variables
            storage_env_vars = [
                'EXTERNAL_STORAGE_ENDPOINT',
                'EXTERNAL_STORAGE_ACCESS_KEY',
                'EXTERNAL_STORAGE_SECRET_KEY',
                'EXTERNAL_BUCKET_DATASETS',
                'INTERNAL_STORAGE_ENDPOINT',
                'INTERNAL_STORAGE_ACCESS_KEY',
                'INTERNAL_STORAGE_SECRET_KEY',
                'INTERNAL_BUCKET_CHECKPOINTS',
            ]
            for var in storage_env_vars:
                if var in os.environ:
                    env[var] = os.environ[var]

            logger.info(f"[EvaluationSubprocess] Environment variables set: TEST_RUN_ID={test_run_id}")

            # Start subprocess in background
            process = subprocess.Popen(
                cmd,
                cwd=str(trainer_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            # Store process (use negative test_run_id to avoid collision with training jobs)
            process_key = f"test_{test_run_id}"
            self.processes[process_key] = process

            logger.info(f"[EvaluationSubprocess] Test run {test_run_id} started (PID: {process.pid})")

            # Start async log monitoring
            asyncio.create_task(self._monitor_process_logs(process_key, process))

            return process

        except FileNotFoundError as e:
            logger.error(f"[EvaluationSubprocess] Setup error: {e}")
            raise
        except Exception as e:
            logger.error(f"[EvaluationSubprocess] Failed to start test run {test_run_id}: {e}")
            raise

    async def start_inference(
        self,
        inference_job_id: int,
        training_job_id: Optional[int],
        framework: str,
        checkpoint_s3_uri: str,
        images_s3_uri: str,
        callback_url: str,
        config: Dict[str, Any],
    ) -> subprocess.Popen:
        """
        Start inference subprocess (predict.py).

        Args:
            inference_job_id: Inference job ID
            training_job_id: Original training job ID (optional)
            framework: Framework name (ultralytics, timm, huggingface)
            checkpoint_s3_uri: S3 URI to checkpoint
            images_s3_uri: S3 URI to input images
            callback_url: Backend API callback URL
            config: Inference configuration dictionary

        Returns:
            subprocess.Popen instance

        Raises:
            FileNotFoundError: If Training Service not found
            subprocess.CalledProcessError: If subprocess fails to start
        """
        try:
            # Get paths
            python_exe = self.get_python_executable(framework)
            trainer_dir = self.get_trainer_directory(framework)

            logger.info(f"[InferenceSubprocess] Starting inference job {inference_job_id}")
            logger.info(f"[InferenceSubprocess]   Framework: {framework}")
            logger.info(f"[InferenceSubprocess]   Trainer dir: {trainer_dir}")
            logger.info(f"[InferenceSubprocess]   Python: {python_exe}")
            logger.info(f"[InferenceSubprocess]   Checkpoint: {checkpoint_s3_uri}")

            # Prepare command (K8s Job style - use env vars instead of CLI args)
            cmd = [
                str(python_exe),
                "predict.py",
                "--log-level", "INFO",  # Only keep log-level as CLI arg for quick override
            ]

            logger.info(f"[InferenceSubprocess] Command: {' '.join(cmd)}")

            # Prepare environment (K8s Job style - all config via env vars)
            env = os.environ.copy()

            # Inference job configuration (K8s Job compatible)
            env['INFERENCE_JOB_ID'] = str(inference_job_id)
            env['CHECKPOINT_S3_URI'] = checkpoint_s3_uri
            env['IMAGES_S3_URI'] = images_s3_uri
            env['CALLBACK_URL'] = callback_url
            env['CONFIG'] = json.dumps(config)

            # Add training_job_id if provided
            if training_job_id:
                env['TRAINING_JOB_ID'] = str(training_job_id)

            # Inject MinIO/Storage environment variables
            storage_env_vars = [
                'EXTERNAL_STORAGE_ENDPOINT',
                'EXTERNAL_STORAGE_ACCESS_KEY',
                'EXTERNAL_STORAGE_SECRET_KEY',
                'EXTERNAL_BUCKET_DATASETS',
                'INTERNAL_STORAGE_ENDPOINT',
                'INTERNAL_STORAGE_ACCESS_KEY',
                'INTERNAL_STORAGE_SECRET_KEY',
                'INTERNAL_BUCKET_CHECKPOINTS',
            ]
            for var in storage_env_vars:
                if var in os.environ:
                    env[var] = os.environ[var]

            logger.info(f"[InferenceSubprocess] Environment variables set: INFERENCE_JOB_ID={inference_job_id}")

            # Start subprocess in background
            process = subprocess.Popen(
                cmd,
                cwd=str(trainer_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            # Store process (use negative inference_job_id to avoid collision)
            process_key = f"inference_{inference_job_id}"
            self.processes[process_key] = process

            logger.info(f"[InferenceSubprocess] Inference job {inference_job_id} started (PID: {process.pid})")

            # Start async log monitoring
            asyncio.create_task(self._monitor_process_logs(process_key, process))

            return process

        except FileNotFoundError as e:
            logger.error(f"[InferenceSubprocess] Setup error: {e}")
            raise
        except Exception as e:
            logger.error(f"[InferenceSubprocess] Failed to start inference job {inference_job_id}: {e}")
            raise

    async def start_export(
        self,
        export_job_id: int,
        training_job_id: int,
        framework: str,
        checkpoint_s3_uri: str,
        export_format: str,
        callback_url: str,
        config: Dict[str, Any],
    ) -> subprocess.Popen:
        """
        Start export subprocess (export.py).

        Args:
            export_job_id: Export job ID
            training_job_id: Original training job ID
            framework: Framework name (ultralytics, timm, huggingface)
            checkpoint_s3_uri: S3 URI to checkpoint
            export_format: Export format (onnx, tensorrt, coreml, tflite, torchscript, openvino)
            callback_url: Backend API callback URL
            config: Export configuration dictionary

        Returns:
            subprocess.Popen instance

        Raises:
            FileNotFoundError: If Training Service not found
            subprocess.CalledProcessError: If subprocess fails to start
        """
        try:
            # Get paths
            python_exe = self.get_python_executable(framework)
            trainer_dir = self.get_trainer_directory(framework)

            logger.info(f"[ExportSubprocess] Starting export job {export_job_id}")
            logger.info(f"[ExportSubprocess]   Framework: {framework}")
            logger.info(f"[ExportSubprocess]   Trainer dir: {trainer_dir}")
            logger.info(f"[ExportSubprocess]   Python: {python_exe}")
            logger.info(f"[ExportSubprocess]   Export format: {export_format}")
            logger.info(f"[ExportSubprocess]   Checkpoint: {checkpoint_s3_uri}")

            # Prepare command (K8s Job style - use env vars instead of CLI args)
            cmd = [
                str(python_exe),
                "export.py",
                "--log-level", "INFO",  # Only keep log-level as CLI arg for quick override
            ]

            logger.info(f"[ExportSubprocess] Command: {' '.join(cmd)}")

            # Prepare environment (K8s Job style - all config via env vars)
            env = os.environ.copy()

            # Export job configuration (K8s Job compatible)
            env['EXPORT_JOB_ID'] = str(export_job_id)
            env['TRAINING_JOB_ID'] = str(training_job_id)
            env['CHECKPOINT_S3_URI'] = checkpoint_s3_uri
            env['EXPORT_FORMAT'] = export_format
            env['CALLBACK_URL'] = callback_url
            env['CONFIG'] = json.dumps(config)

            # Inject MinIO/Storage environment variables
            storage_env_vars = [
                'EXTERNAL_STORAGE_ENDPOINT',
                'EXTERNAL_STORAGE_ACCESS_KEY',
                'EXTERNAL_STORAGE_SECRET_KEY',
                'EXTERNAL_BUCKET_DATASETS',
                'INTERNAL_STORAGE_ENDPOINT',
                'INTERNAL_STORAGE_ACCESS_KEY',
                'INTERNAL_STORAGE_SECRET_KEY',
                'INTERNAL_BUCKET_CHECKPOINTS',
            ]
            for var in storage_env_vars:
                if var in os.environ:
                    env[var] = os.environ[var]

            logger.info(f"[ExportSubprocess] Environment variables set: EXPORT_JOB_ID={export_job_id}")

            # Start subprocess in background
            process = subprocess.Popen(
                cmd,
                cwd=str(trainer_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            # Store process in registry (use f"export_{export_job_id}" to avoid collision)
            process_key = f"export_{export_job_id}"
            self.processes[process_key] = process

            logger.info(f"[ExportSubprocess] Export job {export_job_id} started (PID: {process.pid})")

            # Start async log monitoring
            asyncio.create_task(self._monitor_process_logs(process_key, process))

            return process

        except FileNotFoundError as e:
            logger.error(f"[ExportSubprocess] Setup error: {e}")
            raise
        except Exception as e:
            logger.error(f"[ExportSubprocess] Failed to start export job {export_job_id}: {e}")
            raise


    def cleanup_resources(self, job_id: int) -> None:
        """
        Clean up resources for a training job.

        Implements TrainingManager.cleanup_resources()

        This includes:
        - Stopping running processes
        - Removing from process tracking dictionary

        Args:
            job_id: Training job ID
        """
        logger.info(f"[SubprocessTrainingManager] Cleaning up resources for job {job_id}")

        # Stop training if still running
        self.stop_training(job_id)

        # Remove from process tracking
        if job_id in self.processes:
            del self.processes[job_id]
            logger.info(f"[SubprocessTrainingManager] Removed job {job_id} from process tracking")


# Global singleton instance (backward compatibility)
_training_subprocess_manager: Optional[SubprocessTrainingManager] = None


def get_training_subprocess_manager() -> SubprocessTrainingManager:
    """
    Get or create global SubprocessTrainingManager instance.

    Note: This function is kept for backward compatibility.
    New code should use get_training_manager() from app.core.training_manager instead.
    """
    global _training_subprocess_manager

    if _training_subprocess_manager is None:
        _training_subprocess_manager = SubprocessTrainingManager()

    return _training_subprocess_manager
