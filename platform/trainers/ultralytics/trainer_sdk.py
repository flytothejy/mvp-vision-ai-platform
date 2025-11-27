#!/usr/bin/env python3
"""
Vision AI Training Platform - Trainer SDK

Lightweight SDK for platform communication.
Single file, minimal dependencies.

Usage:
    from trainer_sdk import TrainerSDK

    sdk = TrainerSDK()
    sdk.report_started()

    # Download and convert dataset
    dataset_dir = sdk.download_dataset(dataset_id, '/tmp/dataset')
    sdk.convert_dataset(dataset_dir, 'dice', 'yolo')

    # Training loop
    for epoch in range(1, epochs + 1):
        metrics = train_one_epoch(...)
        sdk.report_progress(epoch, epochs, metrics)

    # Upload checkpoints and report completion
    best_uri = sdk.upload_checkpoint('/tmp/best.pt', 'best')
    sdk.report_completed(final_metrics, checkpoints={'best': best_uri})

Dependencies:
    - httpx: HTTP client with retry support
    - boto3: S3-compatible storage
    - PyYAML: Dataset configuration

Version: 1.0.0
Date: 2025-11-19
"""

__version__ = '1.0.0'

import glob as glob_module
import json
import logging
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import boto3
import httpx
import yaml
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

# ClearML (optional dependency - Phase 12.2)
try:
    from clearml import Task
    CLEARML_AVAILABLE = True
except ImportError:
    CLEARML_AVAILABLE = False

# Configure module logger
logger = logging.getLogger(__name__)


# =============================================================================
# Error Types
# =============================================================================

class ErrorType:
    """Structured error types for report_failed()"""
    DATASET_ERROR = 'DatasetError'       # Dataset not found, corrupted, invalid format
    CHECKPOINT_ERROR = 'CheckpointError' # Checkpoint not found, corrupted, incompatible
    CONFIG_ERROR = 'ConfigError'         # Invalid configuration, unsupported parameters
    RESOURCE_ERROR = 'ResourceError'     # Out of memory, GPU not available
    NETWORK_ERROR = 'NetworkError'       # S3 connection failed, callback failed
    FRAMEWORK_ERROR = 'FrameworkError'   # Framework-specific error (YOLO, timm, etc.)
    VALIDATION_ERROR = 'ValidationError' # Validation failed, NaN loss
    UNKNOWN_ERROR = 'UnknownError'       # Unexpected error


# =============================================================================
# Storage Clients
# =============================================================================

class StorageClient:
    """S3-compatible storage client for single bucket operations"""

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str):
        self.endpoint = endpoint
        self.bucket = bucket
        self.client = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=BotoConfig(
                signature_version='s3v4',
                retries={'max_attempts': 3, 'mode': 'standard'}
            )
        )

    def download_file(self, s3_key: str, local_path: str) -> str:
        """Download file from S3"""
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, s3_key, local_path)
        return local_path

    def upload_file(
        self,
        local_path: str,
        s3_key: str,
        content_type: str = 'application/octet-stream'
    ) -> str:
        """Upload file to S3"""
        extra_args = {'ContentType': content_type}
        self.client.upload_file(local_path, self.bucket, s3_key, ExtraArgs=extra_args)
        return f"s3://{self.bucket}/{s3_key}"

    def download_directory(self, prefix: str, local_dir: str) -> str:
        """Download all files under a prefix"""
        local_dir = Path(local_dir)
        local_dir.mkdir(parents=True, exist_ok=True)

        paginator = self.client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                s3_key = obj['Key']
                relative_path = s3_key[len(prefix):].lstrip('/')
                if relative_path:  # Skip the prefix directory itself
                    local_path = local_dir / relative_path
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    self.client.download_file(self.bucket, s3_key, str(local_path))

        return str(local_dir)


# =============================================================================
# Main SDK Class
# =============================================================================

class TrainerSDK:
    """
    Lightweight SDK for platform communication.

    Features:
    - Minimal dependencies (httpx, boto3, yaml)
    - Backend-proxied observability (MLflow, Loki, Prometheus handled by Backend)
    - Standardized callbacks and error types
    - Dual storage support (External for datasets, Internal for checkpoints)

    Environment Variables:
        Required:
        - CALLBACK_URL: Backend API base URL
        - JOB_ID: Training/Inference/Export job ID

        External Storage (Datasets):
        - EXTERNAL_STORAGE_ENDPOINT: S3 endpoint (default: http://localhost:9000)
        - EXTERNAL_STORAGE_ACCESS_KEY: Access key (default: minioadmin)
        - EXTERNAL_STORAGE_SECRET_KEY: Secret key (default: minioadmin)
        - EXTERNAL_BUCKET_DATASETS: Bucket name (default: training-datasets)

        Internal Storage (Checkpoints/Results):
        - INTERNAL_STORAGE_ENDPOINT: S3 endpoint (default: http://localhost:9002)
        - INTERNAL_STORAGE_ACCESS_KEY: Access key (default: minioadmin)
        - INTERNAL_STORAGE_SECRET_KEY: Secret key (default: minioadmin)
        - INTERNAL_BUCKET_CHECKPOINTS: Bucket name (default: training-checkpoints)
    """

    def __init__(self):
        """Initialize SDK from environment variables"""
        # Required environment variables
        self.callback_url = os.getenv('CALLBACK_URL')
        self.job_id = os.getenv('JOB_ID')

        if not self.callback_url:
            raise ValueError("CALLBACK_URL environment variable is required")
        if not self.job_id:
            raise ValueError("JOB_ID environment variable is required")

        # Track operation type for proper callback routing
        self._operation_type = 'training'

        # HTTP client with retry and timeout
        self.http_client = httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True
        )

        # Initialize storage clients
        self._init_storage_clients()

        # Initialize log buffer
        self._log_buffer: List[Dict[str, Any]] = []
        self._log_buffer_max = 50  # Max logs before flush
        self._log_flush_interval = 5.0  # Seconds

        logger.info(f"TrainerSDK initialized for job {self.job_id}")
        logger.info(f"Callback URL: {self.callback_url}")

    # =========================================================================
    # SDK Properties (Training Job Context)
    # =========================================================================

    @property
    def task_type(self) -> str:
        """Get task type from environment variable"""
        return os.getenv('TASK_TYPE', 'detection')

    @property
    def model_name(self) -> str:
        """Get model name from environment variable"""
        return os.getenv('MODEL_NAME', 'yolo11n')

    @property
    def dataset_id(self) -> str:
        """Get dataset ID from environment variable"""
        return os.getenv('DATASET_ID', '')

    @property
    def framework(self) -> str:
        """Get framework from environment variable"""
        return os.getenv('FRAMEWORK', 'ultralytics')

    # =========================================================================
    # Config Loading Methods
    # =========================================================================

    def get_basic_config(self) -> Dict[str, Any]:
        """
        Load basic config with priority: env vars > CONFIG JSON > CONFIG_ env vars > defaults.

        Basic config is common to all trainers.

        Priority:
        1. Direct environment variables (EPOCHS, BATCH_SIZE, LEARNING_RATE, etc.)
        2. CONFIG JSON (for values not found in env vars)
        3. CONFIG_ prefixed env vars (backward compatibility)
        4. Default values

        Returns:
            Dict with basic config parameters
        """
        # Load CONFIG JSON once
        config_json = {}
        config_str = os.getenv('CONFIG', '{}')
        try:
            config_json = json.loads(config_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse CONFIG JSON: {e}")

        def get_config_value(direct_env: str, config_key: str, legacy_env: str, default: Any, value_type=str) -> Any:
            """Get config value with priority: direct env > CONFIG JSON > legacy env > default"""
            # Priority 1: Direct environment variable
            if direct_env and os.getenv(direct_env):
                value = os.getenv(direct_env)
            # Priority 2: CONFIG JSON
            elif config_key and config_key in config_json:
                value = config_json[config_key]
            # Priority 3: Legacy CONFIG_ prefixed environment variable
            elif legacy_env and os.getenv(legacy_env):
                value = os.getenv(legacy_env)
            # Priority 4: Default value
            else:
                value = default

            # Convert to target type
            if value_type == int:
                return int(value)
            elif value_type == float:
                return float(value)
            elif value_type == bool:
                return str(value).lower() == 'true' if isinstance(value, str) else bool(value)
            else:
                return str(value)

        return {
            'imgsz': get_config_value('IMGSZ', 'imgsz', 'CONFIG_IMGSZ', '640', int),
            'epochs': get_config_value('EPOCHS', 'epochs', 'CONFIG_EPOCHS', '100', int),
            'batch': get_config_value('BATCH_SIZE', 'batch', 'CONFIG_BATCH', '16', int),
            'lr0': get_config_value('LEARNING_RATE', 'learning_rate', 'CONFIG_LR0', '0.01', float),
            'optimizer': get_config_value('OPTIMIZER', 'optimizer', 'CONFIG_OPTIMIZER', 'SGD', str),
            'augment': get_config_value('AUGMENT', 'augment', 'CONFIG_AUGMENT', 'True', bool),
            'device': get_config_value('DEVICE', 'device', 'CONFIG_DEVICE', '0', str),
            'workers': get_config_value('WORKERS', 'workers', 'CONFIG_WORKERS', '8', int),
            'patience': get_config_value('PATIENCE', 'patience', 'CONFIG_PATIENCE', '50', int),
        }

    def get_advanced_config(self) -> Dict[str, Any]:
        """
        Load advanced config from CONFIG JSON.

        Advanced config is framework-specific (e.g., Ultralytics mosaic, mixup).

        Priority:
        1. CONFIG JSON 'advanced_config' field
        2. ADVANCED_CONFIG environment variable (backward compatibility)
        3. Empty dict

        Returns:
            Dict with advanced config parameters
        """
        # Priority 1: CONFIG JSON
        config_str = os.getenv('CONFIG', '{}')
        try:
            config_json = json.loads(config_str)
            if 'advanced_config' in config_json:
                return config_json['advanced_config']
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse CONFIG JSON: {e}")

        # Priority 2: ADVANCED_CONFIG environment variable (backward compatibility)
        advanced_json = os.getenv('ADVANCED_CONFIG', '{}')
        try:
            return json.loads(advanced_json)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse ADVANCED_CONFIG: {e}")
            return {}

    def get_full_config(self) -> Dict[str, Any]:
        """
        Get merged basic and advanced config.

        Returns:
            Dict with 'basic' and 'advanced' keys
        """
        return {
            'basic': self.get_basic_config(),
            'advanced': self.get_advanced_config()
        }

    def _init_storage_clients(self):
        """Initialize dual storage clients"""
        # External Storage (Datasets)
        self.external_storage = StorageClient(
            endpoint=os.getenv('EXTERNAL_STORAGE_ENDPOINT', 'http://localhost:9000'),
            access_key=os.getenv('EXTERNAL_STORAGE_ACCESS_KEY', 'minioadmin'),
            secret_key=os.getenv('EXTERNAL_STORAGE_SECRET_KEY', 'minioadmin'),
            bucket=os.getenv('EXTERNAL_BUCKET_DATASETS', 'training-datasets')
        )

        # Internal Storage (Checkpoints/Results)
        self.internal_storage = StorageClient(
            endpoint=os.getenv('INTERNAL_STORAGE_ENDPOINT', 'http://localhost:9002'),
            access_key=os.getenv('INTERNAL_STORAGE_ACCESS_KEY', 'minioadmin'),
            secret_key=os.getenv('INTERNAL_STORAGE_SECRET_KEY', 'minioadmin'),
            bucket=os.getenv('INTERNAL_BUCKET_CHECKPOINTS', 'training-checkpoints')
        )

    def _get_timestamp(self) -> str:
        """Get current UTC timestamp in ISO format"""
        return datetime.now(timezone.utc).isoformat()

    def _send_callback(self, endpoint: str, data: Dict[str, Any]) -> None:
        """Send callback to Backend with retry"""
        url = f"{self.callback_url.rstrip('/')}/{endpoint.lstrip('/')}"

        try:
            response = self.http_client.post(url, json=data)
            response.raise_for_status()
            logger.debug(f"Callback sent: {endpoint} -> {response.status_code}")
        except httpx.HTTPStatusError as e:
            logger.error(f"Callback failed ({e.response.status_code}): {url}")
            logger.error(f"Response: {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Callback request failed: {e}")
            raise

    # =========================================================================
    # Lifecycle Functions (4)
    # =========================================================================

    def report_started(self, operation_type: str = 'training', total_epochs: Optional[int] = None) -> None:
        """
        Report job started.

        Args:
            operation_type: 'training', 'inference', or 'export'
            total_epochs: Total number of epochs (required for training)
        """
        # Store operation type for use in report_failed()
        self._operation_type = operation_type

        # Use appropriate endpoint and data format based on operation type
        if operation_type == 'inference':
            data = {
                'type': 'started',
                'job_id': int(self.job_id),
                'operation_type': operation_type,
                'timestamp': self._get_timestamp()
            }
            endpoint = f'/inference/jobs/{self.job_id}/callback/started'
        elif operation_type == 'export':
            data = {
                'type': 'started',
                'job_id': int(self.job_id),
                'operation_type': operation_type,
                'timestamp': self._get_timestamp()
            }
            endpoint = f'/export/jobs/{self.job_id}/callback/started'
        else:  # training - use TrainingProgressCallback format
            # Get total_epochs from config if not provided
            if total_epochs is None:
                config = self.get_basic_config()
                total_epochs = config.get('epochs', 100)

            # Store for later use
            self._total_epochs = total_epochs

            # Use TrainingProgressCallback format
            data = {
                'job_id': int(self.job_id),
                'status': 'running',
                'current_epoch': 0,
                'total_epochs': total_epochs,
                'progress_percent': 0.0,
                'metrics': None,
                'checkpoint_path': None
            }
            endpoint = f'/training/jobs/{self.job_id}/callback/progress'

        self._send_callback(endpoint, data)
        logger.info(f"Reported {operation_type} started for job {self.job_id}")

    def report_progress(
        self,
        epoch: int,
        total_epochs: int,
        metrics: Dict[str, float],
        extra_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Report training progress.

        Args:
            epoch: Current epoch (1-indexed)
            total_epochs: Total number of epochs
            metrics: Standardized metrics dict (must include 'loss')
            extra_data: Additional framework-specific data
        """
        progress_percent = (epoch / total_epochs) * 100

        # Convert metrics to Backend schema format
        callback_metrics = {
            'loss': metrics.get('loss'),
            'accuracy': metrics.get('accuracy') or metrics.get('mAP50-95'),
            'learning_rate': metrics.get('learning_rate') or metrics.get('lr'),
            'extra_metrics': metrics  # Include all metrics
        }

        data = {
            'job_id': int(self.job_id),
            'status': 'running',
            'current_epoch': epoch,
            'total_epochs': total_epochs,
            'progress_percent': progress_percent,
            'metrics': callback_metrics,
        }

        if extra_data:
            data['extra_data'] = extra_data

        # Send to Backend API
        self._send_callback(f'/training/jobs/{self.job_id}/callback/progress', data)
        logger.debug(f"Reported progress: epoch {epoch}/{total_epochs} ({progress_percent:.1f}%)")

        # ClearML Integration (Phase 12.2)
        if CLEARML_AVAILABLE:
            try:
                task = Task.current_task()
                if task:
                    # Log all metrics to ClearML
                    for metric_name, metric_value in metrics.items():
                        if metric_value is not None:
                            # Parse metric name to determine title and series
                            # e.g., "train/loss" → title="loss", series="train"
                            if '/' in metric_name:
                                series, title = metric_name.split('/', 1)
                            else:
                                title = metric_name
                                series = 'train'

                            task.get_logger().report_scalar(
                                title=title,
                                series=series,
                                value=float(metric_value),
                                iteration=epoch
                            )
                    logger.debug(f"Logged {len(metrics)} metrics to ClearML task")
            except Exception as e:
                # Don't fail training if ClearML logging fails
                logger.warning(f"Failed to log metrics to ClearML: {e}")

    def report_validation(
        self,
        epoch: int,
        task_type: str,
        primary_metric: Tuple[str, float],
        all_metrics: Dict[str, float],
        class_names: Optional[List[str]] = None,
        visualization_urls: Optional[Dict[str, str]] = None,
        per_class_metrics: Optional[Dict[str, Dict[str, float]]] = None
    ) -> None:
        """
        Report validation results.

        Args:
            epoch: Validation epoch
            task_type: 'detection', 'classification', 'segmentation', 'pose'
            primary_metric: Tuple of (metric_name, metric_value)
            all_metrics: All validation metrics
            class_names: List of class names
            visualization_urls: S3 URIs of validation plots
            per_class_metrics: Per-class AP, precision, recall
        """
        data = {
            'type': 'validation',
            'job_id': int(self.job_id),
            'epoch': epoch,
            'task_type': task_type,
            'primary_metric_name': primary_metric[0],
            'primary_metric_value': primary_metric[1],
            'metrics': all_metrics,
            'timestamp': self._get_timestamp()
        }

        if class_names:
            data['class_names'] = class_names
        if visualization_urls:
            data['visualization_urls'] = visualization_urls
        if per_class_metrics:
            data['per_class_metrics'] = per_class_metrics

        self._send_callback(f'/validation/jobs/{self.job_id}/results', data)
        logger.info(f"Reported validation: {primary_metric[0]}={primary_metric[1]:.4f}")

    def report_completed(
        self,
        final_metrics: Dict[str, float],
        checkpoints: Optional[Dict[str, str]] = None,
        total_epochs: Optional[int] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Report job completed successfully.

        Args:
            final_metrics: Final training/inference metrics
            checkpoints: Dict of checkpoint type to S3 URI
                        e.g., {'best': 's3://...', 'last': 's3://...'}
            total_epochs: Total epochs completed
            extra_data: Additional data
        """
        # Convert metrics to Backend schema format
        callback_metrics = {
            'loss': final_metrics.get('loss'),
            'accuracy': final_metrics.get('accuracy') or final_metrics.get('mAP50-95'),
            'learning_rate': final_metrics.get('learning_rate'),
            'extra_metrics': final_metrics
        }

        data = {
            'job_id': int(self.job_id),
            'status': 'completed',
            'total_epochs_completed': total_epochs or 0,
            'final_metrics': callback_metrics,
            'exit_code': 0,
        }

        if checkpoints:
            data['best_checkpoint_path'] = checkpoints.get('best')
            data['last_checkpoint_path'] = checkpoints.get('last')

        if extra_data:
            data['extra_data'] = extra_data

        self._send_callback(f'/training/jobs/{self.job_id}/callback/completion', data)
        logger.info(f"Reported completion for job {self.job_id}")

    def report_failed(
        self,
        error_type: str,
        message: str,
        traceback: Optional[str] = None,
        epochs_completed: int = 0
    ) -> None:
        """
        Report job failed.

        Args:
            error_type: Structured error type (use ErrorType class)
            message: Human-readable error message
            traceback: Full traceback string
            epochs_completed: Number of epochs completed before failure
        """
        data = {
            'job_id': int(self.job_id),
            'status': 'failed',
            'total_epochs_completed': epochs_completed,
            'error_message': f"[{error_type}] {message}",
            'exit_code': 1,
        }

        if traceback:
            data['traceback'] = traceback

        # Use appropriate endpoint based on operation type
        if self._operation_type == 'inference':
            endpoint = f'/inference/jobs/{self.job_id}/callback/completion'
        elif self._operation_type == 'export':
            endpoint = f'/export/jobs/{self.job_id}/callback/completion'
        else:  # training
            endpoint = f'/training/jobs/{self.job_id}/callback/completion'

        self._send_callback(endpoint, data)
        logger.error(f"Reported failure: {error_type} - {message}")

    # =========================================================================
    # Inference & Export Functions (2)
    # =========================================================================

    def report_inference_completed(
        self,
        total_images: int,
        total_time_ms: float,
        results: List[Dict[str, Any]],
        result_urls: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Report inference job completed.

        Args:
            total_images: Number of images processed
            total_time_ms: Total inference time in milliseconds
            results: Per-image results
            result_urls: S3 URIs of outputs
        """
        avg_time_ms = total_time_ms / total_images if total_images > 0 else 0

        data = {
            'type': 'inference_completed',
            'job_id': int(self.job_id),
            'status': 'completed',
            'total_images': total_images,
            'total_inference_time_ms': total_time_ms,
            'avg_inference_time_ms': avg_time_ms,
            'results': results,
            'timestamp': self._get_timestamp()
        }

        if result_urls:
            data['result_urls'] = result_urls

        self._send_callback(f'/inference/jobs/{self.job_id}/callback/completion', data)
        logger.info(f"Reported inference completed: {total_images} images in {total_time_ms:.1f}ms")

    def report_export_completed(
        self,
        export_format: str,
        output_s3_uri: str,
        file_size_bytes: int,
        metadata: Dict[str, Any]
    ) -> None:
        """
        Report export job completed.

        Args:
            export_format: 'onnx', 'tensorrt', 'coreml', etc.
            output_s3_uri: S3 URI of exported model
            file_size_bytes: Size of exported file
            metadata: Model metadata
        """
        data = {
            'type': 'export_completed',
            'job_id': int(self.job_id),
            'status': 'completed',
            'export_format': export_format,
            'output_s3_uri': output_s3_uri,
            'file_size_bytes': file_size_bytes,
            'metadata': metadata,
            'timestamp': self._get_timestamp()
        }

        self._send_callback(f'/export/jobs/{self.job_id}/callback/completion', data)
        logger.info(f"Reported export completed: {export_format} ({file_size_bytes} bytes)")

    @staticmethod
    def create_export_metadata(
        framework: str,
        model_name: str,
        export_format: str,
        task_type: str,
        input_shape: List[int],
        output_shape: List[List[int]],
        class_names: Optional[List[str]] = None,
        preprocessing: Optional[Dict[str, Any]] = None,
        postprocessing: Optional[Dict[str, Any]] = None,
        export_config: Optional[Dict[str, Any]] = None,
        **extra
    ) -> Dict[str, Any]:
        """
        Create standardized export metadata.

        Args:
            framework: 'ultralytics', 'timm', 'transformers'
            model_name: Model name (e.g., 'yolo11n')
            export_format: 'onnx', 'tensorrt', etc.
            task_type: 'detection', 'classification', etc.
            input_shape: Input tensor shape [H, W, C]
            output_shape: Output tensor shapes [[...], ...]
            class_names: List of class names
            preprocessing: Preprocessing config
            postprocessing: Postprocessing config
            export_config: Export configuration
            **extra: Additional metadata fields

        Returns:
            Standardized metadata dictionary
        """
        metadata = {
            'framework': framework,
            'model_name': model_name,
            'export_format': export_format,
            'task_type': task_type,
            'input_shape': input_shape,
            'input_dtype': 'float32',
            'output_shape': output_shape,
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        if class_names:
            metadata['class_names'] = class_names
            metadata['num_classes'] = len(class_names)

        if preprocessing:
            metadata['preprocessing'] = preprocessing

        if postprocessing:
            metadata['postprocessing'] = postprocessing

        if export_config:
            metadata['export_config'] = export_config

        # Add any extra fields
        metadata.update(extra)

        return metadata

    # =========================================================================
    # Storage Functions (4)
    # =========================================================================

    def upload_checkpoint(
        self,
        local_path: str,
        checkpoint_type: str,
        metrics: Optional[Dict[str, float]] = None
    ) -> str:
        """
        Upload checkpoint to Internal Storage.

        Args:
            local_path: Local file path
            checkpoint_type: 'best', 'last', or 'epoch_{n}'
            metrics: Metrics at checkpoint time

        Returns:
            S3 URI of uploaded checkpoint
        """
        filename = Path(local_path).name
        s3_key = f"checkpoints/{self.job_id}/{checkpoint_type}.pt"

        # Determine content type
        content_type = 'application/octet-stream'
        if filename.endswith('.pt') or filename.endswith('.pth'):
            content_type = 'application/x-pytorch'

        s3_uri = self.internal_storage.upload_file(local_path, s3_key, content_type)
        logger.info(f"Uploaded checkpoint: {checkpoint_type} -> {s3_uri}")

        # Optionally report checkpoint saved
        if metrics:
            self.log_event(
                'checkpoint',
                f'Saved {checkpoint_type} checkpoint',
                data={'s3_uri': s3_uri, 'metrics': metrics}
            )

        return s3_uri

    def download_checkpoint(self, s3_uri: str, local_path: str) -> str:
        """
        Download checkpoint from Internal Storage.

        Args:
            s3_uri: S3 URI of checkpoint (s3://bucket/key)
            local_path: Local destination path

        Returns:
            Local file path
        """
        # Parse S3 URI
        # s3://bucket/key -> key
        parts = s3_uri.replace('s3://', '').split('/', 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid S3 URI: {s3_uri}")

        bucket, key = parts
        return self.internal_storage.download_file(key, local_path)

    def download_dataset(self, dataset_id: str, dest_dir: str) -> str:
        """
        Download dataset from External Storage.

        Args:
            dataset_id: Dataset ID
            dest_dir: Local destination directory

        Returns:
            Local dataset directory path
        """
        prefix = f"datasets/{dataset_id}/"
        local_dir = self.external_storage.download_directory(prefix, dest_dir)
        logger.info(f"Downloaded dataset {dataset_id} to {local_dir}")
        return local_dir

    def upload_file(
        self,
        local_path: str,
        s3_key: str,
        content_type: str = 'application/octet-stream',
        storage_type: str = 'internal'
    ) -> str:
        """
        Upload arbitrary file to storage.

        Args:
            local_path: Local file path
            s3_key: S3 key (path within bucket)
            content_type: MIME type
            storage_type: 'internal' or 'external'

        Returns:
            S3 URI of uploaded file
        """
        storage = self.internal_storage if storage_type == 'internal' else self.external_storage
        return storage.upload_file(local_path, s3_key, content_type)

    # =========================================================================
    # Logging Functions (with buffering)
    # =========================================================================

    def log(
        self,
        message: str,
        level: str = 'INFO',
        source: str = 'trainer',
        **metadata
    ) -> None:
        """
        Log message with buffering support.

        Logs are buffered and sent in batches for efficiency.
        ERROR level logs are sent immediately.

        Args:
            message: Log message
            level: Log level ('DEBUG', 'INFO', 'WARNING', 'ERROR')
            source: Log source ('trainer', 'sdk', 'framework')
            **metadata: Additional metadata (e.g., epoch=5, step=100)
        """
        log_entry = {
            'level': level,
            'message': message,
            'timestamp': self._get_timestamp(),
            'source': source,
            'metadata': metadata if metadata else {}
        }

        # ERROR level sends immediately
        if level == 'ERROR':
            self._send_log_batch([log_entry])
            return

        # Add to buffer
        self._log_buffer.append(log_entry)

        # Flush if buffer is full
        if len(self._log_buffer) >= self._log_buffer_max:
            self.flush_logs()

    def log_info(self, message: str, **metadata) -> None:
        """Log INFO level message"""
        self.log(message, level='INFO', **metadata)

    def log_warning(self, message: str, **metadata) -> None:
        """Log WARNING level message"""
        self.log(message, level='WARNING', **metadata)

    def log_error(self, message: str, **metadata) -> None:
        """Log ERROR level message (sent immediately)"""
        self.log(message, level='ERROR', **metadata)

    def log_debug(self, message: str, **metadata) -> None:
        """Log DEBUG level message"""
        self.log(message, level='DEBUG', **metadata)

    def flush_logs(self) -> None:
        """Flush buffered logs to Backend"""
        if not self._log_buffer:
            return

        logs_to_send = self._log_buffer.copy()
        self._log_buffer.clear()

        self._send_log_batch(logs_to_send)

    def _send_log_batch(self, logs: List[Dict[str, Any]]) -> None:
        """Send batch of logs to Backend (sends each log individually)"""
        if not logs:
            return

        sent_count = 0
        for log_entry in logs:
            # Convert internal log format to LogEventCallback format
            callback_data = {
                'job_id': int(self.job_id),
                'event_type': log_entry.get('source', 'training'),  # source → event_type
                'message': log_entry.get('message', ''),
                'level': log_entry.get('level', 'INFO'),
                'data': log_entry.get('metadata', {}),
                'timestamp': log_entry.get('timestamp')
            }

            try:
                self._send_callback(f'/training/jobs/{self.job_id}/callback/log', callback_data)
                sent_count += 1
            except Exception as e:
                # Don't fail training if log fails
                logger.warning(f"Failed to send log: {e}")
                break  # Stop sending more logs if one fails

        if sent_count > 0:
            logger.debug(f"Sent {sent_count}/{len(logs)} logs to Backend")

    def log_event(
        self,
        event_type: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        level: str = 'INFO'
    ) -> None:
        """
        Log structured event to Backend (legacy method).

        Backend forwards to Loki for centralized logging.

        Args:
            event_type: Event category ('training', 'validation', 'checkpoint', 'error')
            message: Human-readable message
            data: Additional structured data
            level: Log level ('DEBUG', 'INFO', 'WARNING', 'ERROR')
        """
        callback_data = {
            'type': 'log_event',
            'job_id': int(self.job_id),
            'event_type': event_type,
            'message': message,
            'level': level,
            'timestamp': self._get_timestamp()
        }

        if data:
            callback_data['data'] = data

        try:
            self._send_callback(f'/training/jobs/{self.job_id}/callback/log', callback_data)
        except Exception as e:
            # Don't fail training if log event fails
            logger.warning(f"Failed to send log event: {e}")

    # =========================================================================
    # Data Utility Functions (5)
    # =========================================================================

    def convert_dataset(
        self,
        dataset_dir: str,
        source_format: str,
        target_format: str,
        split_config: Optional[Dict[str, Any]] = None,
        task_type: Optional[str] = None
    ) -> str:
        """
        Convert dataset between formats.

        Args:
            dataset_dir: Dataset directory path
            source_format: 'dice', 'coco', 'yolo', 'imagefolder'
            target_format: 'yolo', 'coco', 'imagefolder'
            split_config: Optional split configuration
                {
                    'train_ratio': 0.8,
                    'val_ratio': 0.2,
                    'seed': 42,
                    'splits': {'image_id': 'train'|'val'}
                }
            task_type: Optional task type for selecting annotation file
                      ('detection', 'classification', 'segmentation', 'pose')
                      If not provided, uses sdk.task_type

        Returns:
            Path to converted dataset
        """
        dataset_path = Path(dataset_dir)

        # Use SDK task_type if not provided
        if task_type is None:
            task_type = self.task_type

        # Currently support dice -> yolo conversion
        if source_format == 'dice' and target_format == 'yolo':
            return self._convert_dice_to_yolo(dataset_path, split_config, task_type)
        else:
            raise NotImplementedError(f"Conversion {source_format} -> {target_format} not implemented")

    def _convert_dice_to_yolo(
        self,
        dataset_dir: Path,
        split_config: Optional[Dict[str, Any]] = None,
        task_type: str = 'detection'
    ) -> str:
        """
        Convert DICEFormat (annotations.json) to YOLO format.

        Creates:
        - labels/*.txt (YOLO format labels)
        - train.txt, val.txt (image lists)
        - data.yaml (dataset config)

        Args:
            dataset_dir: Dataset directory path
            split_config: Split configuration
            task_type: Task type for selecting annotation file
                      ('detection', 'classification', 'segmentation', 'pose')
        """
        # Select annotation file based on task_type
        task_annotation_map = {
            'detection': 'annotations_detection.json',
            'object_detection': 'annotations_detection.json',
            'classification': 'annotations_classification.json',
            'image_classification': 'annotations_classification.json',
            'segmentation': 'annotations_segmentation.json',
            'instance_segmentation': 'annotations_segmentation.json',
            'pose': 'annotations_pose.json',
            'pose_estimation': 'annotations_pose.json',
        }

        # Get task-specific annotation file or fallback to generic
        annotation_filename = task_annotation_map.get(task_type, f'annotations_{task_type}.json')
        annotations_file = dataset_dir / annotation_filename

        # Fallback to generic annotations.json if task-specific doesn't exist
        if not annotations_file.exists():
            fallback_file = dataset_dir / "annotations.json"
            if fallback_file.exists():
                logger.info(f"Task-specific {annotation_filename} not found, using annotations.json")
                annotations_file = fallback_file
            else:
                logger.info(f"No annotation files found ({annotation_filename} or annotations.json), skipping DICE conversion")
                return str(dataset_dir)

        logger.info(f"Using annotation file: {annotations_file.name} for task_type={task_type}")

        # Load annotations
        with open(annotations_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        images = data.get('images', [])
        annotations = data.get('annotations', [])
        categories = data.get('categories', [])

        if not images:
            logger.warning("No images in annotations.json")
            return str(dataset_dir)

        logger.info(f"Converting DICE format: {len(images)} images, {len(annotations)} annotations")

        # Create category mapping (category_id -> index)
        category_map = {cat['id']: idx for idx, cat in enumerate(categories)}
        class_names = [cat['name'] for cat in categories]

        # Create image to annotations mapping
        image_annotations = {}
        for ann in annotations:
            image_id = ann['image_id']
            if image_id not in image_annotations:
                image_annotations[image_id] = []
            image_annotations[image_id].append(ann)

        # Create labels directory
        labels_dir = dataset_dir / "labels"
        labels_dir.mkdir(exist_ok=True)

        # Convert annotations to YOLO format
        for img in images:
            image_id = img['id']
            file_name = img['file_name']
            width = img['width']
            height = img['height']

            # Get image stem for label file
            img_stem = Path(file_name).stem
            label_file = labels_dir / f"{img_stem}.txt"

            # Get annotations for this image
            img_anns = image_annotations.get(image_id, [])

            # Convert to YOLO format
            yolo_lines = []
            for ann in img_anns:
                category_id = ann['category_id']
                bbox = ann['bbox']  # [x, y, width, height] in COCO format

                # Convert to YOLO format (normalized center x, y, width, height)
                x, y, w, h = bbox
                x_center = (x + w / 2) / width
                y_center = (y + h / 2) / height
                norm_w = w / width
                norm_h = h / height

                class_idx = category_map.get(category_id, 0)
                yolo_lines.append(f"{class_idx} {x_center:.6f} {y_center:.6f} {norm_w:.6f} {norm_h:.6f}")

            # Write label file
            with open(label_file, 'w') as f:
                f.write('\n'.join(yolo_lines))

        # Split dataset
        if split_config and 'splits' in split_config:
            # Use predefined splits
            splits = split_config['splits']
        else:
            # Random split
            train_ratio = split_config.get('train_ratio', 0.8) if split_config else 0.8
            val_ratio = split_config.get('val_ratio', 0.2) if split_config else 0.2
            seed = split_config.get('seed', 42) if split_config else 42

            splits = self.split_dataset(
                images,
                train_ratio=train_ratio,
                val_ratio=val_ratio,
                seed=seed
            )

        # Create train.txt and val.txt
        train_images = []
        val_images = []

        for img in images:
            image_id = img['id']
            file_name = img['file_name']

            # Handle both 'images/xxx.jpg' and 'xxx.jpg' formats
            if not file_name.startswith('images/'):
                image_path = f"images/{file_name}"
            else:
                image_path = file_name

            split = splits.get(image_id, 'train')
            if split == 'train':
                train_images.append(image_path)
            else:
                val_images.append(image_path)

        # Write split files
        with open(dataset_dir / "train.txt", 'w') as f:
            f.write('\n'.join(train_images))

        with open(dataset_dir / "val.txt", 'w') as f:
            f.write('\n'.join(val_images))

        logger.info(f"Split: {len(train_images)} train, {len(val_images)} val")

        # Create data.yaml
        self.create_data_yaml(
            str(dataset_dir),
            class_names,
            train_path='train.txt',
            val_path='val.txt'
        )

        # Clean cache files
        self.clean_dataset_cache(str(dataset_dir))

        logger.info("DICE to YOLO conversion completed")
        return str(dataset_dir)

    def create_data_yaml(
        self,
        dataset_dir: str,
        class_names: List[str],
        train_path: str = 'train.txt',
        val_path: str = 'val.txt',
        test_path: Optional[str] = None
    ) -> str:
        """
        Create YOLO-format data.yaml file.

        Args:
            dataset_dir: Dataset directory path
            class_names: List of class names (order matters)
            train_path: Path to train image list
            val_path: Path to val image list
            test_path: Optional path to test image list

        Returns:
            Path to created data.yaml
        """
        data_yaml_path = Path(dataset_dir) / "data.yaml"

        data_config = {
            'path': str(Path(dataset_dir).resolve()),
            'train': train_path,
            'val': val_path,
            'nc': len(class_names),
            'names': class_names
        }

        if test_path:
            data_config['test'] = test_path

        with open(data_yaml_path, 'w') as f:
            yaml.dump(data_config, f, default_flow_style=False, allow_unicode=True)

        logger.info(f"Created data.yaml with {len(class_names)} classes")
        return str(data_yaml_path)

    def split_dataset(
        self,
        images: List[Dict[str, Any]],
        train_ratio: float = 0.8,
        val_ratio: float = 0.2,
        test_ratio: float = 0.0,
        seed: int = 42,
        stratify_by: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Split dataset into train/val/test.

        Args:
            images: List of image dictionaries with 'id' key
            train_ratio: Ratio for training set
            val_ratio: Ratio for validation set
            test_ratio: Ratio for test set
            seed: Random seed for reproducibility
            stratify_by: Optional key to stratify by

        Returns:
            Dict mapping image_id to split name
        """
        random.seed(seed)

        # Normalize ratios
        total = train_ratio + val_ratio + test_ratio
        train_ratio /= total
        val_ratio /= total
        test_ratio /= total

        # Shuffle images
        shuffled = images.copy()
        random.shuffle(shuffled)

        # Split
        n = len(shuffled)
        train_end = int(n * train_ratio)
        val_end = train_end + int(n * val_ratio)

        splits = {}
        for i, img in enumerate(shuffled):
            image_id = img['id']
            if i < train_end:
                splits[image_id] = 'train'
            elif i < val_end:
                splits[image_id] = 'val'
            else:
                splits[image_id] = 'test'

        return splits

    def validate_dataset(
        self,
        dataset_dir: str,
        expected_format: str,
        min_images: int = 1,
        check_labels: bool = True
    ) -> Dict[str, Any]:
        """
        Validate dataset structure and content.

        Args:
            dataset_dir: Dataset directory path
            expected_format: 'yolo', 'coco', 'imagefolder'
            min_images: Minimum required images
            check_labels: Whether to validate labels exist

        Returns:
            Validation result with 'valid', 'issues', 'stats' keys
        """
        dataset_path = Path(dataset_dir)
        issues = []
        stats = {
            'total_images': 0,
            'total_labels': 0,
            'classes': [],
            'class_distribution': {}
        }

        if expected_format == 'yolo':
            # Check data.yaml
            data_yaml = dataset_path / "data.yaml"
            if not data_yaml.exists():
                issues.append("Missing data.yaml")
            else:
                with open(data_yaml, 'r') as f:
                    config = yaml.safe_load(f)
                stats['classes'] = config.get('names', [])

            # Check images
            images_dir = dataset_path / "images"
            if images_dir.exists():
                image_files = list(images_dir.glob('**/*.jpg')) + \
                             list(images_dir.glob('**/*.jpeg')) + \
                             list(images_dir.glob('**/*.png'))
                stats['total_images'] = len(image_files)

            # Check labels
            if check_labels:
                labels_dir = dataset_path / "labels"
                if labels_dir.exists():
                    label_files = list(labels_dir.glob('**/*.txt'))
                    stats['total_labels'] = len(label_files)

                    # Count class distribution
                    for label_file in label_files:
                        with open(label_file, 'r') as f:
                            for line in f:
                                parts = line.strip().split()
                                if parts:
                                    class_idx = int(parts[0])
                                    class_name = stats['classes'][class_idx] if class_idx < len(stats['classes']) else str(class_idx)
                                    stats['class_distribution'][class_name] = \
                                        stats['class_distribution'].get(class_name, 0) + 1

        # Check minimum images
        if stats['total_images'] < min_images:
            issues.append(f"Only {stats['total_images']} images found (minimum: {min_images})")

        # Check label count matches
        if check_labels and stats['total_labels'] < stats['total_images']:
            missing = stats['total_images'] - stats['total_labels']
            issues.append(f"Missing labels for {missing} images")

        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'stats': stats
        }

    def clean_dataset_cache(self, dataset_dir: str) -> int:
        """
        Remove stale cache files from dataset directory.

        YOLO creates .cache files that can cause issues when dataset is modified.
        This should be called after dataset conversion or modification.

        Args:
            dataset_dir: Dataset directory path

        Returns:
            Number of cache files deleted
        """
        cache_pattern = str(Path(dataset_dir) / "**/*.cache")
        cache_files = glob_module.glob(cache_pattern, recursive=True)

        deleted = 0
        for cache_file in cache_files:
            try:
                os.remove(cache_file)
                deleted += 1
                logger.debug(f"Deleted cache file: {cache_file}")
            except Exception as e:
                logger.warning(f"Failed to delete cache file {cache_file}: {e}")

        if deleted > 0:
            logger.info(f"Cleaned {deleted} cache files from {dataset_dir}")

        return deleted

    # =========================================================================
    # Cleanup
    # =========================================================================

    def close(self):
        """Close HTTP client and cleanup resources"""
        # Flush any remaining logs
        self.flush_logs()
        self.http_client.close()
        logger.debug("TrainerSDK closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


# =============================================================================
# Convenience Functions
# =============================================================================

def get_sdk() -> TrainerSDK:
    """
    Get or create a singleton TrainerSDK instance.

    Returns:
        TrainerSDK instance
    """
    if not hasattr(get_sdk, '_instance'):
        get_sdk._instance = TrainerSDK()
    return get_sdk._instance
