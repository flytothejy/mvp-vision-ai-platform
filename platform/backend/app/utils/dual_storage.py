"""
Dual Storage Client for Internal and External Storage Management.

Architecture:
- Internal Storage: Pretrained weights, checkpoints, config schemas (MinIO - same location as Backend)
- External Storage: Training datasets, user uploads (S3/R2 - cloud storage)

Environment Configuration:
  Local Development:
    - Both use same MinIO instance (localhost:30900)
    - Different buckets for internal vs external

  Production:
    - Internal: MinIO in Backend cluster
    - External: Cloudflare R2 or AWS S3
"""

import os
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from pathlib import Path
from typing import Optional, Literal, BinaryIO
import logging
from io import BytesIO

logger = logging.getLogger(__name__)

StorageType = Literal["internal", "external"]


class DualStorageClient:
    """
    Dual storage client for managing internal and external storage backends.

    Internal Storage (MinIO - Backend location):
      - Pretrained model weights
      - Training checkpoints
      - Config schemas
      - Training artifacts

    External Storage (S3/R2 - Cloud):
      - Training datasets (images)
      - User uploads
      - Large files
    """

    def __init__(self):
        """Initialize dual storage clients from environment variables."""
        # Initialize internal storage (MinIO - Backend location)
        self.internal_client = self._init_internal_storage()
        self.internal_endpoint = os.getenv("INTERNAL_STORAGE_ENDPOINT")

        # Initialize external storage (S3/R2 - Cloud)
        self.external_client = self._init_external_storage()
        self.external_endpoint = os.getenv("EXTERNAL_STORAGE_ENDPOINT")

        # Internal storage buckets
        self.internal_bucket_weights = os.getenv("INTERNAL_BUCKET_WEIGHTS", "model-weights")
        self.internal_bucket_checkpoints = os.getenv("INTERNAL_BUCKET_CHECKPOINTS", "training-checkpoints")
        self.internal_bucket_schemas = os.getenv("INTERNAL_BUCKET_SCHEMAS", "config-schemas")

        # External storage buckets
        self.external_bucket_datasets = os.getenv("EXTERNAL_BUCKET_DATASETS", "training-datasets")

        # Detect storage types for logging
        self.internal_storage_type = self._detect_storage_type(self.internal_endpoint)
        self.external_storage_type = self._detect_storage_type(self.external_endpoint)

        logger.info(
            f"Dual Storage initialized:\n"
            f"  Internal ({self.internal_storage_type}): {self.internal_endpoint}\n"
            f"    - Buckets: weights={self.internal_bucket_weights}, "
            f"checkpoints={self.internal_bucket_checkpoints}, "
            f"schemas={self.internal_bucket_schemas}\n"
            f"  External ({self.external_storage_type}): {self.external_endpoint}\n"
            f"    - Buckets: datasets={self.external_bucket_datasets}"
        )

    def _init_internal_storage(self):
        """Initialize internal MinIO storage client."""
        endpoint = os.getenv("INTERNAL_STORAGE_ENDPOINT")
        access_key = os.getenv("INTERNAL_STORAGE_ACCESS_KEY")
        secret_key = os.getenv("INTERNAL_STORAGE_SECRET_KEY")

        if not all([endpoint, access_key, secret_key]):
            logger.warning(
                "Internal storage credentials not configured. "
                "Set INTERNAL_STORAGE_ENDPOINT, INTERNAL_STORAGE_ACCESS_KEY, INTERNAL_STORAGE_SECRET_KEY."
            )
            return None

        try:
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(
                    signature_version="s3v4",
                    retries={'max_attempts': 3, 'mode': 'standard'},
                    connect_timeout=5,
                    read_timeout=10,
                ),
            )
        except Exception as e:
            logger.error(f"Failed to initialize internal storage: {e}")
            return None

    def _init_external_storage(self):
        """Initialize external S3/R2 storage client."""
        endpoint = os.getenv("EXTERNAL_STORAGE_ENDPOINT")
        access_key = os.getenv("EXTERNAL_STORAGE_ACCESS_KEY")
        secret_key = os.getenv("EXTERNAL_STORAGE_SECRET_KEY")

        if not all([endpoint, access_key, secret_key]):
            logger.warning(
                "External storage credentials not configured. "
                "Set EXTERNAL_STORAGE_ENDPOINT, EXTERNAL_STORAGE_ACCESS_KEY, EXTERNAL_STORAGE_SECRET_KEY."
            )
            return None

        try:
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(
                    signature_version="s3v4",
                    retries={'max_attempts': 3, 'mode': 'standard'},
                    connect_timeout=5,
                    read_timeout=30,  # Longer timeout for cloud storage
                ),
            )
        except Exception as e:
            logger.error(f"Failed to initialize external storage: {e}")
            return None

    def _detect_storage_type(self, endpoint: Optional[str]) -> str:
        """Detect storage type from endpoint URL."""
        if not endpoint:
            return "unconfigured"

        if "r2.cloudflarestorage.com" in endpoint:
            return "Cloudflare R2"
        elif "localhost" in endpoint or "127.0.0.1" in endpoint:
            return "MinIO (local)"
        elif "amazonaws.com" in endpoint:
            return "AWS S3"
        elif "svc.cluster.local" in endpoint:
            return "MinIO (cluster)"
        return "S3-compatible"

    def get_client(self, storage_type: StorageType):
        """
        Get storage client by type.

        Args:
            storage_type: "internal" or "external"

        Returns:
            boto3 S3 client
        """
        if storage_type == "internal":
            return self.internal_client
        else:
            return self.external_client

    # ==========================================
    # Internal Storage Methods
    # ==========================================

    def upload_weight(
        self,
        file_path: Path,
        weight_key: str,
        content_type: str = "application/octet-stream"
    ) -> bool:
        """
        Upload pretrained weight to internal storage.

        Args:
            file_path: Local file path
            weight_key: Storage key (e.g., "resnet50.pth")
            content_type: MIME type

        Returns:
            True if successful
        """
        if not self.internal_client:
            logger.error("Internal storage not initialized")
            return False

        try:
            self.internal_client.upload_file(
                str(file_path),
                self.internal_bucket_weights,
                weight_key,
                ExtraArgs={"ContentType": content_type}
            )
            logger.info(f"Uploaded weight to internal storage: {weight_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to upload weight: {e}")
            return False

    def download_weight(
        self,
        weight_key: str,
        dest_path: Path
    ) -> bool:
        """
        Download pretrained weight from internal storage.

        Args:
            weight_key: Storage key
            dest_path: Local destination path

        Returns:
            True if successful
        """
        if not self.internal_client:
            logger.error("Internal storage not initialized")
            return False

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            self.internal_client.download_file(
                self.internal_bucket_weights,
                weight_key,
                str(dest_path)
            )
            logger.info(f"Downloaded weight from internal storage: {weight_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to download weight: {e}")
            return False

    def upload_checkpoint(
        self,
        file_path: Path,
        checkpoint_key: str
    ) -> bool:
        """
        Upload training checkpoint to internal storage.

        Args:
            file_path: Local checkpoint file
            checkpoint_key: Storage key (e.g., "jobs/123/checkpoint_epoch_10.pth")

        Returns:
            True if successful
        """
        if not self.internal_client:
            logger.error("Internal storage not initialized")
            return False

        try:
            self.internal_client.upload_file(
                str(file_path),
                self.internal_bucket_checkpoints,
                checkpoint_key
            )
            logger.info(f"Uploaded checkpoint to internal storage: {checkpoint_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to upload checkpoint: {e}")
            return False

    def download_checkpoint(
        self,
        checkpoint_key: str,
        dest_path: Path
    ) -> bool:
        """
        Download training checkpoint from internal storage.

        Args:
            checkpoint_key: Storage key
            dest_path: Local destination path

        Returns:
            True if successful
        """
        if not self.internal_client:
            logger.error("Internal storage not initialized")
            return False

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            self.internal_client.download_file(
                self.internal_bucket_checkpoints,
                checkpoint_key,
                str(dest_path)
            )
            logger.info(f"Downloaded checkpoint from internal storage: {checkpoint_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to download checkpoint: {e}")
            return False

    def get_schema(self, framework: str) -> Optional[bytes]:
        """
        Get config schema from internal storage.

        Args:
            framework: Framework name (e.g., "ultralytics", "timm")

        Returns:
            Schema content as bytes, or None if not found
        """
        if not self.internal_client:
            logger.error("Internal storage not initialized")
            return None

        try:
            # Schema is stored directly in config-schemas bucket (no schemas/ prefix)
            schema_key = f"{framework}.json"
            response = self.internal_client.get_object(
                Bucket=self.internal_bucket_schemas,
                Key=schema_key
            )
            content = response['Body'].read()
            logger.info(f"Retrieved schema from internal storage: {self.internal_bucket_schemas}/{schema_key} ({len(content)} bytes)")
            return content
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning(f"Schema not found: {framework}")
            else:
                logger.error(f"Failed to get schema: {e}")
            return None

    def get_capabilities(self, framework: str) -> Optional[bytes]:
        """
        Get model capabilities from internal storage.

        Capabilities are stored in config-schemas bucket with prefix 'model-capabilities/'.

        Args:
            framework: Framework name (e.g., "ultralytics", "timm")

        Returns:
            Capabilities content as bytes, or None if not found
        """
        if not self.internal_client:
            logger.error("Internal storage not initialized")
            return None

        try:
            # Capabilities are stored with model-capabilities/ prefix
            capabilities_key = f"model-capabilities/{framework}.json"
            response = self.internal_client.get_object(
                Bucket=self.internal_bucket_schemas,
                Key=capabilities_key
            )
            content = response['Body'].read()
            logger.info(f"Retrieved capabilities from internal storage: {self.internal_bucket_schemas}/{capabilities_key} ({len(content)} bytes)")
            return content
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning(f"Capabilities not found: {framework}")
            else:
                logger.error(f"Failed to get capabilities: {e}")
            return None

    def upload_schema(
        self,
        schema_data: bytes,
        framework: str
    ) -> bool:
        """
        Upload config schema to internal storage.

        Args:
            schema_data: Schema JSON bytes
            framework: Framework name

        Returns:
            True if successful
        """
        if not self.internal_client:
            logger.error("Internal storage not initialized")
            return False

        try:
            # Schema is stored directly in config-schemas bucket (no schemas/ prefix)
            schema_key = f"{framework}.json"
            self.internal_client.put_object(
                Bucket=self.internal_bucket_schemas,
                Key=schema_key,
                Body=schema_data,
                ContentType="application/json"
            )
            logger.info(f"Uploaded schema to internal storage: {self.internal_bucket_schemas}/{schema_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to upload schema: {e}")
            return False

    # ==========================================
    # External Storage Methods
    # ==========================================

    def upload_dataset(
        self,
        file_obj: BinaryIO,
        dataset_key: str,
        content_type: str = "application/zip"
    ) -> bool:
        """
        Upload dataset to external storage.

        Args:
            file_obj: File-like object
            dataset_key: Storage key (e.g., "datasets/abc-123.zip")
            content_type: MIME type

        Returns:
            True if successful
        """
        if not self.external_client:
            logger.error("External storage not initialized")
            return False

        try:
            self.external_client.upload_fileobj(
                file_obj,
                self.external_bucket_datasets,
                dataset_key,
                ExtraArgs={"ContentType": content_type}
            )
            logger.info(f"Uploaded dataset to external storage: {dataset_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to upload dataset: {e}")
            return False

    def download_dataset(
        self,
        dataset_key: str,
        dest_path: Path
    ) -> bool:
        """
        Download dataset from external storage.

        Args:
            dataset_key: Storage key
            dest_path: Local destination path

        Returns:
            True if successful
        """
        if not self.external_client:
            logger.error("External storage not initialized")
            return False

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            self.external_client.download_file(
                self.external_bucket_datasets,
                dataset_key,
                str(dest_path)
            )
            logger.info(f"Downloaded dataset from external storage: {dataset_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to download dataset: {e}")
            return False

    def generate_dataset_presigned_url(
        self,
        dataset_key: str,
        expiration: int = 3600
    ) -> Optional[str]:
        """
        Generate presigned URL for dataset download.

        Args:
            dataset_key: Storage key
            expiration: URL expiration in seconds

        Returns:
            Presigned URL or None
        """
        if not self.external_client:
            logger.error("External storage not initialized")
            return None

        try:
            url = self.external_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.external_bucket_datasets,
                    "Key": dataset_key
                },
                ExpiresIn=expiration
            )
            logger.info(f"Generated presigned URL for dataset: {dataset_key}")
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            return None

    def list_datasets(self, prefix: str = "datasets/") -> list[str]:
        """
        List datasets in external storage.

        Args:
            prefix: Prefix to filter datasets

        Returns:
            List of dataset keys
        """
        if not self.external_client:
            logger.error("External storage not initialized")
            return []

        try:
            response = self.external_client.list_objects_v2(
                Bucket=self.external_bucket_datasets,
                Prefix=prefix
            )

            datasets = []
            if 'Contents' in response:
                datasets = [obj['Key'] for obj in response['Contents']]

            logger.info(f"Listed {len(datasets)} datasets from external storage")
            return datasets
        except ClientError as e:
            logger.error(f"Failed to list datasets: {e}")
            return []

    def delete_dataset(self, dataset_key: str) -> bool:
        """
        Delete dataset from external storage.

        Args:
            dataset_key: Storage key

        Returns:
            True if successful
        """
        if not self.external_client:
            logger.error("External storage not initialized")
            return False

        try:
            self.external_client.delete_object(
                Bucket=self.external_bucket_datasets,
                Key=dataset_key
            )
            logger.info(f"Deleted dataset from external storage: {dataset_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete dataset: {e}")
            return False

    # ==========================================
    # Presigned URL Methods (Encapsulated)
    # ==========================================

    def generate_checkpoint_presigned_url(
        self,
        checkpoint_key: str,
        expiration: int = 3600,
        method: str = "get_object"
    ) -> Optional[str]:
        """
        Generate presigned URL for checkpoint access.

        Args:
            checkpoint_key: Storage key (e.g., "jobs/123/checkpoint.pth")
            expiration: URL expiration in seconds (default: 1 hour)
            method: 'get_object' for download, 'put_object' for upload

        Returns:
            Presigned URL or None
        """
        if not self.internal_client:
            logger.error("Internal storage not initialized")
            return None

        try:
            url = self.internal_client.generate_presigned_url(
                method,
                Params={
                    "Bucket": self.internal_bucket_checkpoints,
                    "Key": checkpoint_key
                },
                ExpiresIn=expiration
            )
            logger.info(f"Generated presigned {method} URL for checkpoint: {checkpoint_key}")
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL for checkpoint: {e}")
            return None

    def generate_checkpoint_upload_url(
        self,
        checkpoint_key: str,
        expiration: int = 3600,
        content_type: str = "application/octet-stream"
    ) -> Optional[str]:
        """
        Generate presigned URL for checkpoint upload (PUT).

        Args:
            checkpoint_key: Storage key
            expiration: URL expiration in seconds
            content_type: MIME type

        Returns:
            Presigned upload URL or None
        """
        if not self.internal_client:
            logger.error("Internal storage not initialized")
            return None

        try:
            url = self.internal_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.internal_bucket_checkpoints,
                    "Key": checkpoint_key,
                    "ContentType": content_type
                },
                ExpiresIn=expiration
            )
            logger.info(f"Generated presigned upload URL for checkpoint: {checkpoint_key}")
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned upload URL: {e}")
            return None

    def generate_checkpoint_download_url(
        self,
        checkpoint_key: str,
        expiration: int = 3600
    ) -> Optional[str]:
        """
        Generate presigned URL for checkpoint download (GET).

        Args:
            checkpoint_key: Storage key
            expiration: URL expiration in seconds

        Returns:
            Presigned download URL or None
        """
        return self.generate_checkpoint_presigned_url(
            checkpoint_key,
            expiration,
            method="get_object"
        )


# Global dual storage client instance
dual_storage = DualStorageClient()
