"""
Database migration: Remove FK constraint from dataset_snapshots.created_by_user_id

Phase 11: User table moved to User DB - no FK constraint across databases

Changes:
- DatasetSnapshot: Drop FK constraint on created_by_user_id column

Run: python migrate_remove_snapshot_user_fk.py
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Add backend to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

# Load environment variables
env_path = backend_path / '.env'
load_dotenv(env_path)

from sqlalchemy import create_engine, text, inspect


def migrate():
    """Execute migration."""
    db_url = os.getenv('DATABASE_URL', 'postgresql://platform_user:platform_pass@localhost:5432/platform_db')
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {}
    )

    print(f"[INFO] Connecting to database: {db_url}")
    print(f"[INFO] Database type: {'SQLite' if db_url.startswith('sqlite') else 'PostgreSQL'}")

    inspector = inspect(engine)

    with engine.begin() as conn:
        print("\n[INFO] Checking current schema...")

        # Check if dataset_snapshots table exists
        if 'dataset_snapshots' not in inspector.get_table_names():
            print("[ERROR] dataset_snapshots table does not exist!")
            return

        # Get current columns
        columns = [col['name'] for col in inspector.get_columns('dataset_snapshots')]
        print(f"[INFO] Current columns in dataset_snapshots: {', '.join(columns)}")

        # Check if created_by_user_id exists
        if 'created_by_user_id' not in columns:
            print("[WARNING] created_by_user_id column does not exist, skipping migration")
            return

        print("\n[STEP 1] Checking for FK constraint on created_by_user_id...")

        # Get foreign keys
        fks = inspector.get_foreign_keys('dataset_snapshots')
        fk_name = None
        for fk in fks:
            if 'created_by_user_id' in fk.get('constrained_columns', []):
                fk_name = fk['name']
                print(f"[INFO] Found FK constraint: {fk_name}")
                break

        if not fk_name:
            print("[INFO] No FK constraint found on created_by_user_id, migration already complete")
            return

        print("\n[STEP 2] Dropping FK constraint...")

        if db_url.startswith("sqlite"):
            print("[WARNING] SQLite does not support dropping FK constraints directly")
            print("[INFO] You'll need to recreate the table to remove the constraint")
            print("[INFO] Or just ignore it for SQLite (development only)")
            return
        else:
            # PostgreSQL
            conn.execute(text(f"""
                ALTER TABLE dataset_snapshots
                DROP CONSTRAINT {fk_name}
            """))
            print(f"[OK] FK constraint '{fk_name}' dropped")

        print("\n[SUCCESS] Migration completed successfully!")
        print("\n[SUMMARY]")
        print("  - Removed: FK constraint on dataset_snapshots.created_by_user_id")
        print("  - Reason: Phase 11 moved users table to separate User DB")
        print("  - Note: created_by_user_id column still exists as plain Integer")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"\n[ERROR] Migration failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
