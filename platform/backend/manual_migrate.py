"""
Quick database migration script - minimal imports
"""
import sys

# UTF-8 encoding for Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import create_engine, text

# Hard-coded database URL
DATABASE_URL = "postgresql://admin:devpass@localhost:5432/platform"

def main():
    print("Connecting to database...")
    engine = create_engine(DATABASE_URL, echo=False)

    with engine.connect() as conn:
        # Check if column exists
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'training_jobs'
            AND column_name = 'clearml_task_id'
        """))

        if result.fetchone():
            print("[SKIP] clearml_task_id column already exists")
            return

        print("[INFO] Adding clearml_task_id column...")

        # Add column
        conn.execute(text("""
            ALTER TABLE training_jobs
            ADD COLUMN clearml_task_id VARCHAR(200)
        """))

        # Create index
        conn.execute(text("""
            CREATE INDEX ix_training_jobs_clearml_task_id
            ON training_jobs(clearml_task_id)
        """))

        conn.commit()

        print("[SUCCESS] Migration completed!")
        print("  ✓ Column: clearml_task_id VARCHAR(200)")
        print("  ✓ Index: ix_training_jobs_clearml_task_id")

if __name__ == "__main__":
    main()
