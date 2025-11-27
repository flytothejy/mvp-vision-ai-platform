"""
Add workflow_id column to TrainingJob table.

Phase 12.0.5: Temporal Workflow Integration
"""

import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file before importing app modules
backend_dir = Path(__file__).parent
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"[MIGRATION] Loaded .env from: {env_path}")

# Add parent directory to path
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.db.database import SessionLocal, engine


def migrate_add_workflow_id():
    """Add workflow_id column to training_jobs table."""
    db = SessionLocal()

    try:
        # Check if column already exists
        result = db.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'training_jobs'
            AND column_name = 'workflow_id'
        """))

        if result.fetchone():
            print("[MIGRATION] workflow_id column already exists, skipping")
            return

        # Add workflow_id column
        print("[MIGRATION] Adding workflow_id column to training_jobs table...")
        db.execute(text("""
            ALTER TABLE training_jobs
            ADD COLUMN workflow_id VARCHAR(200)
        """))

        # Add index
        print("[MIGRATION] Creating index on workflow_id...")
        db.execute(text("""
            CREATE INDEX ix_training_jobs_workflow_id
            ON training_jobs(workflow_id)
        """))

        db.commit()
        print("[MIGRATION] Successfully added workflow_id column")

    except Exception as e:
        print(f"[MIGRATION] Error during migration: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 80)
    print("Phase 12.0.5: Add workflow_id column to TrainingJob")
    print("=" * 80)
    migrate_add_workflow_id()
    print("=" * 80)
    print("Migration completed successfully!")
    print("=" * 80)
