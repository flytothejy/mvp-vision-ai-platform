"""Security utilities for password hashing and JWT token management."""

import hashlib
import base64
from datetime import datetime, timedelta
from typing import Optional, Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt 72-byte limit constant
BCRYPT_MAX_BYTES = 72


def _prepare_password_for_bcrypt(password: str) -> str:
    """
    Prepare password for bcrypt hashing by applying 72-byte rule.

    bcrypt only uses the first 72 bytes of a password. To handle longer
    passwords securely, we first hash the password with SHA-256 and then
    base64 encode the result. This produces a 44-byte string that fits
    within bcrypt's limit while preserving full password entropy.

    Args:
        password: Plain text password

    Returns:
        Prepared password string (base64-encoded SHA-256 hash if password
        would exceed 72 bytes, otherwise original password)
    """
    password_bytes = password.encode('utf-8')

    # If password fits within bcrypt limit, use it directly
    if len(password_bytes) <= BCRYPT_MAX_BYTES:
        return password

    # For longer passwords, use SHA-256 pre-hashing
    # SHA-256 produces 32 bytes, base64 encoding produces 44 bytes
    sha256_hash = hashlib.sha256(password_bytes).digest()
    return base64.b64encode(sha256_hash).decode('ascii')

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour
REFRESH_TOKEN_EXPIRE_DAYS = 7  # 7 days
SERVICE_TOKEN_EXPIRE_MINUTES = 5  # 5 minutes (short-lived for SSO)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.

    Applies 72-byte rule for bcrypt compatibility.

    Args:
        plain_password: Plain text password
        hashed_password: Hashed password from database

    Returns:
        True if password matches, False otherwise
    """
    prepared_password = _prepare_password_for_bcrypt(plain_password)
    return pwd_context.verify(prepared_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt with 72-byte rule.

    Applies SHA-256 pre-hashing for passwords exceeding 72 bytes
    to ensure full password entropy is preserved.

    Args:
        password: Plain text password

    Returns:
        Hashed password
    """
    prepared_password = _prepare_password_for_bcrypt(password)
    return pwd_context.hash(prepared_password)


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Data to encode in the token (usually {'sub': user_id})
        expires_delta: Token expiration time (default: 1 hour)

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()
    # Convert sub to string if it's an integer
    if "sub" in to_encode and isinstance(to_encode["sub"], int):
        to_encode["sub"] = str(to_encode["sub"])

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict[str, Any]) -> str:
    """
    Create a JWT refresh token.

    Args:
        data: Data to encode in the token (usually {'sub': user_id})

    Returns:
        Encoded JWT refresh token
    """
    to_encode = data.copy()
    # Convert sub to string if it's an integer
    if "sub" in to_encode and isinstance(to_encode["sub"], int):
        to_encode["sub"] = str(to_encode["sub"])

    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a JWT token.

    Args:
        token: JWT token to decode

    Returns:
        Decoded token payload

    Raises:
        JWTError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        raise JWTError(f"Invalid token: {str(e)}")


def create_service_token(data: dict[str, Any]) -> str:
    """
    Create a service-to-service JWT token for SSO (Phase 11.5.6).

    Used for Platform → Labeler SSO flow. This token uses a separate
    SERVICE_JWT_SECRET and has a short expiration (5 minutes) for security.

    Args:
        data: Data to encode in the token (user_id, email, etc.)

    Returns:
        Encoded JWT service token

    Example:
        >>> token = create_service_token({
        ...     "user_id": 123,
        ...     "email": "user@example.com",
        ...     "full_name": "John Doe"
        ... })
    """
    to_encode = data.copy()

    # Convert user_id to string if it's an integer
    if "user_id" in to_encode and isinstance(to_encode["user_id"], int):
        to_encode["user_id"] = str(to_encode["user_id"])

    expire = datetime.utcnow() + timedelta(minutes=SERVICE_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": expire,
        "type": "service",
        "iss": "platform",  # Issued by Platform
        "aud": "labeler"    # Intended for Labeler
    })

    # Use SERVICE_JWT_SECRET (separate from user JWT_SECRET)
    encoded_jwt = jwt.encode(to_encode, settings.SERVICE_JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


def decode_service_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a service-to-service JWT token.

    Args:
        token: Service JWT token to decode

    Returns:
        Decoded token payload

    Raises:
        JWTError: If token is invalid, expired, or not a service token
    """
    try:
        payload = jwt.decode(
            token,
            settings.SERVICE_JWT_SECRET,
            algorithms=[ALGORITHM],
            options={"verify_aud": False}  # Audience verification optional
        )

        # Verify token type
        if payload.get("type") != "service":
            raise JWTError("Not a service token")

        return payload
    except JWTError as e:
        raise JWTError(f"Invalid service token: {str(e)}")
