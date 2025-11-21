"""Redis-based session store for shared user sessions.

This module provides session management using Redis, enabling session sharing
across multiple backend instances for horizontal scaling.

Design:
- TTL matches JWT expiration (3600s = 1 hour)
- Session data stored as Redis hash
- Graceful fallback to database if Redis unavailable
- Key format: session:{user_id}

See: docs/architecture/REDIS_INTEGRATION_DESIGN.md
"""

import logging
from datetime import datetime
from typing import Dict, Optional

from app.services.redis_manager import RedisManager

logger = logging.getLogger(__name__)


class RedisSessionStore:
    """Redis-based session store for user authentication.

    Stores user session data in Redis for fast access and sharing across
    backend instances.

    Session data includes:
    - user_id: User identifier
    - email: User email
    - username: User username
    - is_active: Account status
    - is_superuser: Admin status
    - last_activity: Last activity timestamp
    - created_at: Session creation time

    Usage:
        session_store = RedisSessionStore(redis_manager)

        # Save session
        await session_store.save_session(
            user_id=123,
            session_data={"email": "user@example.com", ...}
        )

        # Get session
        session = await session_store.get_session(user_id=123)

        # Delete session (logout)
        await session_store.delete_session(user_id=123)
    """

    def __init__(
        self,
        redis_manager: RedisManager,
        default_ttl: int = 3600  # 1 hour, matches JWT expiration
    ):
        """Initialize session store.

        Args:
            redis_manager: RedisManager instance
            default_ttl: Default session TTL in seconds (default: 3600 = 1 hour)
        """
        self.redis = redis_manager
        self.default_ttl = default_ttl

    def _get_session_key(self, user_id: int) -> str:
        """Get Redis key for user session.

        Args:
            user_id: User ID

        Returns:
            Redis key in format: session:{user_id}
        """
        return f"session:{user_id}"

    async def save_session(
        self,
        user_id: int,
        session_data: Dict[str, any],
        ttl: Optional[int] = None
    ) -> bool:
        """Save user session to Redis.

        Args:
            user_id: User ID
            session_data: Session data dict (email, username, is_active, etc.)
            ttl: Time to live in seconds (default: self.default_ttl)

        Returns:
            True if successful, False otherwise
        """
        if not self.redis.is_connected:
            logger.warning(f"Redis not connected, cannot save session for user {user_id}")
            return False

        try:
            key = self._get_session_key(user_id)
            ttl = ttl or self.default_ttl

            # Add metadata
            data = {
                "user_id": str(user_id),
                "created_at": datetime.utcnow().isoformat(),
                "last_activity": datetime.utcnow().isoformat(),
                **session_data
            }

            # Save as hash with TTL
            result = await self.redis.hset(key, data, ttl=ttl)

            if result >= 0:
                logger.debug(f"Session saved for user {user_id} (TTL: {ttl}s)")
                return True
            else:
                logger.warning(f"Failed to save session for user {user_id}")
                return False

        except Exception as e:
            logger.error(f"Error saving session for user {user_id}: {e}")
            return False

    async def get_session(self, user_id: int) -> Optional[Dict[str, str]]:
        """Get user session from Redis.

        Args:
            user_id: User ID

        Returns:
            Session data dict if exists, None otherwise
        """
        if not self.redis.is_connected:
            logger.warning(f"Redis not connected, cannot get session for user {user_id}")
            return None

        try:
            key = self._get_session_key(user_id)
            session_data = await self.redis.hgetall(key)

            if not session_data:
                logger.debug(f"No session found for user {user_id}")
                return None

            logger.debug(f"Session retrieved for user {user_id}")
            return session_data

        except Exception as e:
            logger.error(f"Error getting session for user {user_id}: {e}")
            return None

    async def update_session(
        self,
        user_id: int,
        updates: Dict[str, any],
        extend_ttl: bool = True
    ) -> bool:
        """Update user session data.

        Args:
            user_id: User ID
            updates: Fields to update
            extend_ttl: Whether to extend TTL (default: True)

        Returns:
            True if successful, False otherwise
        """
        if not self.redis.is_connected:
            logger.warning(f"Redis not connected, cannot update session for user {user_id}")
            return False

        try:
            key = self._get_session_key(user_id)

            # Check if session exists
            exists = await self.redis.exists(key)
            if not exists:
                logger.warning(f"Cannot update non-existent session for user {user_id}")
                return False

            # Add last_activity timestamp
            updates["last_activity"] = datetime.utcnow().isoformat()

            # Update fields
            result = await self.redis.hset(key, updates)

            # Extend TTL if requested
            if extend_ttl:
                await self.redis.expire(key, self.default_ttl)

            logger.debug(f"Session updated for user {user_id}")
            return result >= 0

        except Exception as e:
            logger.error(f"Error updating session for user {user_id}: {e}")
            return False

    async def delete_session(self, user_id: int) -> bool:
        """Delete user session (logout).

        Args:
            user_id: User ID

        Returns:
            True if deleted, False otherwise
        """
        if not self.redis.is_connected:
            logger.warning(f"Redis not connected, cannot delete session for user {user_id}")
            return False

        try:
            key = self._get_session_key(user_id)
            deleted = await self.redis.delete(key)

            if deleted > 0:
                logger.info(f"Session deleted for user {user_id}")
                return True
            else:
                logger.debug(f"No session to delete for user {user_id}")
                return False

        except Exception as e:
            logger.error(f"Error deleting session for user {user_id}: {e}")
            return False

    async def extend_session(self, user_id: int, ttl: Optional[int] = None) -> bool:
        """Extend session TTL (keep alive).

        Args:
            user_id: User ID
            ttl: New TTL in seconds (default: self.default_ttl)

        Returns:
            True if extended, False otherwise
        """
        if not self.redis.is_connected:
            return False

        try:
            key = self._get_session_key(user_id)
            ttl = ttl or self.default_ttl

            # Update last_activity
            await self.redis.hset(key, {"last_activity": datetime.utcnow().isoformat()})

            # Extend TTL
            success = await self.redis.expire(key, ttl)

            if success:
                logger.debug(f"Session extended for user {user_id} (TTL: {ttl}s)")
            return success

        except Exception as e:
            logger.error(f"Error extending session for user {user_id}: {e}")
            return False

    async def session_exists(self, user_id: int) -> bool:
        """Check if session exists.

        Args:
            user_id: User ID

        Returns:
            True if session exists, False otherwise
        """
        if not self.redis.is_connected:
            return False

        try:
            key = self._get_session_key(user_id)
            exists = await self.redis.exists(key)
            return exists > 0

        except Exception as e:
            logger.error(f"Error checking session existence for user {user_id}: {e}")
            return False

    async def get_active_sessions_count(self) -> int:
        """Get count of active sessions.

        Returns:
            Number of active sessions (0 if Redis unavailable)
        """
        if not self.redis.is_connected:
            return 0

        try:
            keys = await self.redis.keys("session:*")
            return len(keys)

        except Exception as e:
            logger.error(f"Error counting active sessions: {e}")
            return 0

    async def clear_all_sessions(self) -> int:
        """Clear all sessions (admin operation).

        WARNING: This deletes all user sessions.

        Returns:
            Number of sessions cleared
        """
        if not self.redis.is_connected:
            logger.warning("Redis not connected, cannot clear sessions")
            return 0

        try:
            keys = await self.redis.keys("session:*")
            if not keys:
                return 0

            deleted = await self.redis.delete(*keys)
            logger.warning(f"Cleared {deleted} sessions (admin operation)")
            return deleted

        except Exception as e:
            logger.error(f"Error clearing sessions: {e}")
            return 0
