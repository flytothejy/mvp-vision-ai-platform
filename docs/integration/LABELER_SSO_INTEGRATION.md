# Labeler SSO Integration Guide

Platform → Labeler 간 SSO(Single Sign-On) 통합 구현 가이드

**작성일**: 2025-12-10
**Phase**: 11.5.6 - Hybrid JWT for Microservice SSO
**목적**: Platform 사용자가 Labeler로 자동 로그인되어 데이터셋 관리 작업을 원활하게 수행

---

## 📋 목차

1. [개요](#개요)
2. [아키텍처](#아키텍처)
3. [구현 사항](#구현-사항)
4. [환경 변수 설정](#환경-변수-설정)
5. [보안 고려사항](#보안-고려사항)
6. [테스트 방법](#테스트-방법)
7. [트러블슈팅](#트러블슈팅)

---

## 개요

Platform에서 "데이터셋" 버튼을 클릭하면 Labeler로 자동 리다이렉트되며, 별도의 로그인 없이 사용자 세션이 생성됩니다.

### 주요 특징

- **Service JWT 기반**: Platform이 발급한 단기 토큰 (5분)
- **별도 Secret**: `SERVICE_JWT_SECRET` 사용 (user JWT와 분리)
- **자동 로그인**: 사용자 정보 자동 매핑 및 세션 생성
- **원클릭 전환**: Platform ↔ Labeler 간 끊김 없는 UX

---

## 아키텍처

### SSO Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                Platform Frontend (port 3000)                     │
│                                                                   │
│  1. User clicks "데이터셋"                                       │
│  2. POST /api/v1/auth/labeler-token (with Bearer token)         │
│  3. Receive service_token (expires in 5min)                      │
│  4. window.location.href = "http://localhost:8011/api/v1/auth/sso?token=xxx"│
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    Service JWT (5min)
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                Labeler Backend (port 8011)                       │
│                                                                   │
│  5. GET /api/v1/auth/sso?token=xxx                                           │
│  6. Decode & validate service JWT (SERVICE_JWT_SECRET)           │
│  7. Extract user info (user_id, email, full_name, role, etc)    │
│  8. Find or create user in Shared User DB                       │
│  9. Create user session (HTTP-only cookie)                      │
│ 10. RedirectResponse("http://localhost:3010/datasets")          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                Labeler Frontend (port 3010)                      │
│                                                                   │
│ 11. /datasets page (auto-authenticated via cookie)              │
└─────────────────────────────────────────────────────────────────┘
```

### Service JWT Payload

```json
{
  "user_id": "123",
  "email": "user@example.com",
  "full_name": "홍길동",
  "system_role": "user",
  "badge_color": "blue",
  "exp": 1733900000,
  "type": "service",
  "iss": "platform",
  "aud": "labeler"
}
```

---

## 구현 사항

### 1. 환경 변수 추가

**파일**: `labeler/.env` 또는 환경 변수

```bash
# Service-to-Service JWT Secret (Platform과 동일해야 함)
SERVICE_JWT_SECRET=service-jwt-secret-change-in-production-use-openssl-rand-hex-32

# Shared User Database (Platform과 동일)
# Tier 1 (Local): SQLite
USER_DATABASE_URL=sqlite:///C:/temp/shared_users.db  # Windows
# USER_DATABASE_URL=sqlite:////tmp/shared_users.db   # Linux/Mac

# Tier 2+ (K8s, Production): PostgreSQL
# USER_DATABASE_URL=postgresql://admin:password@postgres-service:5432/users
```

**⚠️ CRITICAL**: `SERVICE_JWT_SECRET`은 Platform과 **완전히 동일**해야 합니다.

### 2. Service JWT 검증 함수 구현

**파일**: `labeler/app/core/security.py` 또는 유사 위치

```python
from datetime import datetime
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from app.core.config import settings

ALGORITHM = "HS256"


def decode_service_token(token: str) -> Dict[str, Any]:
    """
    Decode and verify service JWT token from Platform.

    Args:
        token: Service JWT token from Platform

    Returns:
        Decoded payload with user information

    Raises:
        JWTError: If token is invalid, expired, or not a service token
    """
    try:
        # Decode with SERVICE_JWT_SECRET
        payload = jwt.decode(
            token,
            settings.SERVICE_JWT_SECRET,
            algorithms=[ALGORITHM],
            options={"verify_aud": False}  # Optional audience verification
        )

        # Verify token type
        if payload.get("type") != "service":
            raise JWTError("Not a service token")

        # Verify issuer (optional but recommended)
        if payload.get("iss") != "platform":
            raise JWTError("Invalid issuer")

        # Verify audience (optional)
        if payload.get("aud") != "labeler":
            raise JWTError("Invalid audience")

        return payload

    except JWTError as e:
        raise JWTError(f"Invalid service token: {str(e)}")
```

### 3. SSO 엔드포인트 구현

**파일**: `labeler/app/api/auth.py` 또는 유사 위치

```python
from fastapi import APIRouter, HTTPException, status, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.core.security import decode_service_token, create_access_token
from app.db.database import get_user_db
from app.db import models
from datetime import datetime

router = APIRouter()


@router.get("/sso")
async def sso_login(
    token: str,
    response: Response,
    db: Session = Depends(get_user_db)
):
    """
    SSO endpoint for Platform → Labeler integration.

    Validates service JWT from Platform and creates user session.

    Args:
        token: Service JWT token from Platform
        response: FastAPI response for setting cookies
        db: Shared User Database session

    Returns:
        Redirect to /datasets page

    Raises:
        HTTPException: If token is invalid or user creation fails
    """
    try:
        # 1. Decode and validate service token
        payload = decode_service_token(token)

        # 2. Extract user information
        user_id = int(payload.get("user_id"))
        email = payload.get("email")
        full_name = payload.get("full_name")
        system_role = payload.get("system_role", "user")
        badge_color = payload.get("badge_color", "blue")

        # 3. Find or create user in Shared User DB
        user = db.query(models.User).filter(models.User.id == user_id).first()

        if not user:
            # User doesn't exist - create new user
            user = models.User(
                id=user_id,
                email=email,
                full_name=full_name,
                system_role=system_role,
                badge_color=badge_color,
                is_active=True,
                hashed_password="",  # No password for SSO users
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            # User exists - update info if changed
            user.full_name = full_name
            user.system_role = system_role
            user.badge_color = badge_color
            user.updated_at = datetime.utcnow()
            db.commit()

        # 4. Create session (Option A: Set cookie)
        access_token = create_access_token({"sub": str(user.id)})

        # Set HTTP-only cookie for security
        response.set_cookie(
            key="access_token",
            value=f"Bearer {access_token}",
            httponly=True,
            max_age=3600,  # 1 hour
            samesite="lax"
        )

        # 5. Redirect to datasets page
        return RedirectResponse(
            url="/datasets",
            status_code=status.HTTP_303_SEE_OTHER
        )

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid service token: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SSO login failed: {str(e)}"
        )
```

### 4. User 모델 호환성 확인

**Shared User DB의 User 테이블 스키마**가 Platform과 동일해야 합니다.

**필수 컬럼**:
```python
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    full_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)  # SSO 사용자는 빈 문자열
    system_role = Column(String, default="user")  # 'admin', 'manager', 'user', 'guest'
    badge_color = Column(String, default="blue")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**⚠️ 중요**: Platform의 User 모델과 **완전히 동일**해야 합니다.

### 5. CORS 설정 (필요 시)

Platform에서 Labeler API를 호출하는 경우 CORS 설정이 필요할 수 있습니다.

```python
# labeler/app/main.py

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Platform Frontend
        "http://localhost:8001",  # Platform Backend
        # Production URLs...
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 환경 변수 설정

### Tier 0/1: Local Development (SQLite)

```bash
# .env
SERVICE_JWT_SECRET=service-jwt-secret-change-in-production-use-openssl-rand-hex-32

# Windows
USER_DATABASE_URL=sqlite:///C:/temp/shared_users.db

# Linux/Mac
USER_DATABASE_URL=sqlite:////tmp/shared_users.db
```

### Tier 2: Kind (Kubernetes Local)

```yaml
# labeler-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: labeler-config
data:
  USER_DATABASE_URL: "postgresql://admin:devpass@postgres-service:5432/users"
```

```yaml
# labeler-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: labeler-secrets
type: Opaque
stringData:
  SERVICE_JWT_SECRET: "service-jwt-secret-change-in-production-use-openssl-rand-hex-32"
```

### Tier 3: Production (Railway, AWS, GCP)

**Railway**:
```bash
# Environment Variables in Railway Dashboard
SERVICE_JWT_SECRET=<generate-with-openssl-rand-hex-32>
USER_DATABASE_URL=${{Postgres.DATABASE_URL}}/users
```

**AWS/GCP**:
- AWS Secrets Manager 또는 GCP Secret Manager 사용 권장
- Kubernetes Secrets로 주입

---

## 보안 고려사항

### ✅ DO

1. **SERVICE_JWT_SECRET 보호**
   - 환경 변수 또는 Secret Manager 사용
   - 절대 코드에 하드코딩 금지
   - Platform과 정확히 동일한 값 사용

2. **Token 검증 엄격히**
   - 만료 시간 검증 (`exp` claim)
   - Token 타입 검증 (`type: "service"`)
   - Issuer/Audience 검증 (optional but recommended)

3. **HTTPS 사용** (Production)
   - Service token이 URL에 노출되므로 HTTPS 필수
   - HTTP는 개발 환경에서만 사용

4. **Session 관리**
   - HTTP-only cookie 사용 권장
   - CSRF token 적용 고려

### ❌ DON'T

1. **Service token을 로그에 출력하지 마세요**
   ```python
   # BAD
   print(f"Received token: {token}")

   # GOOD
   print("SSO login attempt received")
   ```

2. **Service token을 재사용하지 마세요**
   - 1회성 사용 후 폐기
   - 세션 생성 후 token 정보 저장 불필요

3. **긴 만료 시간을 설정하지 마세요**
   - Platform이 5분으로 설정한 이유가 있음
   - 보안과 UX의 균형점

---

## 테스트 방법

### 1. Manual Test (브라우저)

```bash
# 1. Platform에 로그인
# Frontend: http://localhost:3000

# 2. 개발자 도구 열기 (F12)
# Console에서 토큰 확인:
localStorage.getItem('access_token')

# 3. "데이터셋" 버튼 클릭
# → Labeler로 자동 리다이렉트 확인
# → 로그인 없이 데이터셋 페이지 표시 확인
```

### 2. API Test (curl)

```bash
# 1. Platform 로그인하여 access_token 획득
curl -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user@example.com&password=password123"

# Response: {"access_token": "eyJ...", ...}

# 2. Service token 발급
curl -X POST http://localhost:8001/api/v1/auth/labeler-token \
  -H "Authorization: Bearer eyJ..."

# Response: {"service_token": "eyJ...", "expires_in": 300}

# 3. Labeler SSO 엔드포인트 테스트
curl -i -X GET "http://localhost:8011/api/v1/auth/sso?token=eyJ..."

# Expected: HTTP 303 Redirect to /datasets
```

### 3. Integration Test (Python)

```python
import requests

# 1. Platform 로그인
login_resp = requests.post(
    "http://localhost:8001/api/v1/auth/login",
    data={"username": "user@example.com", "password": "password123"}
)
access_token = login_resp.json()["access_token"]

# 2. Service token 발급
token_resp = requests.post(
    "http://localhost:8001/api/v1/auth/labeler-token",
    headers={"Authorization": f"Bearer {access_token}"}
)
service_token = token_resp.json()["service_token"]

# 3. Labeler SSO
sso_resp = requests.get(
    f"http://localhost:8011/api/v1/auth/sso?token={service_token}",
    allow_redirects=False
)

assert sso_resp.status_code == 303
assert sso_resp.headers["location"] == "/datasets"
print("✅ SSO integration test passed!")
```

---

## 트러블슈팅

### 문제 1: "Invalid service token" 에러

**원인**: SERVICE_JWT_SECRET이 Platform과 다름

**해결**:
```bash
# Platform의 SERVICE_JWT_SECRET 확인
cd platform/backend
grep SERVICE_JWT_SECRET .env

# Labeler의 SERVICE_JWT_SECRET과 비교
cd labeler
grep SERVICE_JWT_SECRET .env

# 두 값이 완전히 동일해야 함
```

### 문제 2: User 생성 실패

**원인**: Shared User DB 연결 실패 또는 스키마 불일치

**해결**:
```bash
# 1. DB 연결 확인
psql $USER_DATABASE_URL  # PostgreSQL
sqlite3 /tmp/shared_users.db  # SQLite

# 2. User 테이블 스키마 확인
\d users  # PostgreSQL
.schema users  # SQLite

# 3. Platform의 User 모델과 비교
```

### 문제 3: CORS 에러

**원인**: Platform Frontend에서 Labeler API 호출 시 CORS 차단

**해결**:
```python
# labeler/app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Platform Frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 문제 4: Token 만료 에러

**원인**: Service token이 5분 후 만료됨

**해결**:
- 정상 동작 (보안을 위해 의도된 설계)
- 사용자에게 다시 Platform에서 "데이터셋" 버튼 클릭 요청
- 만료 시간 연장 필요 시 Platform의 `SERVICE_TOKEN_EXPIRE_MINUTES` 조정 (권장하지 않음)

### 문제 5: 리다이렉트 루프

**원인**: /api/v1/auth/sso 엔드포인트가 다시 /api/v1/auth/sso로 리다이렉트

**해결**:
```python
# BAD
return RedirectResponse(url="/api/v1/auth/sso?token=xxx")  # 무한 루프!

# GOOD
return RedirectResponse(url="/datasets")
```

---

## 참고 문서

- [Phase 11.5.6: Microservice Separation](../planning/PHASE_11_MICROSERVICE_SEPARATION.md)
- [Platform Backend README](../platform/backend/README.md)
- [Security Design](../platform/docs/architecture/SECURITY.md)

---

## 체크리스트

SSO 통합 구현 완료 전 확인:

- [ ] `SERVICE_JWT_SECRET` 환경 변수 설정 (Platform과 동일)
- [ ] `USER_DATABASE_URL` 환경 변수 설정 (Shared DB)
- [ ] `decode_service_token()` 함수 구현
- [ ] `GET /api/v1/auth/sso?token=xxx` 엔드포인트 구현
- [ ] User 생성/업데이트 로직 구현
- [ ] Session 생성 (cookie 또는 JWT)
- [ ] `/datasets` 페이지로 리다이렉트
- [ ] Manual test 완료 (브라우저)
- [ ] API test 완료 (curl 또는 Postman)
- [ ] Integration test 완료 (Python script)
- [ ] Production 환경 변수 설정 (Secrets Manager)

---

**마지막 업데이트**: 2025-12-10
**담당자**: Platform Team
**문의**: platform-team@example.com
