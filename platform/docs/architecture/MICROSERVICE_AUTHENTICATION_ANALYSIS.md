# Microservice Authentication Strategy Analysis

**Date**: 2025-11-28
**Context**: Phase 11.5 - Platform ↔ Labeler 통합
**Scope**: 현재 및 향후 모든 마이크로서비스 간 인증 결정

## Current Situation

### Architecture
```
Frontend (Next.js)
    ↓ User JWT
Platform Backend (FastAPI)
    ↓ ??? (What authentication?)
Labeler Backend (FastAPI)
Training Services (FastAPI)
Other Future Services...
```

### Problem
Platform Backend에서 Labeler Backend로 API 요청 시 인증 방법 결정 필요:
- 현재: Bearer token with `LABELER_SERVICE_KEY` → 401 Unauthorized
- 원인: Labeler가 유효한 JWT 형식 요구

### Decision Impact
이 결정은 향후 모든 서비스 간 통신에 영향:
- Labeler ↔ Platform
- Platform ↔ Training Services
- Training Services ↔ Model Registry
- Platform ↔ Analytics Service
- etc.

---

## Option 1: User JWT Token Propagation (Pass-Through)

### Description
프론트엔드에서 받은 사용자 JWT를 그대로 downstream 서비스에 전달.

```
Frontend → Platform (User JWT)
              ↓ (Forward same JWT)
           Labeler (Validate JWT, check user_id)
```

### Implementation
```python
# Platform Backend
@router.get("/datasets/available")
async def list_datasets(
    current_user: User = Depends(get_current_user),  # Extract from JWT
    request: Request
):
    # Extract original JWT from request
    auth_header = request.headers.get("Authorization")

    # Forward to Labeler
    headers = {"Authorization": auth_header}
    response = await httpx.get(
        f"{LABELER_URL}/api/v1/datasets",
        headers=headers
    )
```

### Pros
✅ **단순함**: 추가 토큰 생성 불필요
✅ **User Context 보존**: 모든 서비스가 실제 사용자 식별 가능
✅ **Audit Trail**: 모든 서비스에서 사용자 행동 추적 가능
✅ **Security**: 사용자별 권한 체크 가능
✅ **Zero Trust 원칙**: 각 서비스가 독립적으로 JWT 검증

### Cons
❌ **Token Expiration 문제**: Long-running job 중 토큰 만료 가능
❌ **서비스 간 호출 복잡도**: 사용자 컨텍스트 없는 내부 작업 처리 어려움
❌ **JWT Validation 부하**: 모든 서비스가 JWT 검증 로직 필요
❌ **Secret Sharing**: 모든 서비스가 같은 JWT_SECRET 공유 필요

### Industry Examples
- **Netflix**: User token propagation with short-lived tokens
- **Uber**: Request-scoped token forwarding
- **Spotify**: User context propagation in headers

### Best For
- B2C 애플리케이션
- User-centric operations (대부분의 API가 사용자 요청 기반)
- Real-time request-response 패턴

---

## Option 2: Service-to-Service Authentication (Service Token)

### Description
각 서비스가 고유한 service credential을 갖고, 서비스 간 통신 시 사용.

```
Frontend → Platform (User JWT)
              ↓ (Service Token + user_id in payload)
           Labeler (Validate service token, trust user_id)
```

### Implementation
```python
# .env
LABELER_SERVICE_KEY=service-platform-to-labeler-secret-key

# Platform Backend
class LabelerClient:
    def __init__(self):
        self.headers = {
            "X-Service-Key": settings.LABELER_SERVICE_KEY,
            "X-User-ID": str(user_id),  # Pass user context
            "Content-Type": "application/json"
        }

# Labeler Backend
async def verify_service_auth(
    x_service_key: str = Header(...),
    x_user_id: int = Header(...)
):
    if x_service_key != settings.PLATFORM_SERVICE_KEY:
        raise HTTPException(401, "Invalid service key")

    # Trust user_id from Platform (since service auth passed)
    return x_user_id
```

### Pros
✅ **Simplicity**: 간단한 구현 (단순 문자열 비교)
✅ **No Token Expiration**: 서비스 키는 만료되지 않음
✅ **Performance**: JWT 검증 오버헤드 없음
✅ **Service Independence**: 각 서비스가 독립적으로 운영 가능
✅ **Background Jobs**: 사용자 컨텍스트 없는 작업에 적합

### Cons
❌ **Trust Model**: Downstream 서비스가 user_id를 맹목적으로 신뢰
❌ **Security Risk**: Service key 유출 시 전체 시스템 위험
❌ **Key Management**: 여러 서비스 간 키 관리 복잡
❌ **Audit Trail 약화**: 실제 사용자 추적 어려움
❌ **No Fine-grained Permission**: 사용자별 권한 체크 어려움

### Industry Examples
- **AWS Internal Services**: Service credentials for inter-service communication
- **Google Cloud**: Service accounts
- **Azure**: Managed identities

### Best For
- Internal microservices (외부 노출 없음)
- Background processing systems
- High-trust environments

---

## Option 3: OAuth2 Client Credentials Flow

### Description
OAuth2 표준을 사용하여 서비스 간 인증. 각 서비스가 access token을 요청하여 사용.

```
Platform → Auth Server (client_credentials grant)
              ↓ (access_token)
           Platform → Labeler (Bearer access_token)
```

### Implementation
```python
# Platform Backend
class ServiceAuthClient:
    async def get_access_token(self) -> str:
        response = await httpx.post(
            f"{AUTH_SERVER_URL}/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "platform-service",
                "client_secret": settings.CLIENT_SECRET,
                "scope": "labeler:read labeler:write"
            }
        )
        return response.json()["access_token"]

# Labeler Backend
async def verify_service_token(token: str = Depends(oauth2_scheme)):
    # Validate token with Auth Server or JWT verification
    payload = jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])

    if "labeler:read" not in payload["scope"]:
        raise HTTPException(403, "Insufficient scope")

    return payload
```

### Pros
✅ **Industry Standard**: OAuth2는 업계 표준
✅ **Flexible Scoping**: 세분화된 권한 관리 (scopes)
✅ **Token Expiration**: 토큰 만료로 보안 강화
✅ **Centralized Auth**: 중앙 인증 서버로 관리 간소화
✅ **Revocation**: 토큰 즉시 무효화 가능

### Cons
❌ **Complexity**: 인증 서버 구축/운영 필요
❌ **Latency**: 토큰 발급/검증으로 요청 지연
❌ **Infrastructure**: 추가 인프라 (Auth Server) 필요
❌ **Learning Curve**: OAuth2 구현 복잡도 높음

### Industry Examples
- **Google Cloud**: OAuth2 for service-to-service auth
- **Microsoft Azure**: Azure AD OAuth2
- **Auth0**: Service-to-service authentication

### Best For
- Enterprise applications
- Multi-tenant SaaS
- External API 노출하는 서비스

---

## Option 4: Hybrid Approach (User JWT + Service Claims)

### Description
User JWT에 service claim을 추가하여 사용자 + 서비스 컨텍스트 모두 포함.

```
Frontend → Platform (User JWT)
              ↓ (Generate new JWT: user claims + service claims)
           Labeler (Validate JWT with both contexts)
```

### Implementation
```python
# Platform Backend
def create_service_jwt(user_id: int, original_jwt: str) -> str:
    """Generate service-scoped JWT with user context"""
    payload = {
        "user_id": user_id,
        "service": "platform",
        "scopes": ["labeler:read", "labeler:write"],
        "original_token": hash(original_jwt),  # Reference to original
        "exp": datetime.utcnow() + timedelta(minutes=5),  # Short-lived
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SERVICE_JWT_SECRET, algorithm="HS256")

# Labeler Backend
async def verify_service_jwt(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, settings.SERVICE_JWT_SECRET, algorithms=["HS256"])

        # Verify service claim
        if payload.get("service") != "platform":
            raise HTTPException(403, "Invalid service")

        # Verify scopes
        if "labeler:read" not in payload.get("scopes", []):
            raise HTTPException(403, "Insufficient scope")

        return payload  # Contains user_id for permission checks

    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
```

### Pros
✅ **Best of Both Worlds**: User context + service authentication
✅ **Fine-grained Control**: Scopes + user permissions
✅ **Short-lived Tokens**: 보안 강화 (5분 만료)
✅ **Audit Trail**: 사용자 + 서비스 추적 가능
✅ **No External Dependency**: Auth server 불필요

### Cons
❌ **JWT Generation Overhead**: 매 요청마다 새 JWT 생성
❌ **Secret Management**: JWT_SECRET 공유 필요
❌ **Implementation Complexity**: 두 가지 인증 로직 모두 구현

### Industry Examples
- **Airbnb**: Service mesh with user context propagation
- **Lyft**: Hybrid authentication in Envoy proxy
- **Twitter**: Internal service authentication with user context

### Best For
- Microservices with user-centric operations
- Need both service and user authorization
- Internal services with moderate security requirements

---

## Option 5: API Gateway Pattern with Token Exchange

### Description
API Gateway가 사용자 JWT를 받아 service token으로 교환한 뒤 downstream 서비스에 전달.

```
Frontend → API Gateway (User JWT)
              ↓ (Exchange for service token)
           Platform/Labeler/etc. (Service Token)
```

### Implementation
```python
# API Gateway (Kong, Envoy, etc.)
# Plugin: JWT to Service Token Exchange

# Platform/Labeler Backend
async def verify_gateway_token(
    x_gateway_token: str = Header(...),
    x_user_id: int = Header(...)
):
    # Verify token signed by gateway
    payload = jwt.decode(x_gateway_token, GATEWAY_PUBLIC_KEY, algorithms=["RS256"])

    if payload["iss"] != "api-gateway":
        raise HTTPException(401, "Invalid issuer")

    return x_user_id
```

### Pros
✅ **Centralized Authentication**: 게이트웨이가 모든 인증 처리
✅ **Service Simplification**: Backend 서비스는 간단한 검증만
✅ **Rate Limiting**: 게이트웨이에서 통합 관리
✅ **Monitoring**: 중앙 집중식 로깅/모니터링
✅ **Standard Pattern**: 마이크로서비스 아키텍처 표준

### Cons
❌ **Single Point of Failure**: 게이트웨이 장애 시 전체 시스템 영향
❌ **Infrastructure Overhead**: Kong, Envoy 등 추가 인프라
❌ **Latency**: 게이트웨이 홉 추가로 지연
❌ **Complexity**: 게이트웨이 설정/운영 복잡

### Industry Examples
- **Netflix Zuul**: API Gateway with authentication
- **Amazon API Gateway**: Token exchange and validation
- **Kong**: Enterprise API Gateway

### Best For
- Large-scale microservices (10+ services)
- Public API 노출
- Enterprise environments

---

## Recommendation Matrix

| Criterion | User JWT | Service Key | OAuth2 CC | Hybrid JWT | API Gateway |
|-----------|----------|-------------|-----------|------------|-------------|
| **Simplicity** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐ |
| **Security** | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **User Context** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Performance** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| **Scalability** | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Industry Standard** | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Audit Trail** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Ops Complexity** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐ |

---

## Project-Specific Analysis

### Current Architecture
- **Services**: Frontend, Platform, Labeler, 3+ Training Services, Future: Analytics, Model Registry
- **Deployment**: Tier 0 (Docker), Tier 1-2 (Kind), Tier 3-4 (Railway/K8s)
- **Scale**: Small-to-medium (5-10 services 예상)
- **Team Size**: Small (1-3 developers)
- **Security Requirements**: Medium (internal services, some user data)

### Requirements
1. ✅ **User Permission Enforcement**: 각 서비스가 사용자별 권한 체크
2. ✅ **Audit Trail**: 누가 어떤 데이터에 접근했는지 추적
3. ✅ **Background Jobs**: Training job은 사용자 세션과 독립적
4. ✅ **Simple Operations**: 작은 팀이 관리 가능
5. ✅ **Future-proof**: 서비스 추가 시 확장 가능

### Constraints
- ❌ No dedicated Auth Server (현재)
- ❌ No API Gateway infrastructure (현재)
- ✅ Shared PostgreSQL User DB (이미 구축)
- ✅ JWT already implemented in Frontend/Platform

---

## Final Recommendation: **Hybrid Approach (Option 4)**

### Why Hybrid JWT?

#### ✅ Matches Current Architecture
- 이미 User DB와 JWT 인증 구현됨
- 추가 인프라 불필요 (Auth Server, API Gateway 없어도 됨)
- 점진적 마이그레이션 가능

#### ✅ Meets All Requirements
1. **User Permissions**: JWT에 user_id 포함으로 각 서비스가 권한 체크
2. **Audit Trail**: 모든 요청에 사용자 정보 포함
3. **Background Jobs**: Service-only JWT 발급 가능 (user_id=null)
4. **Simple Ops**: 단순 JWT 검증만 필요
5. **Scalable**: 새 서비스 추가 시 JWT 검증 로직만 복사

#### ✅ Industry Best Practices
- **Google Internal**: Similar approach with service mesh
- **Airbnb**: User context propagation in microservices
- **Stripe**: Service-to-service auth with user context

#### ✅ Security Best Practices
- **Short-lived tokens** (5분 만료): 토큰 탈취 위험 최소화
- **Scopes**: 서비스별 권한 세분화
- **Service validation**: 호출 서비스 식별 가능
- **User validation**: 실제 사용자 권한 체크 가능

### Implementation Plan

#### Phase 1: Core JWT Infrastructure (1-2일)
```python
# app/core/service_jwt.py
from datetime import datetime, timedelta
import jwt
from typing import Optional, List

class ServiceJWT:
    """Generate and validate service-scoped JWTs with user context"""

    @staticmethod
    def create_service_token(
        user_id: int,
        service_name: str,
        scopes: List[str],
        expires_minutes: int = 5
    ) -> str:
        """Generate service JWT for inter-service communication"""
        payload = {
            "sub": str(user_id),
            "service": service_name,
            "scopes": scopes,
            "exp": datetime.utcnow() + timedelta(minutes=expires_minutes),
            "iat": datetime.utcnow(),
        }
        return jwt.encode(payload, settings.SERVICE_JWT_SECRET, algorithm="HS256")

    @staticmethod
    def create_background_token(
        service_name: str,
        scopes: List[str],
        expires_hours: int = 1
    ) -> str:
        """Generate service JWT for background jobs (no user context)"""
        payload = {
            "sub": None,  # No user
            "service": service_name,
            "scopes": scopes,
            "exp": datetime.utcnow() + timedelta(hours=expires_hours),
            "iat": datetime.utcnow(),
        }
        return jwt.encode(payload, settings.SERVICE_JWT_SECRET, algorithm="HS256")

    @staticmethod
    def verify_token(token: str, required_scopes: List[str] = None) -> dict:
        """Validate service JWT and check scopes"""
        try:
            payload = jwt.decode(
                token,
                settings.SERVICE_JWT_SECRET,
                algorithms=["HS256"]
            )

            # Check scopes if required
            if required_scopes:
                token_scopes = set(payload.get("scopes", []))
                if not set(required_scopes).issubset(token_scopes):
                    raise HTTPException(403, "Insufficient scope")

            return payload

        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(401, "Invalid token")
```

#### Phase 2: Update LabelerClient (1일)
```python
# app/clients/labeler_client.py
class LabelerClient:
    async def _get_service_token(self, user_id: int) -> str:
        """Generate service token for Labeler API"""
        from app.core.service_jwt import ServiceJWT

        return ServiceJWT.create_service_token(
            user_id=user_id,
            service_name="platform",
            scopes=["labeler:read", "labeler:write"],
            expires_minutes=5
        )

    async def get_dataset(self, dataset_id: str, user_id: int) -> dict:
        """Get dataset with service token"""
        token = await self._get_service_token(user_id)

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        response = await self.client.get(
            f"/api/v1/datasets/{dataset_id}",
            headers=headers
        )
        response.raise_for_status()
        return response.json()
```

#### Phase 3: Update Labeler Backend (1일)
```python
# labeler/app/core/auth.py
from app.core.service_jwt import ServiceJWT

async def verify_service_auth(
    token: str = Depends(oauth2_scheme)
) -> dict:
    """Verify service JWT from Platform"""
    payload = ServiceJWT.verify_token(
        token,
        required_scopes=["labeler:read"]  # or labeler:write
    )

    # Extract user_id for permission checks
    user_id = payload.get("sub")
    service = payload.get("service")

    logger.info(f"Service auth: {service} acting for user {user_id}")

    return {
        "user_id": int(user_id) if user_id else None,
        "service": service,
        "scopes": payload.get("scopes", [])
    }

# labeler/app/api/datasets.py
@router.get("/datasets/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    auth: dict = Depends(verify_service_auth),
    db: Session = Depends(get_db)
):
    """Get dataset - callable by Platform service"""
    user_id = auth["user_id"]

    # Check user permission
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(404, "Dataset not found")

    if dataset.visibility == "private":
        # Check if user has access
        permission = db.query(DatasetPermission).filter(
            DatasetPermission.dataset_id == dataset_id,
            DatasetPermission.user_id == user_id
        ).first()

        if not permission and dataset.owner_id != user_id:
            raise HTTPException(403, "Access denied")

    return dataset
```

#### Phase 4: Background Job Support (1일)
```python
# For training jobs that run independently of user session
async def start_training_job_background(job_id: int):
    """Start training job in background (no user context)"""
    from app.core.service_jwt import ServiceJWT

    # Generate background token (no user_id)
    token = ServiceJWT.create_background_token(
        service_name="platform-training",
        scopes=["labeler:read", "training:execute"],
        expires_hours=24  # Longer expiration for training jobs
    )

    # Use token to access Labeler (if needed)
    # For public datasets or system operations
```

### Migration Path

**Week 1**: Implement core infrastructure
1. Create `ServiceJWT` class
2. Add `SERVICE_JWT_SECRET` to all services
3. Update LabelerClient with token generation
4. Test Platform → Labeler communication

**Week 2**: Roll out to other services
1. Update Training Services authentication
2. Update future Analytics Service
3. Standardize authentication across all services

**Week 3**: Monitoring & Refinement
1. Add metrics for token generation/validation
2. Monitor token expiration issues
3. Tune expiration times based on usage patterns

### Environment Variables
```bash
# Shared across all services
SERVICE_JWT_SECRET=your-service-jwt-secret-change-in-production

# Each service has its own name
SERVICE_NAME=platform  # or labeler, training-ultralytics, etc.
```

---

## Alternative: Start Simple, Migrate Later

If you want to **ship faster** and **iterate**:

### Phase 1: Start with Service Key (Option 2)
```python
# Simple service key for initial launch
LABELER_SERVICE_KEY=simple-service-key
```
- ✅ Ship in 1 hour
- ✅ Test integration immediately
- ⚠️ Less secure, but acceptable for internal dev

### Phase 2: Migrate to Hybrid JWT (Option 4)
- After initial integration works
- When adding more services
- When security becomes critical

This follows **"Make it work, make it right, make it fast"** principle.

---

## Decision Checklist

### Choose **Hybrid JWT** if:
- ✅ Need user permission enforcement in each service
- ✅ Want complete audit trail
- ✅ Have 3+ microservices
- ✅ Plan to scale to 10+ services
- ✅ Security is important
- ✅ Can invest 3-5 days implementation

### Choose **Service Key** if:
- ✅ Need to ship TODAY
- ✅ All services are internal (no external API)
- ✅ High trust environment
- ✅ Small scale (2-3 services)
- ⚠️ Plan to migrate later

### Choose **OAuth2** if:
- ✅ Building enterprise SaaS
- ✅ Have dedicated auth team
- ✅ Need external API access
- ✅ Already using Auth0/Keycloak/etc.

### Choose **API Gateway** if:
- ✅ Have 10+ microservices
- ✅ Need centralized rate limiting
- ✅ Have ops team to manage infrastructure
- ✅ Already using Kong/Envoy

---

## Final Decision for This Project

**Recommendation**: **Hybrid JWT (Option 4)**

**Reasoning**:
1. ✅ Matches current architecture (JWT already implemented)
2. ✅ No additional infrastructure needed
3. ✅ Provides both security and user context
4. ✅ Industry best practice for microservices
5. ✅ Scales from 5 to 50 services
6. ✅ Team can implement in 3-5 days

**Quick Win Option**: Start with Service Key for initial integration test, then migrate to Hybrid JWT within a week.

**Next Steps**:
1. Implement `ServiceJWT` class (2 hours)
2. Update LabelerClient (1 hour)
3. Update Labeler Backend auth (2 hours)
4. Test integration (1 hour)
5. Document for other services (1 hour)

Total: **1 day** to full implementation.
