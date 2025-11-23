"""Phase 11 Tier 1: Remove User tables from Platform DB.

This script:
1. Drops all Foreign Key constraints referencing users, organizations, invitations, project_members
2. Drops the tables: users, organizations, invitations, project_members
3. Keeps user_id columns as plain integers (no FK)

After this cleanup:
- Platform DB: Projects, datasets, training jobs, etc. (with user_id as integer)
- Shared User DB: Users, organizations, invitations, project_members

Usage:
    cd platform/backend
    python scripts/phase11/cleanup_platform_db_user_tables.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text, inspect
from app.db.database import platform_engine


def drop_foreign_keys():
    """Drop all FK constraints referencing User tables."""
    print("\n[1/2] Dropping Foreign Key constraints...")

    inspector = inspect(platform_engine)

    fk_constraints = [
        # datasets
        ('datasets', 'datasets_owner_id_fkey'),

        # projects
        ('projects', 'projects_organization_id_fkey'),
        ('projects', 'projects_user_id_fkey'),

        # sessions
        ('sessions', 'sessions_user_id_fkey'),

        # invitations (will be dropped with table, but for safety)
        ('invitations', 'invitations_invitee_id_fkey'),
        ('invitations', 'invitations_inviter_id_fkey'),
        ('invitations', 'invitations_organization_id_fkey'),

        # project_members (will be dropped with table, but for safety)
        ('project_members', 'project_members_invited_by_fkey'),
        ('project_members', 'project_members_user_id_fkey'),

        # dataset_permissions
        ('dataset_permissions', 'dataset_permissions_granted_by_fkey'),
        ('dataset_permissions', 'dataset_permissions_user_id_fkey'),

        # experiment_stars
        ('experiment_stars', 'experiment_stars_user_id_fkey'),

        # experiment_notes
        ('experiment_notes', 'experiment_notes_user_id_fkey'),

        # training_jobs
        ('training_jobs', 'training_jobs_created_by_fkey'),

        # deployment_history
        ('deployment_history', 'deployment_history_triggered_by_fkey'),

        # users table self-reference
        ('users', 'users_organization_id_fkey'),
    ]

    dropped_count = 0
    with platform_engine.connect() as conn:
        for table_name, constraint_name in fk_constraints:
            try:
                # Check if table exists
                if table_name not in inspector.get_table_names():
                    print(f"  [SKIP] Table {table_name} does not exist")
                    continue

                # Check if constraint exists
                fks = inspector.get_foreign_keys(table_name)
                if not any(fk['name'] == constraint_name for fk in fks):
                    print(f"  [SKIP] Constraint {constraint_name} not found in {table_name}")
                    continue

                # Drop FK constraint
                sql = f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS {constraint_name}"
                conn.execute(text(sql))
                conn.commit()
                print(f"  [OK] Dropped {table_name}.{constraint_name}")
                dropped_count += 1

            except Exception as e:
                print(f"  [ERROR] Failed to drop {table_name}.{constraint_name}: {e}")

    print(f"[OK] Dropped {dropped_count} FK constraints\n")


def drop_user_tables():
    """Drop User-related tables from Platform DB."""
    print("[2/2] Dropping User tables from Platform DB...")

    # Order matters due to dependencies
    tables_to_drop = [
        'project_members',  # References users
        'invitations',      # References users, organizations
        'users',            # References organizations
        'organizations',    # No dependencies
        'sessions',         # References users (also drop sessions as it's user-related)
    ]

    inspector = inspect(platform_engine)
    dropped_count = 0

    with platform_engine.connect() as conn:
        for table_name in tables_to_drop:
            try:
                # Check if table exists
                if table_name not in inspector.get_table_names():
                    print(f"  [SKIP] Table {table_name} does not exist")
                    continue

                # Count rows before drop
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                row_count = result.scalar()

                # Drop table
                conn.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
                conn.commit()
                print(f"  [OK] Dropped {table_name} ({row_count} rows)")
                dropped_count += 1

            except Exception as e:
                print(f"  [ERROR] Failed to drop {table_name}: {e}")

    print(f"[OK] Dropped {dropped_count} tables\n")


def verify_cleanup():
    """Verify that User tables are removed."""
    print("[3/3] Verifying cleanup...")

    inspector = inspect(platform_engine)
    tables = inspector.get_table_names()

    user_tables = ['users', 'organizations', 'invitations', 'project_members', 'sessions']
    remaining = [t for t in user_tables if t in tables]

    if remaining:
        print(f"  [WARNING] Tables still exist: {', '.join(remaining)}")
        return False
    else:
        print("  [OK] All User tables removed")

    # Check remaining FK constraints
    print("\n  Remaining tables in Platform DB:")
    for table in sorted(tables):
        fks = inspector.get_foreign_keys(table)
        user_fks = [fk for fk in fks if fk['referred_table'] in user_tables]
        if user_fks:
            print(f"    [WARNING] {table} still has FK to User tables:")
            for fk in user_fks:
                print(f"      - {fk['name']} -> {fk['referred_table']}")
        else:
            print(f"    [OK] {table}")

    print()
    return len(remaining) == 0


def main():
    """Run Platform DB cleanup."""
    print("\n" + "=" * 60)
    print("Phase 11 Tier 1: Platform DB Cleanup")
    print("Remove User tables from Platform DB")
    print("=" * 60)
    print(f"Platform DB: {platform_engine.url}")
    print("=" * 60 + "\n")

    try:
        # Step 1: Drop FK constraints
        drop_foreign_keys()

        # Step 2: Drop User tables
        drop_user_tables()

        # Step 3: Verify
        success = verify_cleanup()

        if success:
            print("=" * 60)
            print("[SUCCESS] Platform DB cleanup completed!")
            print("=" * 60)
            print("\nPlatform DB now contains:")
            print("  - Projects, datasets, training jobs, experiments")
            print("  - User references are plain integers (no FK)")
            print("\nShared User DB contains:")
            print("  - Users, organizations, invitations, project_members")
            print("=" * 60 + "\n")
        else:
            print("[WARNING] Cleanup completed with warnings. Check output above.")
            sys.exit(1)

    except Exception as e:
        print(f"\n[ERROR] Cleanup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
