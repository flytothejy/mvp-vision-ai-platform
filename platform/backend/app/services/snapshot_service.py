"""
Dataset Snapshot Service

Phase 12.2: Metadata-Only Snapshot Design

Manages dataset snapshots for training job reproducibility without duplicating data.
Instead of copying entire datasets, snapshots store only metadata and reference original data.

Key Features:
- Metadata-only snapshots (no data duplication)
- Collision detection via dataset version hash
- Internal storage (MinIO) for snapshot metadata
- External storage (R2) reference for actual dataset files

Architecture:
- Platform creates snapshots (not Labeler)
- Snapshot metadata stored in internal storage (MinIO)
- Dataset files remain in external storage (R2)
- Hash-based collision detection ensures reproducibility
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.db.models import DatasetSnapshot
from app.utils.dual_storage import dual_storage

logger = logging.getLogger(__name__)


class SnapshotService:
    """
    Service for creating and managing dataset snapshots.

    Phase 12.2: Metadata-Only Snapshot Design
    - Snapshots store metadata only (not full dataset copy)
    - Dataset files remain in external storage (R2)
    - Snapshot metadata stored in internal storage (MinIO)
    - Collision detection ensures reproducibility
    """

    async def create_snapshot(
        self,
        dataset_id: str,
        dataset_path: str,
        user_id: int,
        db: Session,
        notes: Optional[str] = None,
        split_config: Optional[dict] = None
    ) -> DatasetSnapshot:
        """
        Create an immutable snapshot of a dataset (metadata-only).

        Phase 12.2: Metadata-Only Design
        - No data duplication (references original dataset in R2)
        - Metadata stored in internal storage (MinIO)
        - Hash-based collision detection

        Args:
            dataset_id: Original dataset ID (from Labeler)
            dataset_path: Source dataset path in R2 (e.g., "datasets/ds_abc123/")
            user_id: User creating the snapshot
            db: Database session
            notes: Optional notes about the snapshot
            split_config: Resolved split configuration (from resolve_split_configuration)

        Returns:
            DatasetSnapshot model instance

        Raises:
            Exception: If hash calculation or metadata upload fails
        """
        # Generate snapshot ID
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        metadata_path = f"snapshots/{snapshot_id}/metadata.json"

        logger.info(
            f"[SnapshotService] Creating metadata-only snapshot {snapshot_id} "
            f"from dataset {dataset_id} (path: {dataset_path})"
        )

        if split_config:
            logger.info(
                f"[SnapshotService] Snapshot will capture split: "
                f"source={split_config.get('source')}, method={split_config.get('method')}"
            )

        try:
            # 1. Calculate dataset version hash (for collision detection)
            logger.info(f"[SnapshotService] Calculating dataset version hash...")
            dataset_hash = await self._calculate_dataset_hash(dataset_path)
            logger.info(f"[SnapshotService] Dataset hash: {dataset_hash[:16]}...")

            # 2. Create snapshot metadata
            snapshot_metadata = {
                "snapshot_id": snapshot_id,
                "dataset_id": dataset_id,
                "dataset_path": dataset_path,  # Reference to original dataset in R2
                "split_config": split_config,
                "dataset_version_hash": dataset_hash,
                "created_by_user_id": user_id,
                "created_at": datetime.utcnow().isoformat(),
                "notes": notes or f"Snapshot for dataset {dataset_id}",
            }

            # 3. Upload metadata to internal storage (MinIO)
            logger.info(f"[SnapshotService] Uploading metadata to internal storage: {metadata_path}")
            await self._upload_json_to_internal_storage(metadata_path, snapshot_metadata)

            # 4. Create snapshot record in Platform DB
            snapshot = DatasetSnapshot(
                id=snapshot_id,
                dataset_id=dataset_id,
                storage_path=dataset_path,  # Reference to original dataset (not copied)
                snapshot_metadata_path=metadata_path,  # Metadata in internal storage
                dataset_version_hash=dataset_hash,
                created_by_user_id=user_id,
                notes=notes or f"Snapshot for dataset {dataset_id}",
                created_at=datetime.utcnow(),
                split_config=split_config
            )

            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)

            logger.info(
                f"[SnapshotService] Snapshot {snapshot_id} created successfully "
                f"(metadata: {metadata_path}, dataset: {dataset_path})"
            )
            return snapshot

        except Exception as e:
            logger.error(f"[SnapshotService] Failed to create snapshot {snapshot_id}: {e}")
            db.rollback()
            raise

    async def _calculate_dataset_hash(
        self,
        dataset_path: str
    ) -> str:
        """
        Calculate SHA256 hash of dataset for collision detection.

        Strategy: Hash annotations.json and metadata.json only (not images)
        - Fast computation (no need to hash GBs of images)
        - Sufficient for detecting dataset changes
        - Images rarely change; annotations/metadata are what matter

        Args:
            dataset_path: Dataset folder prefix in R2 (e.g., "datasets/ds_abc123/")

        Returns:
            SHA256 hash string (64 characters)

        Raises:
            Exception: If R2 operation fails or files not found
        """
        logger.info(
            f"[SnapshotService] Calculating dataset hash for: {dataset_path}"
        )

        try:
            # List all objects in dataset folder
            response = dual_storage.external_client.list_objects_v2(
                Bucket=dual_storage.external_bucket_datasets,
                Prefix=dataset_path
            )

            objects = response.get('Contents', [])
            if not objects:
                raise ValueError(f"Dataset folder is empty: {dataset_path}")

            # Filter metadata files only (annotations.json, metadata.json, data.yaml, etc.)
            metadata_files = []
            for obj in objects:
                key = obj['Key']
                filename = key.split('/')[-1]

                # Include only metadata files (not images)
                if filename.endswith(('.json', '.yaml', '.yml', '.txt')):
                    metadata_files.append(key)

            if not metadata_files:
                logger.warning(
                    f"[SnapshotService] No metadata files found in {dataset_path}, "
                    f"using all files for hash calculation"
                )
                # Fallback: use all files (but limit to first 100 to avoid timeout)
                metadata_files = [obj['Key'] for obj in objects[:100]]

            logger.info(
                f"[SnapshotService] Hashing {len(metadata_files)} files: "
                f"{', '.join([f.split('/')[-1] for f in metadata_files[:5]])}..."
            )

            # Calculate combined hash
            hasher = hashlib.sha256()

            # Sort files for deterministic hash
            for file_key in sorted(metadata_files):
                # Get file content
                file_obj = dual_storage.external_client.get_object(
                    Bucket=dual_storage.external_bucket_datasets,
                    Key=file_key
                )
                file_content = file_obj['Body'].read()

                # Update hash
                hasher.update(file_content)

            dataset_hash = hasher.hexdigest()

            logger.info(
                f"[SnapshotService] Dataset hash calculated: {dataset_hash[:16]}... "
                f"({len(metadata_files)} files)"
            )

            return dataset_hash

        except Exception as e:
            logger.error(
                f"[SnapshotService] Failed to calculate dataset hash for {dataset_path}: {e}"
            )
            raise

    async def _upload_json_to_internal_storage(
        self,
        key: str,
        data: Dict[str, Any]
    ) -> None:
        """
        Upload JSON data to internal storage (MinIO).

        Args:
            key: Object key (e.g., "snapshots/snap_abc123/metadata.json")
            data: Dictionary to upload as JSON

        Raises:
            Exception: If upload fails
        """
        try:
            json_bytes = json.dumps(data, indent=2).encode('utf-8')

            # Upload to internal storage (MinIO)
            dual_storage.internal_client.put_object(
                Bucket=dual_storage.internal_bucket_checkpoints,
                Key=key,
                Body=json_bytes,
                ContentType='application/json'
            )

            logger.info(
                f"[SnapshotService] Uploaded metadata to internal storage: {key} "
                f"({len(json_bytes)} bytes)"
            )

        except Exception as e:
            logger.error(
                f"[SnapshotService] Failed to upload JSON to internal storage {key}: {e}"
            )
            raise

    async def validate_snapshot(
        self,
        snapshot: DatasetSnapshot,
        db: Session
    ) -> bool:
        """
        Validate snapshot integrity via collision detection.

        Checks if the original dataset has been modified since snapshot creation
        by comparing dataset version hashes.

        Args:
            snapshot: DatasetSnapshot instance
            db: Database session

        Returns:
            True if snapshot is valid (dataset unchanged)

        Raises:
            ValueError: If dataset has been modified (hash mismatch)
            Exception: If validation fails due to R2 error
        """
        logger.info(
            f"[SnapshotService] Validating snapshot {snapshot.id} "
            f"(dataset: {snapshot.dataset_id})"
        )

        try:
            # Skip validation if snapshot doesn't have hash (legacy snapshot)
            if not snapshot.dataset_version_hash:
                logger.warning(
                    f"[SnapshotService] Snapshot {snapshot.id} has no version hash "
                    f"(legacy snapshot) - skipping validation"
                )
                return True

            # Calculate current dataset hash
            current_hash = await self._calculate_dataset_hash(snapshot.storage_path)

            # Compare with snapshot hash
            if current_hash != snapshot.dataset_version_hash:
                raise ValueError(
                    f"Dataset {snapshot.dataset_id} has been modified since snapshot {snapshot.id} was created. "
                    f"Expected hash: {snapshot.dataset_version_hash[:16]}..., "
                    f"Current hash: {current_hash[:16]}... "
                    f"Please create a new snapshot to ensure reproducibility."
                )

            logger.info(
                f"[SnapshotService] Snapshot {snapshot.id} validation successful "
                f"(hash: {current_hash[:16]}...)"
            )
            return True

        except ValueError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.error(
                f"[SnapshotService] Snapshot validation failed for {snapshot.id}: {e}"
            )
            raise

    def get_snapshot(
        self,
        snapshot_id: str,
        db: Session
    ) -> Optional[DatasetSnapshot]:
        """
        Get snapshot by ID.

        Args:
            snapshot_id: Snapshot ID
            db: Database session

        Returns:
            DatasetSnapshot instance or None if not found
        """
        return db.query(DatasetSnapshot).filter(
            DatasetSnapshot.id == snapshot_id
        ).first()

    def list_snapshots_by_dataset(
        self,
        dataset_id: str,
        db: Session,
        limit: int = 20
    ) -> list[DatasetSnapshot]:
        """
        List snapshots for a specific dataset.

        Args:
            dataset_id: Original dataset ID
            db: Database session
            limit: Maximum number of snapshots to return

        Returns:
            List of DatasetSnapshot instances (ordered by created_at desc)
        """
        return db.query(DatasetSnapshot).filter(
            DatasetSnapshot.dataset_id == dataset_id
        ).order_by(DatasetSnapshot.created_at.desc()).limit(limit).all()


# Singleton instance
snapshot_service = SnapshotService()
