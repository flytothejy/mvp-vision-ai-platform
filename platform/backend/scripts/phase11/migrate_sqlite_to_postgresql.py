"""
Phase 11 Tier 2: SQLite -> PostgreSQL Migration Script

Migrates User data from SQLite (Tier 1) to PostgreSQL (Tier 2/3).

Usage:
    python scripts/phase11/migrate_sqlite_to_postgresql.py

Environment Variables:
    - SOURCE_DB: SQLite database URL (default: sqlite:///./shared_users.db)
    - TARGET_DB: PostgreSQL database URL (default: postgresql://admin:devpass@localhost:5433/users)
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file before imports
backend_dir = Path(__file__).parent.parent.parent
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"[OK] Loaded .env from: {env_path}")
else:
    print(f"[WARN] No .env file found at {env_path}")

# Add parent directory to path for imports
sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
from app.db.models import User, Organization, Invitation, ProjectMember
# Session removed in Phase 5 (migrated to Redis)


def get_source_engine():
    """Get SQLite source database engine."""
    source_url = os.getenv('SOURCE_DB', 'sqlite:///./shared_users.db')
    print(f"[SOURCE] DB: {source_url}")
    return create_engine(source_url)


def get_target_engine():
    """Get PostgreSQL target database engine."""
    target_url = os.getenv('TARGET_DB', 'postgresql://admin:devpass@localhost:5433/users')
    print(f"[TARGET] DB: {target_url}")
    return create_engine(target_url)


def verify_source_data(source_session):
    """Verify source database has data."""
    counts = {
        'organizations': source_session.query(Organization).count(),
        'users': source_session.query(User).count(),
        'invitations': source_session.query(Invitation).count(),
        'project_members': source_session.query(ProjectMember).count(),
        # sessions removed in Phase 5 (migrated to Redis)
    }

    print("\n[VERIFY] Source Database Contents:")
    for table, count in counts.items():
        print(f"  - {table}: {count} rows")

    return sum(counts.values()) > 0


def create_target_schema(target_engine):
    """Create tables in target PostgreSQL database."""
    from app.db.models import Base

    print("\n[SCHEMA] Creating tables in target database...")
    Base.metadata.create_all(bind=target_engine)
    print("[OK] Tables created successfully")


def migrate_table(source_session, target_session, model, table_name):
    """Migrate a single table from source to target."""
    print(f"\n[MIGRATE] {table_name}...")

    # Fetch all rows from source
    rows = source_session.query(model).all()
    count = len(rows)

    if count == 0:
        print(f"  [SKIP] No data in {table_name}, skipping")
        return 0

    # Use merge to handle primary key conflicts
    for i, row in enumerate(rows, 1):
        target_session.merge(row)
        if i % 10 == 0 or i == count:
            print(f"  Progress: {i}/{count} rows", end='\r')

    target_session.commit()
    print(f"\n  [OK] Migrated {count} rows")
    return count


def verify_target_data(target_session):
    """Verify target database has correct data."""
    counts = {
        'organizations': target_session.query(Organization).count(),
        'users': target_session.query(User).count(),
        'invitations': target_session.query(Invitation).count(),
        'project_members': target_session.query(ProjectMember).count(),
        # sessions removed in Phase 5 (migrated to Redis)
    }

    print("\n[VERIFY] Target Database Contents (After Migration):")
    for table, count in counts.items():
        print(f"  - {table}: {count} rows")

    return counts


def main():
    """Run migration."""
    print("=" * 60)
    print("Phase 11 Tier 2: SQLite -> PostgreSQL Migration")
    print("=" * 60)

    # Get engines
    source_engine = get_source_engine()
    target_engine = get_target_engine()

    # Create sessions
    SourceSession = sessionmaker(bind=source_engine)
    TargetSession = sessionmaker(bind=target_engine)

    source_session = SourceSession()
    target_session = TargetSession()

    try:
        # Step 1: Verify source data
        print("\n" + "=" * 60)
        print("Step 1: Verify Source Data")
        print("=" * 60)
        has_data = verify_source_data(source_session)
        if not has_data:
            print("\n[ERROR] Source database is empty. Nothing to migrate.")
            return

        # Step 2: Create target schema
        print("\n" + "=" * 60)
        print("Step 2: Create Target Schema")
        print("=" * 60)
        create_target_schema(target_engine)

        # Step 3: Migrate data (FK order: organizations -> users -> invitations, project_members, sessions)
        print("\n" + "=" * 60)
        print("Step 3: Migrate Data")
        print("=" * 60)

        total_rows = 0
        migration_order = [
            (Organization, 'organizations'),
            (User, 'users'),
            (Invitation, 'invitations'),
            (ProjectMember, 'project_members'),
            # UserSession removed in Phase 5 (migrated to Redis)
        ]

        for model, table_name in migration_order:
            rows_migrated = migrate_table(source_session, target_session, model, table_name)
            total_rows += rows_migrated

        # Step 4: Verify target data
        print("\n" + "=" * 60)
        print("Step 4: Verify Target Data")
        print("=" * 60)
        target_counts = verify_target_data(target_session)

        # Step 5: Final summary
        print("\n" + "=" * 60)
        print("Migration Complete!")
        print("=" * 60)
        print(f"[SUCCESS] Total rows migrated: {total_rows}")
        print(f"\n[NEXT STEPS]")
        print(f"  1. Update .env file:")
        print(f"     USER_DATABASE_URL=postgresql://admin:devpass@localhost:5433/users")
        print(f"  2. Restart Backend:")
        print(f"     cd platform/backend && poetry run uvicorn app.main:app --reload")
        print(f"  3. Test login and user operations")
        print(f"  4. If successful, you can delete shared_users.db")

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()
        target_session.rollback()
        raise
    finally:
        source_session.close()
        target_session.close()


if __name__ == '__main__':
    main()
