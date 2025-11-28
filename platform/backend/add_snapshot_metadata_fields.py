"""
Migration: Add Metadata-Only Snapshot Fields

Phase 12.2: Metadata-Only Snapshot Design

Adds the following columns to dataset_snapshots table:
- snapshot_metadata_path: Path to metadata JSON in internal storage
- dataset_version_hash: SHA256 hash for collision detection
"""

from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://admin:devpass@localhost:5432/platform"
engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    # Add snapshot_metadata_path column
    conn.execute(text(
        "ALTER TABLE dataset_snapshots "
        "ADD COLUMN IF NOT EXISTS snapshot_metadata_path VARCHAR(500)"
    ))
    print("Added snapshot_metadata_path column")

    # Add dataset_version_hash column
    conn.execute(text(
        "ALTER TABLE dataset_snapshots "
        "ADD COLUMN IF NOT EXISTS dataset_version_hash VARCHAR(64)"
    ))
    print("Added dataset_version_hash column")

    # Add index on dataset_version_hash for faster collision detection queries
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_dataset_snapshots_version_hash "
        "ON dataset_snapshots(dataset_version_hash)"
    ))
    print("Created index on dataset_version_hash")

print("\n[Migration Complete] dataset_snapshots table updated for Phase 12.2 Metadata-Only Snapshot")
