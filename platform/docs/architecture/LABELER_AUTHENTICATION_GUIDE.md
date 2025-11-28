# Labeler Backend Authentication Guide

**Phase 11.5.6: Hybrid JWT Authentication**
**Document Version**: 1.0
**Last Updated**: 2025-11-28

## Overview

Platform Backend communicates with Labeler Backend using **Hybrid JWT** authentication. This approach combines:
- **User context** (user_id) for permission checks
- **Service identity** (service name) for audit trail
- **Scopes** for fine-grained authorization
- **Short-lived tokens** (5min) for security

## Authentication Flow

```
User Request
    ↓
Platform Backend
    ↓ Generate Service JWT (5min)
    ↓ - user_id: from authenticated user
    ↓ - service: "platform"
    ↓ - scopes: ["labeler:read", "labeler:write"]
    ↓
Labeler Backend
    ↓ Verify JWT signature
    ↓ Check token expiration
    ↓ Validate scopes
    ↓ Extract user_id
    ↓ Enforce user permissions
    ↓
Return Response
```

## JWT Token Structure

### User-Initiated Request Token

Platform sends this when a user makes a request (e.g., list datasets, get dataset):

```json
{
  "sub": "123",                    // User ID (string)
  "service": "platform",            // Calling service name
  "scopes": ["labeler:read"],       // Permissions
  "type": "service",                // Token type
  "iat": 1732780800,                // Issued at (Unix timestamp)
  "exp": 1732781100,                // Expires at (Unix + 300s = 5min)
  "nbf": 1732780800                 // Not before (Unix timestamp)
}
```

### Background Job Token

Platform sends this for long-running training jobs (no active user):

```json
{
  "sub": null,                      // No user context
  "service": "platform-training",   // Service identity
  "scopes": ["labeler:read"],       // Read-only for training
  "type": "background",             // Background job marker
  "iat": 1732780800,
  "exp": 1732784400,                // Longer expiry (1 hour)
  "nbf": 1732780800
}
```

## Standard Scopes

Platform uses these scopes when calling Labeler API:

| Scope | Description | Used For |
|-------|-------------|----------|
| `labeler:read` | Read dataset metadata and annotations | All GET endpoints |
| `labeler:write` | Create/update datasets and annotations | POST/PUT endpoints (e.g., split updates) |
| `labeler:delete` | Delete datasets | DELETE endpoints |
| `labeler:admin` | Administrative operations | Reserved for future use |

**Important**: Platform currently only uses `labeler:read` and `labeler:write`. Labeler can enforce stricter permissions per endpoint.

## Verification Implementation

### Step 1: Install PyJWT

```bash
pip install pyjwt
```

### Step 2: Get SERVICE_JWT_SECRET

**Development**: Use the same secret as Platform:
```python
# In Labeler's .env or config
SERVICE_JWT_SECRET = "8f7e6d5c4b3a29180716253e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a"
```

**Production**: Generate separate secret and share securely:
```bash
openssl rand -hex 32
```

### Step 3: Verify JWT in Labeler Backend

```python
import jwt
from datetime import datetime
from fastapi import HTTPException, Header
from typing import Optional, List, Dict, Any

# Configuration
SERVICE_JWT_SECRET = "8f7e6d5c4b3a29180716253e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a"
JWT_ALGORITHM = "HS256"


def verify_service_jwt(
    authorization: str = Header(...),
    required_scopes: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Verify service JWT from Platform.

    Args:
        authorization: Authorization header (Bearer {token})
        required_scopes: Optional list of required scopes

    Returns:
        JWT payload with user_id, service, scopes

    Raises:
        HTTPException(401): Invalid or expired token
        HTTPException(403): Insufficient scopes
    """
    # Extract token from "Bearer {token}"
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format"
        )

    token = authorization.replace("Bearer ", "")

    try:
        # Decode and verify JWT
        payload = jwt.decode(
            token,
            SERVICE_JWT_SECRET,
            algorithms=[JWT_ALGORITHM]
        )

        # Verify token type
        token_type = payload.get("type")
        if token_type not in ["service", "background"]:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token type: {token_type}"
            )

        # Verify scopes if required
        if required_scopes:
            token_scopes = set(payload.get("scopes", []))
            required_set = set(required_scopes)

            if not required_set.issubset(token_scopes):
                missing = required_set - token_scopes
                raise HTTPException(
                    status_code=403,
                    detail=f"Insufficient scope. Required: {list(missing)}"
                )

        # Return payload for further processing
        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Service token expired"
        )

    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid service token: {str(e)}"
        )


def get_user_id_from_payload(payload: Dict[str, Any]) -> Optional[int]:
    """
    Extract user ID from verified JWT payload.

    Args:
        payload: Verified JWT payload

    Returns:
        User ID as integer, or None for background jobs
    """
    sub = payload.get("sub")
    if sub is None:
        return None  # Background job

    try:
        return int(sub)
    except (ValueError, TypeError):
        return None
```

### Step 4: Use in FastAPI Endpoints

```python
from fastapi import APIRouter, Depends

router = APIRouter()


@router.get("/api/v1/datasets/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    auth_payload: dict = Depends(verify_service_jwt)
):
    """
    Get dataset metadata.

    Labeler should:
    1. Extract user_id from auth_payload
    2. Check if user has permission to access dataset
    3. Return dataset if authorized, 403 if not
    """
    user_id = get_user_id_from_payload(auth_payload)

    # Check permissions (your existing logic)
    if not has_dataset_access(dataset_id, user_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Return dataset
    dataset = get_dataset_from_db(dataset_id)
    return dataset


@router.get("/api/v1/datasets")
async def list_datasets(
    auth_payload: dict = Depends(verify_service_jwt)
):
    """
    List datasets.

    Labeler should:
    1. Extract user_id from auth_payload
    2. Return only datasets user has access to
    """
    user_id = get_user_id_from_payload(auth_payload)

    # Filter by user permissions
    datasets = get_accessible_datasets(user_id)
    return {"datasets": datasets, "total": len(datasets)}


@router.post("/api/v1/datasets/{dataset_id}/split")
async def update_dataset_split(
    dataset_id: str,
    split_request: dict,
    auth_payload: dict = Depends(
        lambda auth=Header(...): verify_service_jwt(
            auth, required_scopes=["labeler:write"]
        )
    )
):
    """
    Update dataset split configuration.

    Requires labeler:write scope.
    Only dataset owner can update split.
    """
    user_id = get_user_id_from_payload(auth_payload)

    # Check ownership
    dataset = get_dataset_from_db(dataset_id)
    if dataset.owner_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Only dataset owner can update split"
        )

    # Update split
    update_split_in_annotations(dataset_id, split_request)
    return {"status": "success"}
```

## Error Handling

### 401 Unauthorized

Return when token is invalid or expired:

```json
{
  "detail": "Service token expired"
}
```

```json
{
  "detail": "Invalid service token"
}
```

### 403 Forbidden

Return when scopes are insufficient or user lacks permission:

```json
{
  "detail": "Insufficient scope. Required: ['labeler:write']"
}
```

```json
{
  "detail": "Access denied"
}
```

## Health Check Endpoint

**Important**: The `/health` endpoint should NOT require authentication. Platform uses it to check if Labeler is reachable.

```python
@router.get("/health")
async def health_check():
    """Health check - no authentication required."""
    return {"status": "healthy"}
```

## Testing JWT Verification

### Test Valid Token

```python
import jwt
from datetime import datetime, timedelta

# Generate test token
payload = {
    "sub": "1",
    "service": "platform",
    "scopes": ["labeler:read"],
    "type": "service",
    "iat": datetime.utcnow(),
    "exp": datetime.utcnow() + timedelta(minutes=5),
    "nbf": datetime.utcnow(),
}

token = jwt.encode(payload, SERVICE_JWT_SECRET, algorithm="HS256")
print(f"Test Token: {token}")

# Verify token
decoded = jwt.decode(token, SERVICE_JWT_SECRET, algorithms=["HS256"])
print(f"Decoded: {decoded}")
```

### Test Expired Token

```python
# Generate expired token
payload = {
    "sub": "1",
    "service": "platform",
    "scopes": ["labeler:read"],
    "type": "service",
    "iat": datetime.utcnow() - timedelta(minutes=10),
    "exp": datetime.utcnow() - timedelta(minutes=5),  # Already expired
    "nbf": datetime.utcnow() - timedelta(minutes=10),
}

token = jwt.encode(payload, SERVICE_JWT_SECRET, algorithm="HS256")

# This should raise jwt.ExpiredSignatureError
try:
    decoded = jwt.decode(token, SERVICE_JWT_SECRET, algorithms=["HS256"])
except jwt.ExpiredSignatureError:
    print("Token expired (expected)")
```

## Migration Path

### Phase 1: Update Labeler Backend (1 day)

1. Install PyJWT: `pip install pyjwt`
2. Add `SERVICE_JWT_SECRET` to config/env
3. Create `verify_service_jwt()` function
4. Update all endpoints to use `Depends(verify_service_jwt)`
5. Keep `/health` endpoint public

### Phase 2: Test Integration (1 day)

1. Run Platform's integration tests: `python test_phase_11_5_integration.py`
2. Expected results:
   - [PASS] Labeler health check
   - [PASS] LabelerClient health check
   - [PASS] List datasets
   - [PASS] Get dataset metadata
   - [PASS] Check permissions
   - [PASS] Create snapshot

### Phase 3: Production Deployment

1. Generate new `SERVICE_JWT_SECRET` for production:
   ```bash
   openssl rand -hex 32
   ```
2. Share secret securely with Platform team (encrypted channel)
3. Update both services with new secret
4. Deploy Labeler first, then Platform

## Security Best Practices

1. **Never log the SERVICE_JWT_SECRET**
2. **Use different secrets for dev/staging/prod**
3. **Rotate secrets periodically** (every 90 days)
4. **Validate scopes strictly** - reject requests with insufficient permissions
5. **Fail closed** - deny access on any error (don't return data if JWT verification fails)
6. **Log authentication failures** for security monitoring

## Troubleshooting

### "Not enough segments" error

**Cause**: Token format is invalid (not a valid JWT)

**Solution**: Check that Platform is sending `Bearer {token}` format

### "Signature verification failed"

**Cause**: SERVICE_JWT_SECRET mismatch between Platform and Labeler

**Solution**: Verify both services use the same secret

### "Token expired"

**Cause**: Token is older than 5 minutes (user requests) or 1 hour (background jobs)

**Solution**: This is expected behavior - Platform generates new token per request

### User permission denied but token valid

**Cause**: JWT is valid but user doesn't have permission to access resource

**Solution**: Check Labeler's permission logic - ensure user_id from JWT is used correctly

## FAQ

**Q: Why not use simple API keys?**

A: Simple keys don't carry user context - we need to know which user is making the request for permission checks.

**Q: Why such short token expiry (5min)?**

A: Security best practice - if token is leaked, it expires quickly. Platform generates new token per request.

**Q: What if training job runs for 10 hours?**

A: Background jobs use longer-lived tokens (1 hour) and can be refreshed automatically by Platform.

**Q: Can we validate the service name?**

A: Yes! You can check `payload["service"] == "platform"` to ensure requests only come from Platform.

**Q: What about rate limiting?**

A: Consider implementing rate limiting per service (using `payload["service"]`) to prevent abuse.

## Reference

- **Full Analysis**: [MICROSERVICE_AUTHENTICATION_ANALYSIS.md](./MICROSERVICE_AUTHENTICATION_ANALYSIS.md)
- **Platform Implementation**: `platform/backend/app/core/service_jwt.py`
- **LabelerClient**: `platform/backend/app/clients/labeler_client.py`

## Contact

For questions or issues with authentication:
- Platform Team: (your contact info)
- Labeler Team: (labeler team contact)
- Shared secret management: (security team contact)
