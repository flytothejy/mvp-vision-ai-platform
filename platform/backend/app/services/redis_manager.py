"""Redis Manager for state management and pub/sub communication.

This module provides a centralized Redis connection manager with support for:
- Basic key-value operations
- Hash operations
- Set operations
- Pub/Sub messaging
- Distributed locks
- Connection pooling
- Health checks

Design Principles:
1. Shared State, Local Connections
2. Eventual Consistency
3. Graceful Degradation
4. No Redis-Managed Persistence
5. TTL-First Design

See: docs/architecture/REDIS_INTEGRATION_DESIGN.md
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class RedisManager:
    """Central Redis connection and operation manager.

    Provides unified interface for all Redis operations with:
    - Connection pooling (max 50 connections)
    - Graceful error handling
    - TTL-first design
    - Automatic reconnection

    Usage:
        redis_manager = RedisManager(redis_url="redis://localhost:6379/0")
        await redis_manager.connect()

        # Basic operations
        await redis_manager.set("key", "value", ttl=3600)
        value = await redis_manager.get("key")

        # Graceful shutdown
        await redis_manager.close()
    """

    def __init__(
        self,
        redis_url: str,
        max_connections: int = 50,
        socket_timeout: float = 5.0,
        socket_connect_timeout: float = 5.0,
        retry_on_timeout: bool = True,
    ):
        """Initialize Redis manager with connection pool.

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:6379/0)
            max_connections: Maximum number of connections in pool
            socket_timeout: Socket timeout in seconds
            socket_connect_timeout: Socket connect timeout in seconds
            retry_on_timeout: Retry operations on timeout
        """
        self.redis_url = redis_url
        self.max_connections = max_connections
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout
        self.retry_on_timeout = retry_on_timeout

        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[redis.Redis] = None
        self._connected = False

    async def connect(self) -> None:
        """Establish Redis connection pool.

        Raises:
            RedisError: If connection fails
        """
        try:
            self._pool = ConnectionPool.from_url(
                self.redis_url,
                max_connections=self.max_connections,
                socket_timeout=self.socket_timeout,
                socket_connect_timeout=self.socket_connect_timeout,
                retry_on_timeout=self.retry_on_timeout,
                decode_responses=True,  # Auto-decode bytes to strings
            )

            self._client = redis.Redis(connection_pool=self._pool)

            # Test connection
            await self._client.ping()
            self._connected = True

            logger.info(
                f"Redis connected successfully to {self.redis_url} "
                f"(max_connections={self.max_connections})"
            )

        except RedisError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self._connected = False
            raise

    async def close(self) -> None:
        """Close Redis connection pool gracefully."""
        if self._client:
            await self._client.aclose()
            self._client = None

        if self._pool:
            await self._pool.aclose()
            self._pool = None

        self._connected = False
        logger.info("Redis connection closed")

    async def ping(self) -> bool:
        """Health check - test Redis connectivity.

        Returns:
            True if Redis is responsive, False otherwise
        """
        if not self._client:
            return False

        try:
            await self._client.ping()
            return True
        except RedisError as e:
            logger.warning(f"Redis ping failed: {e}")
            return False

    # ===================================================================
    # Basic Key-Value Operations
    # ===================================================================

    async def get(self, key: str) -> Optional[str]:
        """Get value by key.

        Args:
            key: Redis key

        Returns:
            Value as string, or None if key doesn't exist
        """
        if not self._client:
            logger.warning("Redis not connected, cannot get key")
            return None

        try:
            return await self._client.get(key)
        except RedisError as e:
            logger.error(f"Redis GET failed for key {key}: {e}")
            return None

    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None
    ) -> bool:
        """Set key-value pair with optional TTL.

        Args:
            key: Redis key
            value: Value to store (will be converted to string)
            ttl: Time to live in seconds (None = no expiration)

        Returns:
            True if successful, False otherwise
        """
        if not self._client:
            logger.warning("Redis not connected, cannot set key")
            return False

        try:
            if ttl:
                await self._client.setex(key, ttl, value)
            else:
                await self._client.set(key, value)
            return True
        except RedisError as e:
            logger.error(f"Redis SET failed for key {key}: {e}")
            return False

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys.

        Args:
            *keys: Keys to delete

        Returns:
            Number of keys deleted
        """
        if not self._client:
            logger.warning("Redis not connected, cannot delete keys")
            return 0

        try:
            return await self._client.delete(*keys)
        except RedisError as e:
            logger.error(f"Redis DELETE failed for keys {keys}: {e}")
            return 0

    async def exists(self, *keys: str) -> int:
        """Check if keys exist.

        Args:
            *keys: Keys to check

        Returns:
            Number of existing keys
        """
        if not self._client:
            return 0

        try:
            return await self._client.exists(*keys)
        except RedisError as e:
            logger.error(f"Redis EXISTS failed for keys {keys}: {e}")
            return 0

    async def expire(self, key: str, ttl: int) -> bool:
        """Set TTL on existing key.

        Args:
            key: Redis key
            ttl: Time to live in seconds

        Returns:
            True if TTL was set, False if key doesn't exist or error
        """
        if not self._client:
            return False

        try:
            return await self._client.expire(key, ttl)
        except RedisError as e:
            logger.error(f"Redis EXPIRE failed for key {key}: {e}")
            return False

    # ===================================================================
    # Hash Operations
    # ===================================================================

    async def hset(
        self,
        name: str,
        mapping: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> int:
        """Set hash fields.

        Args:
            name: Hash name
            mapping: Dict of field-value pairs
            ttl: Optional TTL in seconds

        Returns:
            Number of fields added
        """
        if not self._client:
            logger.warning("Redis not connected, cannot hset")
            return 0

        try:
            # Convert values to strings
            str_mapping = {k: str(v) for k, v in mapping.items()}
            result = await self._client.hset(name, mapping=str_mapping)

            if ttl:
                await self._client.expire(name, ttl)

            return result
        except RedisError as e:
            logger.error(f"Redis HSET failed for hash {name}: {e}")
            return 0

    async def hget(self, name: str, key: str) -> Optional[str]:
        """Get hash field value.

        Args:
            name: Hash name
            key: Field name

        Returns:
            Field value or None
        """
        if not self._client:
            return None

        try:
            return await self._client.hget(name, key)
        except RedisError as e:
            logger.error(f"Redis HGET failed for hash {name}, key {key}: {e}")
            return None

    async def hgetall(self, name: str) -> Dict[str, str]:
        """Get all hash fields.

        Args:
            name: Hash name

        Returns:
            Dict of all field-value pairs (empty dict if error)
        """
        if not self._client:
            return {}

        try:
            return await self._client.hgetall(name)
        except RedisError as e:
            logger.error(f"Redis HGETALL failed for hash {name}: {e}")
            return {}

    async def hdel(self, name: str, *keys: str) -> int:
        """Delete hash fields.

        Args:
            name: Hash name
            *keys: Field names to delete

        Returns:
            Number of fields deleted
        """
        if not self._client:
            return 0

        try:
            return await self._client.hdel(name, *keys)
        except RedisError as e:
            logger.error(f"Redis HDEL failed for hash {name}, keys {keys}: {e}")
            return 0

    # ===================================================================
    # Set Operations
    # ===================================================================

    async def sadd(self, name: str, *values: str) -> int:
        """Add members to set.

        Args:
            name: Set name
            *values: Members to add

        Returns:
            Number of members added
        """
        if not self._client:
            return 0

        try:
            return await self._client.sadd(name, *values)
        except RedisError as e:
            logger.error(f"Redis SADD failed for set {name}: {e}")
            return 0

    async def srem(self, name: str, *values: str) -> int:
        """Remove members from set.

        Args:
            name: Set name
            *values: Members to remove

        Returns:
            Number of members removed
        """
        if not self._client:
            return 0

        try:
            return await self._client.srem(name, *values)
        except RedisError as e:
            logger.error(f"Redis SREM failed for set {name}: {e}")
            return 0

    async def smembers(self, name: str) -> set:
        """Get all set members.

        Args:
            name: Set name

        Returns:
            Set of members (empty set if error)
        """
        if not self._client:
            return set()

        try:
            return await self._client.smembers(name)
        except RedisError as e:
            logger.error(f"Redis SMEMBERS failed for set {name}: {e}")
            return set()

    async def sismember(self, name: str, value: str) -> bool:
        """Check if value is member of set.

        Args:
            name: Set name
            value: Value to check

        Returns:
            True if member exists, False otherwise
        """
        if not self._client:
            return False

        try:
            return await self._client.sismember(name, value)
        except RedisError as e:
            logger.error(f"Redis SISMEMBER failed for set {name}, value {value}: {e}")
            return False

    # ===================================================================
    # Pub/Sub Operations
    # ===================================================================

    async def publish(self, channel: str, message: str) -> int:
        """Publish message to channel.

        Args:
            channel: Channel name
            message: Message to publish (will be converted to string)

        Returns:
            Number of subscribers that received the message
        """
        if not self._client:
            logger.warning(f"Redis not connected, cannot publish to {channel}")
            return 0

        try:
            return await self._client.publish(channel, message)
        except RedisError as e:
            logger.error(f"Redis PUBLISH failed for channel {channel}: {e}")
            return 0

    async def publish_json(self, channel: str, data: Dict[str, Any]) -> int:
        """Publish JSON data to channel.

        Args:
            channel: Channel name
            data: Data to publish as JSON

        Returns:
            Number of subscribers that received the message
        """
        try:
            message = json.dumps(data)
            return await self.publish(channel, message)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize data for channel {channel}: {e}")
            return 0

    @asynccontextmanager
    async def subscribe(self, *channels: str) -> AsyncIterator:
        """Subscribe to channels and yield messages.

        Args:
            *channels: Channel names to subscribe

        Yields:
            Message dict with 'type', 'channel', and 'data' keys

        Usage:
            async with redis_manager.subscribe("events:training") as messages:
                async for message in messages:
                    if message["type"] == "message":
                        print(f"Received: {message['data']}")
        """
        if not self._client:
            logger.error("Redis not connected, cannot subscribe")
            return

        pubsub = self._client.pubsub()

        try:
            await pubsub.subscribe(*channels)
            logger.info(f"Subscribed to channels: {channels}")

            async def message_iterator():
                try:
                    async for message in pubsub.listen():
                        yield message
                except RedisError as e:
                    logger.error(f"Error in pubsub listen: {e}")

            yield message_iterator()

        finally:
            await pubsub.unsubscribe(*channels)
            await pubsub.aclose()
            logger.info(f"Unsubscribed from channels: {channels}")

    # ===================================================================
    # Distributed Lock Operations
    # ===================================================================

    @asynccontextmanager
    async def acquire_lock(
        self,
        lock_key: str,
        timeout: int = 30,
        blocking_timeout: float = 10.0
    ) -> AsyncIterator[bool]:
        """Acquire distributed lock with automatic release.

        Args:
            lock_key: Lock identifier (e.g., "lock:dataset:123")
            timeout: Lock expiration timeout in seconds
            blocking_timeout: Max time to wait for lock in seconds

        Yields:
            True if lock acquired, False otherwise

        Usage:
            async with redis_manager.acquire_lock("lock:dataset:123") as acquired:
                if acquired:
                    # Do work with exclusive access
                    pass
        """
        if not self._client:
            logger.warning("Redis not connected, cannot acquire lock")
            yield False
            return

        lock = self._client.lock(
            lock_key,
            timeout=timeout,
            blocking_timeout=blocking_timeout
        )

        acquired = False
        try:
            acquired = await lock.acquire()
            if acquired:
                logger.debug(f"Lock acquired: {lock_key}")
            else:
                logger.warning(f"Failed to acquire lock: {lock_key}")

            yield acquired

        finally:
            if acquired:
                try:
                    await lock.release()
                    logger.debug(f"Lock released: {lock_key}")
                except RedisError as e:
                    logger.error(f"Failed to release lock {lock_key}: {e}")

    # ===================================================================
    # Utility Methods
    # ===================================================================

    async def keys(self, pattern: str = "*") -> List[str]:
        """Get keys matching pattern.

        WARNING: This is expensive on large datasets. Use sparingly.

        Args:
            pattern: Key pattern (e.g., "session:*")

        Returns:
            List of matching keys
        """
        if not self._client:
            return []

        try:
            return await self._client.keys(pattern)
        except RedisError as e:
            logger.error(f"Redis KEYS failed for pattern {pattern}: {e}")
            return []

    async def flushdb(self) -> bool:
        """Delete all keys in current database.

        WARNING: This is destructive. Use only in tests.

        Returns:
            True if successful, False otherwise
        """
        if not self._client:
            return False

        try:
            await self._client.flushdb()
            logger.warning("Redis database flushed (all keys deleted)")
            return True
        except RedisError as e:
            logger.error(f"Redis FLUSHDB failed: {e}")
            return False

    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected.

        Returns:
            True if connected, False otherwise
        """
        return self._connected

    def __repr__(self) -> str:
        """String representation."""
        status = "connected" if self._connected else "disconnected"
        return f"RedisManager(url={self.redis_url}, status={status})"
