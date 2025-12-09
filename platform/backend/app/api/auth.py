"""Authentication API endpoints."""

import random
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_token
)
from app.db.database import get_user_db
from app.db import models
from app.schemas import user as user_schemas
from app.utils.dependencies import get_current_user

router = APIRouter()

# Avatar badge colors (excluding light colors like yellow, amber, lime)
BADGE_COLORS = [
    'red', 'orange', 'green', 'emerald',
    'teal', 'cyan', 'sky', 'blue',
    'indigo', 'violet', 'purple', 'fuchsia', 'pink'
]

# Avatar name adjectives and nouns for random generation
AVATAR_ADJECTIVES = [
    'happy', 'brave', 'clever', 'wise', 'swift',
    'bright', 'cool', 'kind', 'bold', 'calm',
    'eager', 'fair', 'gentle', 'keen', 'noble'
]

AVATAR_NOUNS = [
    'panda', 'tiger', 'eagle', 'dolphin', 'fox',
    'wolf', 'lion', 'bear', 'hawk', 'owl',
    'falcon', 'lynx', 'otter', 'raven', 'phoenix'
]


def generate_avatar_name() -> str:
    """Generate a random avatar name in the format 'adjective-noun-number'."""
    adjective = random.choice(AVATAR_ADJECTIVES)
    noun = random.choice(AVATAR_NOUNS)
    number = random.randint(100, 999)
    return f"{adjective}-{noun}-{number}"


def find_or_create_organization(
    db: Session,
    company: str | None,
    company_custom: str | None,
    division: str | None,
    division_custom: str | None
) -> models.Organization:
    """
    Find or create an organization based on company and division.

    Args:
        db: Database session
        company: Company name or selection
        company_custom: Custom company name if "직접입력" selected
        division: Division name or selection
        division_custom: Custom division name if "직접입력" selected

    Returns:
        Organization object
    """
    # Determine actual company name
    actual_company = company_custom if company == "직접입력" else (company or "Default")

    # Determine actual division name
    actual_division = division_custom if division == "직접입력" else (division or "Engineering")

    # Try to find existing organization with same company and division
    org = db.query(models.Organization).filter(
        models.Organization.company == actual_company,
        models.Organization.division == actual_division
    ).first()

    if org:
        return org

    # Create new organization
    org_name = f"{actual_company} - {actual_division}"
    new_org = models.Organization(
        name=org_name,
        company=actual_company,
        division=actual_division,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.add(new_org)
    db.commit()
    db.refresh(new_org)

    return new_org


@router.post("/register", response_model=user_schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    user_in: user_schemas.UserCreate,
    db: Session = Depends(get_user_db)
):
    """
    Register a new user.

    Args:
        user_in: User registration data
        db: Database session

    Returns:
        Created user object

    Raises:
        HTTPException: If email already registered
    """
    # Check if user already exists
    existing_user = db.query(models.User).filter(models.User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Find or create organization
    organization = find_or_create_organization(
        db=db,
        company=user_in.company,
        company_custom=user_in.company_custom,
        division=user_in.division,
        division_custom=user_in.division_custom
    )

    # Create new user with default system_role='guest', random badge color, and avatar name
    hashed_password = get_password_hash(user_in.password)
    db_user = models.User(
        email=user_in.email,
        hashed_password=hashed_password,
        full_name=user_in.full_name,
        company=user_in.company,
        company_custom=user_in.company_custom,
        division=user_in.division,
        division_custom=user_in.division_custom,
        department=user_in.department,
        phone_number=user_in.phone_number,
        bio=user_in.bio,
        organization_id=organization.id,
        system_role=models.UserRole.GUEST,  # New users start as guest
        avatar_name=generate_avatar_name(),  # Generate random avatar name
        is_active=True,
        badge_color=random.choice(BADGE_COLORS)  # Assign random badge color
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


@router.post("/login", response_model=user_schemas.Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_user_db)
):
    """
    Login with email and password.

    Args:
        form_data: OAuth2 form data (username=email, password)
        db: Database session

    Returns:
        Access and refresh tokens

    Raises:
        HTTPException: If credentials are invalid
    """
    # Find user by email (OAuth2 uses 'username' field)
    try:
        user = db.query(models.User).filter(models.User.email == form_data.username).first()
    except Exception as e:
        # Database connection error or other DB-related errors
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Database error during login: {str(e)}")

        # Check if it's a connection error
        error_msg = str(e).lower()
        if "connection refused" in error_msg or "could not connect" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database server is not available. Please ensure PostgreSQL is running and accessible."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}"
            )

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    # Create tokens with additional user data for frontend
    token_data = {
        "sub": user.id,
        "email": user.email,
        "role": user.system_role.value,  # Include role for permission checks
        "organization_id": user.organization_id  # Include org for multi-tenancy
    }
    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data={"sub": user.id})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.post("/refresh", response_model=user_schemas.Token)
def refresh_token(
    refresh_token: str,
    db: Session = Depends(get_user_db)
):
    """
    Refresh access token using refresh token.

    Args:
        refresh_token: Refresh token
        db: Database session

    Returns:
        New access and refresh tokens

    Raises:
        HTTPException: If refresh token is invalid
    """
    try:
        payload = decode_token(refresh_token)
        user_id = payload.get("sub")
        token_type = payload.get("type")

        if user_id is None or token_type != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )

        # Verify user exists
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive"
            )

        # Create new tokens with additional user data
        token_data = {
            "sub": user.id,
            "email": user.email,
            "role": user.system_role.value,
            "organization_id": user.organization_id
        }
        new_access_token = create_access_token(data=token_data)
        new_refresh_token = create_refresh_token(data={"sub": user.id})

        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer"
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid refresh token: {str(e)}"
        )


@router.get("/me", response_model=user_schemas.UserResponse)
def get_current_user_info(
    current_user: models.User = Depends(get_current_user)
):
    """
    Get current user information.

    Args:
        current_user: Current authenticated user

    Returns:
        Current user object
    """
    return current_user


@router.put("/me", response_model=user_schemas.UserResponse)
def update_current_user(
    user_update: user_schemas.UserUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_user_db)
):
    """
    Update current user information.

    Args:
        user_update: User update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated user object
    """
    from datetime import datetime

    # Update fields if provided
    if user_update.full_name is not None:
        current_user.full_name = user_update.full_name
    if user_update.company is not None:
        current_user.company = user_update.company
    if user_update.company_custom is not None:
        current_user.company_custom = user_update.company_custom
    if user_update.division is not None:
        current_user.division = user_update.division
    if user_update.division_custom is not None:
        current_user.division_custom = user_update.division_custom
    if user_update.department is not None:
        current_user.department = user_update.department
    if user_update.phone_number is not None:
        current_user.phone_number = user_update.phone_number
    if user_update.bio is not None:
        current_user.bio = user_update.bio

    # Update password if provided
    if user_update.password is not None:
        current_user.hashed_password = get_password_hash(user_update.password)

    current_user.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(current_user)

    return current_user


@router.post("/logout")
def logout():
    """
    Logout (client-side token deletion).

    Note: Since we're using JWT tokens, logout is handled client-side
    by deleting the tokens. This endpoint is a placeholder for future
    token blacklisting implementation.

    Returns:
        Success message
    """
    return {"message": "Successfully logged out"}


@router.post("/forgot-password")
def request_password_reset(
    request: user_schemas.ForgotPasswordRequest,
    db: Session = Depends(get_user_db)
):
    """
    Request a password reset email.

    Args:
        request: Email of the user requesting password reset
        db: Database session

    Returns:
        Success message (always returns success to prevent email enumeration)

    Note:
        Even if the email doesn't exist, we return success to prevent
        email enumeration attacks.
    """
    # Find user by email
    user = db.query(models.User).filter(models.User.email == request.email).first()

    if user and user.is_active:
        # Generate password reset token (expires in 1 hour)
        import secrets
        reset_token = secrets.token_urlsafe(32)

        # Store token in database with expiration
        from datetime import timedelta
        user.password_reset_token = reset_token
        user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
        db.commit()

        # Send password reset email
        from app.services.email_service import get_email_service
        email_service = get_email_service()
        email_service.send_password_reset_email(
            to_email=user.email,
            reset_token=reset_token,
            user_name=user.full_name
        )

    # Always return success to prevent email enumeration
    return {
        "message": "If the email exists, a password reset link has been sent",
        "detail": "Please check your email for the password reset link"
    }


@router.post("/reset-password")
def reset_password(
    request: user_schemas.ResetPasswordRequest,
    db: Session = Depends(get_user_db)
):
    """
    Reset password using a reset token.

    Args:
        request: Reset token and new password
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If token is invalid or expired
    """
    # Find user by reset token
    user = db.query(models.User).filter(
        models.User.password_reset_token == request.token
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    # Check if token is expired
    if not user.password_reset_expires or user.password_reset_expires < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired. Please request a new one."
        )

    # Update password
    user.hashed_password = get_password_hash(request.new_password)

    # Clear reset token
    user.password_reset_token = None
    user.password_reset_expires = None

    user.updated_at = datetime.utcnow()

    db.commit()

    return {
        "message": "Password has been reset successfully",
        "detail": "You can now login with your new password"
    }

