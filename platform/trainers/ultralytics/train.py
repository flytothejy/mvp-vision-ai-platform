#!/usr/bin/env python3
"""
Ultralytics YOLO Trainer (SDK Version)

Simple CLI script for training YOLO models using the Trainer SDK.
All observability (MLflow, Loki, Prometheus) is handled by Backend.

Usage:
    python train.py \\
        --job-id 123 \\
        --model-name yolo11n \\
        --dataset-s3-uri s3://bucket/datasets/abc-123/ \\
        --callback-url http://localhost:8000/api/v1/training \\
        --config '{"epochs": 50, "batch": 16, "imgsz": 640}'

Environment Variables (alternative to CLI args):
    JOB_ID, MODEL_NAME, DATASET_S3_URI, CALLBACK_URL, CONFIG

Exit Codes:
    0 = Success
    1 = Training failure
    2 = Callback failure
"""

import argparse
import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict

from ultralytics import YOLO

from trainer_sdk import ErrorType, TrainerSDK

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(description='Ultralytics YOLO Trainer')

    parser.add_argument('--job-id', type=str, help='Training job ID')
    parser.add_argument('--model-name', type=str, help='YOLO model name (e.g., yolo11n)')
    parser.add_argument('--dataset-s3-uri', type=str, help='S3 URI to dataset')
    parser.add_argument('--callback-url', type=str, help='Backend API base URL')
    parser.add_argument('--config', type=str, help='Training config JSON string')
    parser.add_argument('--config-file', type=str, help='Path to training config JSON file')
    parser.add_argument('--log-level', type=str, default='INFO', help='Logging level')

    return parser.parse_args()


def load_config(args) -> Dict[str, Any]:
    """Load configuration from args or environment"""
    # Priority: CLI args > env vars
    job_id = args.job_id or os.getenv('JOB_ID')
    model_name = args.model_name or os.getenv('MODEL_NAME')
    dataset_s3_uri = args.dataset_s3_uri or os.getenv('DATASET_S3_URI')
    callback_url = args.callback_url or os.getenv('CALLBACK_URL')

    if args.config_file:
        with open(args.config_file, 'r') as f:
            config = json.load(f)
    elif args.config:
        config = json.loads(args.config)
    elif os.getenv('CONFIG'):
        config = json.loads(os.getenv('CONFIG'))
    else:
        config = {}

    # Validate required fields
    if not all([job_id, model_name, dataset_s3_uri, callback_url]):
        raise ValueError("Missing required arguments: job_id, model_name, dataset_s3_uri, callback_url")

    # Set environment variables for SDK
    os.environ['JOB_ID'] = str(job_id)
    os.environ['CALLBACK_URL'] = callback_url

    return {
        'job_id': job_id,
        'model_name': model_name,
        'dataset_s3_uri': dataset_s3_uri,
        'callback_url': callback_url,
        'config': config
    }


def calculate_fitness(metrics: dict, primary_metric: str, primary_metric_mode: str = "max") -> float:
    """
    Calculate fitness score based on primary_metric configuration.

    Args:
        metrics: Trainer metrics dictionary
        primary_metric: Metric name to optimize (e.g., 'mAP50', 'mAP50-95', 'precision')
        primary_metric_mode: 'max' (higher is better) or 'min' (lower is better)

    Returns:
        Fitness score (higher is always better)
    """
    # Map user-friendly metric names to YOLO metric keys
    metric_key_map = {
        'mAP50': 'metrics/mAP50(B)',
        'mAP50-95': 'metrics/mAP50-95(B)',
        'precision': 'metrics/precision(B)',
        'recall': 'metrics/recall(B)',
        'loss': 'val/box_loss',
        'box_loss': 'val/box_loss',
        'cls_loss': 'val/cls_loss',
        'dfl_loss': 'val/dfl_loss',
    }

    metric_key = metric_key_map.get(primary_metric, primary_metric)
    fitness_value = metrics.get(metric_key, 0.0)

    # For 'min' metrics (like loss), invert so higher is better
    if primary_metric_mode == "min":
        fitness_value = -float(fitness_value) if fitness_value else 0.0
    else:
        fitness_value = float(fitness_value)

    return fitness_value


def train_model(
    job_id: str,
    model_name: str,
    dataset_s3_uri: str,
    config: Dict[str, Any]
) -> int:
    """
    Main training function

    Returns:
        Exit code (0 = success, 1 = training failure, 2 = callback failure)
    """
    # Training state tracking
    training_state = {
        'current_epoch': 0,
        'best_metric': 0.0
    }

    # Initialize SDK
    sdk = TrainerSDK()

    try:
        logger.info("=" * 80)
        logger.info(f"Ultralytics Training Service - Job {job_id}")
        logger.info("=" * 80)
        logger.info(f"Model: {model_name}")
        logger.info(f"Dataset: {dataset_s3_uri}")
        logger.info(f"Training config: {json.dumps(config, indent=2)}")
        logger.info("=" * 80)

        # Report started
        sdk.report_started('training')

        # Extract dataset ID from S3 URI
        dataset_id = dataset_s3_uri.rstrip('/').split('/')[-1]

        # Phase 12.9: Check for caching parameters
        snapshot_id = os.getenv('SNAPSHOT_ID')
        dataset_version_hash = os.getenv('DATASET_VERSION_HASH')

        # Download dataset (with caching if parameters provided)
        job_working_dir = Path(f"/tmp/training/{job_id}")

        if snapshot_id and dataset_version_hash:
            # Phase 12.9: Download with caching + selective download
            logger.info(f"[Phase 12.9] Downloading dataset with caching")
            logger.info(f"  SNAPSHOT_ID: {snapshot_id}")
            logger.info(f"  DATASET_VERSION_HASH: {dataset_version_hash}")
            dataset_dir = Path(sdk.download_dataset_with_cache(
                snapshot_id=snapshot_id,
                dataset_id=dataset_id,
                dataset_version_hash=dataset_version_hash,
                dest_dir=str(job_working_dir)
            ))
            logger.info(f"Dataset ready at {dataset_dir}")
        else:
            # Legacy: Download without caching
            dataset_dir = Path(f"/tmp/training/{job_id}/dataset")
            logger.info(f"Downloading dataset from {dataset_s3_uri}")
            sdk.download_dataset(dataset_id, str(dataset_dir))
            logger.info(f"Dataset downloaded to {dataset_dir}")

        # Convert DICEFormat to YOLO if needed
        split_config = config.get('split_config')
        sdk.convert_dataset(str(dataset_dir), 'dice', 'yolo', split_config)

        # Extract training parameters
        epochs = config.get('epochs', 50)
        batch_size = config.get('batch', 16)
        image_size = config.get('imgsz', 640)
        device = config.get('device', 'cpu')
        primary_metric = config.get('primary_metric', 'mAP50-95')
        primary_metric_mode = config.get('primary_metric_mode', 'max')

        # Extract advanced config parameters
        advanced_params = {}
        advanced_keys = [
            'optimizer', 'weight_decay', 'momentum',
            'cos_lr', 'lrf', 'warmup_epochs', 'warmup_momentum', 'warmup_bias_lr',
            'mosaic', 'mixup', 'copy_paste', 'degrees', 'translate', 'scale',
            'shear', 'perspective', 'flipud', 'fliplr', 'hsv_h', 'hsv_s', 'hsv_v',
            'amp', 'close_mosaic', 'val'
        ]
        for key in advanced_keys:
            if key in config:
                advanced_params[key] = config[key]

        logger.info(f"Advanced config parameters: {list(advanced_params.keys())}")

        # Log training start event
        sdk.log_event(
            'training',
            f'Starting training: {model_name} for {epochs} epochs',
            data={
                'model_name': model_name,
                'epochs': epochs,
                'batch_size': batch_size,
                'device': device,
                'primary_metric': primary_metric
            }
        )

        # Load model
        logger.info(f"Loading model: {model_name}")
        model = YOLO(f"{model_name}.pt")

        # Track logged epochs to prevent duplicates
        logged_epochs = set()

        # Epoch callback for progress updates
        def on_fit_epoch_end(trainer):
            """Called at end of each fit epoch"""
            try:
                nonlocal training_state, logged_epochs

                epoch = trainer.epoch + 1

                # Prevent duplicate logging
                if epoch in logged_epochs:
                    return

                logged_epochs.add(epoch)
                training_state['current_epoch'] = epoch

                # Extract metrics
                metrics = {}
                if hasattr(trainer, 'metrics') and trainer.metrics:
                    metrics = {k: float(v) if isinstance(v, (int, float)) else v
                               for k, v in trainer.metrics.items()}

                # Add train losses
                if hasattr(trainer, 'tloss') and trainer.tloss is not None:
                    train_loss_dict = trainer.label_loss_items(trainer.tloss, prefix="train")
                    if train_loss_dict:
                        metrics.update(train_loss_dict)

                # Calculate custom fitness
                custom_fitness = calculate_fitness(metrics, primary_metric, primary_metric_mode)
                metrics['fitness'] = custom_fitness

                # Override YOLO's fitness
                if hasattr(trainer, 'best_fitness'):
                    current_best = trainer.best_fitness
                    if custom_fitness > current_best:
                        trainer.best_fitness = custom_fitness
                        logger.info(f"[FITNESS] New best {primary_metric}! {custom_fitness:.4f}")

                # Send progress callback
                callback_interval = int(os.getenv('CALLBACK_INTERVAL', '1'))
                if epoch % callback_interval == 0 or epoch == epochs:
                    # Convert YOLO metrics to standardized format
                    standardized_metrics = {
                        'loss': metrics.get('train/box_loss', 0.0),
                        'box_loss': metrics.get('train/box_loss', 0.0),
                        'cls_loss': metrics.get('train/cls_loss', 0.0),
                        'dfl_loss': metrics.get('train/dfl_loss', 0.0),
                        'mAP50': metrics.get('metrics/mAP50(B)', 0.0),
                        'mAP50-95': metrics.get('metrics/mAP50-95(B)', 0.0),
                        'precision': metrics.get('metrics/precision(B)', 0.0),
                        'recall': metrics.get('metrics/recall(B)', 0.0),
                        'fitness': custom_fitness
                    }

                    sdk.report_progress(
                        epoch=epoch,
                        total_epochs=epochs,
                        metrics=standardized_metrics,
                        extra_data={'raw_metrics': metrics}
                    )

            except Exception as e:
                logger.error(f"Error in epoch callback: {e}")

        # Add callback
        model.add_callback("on_fit_epoch_end", on_fit_epoch_end)

        # Run training
        logger.info(f"Training {model_name} for {epochs} epochs")

        # Allow local dataset override for testing
        local_dataset_override = os.getenv('LOCAL_DATASET_PATH')
        if local_dataset_override:
            dataset_dir = Path(local_dataset_override)
            logger.warning(f"[DEBUG] Using LOCAL_DATASET_PATH override: {dataset_dir}")

        data_yaml = dataset_dir / "data.yaml"
        project_dir = Path(f"/tmp/training/{job_id}/runs")

        # Build training arguments
        train_args = {
            'data': str(data_yaml),
            'epochs': epochs,
            'batch': batch_size,
            'imgsz': image_size,
            'device': device,
            'project': str(project_dir),
            'name': 'train',
            'exist_ok': True,
            'verbose': True,
        }
        train_args.update(advanced_params)

        logger.info(f"Training with {len(train_args)} parameters")
        results = model.train(**train_args)

        logger.info("Training completed")

        # Upload checkpoints
        best_pt = project_dir / "train" / "weights" / "best.pt"
        last_pt = project_dir / "train" / "weights" / "last.pt"

        best_checkpoint_uri = None
        last_checkpoint_uri = None

        if best_pt.exists():
            logger.info("Uploading best checkpoint...")
            best_checkpoint_uri = sdk.upload_checkpoint(str(best_pt), 'best')

        if last_pt.exists():
            logger.info("Uploading last checkpoint...")
            last_checkpoint_uri = sdk.upload_checkpoint(str(last_pt), 'last')

        # Extract final metrics
        final_metrics = {}
        if hasattr(results, 'results_dict'):
            final_metrics = results.results_dict
        elif hasattr(results, 'box'):
            final_metrics = {
                'mAP50': float(results.box.map50),
                'mAP50-95': float(results.box.map),
                'precision': float(results.box.mp),
                'recall': float(results.box.mr),
            }

        # Process validation results
        try:
            logger.info("Processing validation results...")

            # Find and upload validation plots
            plots_dir = project_dir / "train"
            visualization_urls = {}

            plot_files = {
                'confusion_matrix': 'confusion_matrix.png',
                'confusion_matrix_normalized': 'confusion_matrix_normalized.png',
                'f1_curve': 'F1_curve.png',
                'pr_curve': 'PR_curve.png',
                'p_curve': 'P_curve.png',
                'r_curve': 'R_curve.png',
            }

            for plot_name, plot_file in plot_files.items():
                plot_path = plots_dir / plot_file
                if plot_path.exists():
                    try:
                        s3_key = f"job{job_id}/validation/{plot_file}"
                        plot_uri = sdk.upload_file(
                            str(plot_path),
                            s3_key,
                            content_type='image/png',
                            storage_type='internal'
                        )
                        visualization_urls[plot_name] = plot_uri
                        logger.info(f"Uploaded {plot_file}")
                    except Exception as e:
                        logger.warning(f"Failed to upload {plot_file}: {e}")

            # Extract class names
            import yaml as yaml_module
            class_names = None
            try:
                with open(data_yaml, 'r') as f:
                    data_config = yaml_module.safe_load(f)
                    class_names = data_config.get('names', [])
            except Exception as e:
                logger.warning(f"Failed to extract class names: {e}")

            # Determine task type
            task_type = 'detection'
            if 'seg' in model_name.lower():
                task_type = 'segmentation'
            elif 'pose' in model_name.lower():
                task_type = 'pose'
            elif 'cls' in model_name.lower():
                task_type = 'classification'

            # Send validation results
            primary_value = final_metrics.get('mAP50-95') or final_metrics.get('metrics/mAP50-95(B)', 0.0)
            sdk.report_validation(
                epoch=epochs,
                task_type=task_type,
                primary_metric=('mAP50-95', float(primary_value)),
                all_metrics=final_metrics,
                class_names=class_names,
                visualization_urls=visualization_urls if visualization_urls else None
            )
            logger.info(f"Validation results sent")

        except Exception as e:
            logger.warning(f"Failed to process validation results: {e}")

        # Prepare checkpoints dict
        checkpoints = {}
        if best_checkpoint_uri:
            checkpoints['best'] = best_checkpoint_uri
        if last_checkpoint_uri:
            checkpoints['last'] = last_checkpoint_uri

        # Send completion
        sdk.report_completed(
            final_metrics=final_metrics,
            checkpoints=checkpoints if checkpoints else None,
            total_epochs=epochs
        )

        logger.info("Training completed successfully")
        sdk.close()
        return 0

    except Exception as e:
        logger.error(f"Training failed for job {job_id}")
        logger.error(traceback.format_exc())

        # Determine error type
        error_type = ErrorType.UNKNOWN_ERROR
        error_msg = str(e)

        if 'CUDA' in error_msg or 'memory' in error_msg.lower():
            error_type = ErrorType.RESOURCE_ERROR
        elif 'dataset' in error_msg.lower() or 'not found' in error_msg.lower():
            error_type = ErrorType.DATASET_ERROR
        elif 'config' in error_msg.lower() or 'parameter' in error_msg.lower():
            error_type = ErrorType.CONFIG_ERROR

        try:
            sdk.report_failed(
                error_type=error_type,
                message=error_msg,
                traceback=traceback.format_exc(),
                epochs_completed=training_state.get('current_epoch', 0)
            )
        except Exception as cb_error:
            logger.error(f"Failed to send error callback: {cb_error}")

        sdk.close()
        return 1


def main():
    """Main entry point"""
    args = parse_args()

    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))

    try:
        # Load configuration
        cfg = load_config(args)

        # Run training (no longer async)
        exit_code = train_model(
            job_id=cfg['job_id'],
            model_name=cfg['model_name'],
            dataset_s3_uri=cfg['dataset_s3_uri'],
            config=cfg['config']
        )

        logger.info(f"Training job {cfg['job_id']} finished with exit code {exit_code}")
        sys.exit(exit_code)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
