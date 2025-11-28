# Temporal Worker와 Hybrid JWT 통합 가이드

**Phase 12.2: Temporal Workflow + Labeler Integration**
**작성일**: 2025-01-28
**대상**: Platform Backend 개발팀
**목적**: Temporal Worker에서 Labeler API를 호출하기 위한 Background Job JWT 생성 가이드

---

## 📋 요약

Temporal Worker는 **User JWT 없이** Labeler API를 호출해야 합니다.
기존 Hybrid JWT가 이미 **Background Job Token**을 지원하므로, 새로운 인증 방식을 추가할 필요가 없습니다.

**결론**: `sub: null` + `type: "background"` + `exp: 1h`로 JWT 생성하면 됩니다.

---

## 🔍 배경

### 문제 상황

```
[User Request: POST /api/v1/training/jobs]
    ↓
[Platform API: Create TrainingJob, Start Temporal Workflow]
    ↓
[Temporal Worker: 별도 프로세스, User JWT 없음] ❌
    ↓
[Activity: validate_dataset]
    ├─ labeler_client.get_dataset(dataset_id)
    └─ 401 Unauthorized - User JWT 없음 ❌
```

### 왜 User JWT가 없나?

- Temporal Worker는 user request와 무관하게 실행됨
- Long-running workflow (몇 시간~며칠 동안 실행 가능)
- User session timeout 문제 (User JWT는 5분 후 만료)
- Workflow 입력에는 `job_id`만 전달됨 (user context 없음)

---

## ✅ 해결 방안: Background Job JWT

**Hybrid JWT는 이미 Background Job Token을 지원합니다!**

[`LABELER_AUTHENTICATION_GUIDE.md`](./LABELER_AUTHENTICATION_GUIDE.md) Line 54-68 참조:

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

**Labeler Backend는 이미 이 형식을 지원합니다**:
- `verify_service_jwt()`: `type: "background"` 허용 (Line 154)
- `get_user_id_from_payload()`: `sub: null` 처리 (Line 188-206)

---

## 🛠️ Platform Backend 구현

### 1. Background Job JWT 생성 함수 추가

**파일**: `platform/backend/app/core/service_jwt.py`

```python
import jwt
from datetime import datetime, timedelta
from typing import Optional, List

from app.core.config import settings


def generate_background_jwt(
    service_name: str = "platform-training",
    scopes: Optional[List[str]] = None,
    job_id: Optional[int] = None,
    expiry_hours: int = 1
) -> str:
    """
    Generate JWT for background jobs (Temporal Worker).

    Args:
        service_name: Service identity (default: "platform-training")
        scopes: List of scopes (default: ["labeler:read"])
        job_id: Optional job ID for audit logging
        expiry_hours: Token expiry in hours (default: 1)

    Returns:
        JWT token string

    Example:
        >>> token = generate_background_jwt(job_id=123)
        >>> # Use in LabelerClient: labeler_client.set_background_token(token)
    """
    if scopes is None:
        scopes = ["labeler:read"]

    now = datetime.utcnow()

    payload = {
        "sub": None,  # No user context for background jobs
        "service": service_name,
        "scopes": scopes,
        "type": "background",  # Background job marker
        "iat": now,
        "exp": now + timedelta(hours=expiry_hours),
        "nbf": now,
    }

    # Add job_id for audit logging (optional)
    if job_id is not None:
        payload["job_id"] = job_id

    # Sign JWT with same secret as user JWT
    token = jwt.encode(
        payload,
        settings.SERVICE_JWT_SECRET,
        algorithm=settings.SERVICE_JWT_ALGORITHM
    )

    return token
```

### 2. LabelerClient에 Background Token 지원 추가

**파일**: `platform/backend/app/clients/labeler_client.py`

```python
import httpx
from typing import Optional

from app.core.config import settings
from app.core.service_jwt import generate_service_jwt, generate_background_jwt


class LabelerClient:
    def __init__(self):
        self.base_url = settings.LABELER_SERVICE_URL
        self._background_token: Optional[str] = None

    def set_background_token(self, token: str):
        """
        Set background job token for subsequent requests.

        Used by Temporal Worker activities to authenticate without user context.

        Args:
            token: Background job JWT token
        """
        self._background_token = token

    def _get_headers(self, user_id: Optional[int] = None) -> dict:
        """
        Get request headers with appropriate JWT.

        Args:
            user_id: User ID (for user requests) or None (for background jobs)

        Returns:
            Headers dictionary with Authorization bearer token
        """
        # Use background token if set (Temporal Worker context)
        if self._background_token:
            return {"Authorization": f"Bearer {self._background_token}"}

        # Otherwise generate user JWT (normal request context)
        if user_id is None:
            raise ValueError("user_id required for non-background requests")

        user_token = generate_service_jwt(
            user_id=user_id,
            scopes=["labeler:read"]
        )
        return {"Authorization": f"Bearer {user_token}"}

    async def get_dataset(
        self,
        dataset_id: str,
        user_id: Optional[int] = None
    ) -> dict:
        """
        Get dataset information from Labeler.

        Args:
            dataset_id: Dataset ID
            user_id: User ID (required for user requests, None for background jobs)

        Returns:
            Dataset information dictionary

        Raises:
            HTTPStatusError: If request fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/v1/datasets/{dataset_id}",
                headers=self._get_headers(user_id),
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()


# Singleton instance
labeler_client = LabelerClient()
```

### 3. Temporal Activity에서 사용

**파일**: `platform/backend/app/workflows/training_workflow.py`

```python
@activity.defn(name="validate_dataset")
async def validate_dataset(job_id: int) -> Dict[str, Any]:
    """
    Validate dataset existence and format via Labeler API.

    Phase 12.2: Uses Background Job JWT (no user context required).

    Args:
        job_id: TrainingJob ID

    Returns:
        Dict containing validation results and dataset metadata

    Raises:
        ValueError: If dataset is invalid or not found
    """
    logger.info(f"[Activity] validate_dataset - job_id={job_id}")

    from app.db.database import SessionLocal
    from app.db import models
    from app.clients.labeler_client import labeler_client
    from app.core.service_jwt import generate_background_jwt

    db = SessionLocal()
    try:
        # 1. Load TrainingJob from database
        job = db.query(models.TrainingJob).filter(
            models.TrainingJob.id == job_id
        ).first()

        if not job:
            raise ValueError(f"TrainingJob {job_id} not found")

        # 2. Generate background job JWT (valid for 1 hour)
        background_token = generate_background_jwt(
            job_id=job_id,
            scopes=["labeler:read"]
        )

        # 3. Set background token in LabelerClient
        labeler_client.set_background_token(background_token)

        # 4. Query dataset from Labeler (no user_id required)
        if job.dataset_id:
            try:
                dataset = await labeler_client.get_dataset(
                    dataset_id=job.dataset_id
                    # user_id=None ← Background job, no user context
                )
                dataset_path = dataset['storage_path']
                logger.info(
                    f"[validate_dataset] Using Dataset ID: {job.dataset_id}, "
                    f"storage: {dataset_path}"
                )
            except Exception as e:
                raise ValueError(f"Dataset {job.dataset_id} not found in Labeler: {e}")
        else:
            raise ValueError(f"Job {job_id} has no dataset_id")

        # 5. Return metadata
        dataset_format = job.dataset_format or "imagefolder"
        return {
            "valid": True,
            "dataset_path": str(dataset_path),
            "dataset_format": dataset_format,
            "job_id": job_id,
        }

    finally:
        # Clear background token after use
        labeler_client.set_background_token(None)
        db.close()
```

---

## 🔐 보안 고려사항

### 1. Token Expiry

**User JWT**: 5분 (짧은 요청용)
**Background JWT**: 1시간 (Long-running workflow용)

```python
# User request
generate_service_jwt(user_id=123, expiry_minutes=5)

# Background job
generate_background_jwt(job_id=123, expiry_hours=1)
```

### 2. Scope 제한

Background job은 **read-only** 권장:

```python
# Training workflow: Read dataset only
generate_background_jwt(scopes=["labeler:read"])

# Data processing workflow: Write split updates
generate_background_jwt(scopes=["labeler:read", "labeler:write"])
```

### 3. 권한 체크 로직 (Labeler Backend)

Labeler Backend는 `sub: null`일 때 user permission check를 **skip**해야 합니다:

```python
# Labeler: platform_datasets.py
async def get_dataset_for_platform(
    dataset_id: str,
    jwt_payload: Dict[str, Any] = Depends(get_service_jwt_payload),
    db: Session = Depends(get_labeler_db),
):
    # Extract user_id (can be None for background jobs)
    user_id = get_user_id_from_payload(jwt_payload)

    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(404, f"Dataset {dataset_id} not found")

    # Permission check: Skip if background job (user_id is None)
    if user_id is not None:
        # User request: Check user permissions
        if not has_dataset_access(dataset, user_id):
            raise HTTPException(403, "Access denied")
    else:
        # Background job: Skip permission check (Platform is trusted)
        logger.info(f"Background job accessing dataset {dataset_id}")

    return _dataset_to_response(dataset)
```

---

## 🧪 테스트

### 1. Background JWT 생성 테스트

```python
from app.core.service_jwt import generate_background_jwt
import jwt

# Generate background token
token = generate_background_jwt(job_id=123)
print(f"Background Token: {token}")

# Decode and verify
from app.core.config import settings
payload = jwt.decode(token, settings.SERVICE_JWT_SECRET, algorithms=["HS256"])
print(f"Payload: {payload}")

# Expected:
# {
#   "sub": None,
#   "service": "platform-training",
#   "scopes": ["labeler:read"],
#   "type": "background",
#   "job_id": 123,
#   "iat": ...,
#   "exp": ...,  # 1 hour from now
#   "nbf": ...
# }
```

### 2. Labeler API 호출 테스트

```python
import asyncio
from app.clients.labeler_client import labeler_client
from app.core.service_jwt import generate_background_jwt

async def test_background_request():
    # Generate background token
    token = generate_background_jwt(job_id=123)
    labeler_client.set_background_token(token)

    # Call Labeler API (no user_id required)
    dataset = await labeler_client.get_dataset("ds_564a6a351e7f4668")
    print(f"Dataset: {dataset}")

# Run test
asyncio.run(test_background_request())
```

### 3. Temporal Workflow E2E 테스트

```bash
cd platform/backend

# 1. Start Temporal Worker
venv/Scripts/python.exe -m app.workflows.worker

# 2. Run E2E test (creates training job → triggers workflow)
venv/Scripts/python.exe test_e2e.py

# Expected:
# [PASS] Job created
# [PASS] Workflow started
# [PASS] validate_dataset activity succeeded (background JWT)
# [PASS] Training started
```

---

## 📊 아키텍처 비교

### ❌ 잘못된 방향: Service Token 추가

```
인증 시스템:
├─ User JWT          → 일반 사용자 API
├─ Hybrid JWT        → Platform user requests
└─ Service Token     → Platform background jobs ❌ 불필요!

문제점:
- 3개 인증 시스템 관리
- 단순 문자열 비교 (보안 약화)
- 만료 시간 없음
- 기존 설계와 모순
```

### ✅ 올바른 방향: Hybrid JWT 활용

```
인증 시스템:
├─ User JWT          → 일반 사용자 API
└─ Hybrid JWT        → Platform requests (user + background 모두)
    ├─ type: "service"     (sub: user_id, exp: 5min)
    └─ type: "background"  (sub: null, exp: 1h)

장점:
- 2개 인증 시스템으로 단순화
- JWT 서명 검증 (보안 유지)
- 자동 만료 관리
- 기존 설계 일관성
```

---

## ✅ 체크리스트

Platform 팀 구현 완료 시 체크:

- [ ] `app/core/service_jwt.py`에 `generate_background_jwt()` 추가
- [ ] `app/clients/labeler_client.py`에 `set_background_token()` 추가
- [ ] `app/workflows/training_workflow.py`에서 background JWT 사용
- [ ] Background JWT 생성 테스트 (unit test)
- [ ] Labeler API 호출 테스트 (integration test)
- [ ] Temporal Workflow E2E 테스트
- [ ] Labeler 팀에 `sub: null` 처리 확인 요청

Labeler 팀 확인 사항:

- [ ] `verify_service_jwt()`가 `type: "background"` 허용하는지 확인
- [ ] `get_user_id_from_payload()`가 `sub: null` 반환하는지 확인
- [ ] Permission check에서 `user_id is None`일 때 skip하는지 확인
- [ ] Background job 로그 추가 (audit trail)

---

## 🔗 관련 문서

- [Labeler Authentication Guide](./LABELER_AUTHENTICATION_GUIDE.md) - Hybrid JWT 전체 명세
- [Microservice Authentication Analysis](./MICROSERVICE_AUTHENTICATION_ANALYSIS.md) - 인증 설계 분석
- [Phase 12.2 Metadata-Only Snapshot](../architecture/SNAPSHOT_DESIGN.md) - Snapshot 대안 설계

---

## 📞 문의

- **구현 질문**: Platform Backend 팀
- **인증 설계**: 아키텍처 팀
- **Labeler 연동**: Labeler Backend 팀

---

## 📝 변경 이력

- **2025-01-28**: 초기 작성 (Service Token 방식 폐기, Hybrid JWT 확장 채택)
