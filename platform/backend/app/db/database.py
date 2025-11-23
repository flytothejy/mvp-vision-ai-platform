"""Database connection and session management.

Phase 11: Microservice Separation - 2-DB Pattern
- Platform DB: Projects, training jobs, etc.
- Shared User DB: Users, organizations, etc. (shared with Labeler)
"""

from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def _create_engine(database_url: str):
    """Create database engine with appropriate configuration."""
    is_sqlite = database_url.startswith("sqlite")

    if is_sqlite:
        # SQLite-specific configuration
        engine = create_engine(
            database_url,
            connect_args={
                "check_same_thread": False,  # Needed for SQLite
                "timeout": 30.0,  # 30 second timeout for locks
            },
        )

        # Enable WAL mode for better concurrent access
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")  # 30 seconds
            cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
            cursor.close()
    else:
        # PostgreSQL/other databases - use connection pooling
        engine = create_engine(
            database_url,
            pool_size=5,  # Number of connections to maintain
            max_overflow=10,  # Maximum overflow connections
            pool_pre_ping=True,  # Verify connections before using
        )

    return engine


# ============================================
# Platform DB (Projects, Training Jobs, etc.)
# ============================================
platform_engine = _create_engine(settings.DATABASE_URL)
PlatformSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=platform_engine)

# ============================================
# Shared User DB (Users, Organizations, etc.)
# Phase 11: Shared between Platform and Labeler
# ============================================
user_engine = _create_engine(settings.USER_DATABASE_URL)
UserSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=user_engine)

# Base class for models
Base = declarative_base()


def get_db():
    """Platform DB session dependency."""
    db = PlatformSessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_user_db():
    """Shared User DB session dependency.

    Phase 11: This database is shared between Platform and Labeler.
    Contains: users, organizations, invitations, project_members, etc.
    """
    db = UserSessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Initialize Platform database - create all tables."""
    Base.metadata.create_all(bind=platform_engine)


def init_user_db():
    """Initialize Shared User database - create all tables.

    Phase 11: Call this to set up the shared User DB.
    """
    Base.metadata.create_all(bind=user_engine)


# ============================================
# Backward Compatibility (Phase 11)
# ============================================
# Legacy code still references SessionLocal and engine
# These are aliases to PlatformSessionLocal and platform_engine
SessionLocal = PlatformSessionLocal
engine = platform_engine
