"""
Dataset Snapshot Service

Manages dataset snapshots for training job reproducibility.
Platform creates immutable snapshots by copying datasets from R2 storage.

Phase 11.5: Dataset Service Integration
"""

import logging
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from app.db.models import DatasetSnapshot
from app.utils.dual_storage import dual_storage

logger = logging.getLogger(__name__)


class SnapshotService:
    """
    Service for creating and managing dataset snapshots.

    Snapshots are immutable copies of datasets created at training job start time.
    This ensures training reproducibility even if the original dataset is modified.

    Architecture:
    - Platform creates snapshots (not Labeler)
    - Platform has direct R2 access via dual_storage
    - Snapshot metadata stored in Platform DB
    - Snapshot files stored in R2 (snapshots/ prefix)
    """

    async def create_snapshot(
        self,
        dataset_id: str,
        dataset_path: str,
        user_id: int,
        db: Session,
        notes: Optional[str] = None
    ) -> DatasetSnapshot:
        """
        Create an immutable snapshot of a dataset.

        Args:
            dataset_id: Original dataset ID (from Labeler)
            dataset_path: Source dataset path in R2 (e.g., "datasets/ds_abc123/")
            user_id: User creating the snapshot
            db: Database session
            notes: Optional notes about the snapshot

        Returns:
            DatasetSnapshot model instance

        Raises:
            Exception: If R2 copy fails or database error occurs
        """
        # Generate snapshot ID
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        snapshot_path = f"snapshots/{snapshot_id}/"

        logger.info(
            f"[SnapshotService] Creating snapshot {snapshot_id} "
            f"from dataset {dataset_id} (path: {dataset_path})"
        )

        try:
            # Copy dataset from R2 (datasets/ → snapshots/)
            await self._copy_r2_folder(
                source=dataset_path,
                destination=snapshot_path
            )

            # Create snapshot record in Platform DB
            snapshot = DatasetSnapshot(
                id=snapshot_id,
                dataset_id=dataset_id,
                storage_path=snapshot_path,
                created_by_user_id=user_id,
                notes=notes or f"Snapshot for dataset {dataset_id}",
                created_at=datetime.utcnow()
            )

            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)

            logger.info(
                f"[SnapshotService] Snapshot {snapshot_id} created successfully "
                f"(storage_path: {snapshot_path})"
            )
            return snapshot

        except Exception as e:
            logger.error(f"[SnapshotService] Failed to create snapshot {snapshot_id}: {e}")
            db.rollback()
            raise

    async def _copy_r2_folder(
        self,
        source: str,
        destination: str
    ) -> int:
        """
        Copy all objects from source folder to destination folder in R2.

        Uses S3-compatible copy_object API (no data transfer through server).

        Args:
            source: Source folder prefix (e.g., "datasets/ds_abc123/")
            destination: Destination folder prefix (e.g., "snapshots/snap_xyz/")

        Returns:
            Number of objects copied

        Raises:
            Exception: If R2 operation fails
        """
        logger.info(
            f"[SnapshotService] Copying R2 folder: {source} → {destination}"
        )

        try:
            # List all objects in source folder
            response = dual_storage.external_client.list_objects_v2(
                Bucket=dual_storage.external_bucket_datasets,
                Prefix=source
            )

            objects = response.get('Contents', [])
            if not objects:
                logger.warning(
                    f"[SnapshotService] No objects found in source folder: {source}"
                )
                return 0

            # Copy each object
            copied_count = 0
            for obj in objects:
                source_key = obj['Key']
                # Replace source prefix with destination prefix
                dest_key = source_key.replace(source, destination, 1)

                # Copy object (server-side copy, no download/upload)
                dual_storage.external_client.copy_object(
                    CopySource={
                        'Bucket': dual_storage.external_bucket_datasets,
                        'Key': source_key
                    },
                    Bucket=dual_storage.external_bucket_datasets,
                    Key=dest_key
                )
                copied_count += 1

            logger.info(
                f"[SnapshotService] Copied {copied_count} objects from {source} to {destination}"
            )
            return copied_count

        except Exception as e:
            logger.error(
                f"[SnapshotService] Failed to copy R2 folder {source} → {destination}: {e}"
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
