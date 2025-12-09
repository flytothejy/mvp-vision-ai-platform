"""Database initialization script for Vision AI Training Platform.

This script creates all required database tables for both Platform DB and User DB.

Usage:
    python init_db.py                 # Initialize both databases
    python init_db.py --platform-only # Initialize platform DB only
    python init_db.py --user-only     # Initialize user DB only
    python init_db.py --reset         # Drop and recreate all tables (CAUTION!)

Environment Variables:
    DATABASE_URL - PostgreSQL connection string for Platform DB
    USER_DATABASE_URL - PostgreSQL connection string for User DB
"""

import sys
import argparse
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

# Load .env file for local development
from dotenv import load_dotenv
load_dotenv()

from app.core.config import settings
from app.db.database import Base
from app.db.models import (
    Organization, Invitation, User, ProjectMember,
    DatasetSnapshot, Project, Experiment, ExperimentStar, ExperimentNote,
    Session, Message, TrainingJob, TrainingMetric, TrainingLog,
    ValidationResult, ValidationImageResult, TestRun, TestImageResult,
    InferenceJob, InferenceResult, ExportJob, DeploymentTarget, DeploymentHistory
)


def get_table_names(engine):
    """Get list of existing tables in database."""
    inspector = inspect(engine)
    return inspector.get_table_names()


def create_platform_db(engine, reset=False):
    """Create Platform DB tables.

    Args:
        engine: SQLAlchemy engine for Platform DB
        reset: If True, drop all existing tables first (CAUTION!)
    """
    print("=" * 60)
    print("Platform Database Initialization")
    print("=" * 60)
    print(f"Database URL: {settings.DATABASE_URL}")
    print()

    # Get existing tables
    existing_tables = get_table_names(engine)
    print(f"Existing tables: {len(existing_tables)}")
    if existing_tables:
        print(f"  {', '.join(existing_tables)}")
    print()

    if reset:
        print("[WARNING]  WARNING: Dropping all existing tables...")
        confirmation = input("Are you sure? Type 'yes' to confirm: ")
        if confirmation.lower() != 'yes':
            print("Aborted.")
            return
        Base.metadata.drop_all(bind=engine)
        print("[OK] All tables dropped.")
        print()

    # Create all tables
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)

    # Verify creation
    new_tables = get_table_names(engine)
    print()
    print(f"[OK] Database initialized successfully!")
    print(f"Total tables: {len(new_tables)}")
    print()
    print("Tables created:")
    for table in sorted(new_tables):
        print(f"  - {table}")
    print()


def create_user_db(engine, reset=False):
    """Create User DB tables.

    Note: Currently uses same schema as Platform DB for shared User model.
    In production, you may want to separate User-specific tables.

    Args:
        engine: SQLAlchemy engine for User DB
        reset: If True, drop all existing tables first (CAUTION!)
    """
    print("=" * 60)
    print("User Database Initialization")
    print("=" * 60)
    print(f"Database URL: {settings.USER_DATABASE_URL}")
    print()

    # Get existing tables
    existing_tables = get_table_names(engine)
    print(f"Existing tables: {len(existing_tables)}")
    if existing_tables:
        print(f"  {', '.join(existing_tables)}")
    print()

    if reset:
        print("[WARNING]  WARNING: Dropping all existing tables...")
        confirmation = input("Are you sure? Type 'yes' to confirm: ")
        if confirmation.lower() != 'yes':
            print("Aborted.")
            return
        Base.metadata.drop_all(bind=engine)
        print("[OK] All tables dropped.")
        print()

    # Create tables
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)

    # Verify creation
    new_tables = get_table_names(engine)
    print()
    print(f"[OK] User database initialized successfully!")
    print(f"Total tables: {len(new_tables)}")
    print()
    print("Tables created:")
    for table in sorted(new_tables):
        print(f"  - {table}")
    print()


def test_connection(engine, db_name):
    """Test database connection."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        print(f"[OK] {db_name} connection successful")
        return True
    except Exception as e:
        print(f"[ERROR] {db_name} connection failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Initialize Vision AI Platform databases")
    parser.add_argument('--platform-only', action='store_true', help='Initialize Platform DB only')
    parser.add_argument('--user-only', action='store_true', help='Initialize User DB only')
    parser.add_argument('--reset', action='store_true', help='Drop and recreate all tables (CAUTION!)')
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("Vision AI Training Platform - Database Initialization")
    print("=" * 60)
    print()

    # Determine which databases to initialize
    init_platform = not args.user_only
    init_user = not args.platform_only

    if args.reset:
        print("[WARNING]  RESET MODE: All existing data will be deleted!")
        print()

    success = True

    # Initialize Platform DB
    if init_platform:
        try:
            platform_engine = create_engine(
                settings.DATABASE_URL,
                pool_pre_ping=True,
                echo=False
            )

            if not test_connection(platform_engine, "Platform DB"):
                success = False
            else:
                print()
                create_platform_db(platform_engine, reset=args.reset)
                platform_engine.dispose()
        except Exception as e:
            print(f"[ERROR] Platform DB initialization failed: {e}")
            success = False

    # Initialize User DB (if separate from Platform DB)
    if init_user and settings.USER_DATABASE_URL:
        # Only initialize if User DB is different from Platform DB
        if settings.USER_DATABASE_URL != settings.DATABASE_URL:
            try:
                user_engine = create_engine(
                    settings.USER_DATABASE_URL,
                    pool_pre_ping=True,
                    echo=False
                )

                if not test_connection(user_engine, "User DB"):
                    success = False
                else:
                    print()
                    create_user_db(user_engine, reset=args.reset)
                    user_engine.dispose()
            except Exception as e:
                print(f"[ERROR] User DB initialization failed: {e}")
                success = False
        else:
            print("[INFO]  User DB uses same database as Platform DB (skipping separate initialization)")
            print()

    # Summary
    print("=" * 60)
    if success:
        print("[OK] Database initialization completed successfully!")
        print()
        print("Next steps:")
        print("1. Start the backend server:")
        print("   poetry run uvicorn app.main:app --reload --port 8000")
        print()
        print("2. Start the Temporal worker:")
        print("   poetry run python -m app.workflows.worker")
        print()
        print("3. Access the API documentation:")
        print("   http://localhost:8000/docs")
    else:
        print("[ERROR] Database initialization completed with errors.")
        print("Please check the error messages above and try again.")
        sys.exit(1)
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
