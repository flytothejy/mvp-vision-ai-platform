"""Unit tests for RedisManager.

Tests cover:
- Connection management
- Basic key-value operations
- Hash operations
- Set operations
- Pub/Sub messaging
- Distributed locks
- Error handling and graceful degradation
"""

import asyncio
import json

import pytest

from app.services.redis_manager import RedisManager


class TestRedisManagerConnection:
    """Test Redis connection management."""

    @pytest.mark.asyncio
    async def test_connect_success(self, redis_manager):
        """Test successful Redis connection."""
        assert redis_manager.is_connected
        assert await redis_manager.ping()

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test connection failure with invalid URL."""
        manager = RedisManager(redis_url="redis://invalid-host:6379/0")

        with pytest.raises(Exception):  # RedisError or ConnectionError
            await manager.connect()

        assert not manager.is_connected

    @pytest.mark.asyncio
    async def test_close_connection(self, redis_manager):
        """Test closing Redis connection."""
        assert redis_manager.is_connected

        await redis_manager.close()

        assert not redis_manager.is_connected
        assert not await redis_manager.ping()


class TestRedisManagerBasicOperations:
    """Test basic key-value operations."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, redis_manager):
        """Test SET and GET operations."""
        # Set value
        success = await redis_manager.set("test:key", "test_value")
        assert success

        # Get value
        value = await redis_manager.get("test:key")
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_set_with_ttl(self, redis_manager):
        """Test SET with TTL."""
        # Set value with 1 second TTL
        success = await redis_manager.set("test:ttl", "expires", ttl=1)
        assert success

        # Value exists immediately
        value = await redis_manager.get("test:ttl")
        assert value == "expires"

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Value should be gone
        value = await redis_manager.get("test:ttl")
        assert value is None

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, redis_manager):
        """Test GET for non-existent key."""
        value = await redis_manager.get("nonexistent:key")
        assert value is None

    @pytest.mark.asyncio
    async def test_delete_key(self, redis_manager):
        """Test DELETE operation."""
        # Create key
        await redis_manager.set("test:delete", "value")

        # Delete key
        deleted = await redis_manager.delete("test:delete")
        assert deleted == 1

        # Key should be gone
        value = await redis_manager.get("test:delete")
        assert value is None

    @pytest.mark.asyncio
    async def test_delete_multiple_keys(self, redis_manager):
        """Test deleting multiple keys."""
        # Create keys
        await redis_manager.set("test:delete1", "value1")
        await redis_manager.set("test:delete2", "value2")
        await redis_manager.set("test:delete3", "value3")

        # Delete all keys
        deleted = await redis_manager.delete(
            "test:delete1",
            "test:delete2",
            "test:delete3"
        )
        assert deleted == 3

    @pytest.mark.asyncio
    async def test_exists(self, redis_manager):
        """Test EXISTS operation."""
        # Create key
        await redis_manager.set("test:exists", "value")

        # Check existence
        exists = await redis_manager.exists("test:exists")
        assert exists == 1

        # Check non-existent key
        exists = await redis_manager.exists("test:nonexistent")
        assert exists == 0

    @pytest.mark.asyncio
    async def test_expire(self, redis_manager):
        """Test setting TTL on existing key."""
        # Create key without TTL
        await redis_manager.set("test:expire", "value")

        # Set TTL
        success = await redis_manager.expire("test:expire", 1)
        assert success

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Key should be gone
        value = await redis_manager.get("test:expire")
        assert value is None


class TestRedisManagerHashOperations:
    """Test hash operations."""

    @pytest.mark.asyncio
    async def test_hset_and_hgetall(self, redis_manager):
        """Test HSET and HGETALL operations."""
        # Set hash fields
        data = {
            "field1": "value1",
            "field2": "value2",
            "field3": "123"
        }
        result = await redis_manager.hset("test:hash", data)
        assert result >= 0  # Number of fields added

        # Get all fields
        retrieved = await redis_manager.hgetall("test:hash")
        assert retrieved == data

    @pytest.mark.asyncio
    async def test_hget(self, redis_manager):
        """Test HGET operation."""
        # Set hash
        data = {"field1": "value1", "field2": "value2"}
        await redis_manager.hset("test:hash", data)

        # Get single field
        value = await redis_manager.hget("test:hash", "field1")
        assert value == "value1"

        # Get non-existent field
        value = await redis_manager.hget("test:hash", "nonexistent")
        assert value is None

    @pytest.mark.asyncio
    async def test_hset_with_ttl(self, redis_manager):
        """Test HSET with TTL."""
        # Set hash with TTL
        data = {"field": "value"}
        await redis_manager.hset("test:hash:ttl", data, ttl=1)

        # Hash exists immediately
        retrieved = await redis_manager.hgetall("test:hash:ttl")
        assert retrieved == data

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Hash should be gone
        retrieved = await redis_manager.hgetall("test:hash:ttl")
        assert retrieved == {}

    @pytest.mark.asyncio
    async def test_hdel(self, redis_manager):
        """Test HDEL operation."""
        # Set hash
        data = {"field1": "value1", "field2": "value2", "field3": "value3"}
        await redis_manager.hset("test:hash", data)

        # Delete field
        deleted = await redis_manager.hdel("test:hash", "field1")
        assert deleted == 1

        # Field should be gone
        value = await redis_manager.hget("test:hash", "field1")
        assert value is None

        # Other fields remain
        value = await redis_manager.hget("test:hash", "field2")
        assert value == "value2"


class TestRedisManagerSetOperations:
    """Test set operations."""

    @pytest.mark.asyncio
    async def test_sadd_and_smembers(self, redis_manager):
        """Test SADD and SMEMBERS operations."""
        # Add members
        added = await redis_manager.sadd("test:set", "member1", "member2", "member3")
        assert added == 3

        # Get all members
        members = await redis_manager.smembers("test:set")
        assert members == {"member1", "member2", "member3"}

    @pytest.mark.asyncio
    async def test_srem(self, redis_manager):
        """Test SREM operation."""
        # Create set
        await redis_manager.sadd("test:set", "member1", "member2", "member3")

        # Remove member
        removed = await redis_manager.srem("test:set", "member1")
        assert removed == 1

        # Member should be gone
        members = await redis_manager.smembers("test:set")
        assert "member1" not in members
        assert members == {"member2", "member3"}

    @pytest.mark.asyncio
    async def test_sismember(self, redis_manager):
        """Test SISMEMBER operation."""
        # Create set
        await redis_manager.sadd("test:set", "member1", "member2")

        # Check membership
        is_member = await redis_manager.sismember("test:set", "member1")
        assert is_member

        # Check non-member
        is_member = await redis_manager.sismember("test:set", "nonexistent")
        assert not is_member


class TestRedisManagerPubSub:
    """Test Pub/Sub operations."""

    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self, redis_manager):
        """Test basic publish and subscribe."""
        messages_received = []

        async def subscriber():
            """Subscribe and collect messages."""
            async with redis_manager.subscribe("test:channel") as messages:
                async for message in messages:
                    if message["type"] == "message":
                        messages_received.append(message["data"])
                        if len(messages_received) >= 2:
                            break

        # Start subscriber
        subscriber_task = asyncio.create_task(subscriber())

        # Wait for subscription to be ready
        await asyncio.sleep(0.1)

        # Publish messages
        await redis_manager.publish("test:channel", "message1")
        await redis_manager.publish("test:channel", "message2")

        # Wait for subscriber to receive messages
        await asyncio.wait_for(subscriber_task, timeout=2.0)

        # Check received messages
        assert "message1" in messages_received
        assert "message2" in messages_received

    @pytest.mark.asyncio
    async def test_publish_json(self, redis_manager):
        """Test publishing JSON data."""
        messages_received = []

        async def subscriber():
            """Subscribe and collect JSON messages."""
            async with redis_manager.subscribe("test:json") as messages:
                async for message in messages:
                    if message["type"] == "message":
                        data = json.loads(message["data"])
                        messages_received.append(data)
                        break

        # Start subscriber
        subscriber_task = asyncio.create_task(subscriber())

        # Wait for subscription
        await asyncio.sleep(0.1)

        # Publish JSON
        test_data = {"key": "value", "number": 123}
        await redis_manager.publish_json("test:json", test_data)

        # Wait for subscriber
        await asyncio.wait_for(subscriber_task, timeout=2.0)

        # Check received data
        assert len(messages_received) == 1
        assert messages_received[0] == test_data


class TestRedisManagerDistributedLock:
    """Test distributed lock operations."""

    @pytest.mark.asyncio
    async def test_acquire_and_release_lock(self, redis_manager):
        """Test basic lock acquisition and release."""
        lock_key = "lock:test:resource"

        async with redis_manager.acquire_lock(lock_key) as acquired:
            assert acquired
            # Lock is held here

        # Lock should be released after context manager exits

    @pytest.mark.asyncio
    async def test_lock_prevents_concurrent_access(self, redis_manager):
        """Test that lock prevents concurrent access."""
        lock_key = "lock:test:concurrent"
        results = []

        async def worker(worker_id: int):
            """Try to acquire lock and record result."""
            async with redis_manager.acquire_lock(
                lock_key,
                timeout=5,
                blocking_timeout=0.1  # Don't wait long
            ) as acquired:
                if acquired:
                    results.append(worker_id)
                    await asyncio.sleep(0.2)  # Hold lock briefly

        # Start two workers concurrently
        await asyncio.gather(
            worker(1),
            worker(2)
        )

        # Only one worker should have acquired the lock
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_lock_expires_after_timeout(self, redis_manager):
        """Test that lock expires after timeout."""
        lock_key = "lock:test:timeout"

        # Acquire lock with short timeout
        async with redis_manager.acquire_lock(lock_key, timeout=1) as acquired:
            assert acquired

        # Wait for lock to expire
        await asyncio.sleep(1.1)

        # Should be able to acquire lock again
        async with redis_manager.acquire_lock(lock_key, timeout=1) as acquired:
            assert acquired


class TestRedisManagerUtilities:
    """Test utility methods."""

    @pytest.mark.asyncio
    async def test_keys_pattern_matching(self, redis_manager):
        """Test keys pattern matching."""
        # Create keys with pattern
        await redis_manager.set("test:user:1", "alice")
        await redis_manager.set("test:user:2", "bob")
        await redis_manager.set("test:session:1", "data")

        # Find keys with pattern
        user_keys = await redis_manager.keys("test:user:*")
        assert len(user_keys) == 2
        assert "test:user:1" in user_keys
        assert "test:user:2" in user_keys

    @pytest.mark.asyncio
    async def test_flushdb(self, redis_manager):
        """Test flushing database."""
        # Create some keys
        await redis_manager.set("test:key1", "value1")
        await redis_manager.set("test:key2", "value2")

        # Flush database
        success = await redis_manager.flushdb()
        assert success

        # All keys should be gone
        keys = await redis_manager.keys("*")
        assert len(keys) == 0


class TestRedisManagerErrorHandling:
    """Test error handling and graceful degradation."""

    @pytest.mark.asyncio
    async def test_operations_fail_gracefully_when_disconnected(self):
        """Test that operations fail gracefully when Redis is not connected."""
        manager = RedisManager(redis_url="redis://localhost:6379/15")
        # Don't connect

        # Operations should return None/False/empty instead of raising
        assert await manager.get("key") is None
        assert await manager.set("key", "value") is False
        assert await manager.hgetall("hash") == {}
        assert await manager.smembers("set") == set()
        assert await manager.publish("channel", "message") == 0

    @pytest.mark.asyncio
    async def test_repr(self, redis_manager):
        """Test string representation."""
        repr_str = repr(redis_manager)
        assert "RedisManager" in repr_str
        assert "connected" in repr_str
