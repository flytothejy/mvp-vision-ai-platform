"""Authentication dependencies for FastAPI endpoints."""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.database import get_db, get_user_db
from app.db import models

# OAuth2 scheme for token extraction
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    user_db: Session = Depends(get_user_db)
) -> models.User:
    """
    Get the current authenticated user from JWT token.

    Phase 11: Uses Shared User DB for authentication.

    Args:
        token: JWT access token from Authorization header
        user_db: Shared User database session

    Returns:
        Current user object

    Raises:
        HTTPException: If token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token)
        user_id_str: Optional[str] = payload.get("sub")
        token_type: Optional[str] = payload.get("type")

        if user_id_str is None or token_type != "access":
            raise credentials_exception

        # Convert user_id from string to int
        try:
            user_id = int(user_id_str)
        except (ValueError, TypeError):
            raise credentials_exception

    except JWTError as e:
        raise credentials_exception
    except Exception as e:
        raise credentials_exception

    user = user_db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise credentials_exception

    return user


def get_current_active_user(
    current_user: models.User = Depends(get_current_user)
) -> models.User:
    """
    Get the current active user (is_active=True).

    Args:
        current_user: Current user from get_current_user

    Returns:
        Active user object

    Raises:
        HTTPException: If user is inactive
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


def get_current_superuser(
    current_user: models.User = Depends(get_current_user)
) -> models.User:
    """
    Get the current superuser.

    Args:
        current_user: Current user from get_current_user

    Returns:
        Superuser object

    Raises:
        HTTPException: If user is not a superuser
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user


def check_project_permission(project_id: int, user_id: int, db: Session) -> bool:
    """
    Check if user has permission to access a project.

    Args:
        project_id: Project ID to check
        user_id: User ID to check
        db: Database session

    Returns:
        True if user has permission, False otherwise
    """
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        return False

    # Check if user is the owner
    if project.user_id == user_id:
        return True

    # Check if user is a member (when ProjectMember model is implemented)
    # member = db.query(models.ProjectMember).filter(
    #     models.ProjectMember.project_id == project_id,
    #     models.ProjectMember.user_id == user_id
    # ).first()
    # return member is not None

    return False
