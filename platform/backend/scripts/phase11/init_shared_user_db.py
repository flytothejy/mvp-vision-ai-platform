"""Phase 11 Tier 1: Migrate User data from Platform DB to Shared User DB.

This script:
1. Creates Shared User DB (SQLite) with schema
2. Copies User-related data from Platform DB to Shared User DB
3. Verifies data integrity

Tables to migrate:
- organizations
- users
- invitations
- project_members

Usage:
    python migrate_phase11_tier1_user_db.py
"""

import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Load .env file
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text, inspect
from app.db.database import platform_engine, user_engine, Base
from app.db.models import Organization, User, Invitation, ProjectMember


def create_user_db_schema():
    """Create tables in Shared User DB."""
    print("\n[1/4] Creating Shared User DB schema...")

    # Import all models to ensure they're registered with Base
    from app.db import models  # noqa: F401

    # Get all tables
    all_tables = Base.metadata.tables

    # User-related tables to create
    user_tables = [
        'organizations',
        'users',
        'invitations',
        'project_members'
    ]

    # Create only User-related tables in User DB
    print(f"[INFO] Creating tables: {', '.join(user_tables)}")
    for table_name in user_tables:
        if table_name in all_tables:
            table = all_tables[table_name]
            table.create(bind=user_engine, checkfirst=True)
            print(f"  [OK] Created table: {table_name}")
        else:
            print(f"  [WARNING] Table not found in models: {table_name}")

    print("[OK] Shared User DB schema created\n")


def migrate_table(table_name: str, order_by: str = None):
    """Migrate a single table from Platform DB to User DB."""
    print(f"  Migrating {table_name}...")

    # Check if table exists in Platform DB
    inspector = inspect(platform_engine)
    if table_name not in inspector.get_table_names():
        print(f"    [SKIP] Table {table_name} not found in Platform DB")
        return 0

    # Read from Platform DB
    query = f"SELECT * FROM {table_name}"
    if order_by:
        query += f" ORDER BY {order_by}"

    with platform_engine.connect() as platform_conn:
        result = platform_conn.execute(text(query))
        rows = result.fetchall()
        columns = result.keys()

    if not rows:
        print(f"    [SKIP] No data in {table_name}")
        return 0

    # Write to User DB
    with user_engine.connect() as user_conn:
        # Clear existing data
        user_conn.execute(text(f"DELETE FROM {table_name}"))
        user_conn.commit()

        # Insert rows
        placeholders = ', '.join([f":{col}" for col in columns])
        insert_query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"

        for row in rows:
            # Convert row to dict for named parameters
            row_dict = dict(zip(columns, row))
            user_conn.execute(text(insert_query), row_dict)

        user_conn.commit()

    print(f"    [OK] Migrated {len(rows)} rows")
    return len(rows)


def migrate_user_data():
    """Migrate all User-related data from Platform DB to User DB."""
    print("[2/4] Migrating User data from Platform DB to Shared User DB...")

    total_rows = 0

    # Migrate in order (respecting foreign keys)
    total_rows += migrate_table('organizations', order_by='id')
    total_rows += migrate_table('users', order_by='id')
    total_rows += migrate_table('invitations', order_by='id')
    total_rows += migrate_table('project_members', order_by='id')

    print(f"[OK] Migrated {total_rows} total rows\n")
    return total_rows


def verify_migration():
    """Verify data integrity after migration."""
    print("[3/4] Verifying migration...")

    tables = ['organizations', 'users', 'invitations', 'project_members']
    all_match = True

    for table_name in tables:
        # Count rows in Platform DB
        with platform_engine.connect() as platform_conn:
            result = platform_conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            platform_count = result.scalar()

        # Count rows in User DB
        with user_engine.connect() as user_conn:
            result = user_conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            user_count = result.scalar()

        match = platform_count == user_count
        all_match = all_match and match

        status = "[OK]" if match else "[ERROR]"
        print(f"  {status} {table_name}: Platform={platform_count}, Shared User DB={user_count}")

    if all_match:
        print("[OK] All tables verified successfully\n")
    else:
        print("[ERROR] Some tables have mismatched row counts\n")

    return all_match


def display_summary():
    """Display migration summary."""
    print("[4/4] Migration Summary")
    print("=" * 60)

    with user_engine.connect() as conn:
        # Organizations
        result = conn.execute(text("SELECT COUNT(*) FROM organizations"))
        org_count = result.scalar()

        # Users
        result = conn.execute(text("SELECT COUNT(*) FROM users"))
        user_count = result.scalar()

        # Invitations
        result = conn.execute(text("SELECT COUNT(*) FROM invitations"))
        invitation_count = result.scalar()

        # Project Members
        result = conn.execute(text("SELECT COUNT(*) FROM project_members"))
        member_count = result.scalar()

    print(f"Shared User DB: {user_engine.url}")
    print(f"  Organizations:   {org_count}")
    print(f"  Users:           {user_count}")
    print(f"  Invitations:     {invitation_count}")
    print(f"  Project Members: {member_count}")
    print("=" * 60)
    print("\n[SUCCESS] Phase 11 Tier 1 migration completed!")
    print("\nNext steps:")
    print("1. Update API endpoints to use get_user_db() dependency")
    print("2. Test Platform and Labeler with shared User DB")
    print("3. Verify JWT token compatibility between services\n")


def main():
    """Run Phase 11 Tier 1 migration."""
    print("\n" + "=" * 60)
    print("Phase 11 Tier 1: User DB Migration")
    print("Platform DB -> Shared User DB (SQLite)")
    print("=" * 60)
    print(f"Platform DB:     {platform_engine.url}")
    print(f"Shared User DB:  {user_engine.url}")
    print("=" * 60 + "\n")

    try:
        # Step 1: Create schema
        create_user_db_schema()

        # Step 2: Migrate data
        total_rows = migrate_user_data()

        if total_rows == 0:
            print("[WARNING] No data to migrate. Platform DB may be empty.\n")
            return

        # Step 3: Verify
        verified = verify_migration()

        if not verified:
            print("[ERROR] Migration verification failed!")
            sys.exit(1)

        # Step 4: Summary
        display_summary()

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
