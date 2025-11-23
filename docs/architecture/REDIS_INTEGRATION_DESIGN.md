# Redis Integration Design

**Author**: Development Team
**Created**: 2025-11-21
**Status**: Design Review
**Phase**: 5.0 - Redis Integration

---

## Executive Summary

This document outlines the design for integrating Redis as a central communication and state management layer for the Vision AI Training Platform's multi-backend architecture. Redis will enable horizontal scaling by providing shared state management, cross-backend communication, and distributed coordination across Common Backend (8000), Data Backend (8010), Labeler Backend (8020), and Training Backend (8030).

**Key Benefits**:
- ✅ Horizontal scaling: Add backend instances without coordination
- ✅ Service isolation: Independent deployment and failure domains
- ✅ Real-time communication: Sub-millisecond Pub/Sub latency
- ✅ Session portability: Users can switch between backend instances
- ✅ Graceful degradation: Continue operation if Redis temporarily unavailable

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Design Principles](#design-principles)
3. [Core Components](#core-components)
4. [Data Structures & Key Naming](#data-structures--key-naming)
5. [Implementation Details](#implementation-details)
6. [Security Considerations](#security-considerations)
7. [Performance & Optimization](#performance--optimization)
8. [Monitoring & Operations](#monitoring--operations)
9. [Migration Plan](#migration-plan)
10. [Testing Strategy](#testing-strategy)

---

## Architecture Overview

### Current State (Single Backend)

```
┌─────────────────────────────────────┐
│     Common Backend (Port 8000)      │
│  ┌─────────────────────────────┐   │
│  │   In-Memory State           │   │
│  │  - active_connections: {}   │   │
│  │  - job_connections: {}      │   │
│  └─────────────────────────────┘   │
└─────────────────────────────────────┘
```

**Limitations**:
- ❌ Cannot scale horizontally (state tied to single instance)
- ❌ WebSocket reconnection fails if backend restarts
- ❌ No session sharing across services
- ❌ Single point of failure

### Target State (Multi-Backend with Redis)

```
                ┌─────────────────────────────┐
                │      API Gateway (Kong)      │
                │   Load Balancer / Routing    │
                └──────────┬──────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼─────┐      ┌────▼─────┐      ┌────▼─────┐
   │ Common-1 │      │ Common-2 │      │  Data    │
   │ Backend  │      │ Backend  │      │ Backend  │
   │  (8000)  │      │  (8000)  │      │  (8010)  │
   └────┬─────┘      └────┬─────┘      └────┬─────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
                ┌──────────▼──────────┐
                │   Redis (6379)      │
                │  ┌───────────────┐  │
                │  │ Session Store │  │
                │  │ Pub/Sub       │  │
                │  │ WebSocket Map │  │
                │  │ Cache Layer   │  │
                │  │ Dist. Locks   │  │
                │  └───────────────┘  │
                └─────────────────────┘
```

**Benefits**:
- ✅ Horizontal scaling: Multiple Common Backend instances behind load balancer
- ✅ Session portability: User session accessible from any backend
- ✅ WebSocket reconnection: Can reconnect to different backend instance
- ✅ Cross-service communication: Data Backend can trigger events in Common Backend
- ✅ Distributed coordination: Locks prevent race conditions

---

## Design Principles

### 1. **Shared State, Local Connections**
- **Redis**: Stores metadata about connections (who's connected to what)
- **Local Memory**: Stores actual WebSocket connections (cannot be serialized)

**Why**: WebSocket objects cannot be serialized/shared. Redis tracks "which backend has which connection", then messages are routed via Pub/Sub.

### 2. **Eventual Consistency**
- Some operations (cache invalidation, connection cleanup) are eventually consistent
- Critical operations (locks, session writes) are strongly consistent

**Trade-off**: Performance vs Consistency. We prioritize performance for non-critical paths.

### 3. **Graceful Degradation**
- If Redis is unavailable, backends continue operating with limited functionality
- Session Store: Falls back to JWT validation only
- WebSocket: Falls back to local connections only
- Cache: Falls back to direct database queries

**Why**: Redis downtime shouldn't cause total platform outage.

### 4. **No Redis-Managed Persistence**
- Database remains source of truth for all persistent data
- Redis is purely for real-time state and coordination

**Why**: Simplifies disaster recovery and backup strategies.

### 5. **TTL-First Design**
- All keys have TTL (Time To Live)
- No indefinite keys to prevent memory leaks
- Short TTL for transient data (connections: 1h)
- Longer TTL for semi-static data (model metadata: 10m)

**Why**: Automatic cleanup, predictable memory usage.

---

## Core Components

### 1. Session Store

**Purpose**: Share user authentication state across all backends.

**Use Case**:
- User logs in via Common Backend → Session saved to Redis
- User makes request to Data Backend → Session validated from Redis
- No need to re-authenticate or hit database

**Data Structure**:
```redis
Key: session:{user_id}
Type: Hash
Fields:
  - user_id: 123
  - username: "john"
  - email: "john@example.com"
  - role: "admin"
  - organization_id: 456
  - created_at: "2025-11-21T10:00:00Z"
  - last_activity: "2025-11-21T10:30:00Z"
TTL: 3600 seconds (1 hour)
```

**Operations**:
- `save_session(user_id, data, ttl=3600)` - Login
- `get_session(user_id)` - Request validation
- `refresh_session(user_id)` - Update last_activity
- `invalidate_session(user_id)` - Logout

**Security**:
- Session data is non-sensitive (no passwords)
- JWT token still required for API calls
- Redis session is secondary validation layer

---

### 2. Pub/Sub Event System

**Purpose**: Cross-backend event-driven communication.

**Use Case**:
- Training completes in Training Backend → Event published
- Common Backend receives event → Updates UI via WebSocket
- Data Backend receives event → Updates dataset usage stats

**Channel Naming**:
```
events:training_completed
events:dataset_uploaded
events:model_exported
events:inference_finished
```

**Message Format**:
```json
{
  "event_type": "training_completed",
  "timestamp": "2025-11-21T10:30:00Z",
  "source": "training-backend-1",
  "data": {
    "job_id": 123,
    "status": "completed",
    "final_accuracy": 0.95,
    "mlflow_run_id": "abc123"
  }
}
```

**Subscriber Pattern**:
```python
# Each backend subscribes to relevant events
async for message in pubsub.subscribe(["events:training_*", "events:dataset_*"]):
    await handle_event(message)
```

**Reliability**:
- ⚠️ Pub/Sub is fire-and-forget (no delivery guarantee)
- Critical operations still use database as source of truth
- Events are **notifications**, not **state changes**

---

### 3. WebSocket State Sharing

**Purpose**: Enable WebSocket broadcasting across backend instances.

**Current Problem**:
```python
# Backend 1: User connects via WebSocket
active_connections[connection_id] = websocket

# Backend 2: Training completes, tries to broadcast
# ❌ Cannot access Backend 1's active_connections
```

**Solution with Redis**:
```python
# Backend 1: Register connection in Redis
await redis.hset(f"ws:connection:{conn_id}", {
    "user_id": 123,
    "backend_id": "common-1",
    "job_id": 456,
    "connected_at": "2025-11-21T10:00:00Z"
})
await redis.sadd(f"ws:job:{job_id}", connection_id)

# Backend 2: Broadcast to job
await redis.publish(f"ws:job:{job_id}", json.dumps(message))

# Backend 1: Receives pub/sub message, sends via local WebSocket
async for msg in redis.subscribe(f"ws:job:*"):
    local_websocket = local_connections[conn_id]
    await local_websocket.send_json(msg)
```

**Data Structures**:
```redis
# Connection metadata
Key: ws:connection:{connection_id}
Type: Hash
TTL: 3600s (1 hour)

# Job → Connections mapping
Key: ws:job:{job_id}
Type: Set
TTL: 86400s (24 hours)

# User → Connections mapping
Key: ws:user:{user_id}
Type: Set
TTL: 3600s (1 hour)
```

**Connection Lifecycle**:
1. **Connect**: Register in Redis, subscribe to job channel
2. **Heartbeat**: Update TTL every 30 seconds
3. **Disconnect**: Remove from Redis, unsubscribe
4. **Timeout**: TTL expires, automatic cleanup

---

### 4. Distributed Locks

**Purpose**: Prevent race conditions in concurrent operations.

**Use Cases**:
- Dataset modification (only one backend can modify at a time)
- Model export (prevent duplicate export jobs)
- Resource allocation (GPU assignment)

**Implementation** (Redis SET NX + EX):
```redis
# Acquire lock
SET lock:dataset:123 <lock_id> NX EX 30

# Release lock (only if we own it)
if redis.call("GET", "lock:dataset:123") == <lock_id> then
    redis.call("DEL", "lock:dataset:123")
end
```

**Lock Pattern**:
```python
async with RedisLock(f"dataset:{dataset_id}", ttl=30):
    # Critical section: Only one backend can enter
    dataset = await db.query(Dataset).filter_by(id=dataset_id).first()
    dataset.version += 1
    await db.commit()
# Lock automatically released
```

**Lock Types**:
1. **Exclusive Lock** (default): Only one holder
2. **Timeout Lock**: Automatic release after TTL
3. **Reentrant Lock**: Same process can re-acquire

**Edge Cases**:
- **Lock expiration**: Operation takes longer than TTL → Lock auto-releases
  - **Solution**: Extend TTL with heartbeat
- **Process crash**: Lock holder crashes → Lock stuck until TTL
  - **Solution**: Short TTL (30s-60s)
- **Clock skew**: Different backend clocks → TTL inconsistent
  - **Solution**: Redis server time is authoritative

---

### 5. Cache Layer

**Purpose**: Reduce database load and Training Service API calls.

**Use Cases**:
- Model metadata caching (fetch from Training Service)
- Dataset statistics (expensive DB query)
- User preferences (frequently accessed)

**Cache Pattern**:
```python
async def get_model_metadata(model_name: str):
    key = f"cache:model:{model_name}"

    # Try cache first
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)

    # Cache miss: Fetch from Training Service
    response = await httpx.get(f"{TRAINING_SERVICE_URL}/models/{model_name}")
    data = response.json()

    # Cache for 10 minutes
    await redis.set(key, json.dumps(data), ex=600)
    return data
```

**Cache Key Structure**:
```
cache:model:{model_name}           # TTL: 600s (10 min)
cache:dataset:{dataset_id}:stats   # TTL: 300s (5 min)
cache:user:{user_id}:preferences   # TTL: 1800s (30 min)
```

**Invalidation Strategies**:
1. **TTL-based** (default): Let cache expire naturally
2. **Event-based**: Invalidate on Pub/Sub event
3. **Manual**: Explicit `cache.delete(key)` on mutation

**Cache Miss Handling**:
```python
# Thundering herd prevention
async def get_or_compute(key, compute_fn, ttl):
    # Try get
    value = await redis.get(key)
    if value:
        return value

    # Acquire lock to prevent multiple backends computing simultaneously
    async with RedisLock(f"compute:{key}", ttl=5):
        # Double-check (another backend might have cached while we waited)
        value = await redis.get(key)
        if value:
            return value

        # Compute and cache
        value = await compute_fn()
        await redis.set(key, value, ex=ttl)
        return value
```

---

## Data Structures & Key Naming

### Key Naming Convention

**Format**: `{namespace}:{entity}:{id}[:{sub_entity}]`

**Namespaces**:
- `session:` - User sessions
- `ws:` - WebSocket connections
- `lock:` - Distributed locks
- `cache:` - Application cache
- `events:` - Pub/Sub event channels
- `queue:` - Background job queues

**Examples**:
```
session:123                          # User 123's session
ws:connection:abc-def-ghi            # WebSocket connection metadata
ws:job:456                           # Set of connections watching job 456
ws:user:123                          # Set of user 123's connections
lock:dataset:789                     # Lock for dataset 789
cache:model:yolo11n                  # Cached model metadata
events:training_completed            # Pub/Sub channel
queue:inference:pending              # Pending inference jobs
```

### TTL Strategy

| Data Type | TTL | Rationale |
|-----------|-----|-----------|
| Session | 3600s (1h) | Match JWT expiration |
| WebSocket Connection | 3600s (1h) | Max inactive connection time |
| WebSocket Job Mapping | 86400s (24h) | Persist for job lifetime |
| Lock | 30-60s | Short timeout for safety |
| Cache (Model) | 600s (10m) | Model metadata rarely changes |
| Cache (Dataset Stats) | 300s (5m) | May change during training |
| Cache (User Prefs) | 1800s (30m) | Rarely changed |

### Memory Estimation

**Assumptions**:
- 1000 concurrent users
- 500 active WebSocket connections
- 100 models cached
- 1000 datasets

**Storage**:
```
Sessions: 1000 * 1KB = 1MB
WebSocket Connections: 500 * 500B = 250KB
WebSocket Job Mappings: 100 jobs * 10 connections * 100B = 100KB
Locks: 50 * 100B = 5KB
Model Cache: 100 * 5KB = 500KB
Dataset Cache: 1000 * 2KB = 2MB

Total: ~4MB
```

**With 10x growth**: ~40MB (well within Redis capacity)

---

## Implementation Details

### RedisManager Class

```python
# app/services/redis_manager.py

import redis.asyncio as redis
from typing import Optional, AsyncIterator
import json
import logging

logger = logging.getLogger(__name__)

class RedisManager:
    """Central Redis connection and operation manager"""

    def __init__(self, redis_url: str, max_connections: int = 50):
        """
        Initialize Redis manager with connection pooling.

        Args:
            redis_url: Redis connection URL (redis://host:port/db)
            max_connections: Max connections in pool
        """
        self.redis_url = redis_url
        self.client = redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=max_connections
        )
        self._pubsub = None

    async def ping(self) -> bool:
        """Health check"""
        try:
            await self.client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis ping failed: {e}")
            return False

    async def info(self) -> dict:
        """Get Redis server info"""
        return await self.client.info()

    # Basic operations
    async def get(self, key: str) -> Optional[str]:
        """Get string value"""
        return await self.client.get(key)

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set string value with optional TTL"""
        return await self.client.set(key, value, ex=ttl)

    async def delete(self, key: str) -> int:
        """Delete key"""
        return await self.client.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        return await self.client.exists(key) > 0

    async def expire(self, key: str, ttl: int) -> bool:
        """Set TTL on existing key"""
        return await self.client.expire(key, ttl)

    # Hash operations
    async def hset(self, name: str, mapping: dict) -> int:
        """Set hash fields"""
        return await self.client.hset(name, mapping=mapping)

    async def hget(self, name: str, key: str) -> Optional[str]:
        """Get single hash field"""
        return await self.client.hget(name, key)

    async def hgetall(self, name: str) -> dict:
        """Get all hash fields"""
        return await self.client.hgetall(name)

    async def hdel(self, name: str, *keys: str) -> int:
        """Delete hash fields"""
        return await self.client.hdel(name, *keys)

    # Set operations
    async def sadd(self, name: str, *values: str) -> int:
        """Add members to set"""
        return await self.client.sadd(name, *values)

    async def srem(self, name: str, *values: str) -> int:
        """Remove members from set"""
        return await self.client.srem(name, *values)

    async def smembers(self, name: str) -> set:
        """Get all set members"""
        return await self.client.smembers(name)

    async def sismember(self, name: str, value: str) -> bool:
        """Check if member in set"""
        return await self.client.sismember(name, value)

    # List operations
    async def lpush(self, name: str, *values: str) -> int:
        """Push to list head"""
        return await self.client.lpush(name, *values)

    async def rpush(self, name: str, *values: str) -> int:
        """Push to list tail"""
        return await self.client.rpush(name, *values)

    async def lpop(self, name: str) -> Optional[str]:
        """Pop from list head"""
        return await self.client.lpop(name)

    async def rpop(self, name: str) -> Optional[str]:
        """Pop from list tail"""
        return await self.client.rpop(name)

    async def lrange(self, name: str, start: int, end: int) -> list:
        """Get list range"""
        return await self.client.lrange(name, start, end)

    # Pub/Sub operations
    async def publish(self, channel: str, message: str) -> int:
        """Publish message to channel"""
        return await self.client.publish(channel, message)

    async def subscribe(self, *channels: str) -> AsyncIterator[dict]:
        """Subscribe to channels and yield messages"""
        pubsub = self.client.pubsub()
        await pubsub.subscribe(*channels)

        try:
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    yield {
                        'channel': message['channel'],
                        'data': message['data']
                    }
        finally:
            await pubsub.unsubscribe(*channels)
            await pubsub.close()

    async def close(self):
        """Close Redis connection"""
        await self.client.close()
```

### Usage Examples

```python
# Initialization (in app startup)
from app.services.redis_manager import RedisManager

redis_manager = RedisManager(settings.REDIS_URL)
await redis_manager.ping()  # Verify connection

# Session Store
await redis_manager.hset(f"session:{user_id}", {
    "user_id": str(user_id),
    "username": user.username,
    "role": user.role
})
await redis_manager.expire(f"session:{user_id}", 3600)

# WebSocket Registration
connection_id = str(uuid.uuid4())
await redis_manager.hset(f"ws:connection:{connection_id}", {
    "user_id": str(user_id),
    "backend_id": "common-1",
    "connected_at": datetime.utcnow().isoformat()
})
await redis_manager.sadd(f"ws:job:{job_id}", connection_id)

# Broadcast via Pub/Sub
message = json.dumps({"type": "training_progress", "job_id": job_id, "epoch": 5})
await redis_manager.publish(f"ws:job:{job_id}", message)

# Cache
model_data = json.dumps({"name": "yolo11n", "params": 1000000})
await redis_manager.set(f"cache:model:yolo11n", model_data, ttl=600)
```

---

## Security Considerations

### 1. Access Control

**Redis AUTH**:
```bash
# Redis server configuration
requirepass your-strong-password-here

# Connection string
redis://:your-strong-password@localhost:6379/0
```

**Network Security**:
- Redis bound to private network only (not public internet)
- TLS encryption for production (`rediss://` protocol)
- Firewall rules: Only backend servers can access Redis

### 2. Data Sensitivity

**Stored in Redis**:
- ✅ User ID, username, role (non-sensitive metadata)
- ✅ Connection IDs (random UUIDs)
- ✅ WebSocket metadata (job IDs, timestamps)

**NOT Stored in Redis**:
- ❌ Passwords (even hashed)
- ❌ JWT tokens (only in HTTP-only cookies)
- ❌ API keys
- ❌ Sensitive user data (email visible in session, acceptable for internal use)

### 3. Key Isolation

**Multi-tenancy**:
- Prefix all keys with organization ID for strict isolation
- Example: `org:456:session:123` instead of `session:123`

**Why**: Prevents data leakage between organizations.

### 4. Injection Prevention

**Safe Key Construction**:
```python
# ❌ Unsafe (user input not validated)
key = f"session:{user_provided_id}"

# ✅ Safe (validated integer)
user_id = int(user_provided_id)  # Raises ValueError if not int
key = f"session:{user_id}"
```

---

## Performance & Optimization

### 1. Connection Pooling

**Configuration**:
```python
redis_manager = RedisManager(
    redis_url=settings.REDIS_URL,
    max_connections=50  # Pool size
)
```

**Why**: Reuse connections, avoid TCP handshake overhead.

### 2. Pipelining

**Batch Operations**:
```python
# ❌ Slow: 3 round trips
await redis.set("key1", "value1")
await redis.set("key2", "value2")
await redis.set("key3", "value3")

# ✅ Fast: 1 round trip
async with redis.pipeline() as pipe:
    pipe.set("key1", "value1")
    pipe.set("key2", "value2")
    pipe.set("key3", "value3")
    await pipe.execute()
```

### 3. Lua Scripts

**Atomic Operations**:
```python
# Delete only if we own the lock (atomic)
release_lock_script = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

await redis.eval(release_lock_script, 1, f"lock:dataset:{id}", lock_id)
```

**Why**: Prevents race conditions without round trips.

### 4. Memory Optimization

**Compression**:
```python
import zlib
import json

# Compress large data
data = json.dumps(large_dataset_stats)
compressed = zlib.compress(data.encode())
await redis.set(key, compressed)

# Decompress
compressed = await redis.get(key)
data = zlib.decompress(compressed).decode()
dataset_stats = json.loads(data)
```

**When to use**: Data > 1KB

### 5. Monitoring Metrics

**Key Metrics**:
- `redis_connected_clients` - Active connections
- `redis_used_memory_bytes` - Memory usage
- `redis_commands_processed_total` - Throughput
- `redis_keyspace_hits_total` - Cache hit rate
- `redis_keyspace_misses_total` - Cache miss rate

**Prometheus Exporter**:
```yaml
# docker-compose.yml
redis-exporter:
  image: oliver006/redis_exporter:latest
  environment:
    REDIS_ADDR: redis:6379
  ports:
    - "9121:9121"
```

---

## Monitoring & Operations

### 1. Health Checks

```python
@router.get("/health")
async def health_check():
    redis_healthy = await redis_manager.ping()
    redis_info = await redis_manager.info() if redis_healthy else {}

    return {
        "redis": {
            "status": "healthy" if redis_healthy else "unhealthy",
            "used_memory": redis_info.get("used_memory_human"),
            "connected_clients": redis_info.get("connected_clients"),
            "uptime_seconds": redis_info.get("uptime_in_seconds")
        }
    }
```

### 2. Logging

**Structured Logs**:
```python
logger.info(
    "Redis operation",
    extra={
        "operation": "hset",
        "key": f"session:{user_id}",
        "ttl": 3600,
        "duration_ms": duration
    }
)
```

### 3. Alerting

**Critical Alerts**:
- Redis unavailable for > 1 minute
- Memory usage > 80%
- Eviction rate > 100/sec (memory pressure)
- Slow commands > 100ms

**Warning Alerts**:
- Cache hit rate < 70%
- Connected clients > 1000

### 4. Debugging Tools

**Redis CLI**:
```bash
# Connect to Redis
redis-cli -h localhost -p 6379

# List all keys (dev only, slow on production)
KEYS *

# Get key info
TYPE session:123
TTL session:123
HGETALL session:123

# Monitor commands in real-time
MONITOR

# Check memory usage
INFO memory

# Get slow commands
SLOWLOG GET 10
```

---

## Migration Plan

### Phase 1: Infrastructure Setup (Week 1)

**Tasks**:
1. ✅ Install Redis library (`redis[hiredis]`)
2. ✅ Implement `RedisManager` class
3. ✅ Add Redis to `docker-compose.yml` (already exists)
4. ✅ Add Redis health check to `/health` endpoint
5. ✅ Write unit tests for `RedisManager`

**Verification**:
```bash
pytest tests/unit/test_redis_manager.py -v
curl http://localhost:8000/health | jq .redis
```

### Phase 2: Core Features (Week 2)

**Tasks**:
1. ✅ Implement Session Store
2. ✅ Implement Pub/Sub system
3. ✅ Migrate WebSocket state to Redis
4. ✅ Integration tests for each feature

**Verification**:
```bash
pytest tests/integration/test_redis_session.py -v
pytest tests/integration/test_redis_websocket.py -v
```

### Phase 3: Advanced Features (Week 3)

**Tasks**:
1. ✅ Implement distributed locks
2. ✅ Implement cache layer
3. ✅ Add monitoring and metrics
4. ✅ E2E tests with multiple backend instances

**Verification**:
```bash
pytest tests/e2e/test_multi_backend.py -v
```

### Phase 4: Production Rollout (Week 4)

**Tasks**:
1. ✅ Deploy to staging environment
2. ✅ Load testing (1000 concurrent users)
3. ✅ Chaos testing (Redis failure scenarios)
4. ✅ Documentation updates
5. ✅ Production deployment

**Rollback Plan**:
- Redis failures degrade to local-only mode
- Can disable Redis via environment variable: `REDIS_ENABLED=false`
- Database and core functionality unaffected

---

## Testing Strategy

### Unit Tests

**`tests/unit/test_redis_manager.py`**:
```python
async def test_redis_set_get():
    await redis.set("test_key", "test_value", ttl=60)
    value = await redis.get("test_key")
    assert value == "test_value"

async def test_redis_hash_operations():
    await redis.hset("test_hash", {"field1": "value1", "field2": "value2"})
    data = await redis.hgetall("test_hash")
    assert data == {"field1": "value1", "field2": "value2"}

async def test_redis_ttl_expiration():
    await redis.set("test_ttl", "value", ttl=1)
    await asyncio.sleep(2)
    value = await redis.get("test_ttl")
    assert value is None
```

### Integration Tests

**`tests/integration/test_redis_session.py`**:
```python
async def test_session_sharing_across_backends():
    # Backend 1: Save session
    backend1 = create_test_backend(redis_url)
    await backend1.session_store.save_session(user_id, session_data)

    # Backend 2: Read session
    backend2 = create_test_backend(redis_url)
    session = await backend2.session_store.get_session(user_id)

    assert session == session_data
```

**`tests/integration/test_redis_websocket.py`**:
```python
async def test_websocket_broadcast_across_instances():
    # Connect to Backend 1
    ws1 = await connect_websocket(backend1_url, job_id)

    # Connect to Backend 2
    ws2 = await connect_websocket(backend2_url, job_id)

    # Broadcast from Backend 1
    await backend1.broadcast_to_job(job_id, {"status": "completed"})

    # Both connections receive
    msg1 = await ws1.receive_json()
    msg2 = await ws2.receive_json()
    assert msg1 == msg2 == {"status": "completed"}
```

### E2E Tests

**`tests/e2e/test_multi_backend.py`**:
```python
async def test_user_session_persistence():
    # User logs in via Backend 1
    response1 = await backend1.post("/auth/login", json=credentials)
    token = response1.json()["access_token"]

    # User makes request to Backend 2 with same token
    response2 = await backend2.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    # Should succeed (session shared via Redis)
    assert response2.status_code == 200
    assert response2.json()["username"] == credentials["username"]

async def test_training_completion_broadcast():
    # Start training via Backend 1
    response = await backend1.post("/training/jobs", json=training_config)
    job_id = response.json()["id"]

    # Connect WebSocket to Backend 2
    async with websockets.connect(f"{backend2_ws_url}/ws/training/{job_id}") as ws:
        # Training completes (simulate)
        await simulate_training_completion(job_id)

        # Backend 2 should receive completion event
        message = await ws.recv()
        data = json.loads(message)
        assert data["type"] == "training_complete"
        assert data["job_id"] == job_id
```

### Load Tests

**`tests/load/test_redis_performance.py`**:
```python
async def test_session_throughput():
    """Test 1000 concurrent session reads"""
    async def read_session(user_id):
        return await session_store.get_session(user_id)

    tasks = [read_session(i) for i in range(1000)]
    start = time.time()
    await asyncio.gather(*tasks)
    duration = time.time() - start

    # Should complete in < 1 second
    assert duration < 1.0
    print(f"Throughput: {1000/duration:.0f} ops/sec")
```

---

## Appendix

### A. Redis Commands Quick Reference

| Command | Purpose | Example |
|---------|---------|---------|
| `PING` | Health check | `PING` → PONG |
| `SET key value EX 60` | Set with TTL | `SET session:123 {...} EX 3600` |
| `GET key` | Get value | `GET session:123` |
| `DEL key` | Delete | `DEL session:123` |
| `EXISTS key` | Check existence | `EXISTS session:123` → 1 |
| `TTL key` | Get remaining TTL | `TTL session:123` → 3599 |
| `HSET key field value` | Hash set | `HSET session:123 username john` |
| `HGETALL key` | Hash get all | `HGETALL session:123` |
| `SADD key member` | Set add | `SADD ws:job:456 conn-abc` |
| `SMEMBERS key` | Set members | `SMEMBERS ws:job:456` |
| `PUBLISH channel msg` | Pub/Sub publish | `PUBLISH events:training {...}` |
| `SUBSCRIBE channel` | Pub/Sub subscribe | `SUBSCRIBE events:*` |

### B. Configuration Examples

**Development (.env)**:
```bash
REDIS_URL=redis://localhost:6379/0
REDIS_ENABLED=true
REDIS_MAX_CONNECTIONS=50
```

**Production (Kubernetes)**:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: backend-config
data:
  REDIS_URL: "redis://redis-service:6379/0"
  REDIS_ENABLED: "true"
  REDIS_MAX_CONNECTIONS: "200"

---

apiVersion: v1
kind: Secret
metadata:
  name: backend-secrets
type: Opaque
stringData:
  REDIS_PASSWORD: "your-secure-password"
```

### C. Troubleshooting Guide

**Problem: Redis connection refused**
```bash
# Check Redis is running
docker-compose ps redis

# Check Redis logs
docker-compose logs redis

# Test connection
redis-cli -h localhost -p 6379 ping
```

**Problem: High memory usage**
```bash
# Check memory info
redis-cli INFO memory

# Check keyspace
redis-cli INFO keyspace

# Find large keys
redis-cli --bigkeys
```

**Problem: Pub/Sub messages not delivered**
```bash
# Check subscribers
redis-cli PUBSUB NUMSUB events:training_completed

# Monitor in real-time
redis-cli MONITOR
```

---

## Approval & Sign-off

This design document must be reviewed and approved before implementation begins.

**Reviewers**:
- [ ] Backend Team Lead
- [ ] DevOps Engineer
- [ ] Security Engineer

**Approval Date**: _____________

**Implementation Start Date**: _____________

---

**Document Version**: 1.0
**Last Updated**: 2025-11-21
