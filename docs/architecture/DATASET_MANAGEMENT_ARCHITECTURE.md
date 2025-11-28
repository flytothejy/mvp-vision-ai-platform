# Dataset Management Architecture

**Status**: Implementation Required
**Created**: 2025-11-27
**Owner**: Platform Team + Labeler Team
**Related**: Phase 11 (Microservice Separation), Phase 12.5 (E2E Testing)

---

## Executive Summary

Vision AI Training Platform의 dataset 관리 책임을 Platform Backend에서 Labeler Backend로 완전히 이전하여, **Single Source of Truth** 원칙을 구현합니다.

**Key Decision**: Labeler가 모든 dataset 메타데이터를 소유하고, Platform은 Labeler API를 통해 dataset 정보를 조회합니다.

**Reference Documents**:
- `docs/cowork/LABELER_DATASET_API_REQUIREMENTS.md` - Labeler API 명세 (레이블팀 전달용)
- `docs/planning/PHASE_11_RAILWAY_DEPLOYMENT_PLAN.md` - Stage 2.5 Dataset Service Integration

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Architecture Decision](#architecture-decision)
3. [System Architecture](#system-architecture)
4. [Data Flow](#data-flow)
5. [API Integration](#api-integration)
6. [Migration Strategy](#migration-strategy)
7. [Implementation Checklist](#implementation-checklist)

---

## Problem Statement

### Current Issues

**데이터 중복 문제:**
- Platform DB의 `datasets` 테이블에 메타데이터 저장
- Labeler가 별도로 annotation 정보 관리
- 동기화 문제 발생 (이미지 추가/삭제 시)

**책임 소재 불명확:**
- Dataset 소유권: Platform vs Labeler?
- Annotation 상태: 누가 관리?
- Storage 동기화: 누가 책임?

**실제 상황 (2025-11-27 분석 결과):**
```
Platform DB: 3 datasets (모두 MinIO, legacy)
  - sample-det-coco32
  - sample-det-coco128
  - det-mvtec-ad

R2 Bucket: 1 dataset (Labeler 관리)
  - ds_c75023ca76d7448b (mvtec-bottle-detection, 1000 images)
```

→ **데이터 불일치로 인해 E2E 테스트 실패**

### Analysis Results

**Platform DB Dataset 의존성 분석:**
```python
# Foreign Key Dependencies
1. TrainingJob.dataset_id → datasets.id
2. TrainingJob.dataset_snapshot_id → datasets.id
3. Invitation.dataset_id → datasets.id
4. DatasetPermission.dataset_id → datasets.id
5. User.owned_datasets → datasets (relationship)
```

**분석 스크립트:** `platform/backend/analyze_dataset_usage.py`

---

## Architecture Decision

### Single Source of Truth: Labeler

**Decision:**
- **Labeler Backend**: Dataset 메타데이터의 Single Source of Truth
- **Platform Backend**: Labeler API를 쿼리하여 dataset 정보 조회
- **Platform DB**: `dataset_id` (UUID)만 FK로 저장, 메타데이터는 저장하지 않음

### Design Principles

1. **Separation of Concerns**
   - Labeler: Dataset annotation, metadata 관리
   - Platform: Training orchestration, model management

2. **API Gateway Pattern**
   - Platform이 Labeler API를 프록시
   - Frontend는 Platform API만 호출 (Labeler 직접 호출 안 함)

3. **Service-to-Service Authentication**
   - Platform → Labeler: JWT Bearer token
   - User → Platform: JWT Bearer token (기존 유지)

4. **Data Consistency**
   - Dataset snapshot 생성으로 training job 재현성 보장
   - Immutable snapshot storage (R2)

---

## System Architecture

### High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      Frontend (Next.js)                       │
│                    http://localhost:3000                      │
└────────────────────────────┬─────────────────────────────────┘
                             │ HTTPS
                             ▼
┌──────────────────────────────────────────────────────────────┐
│                   Platform Backend (FastAPI)                  │
│                    http://localhost:8000                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Dataset API Endpoints (Proxy Pattern)               │   │
│  │  - GET /api/v1/datasets/available                    │   │
│  │  - GET /api/v1/datasets/{id}                         │   │
│  │  - POST /api/v1/training (dataset validation)        │   │
│  └────────────┬─────────────────────────────────────────┘   │
│               │                                              │
│               │ LabelerClient (httpx)                        │
│               │ Authorization: Bearer {SERVICE_KEY}          │
│               ▼                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            app/clients/labeler_client.py             │   │
│  │  - get_dataset(dataset_id)                           │   │
│  │  - list_datasets(filters)                            │   │
│  │  - create_snapshot(dataset_id, version_tag)          │   │
│  │  - get_download_url(dataset_id)                      │   │
│  │  - check_permission(dataset_id, user_id)             │   │
│  └────────────┬─────────────────────────────────────────┘   │
└────────────────┼─────────────────────────────────────────────┘
                 │ HTTP/JSON
                 ▼
┌──────────────────────────────────────────────────────────────┐
│                   Labeler Backend (FastAPI)                   │
│                    http://localhost:8020                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Dataset API Endpoints (Implementation)              │   │
│  │  - GET /api/v1/datasets/{id}                         │   │
│  │  - GET /api/v1/datasets (with filters)               │   │
│  │  - POST /api/v1/datasets/{id}/snapshots              │   │
│  │  - POST /api/v1/datasets/{id}/download-url           │   │
│  │  - GET /api/v1/datasets/{id}/permissions/{user_id}   │   │
│  │  - POST /api/v1/datasets/batch                       │   │
│  └────────────┬─────────────────────────────────────────┘   │
└────────────────┼─────────────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
        ▼                 ▼
┌─────────────┐   ┌──────────────────┐
│  Labeler DB │   │  Cloudflare R2   │
│ (PostgreSQL)│   │  (Object Storage)│
│             │   │                  │
│ - datasets  │   │ - datasets/      │
│ - snapshots │   │ - snapshots/     │
│ - annot...  │   │ - images/        │
└─────────────┘   └──────────────────┘
```

### Database Schema Changes

**Platform DB (PostgreSQL):**
```python
# TrainingJob 테이블 (변경 없음)
class TrainingJob(Base):
    id: int
    dataset_id: str  # FK to datasets.id (UUID only, no metadata)
    dataset_snapshot_id: str  # FK to datasets.id (snapshot UUID)
    # ... other fields
```

**Labeler DB (PostgreSQL):**
```python
# Dataset 테이블 (Labeler 소유)
class Dataset(Base):
    id: str  # UUID (e.g., "ds_c75023ca76d7448b")
    name: str
    description: str
    format: str  # coco, yolo, voc, etc.
    labeled: bool
    storage_type: str  # r2, s3, minio
    storage_path: str  # R2 path (e.g., "datasets/ds_xxx/")
    visibility: str  # public, private, organization
    owner_id: int
    num_classes: int
    num_images: int
    class_names: List[str]
    tags: List[str]
    created_at: datetime
    updated_at: datetime

# Snapshot 테이블 (새로 추가)
class DatasetSnapshot(Base):
    id: str  # UUID (e.g., "snap_abc123")
    dataset_id: str  # FK to datasets.id
    version_tag: str  # e.g., "v1.0-training-20251127"
    storage_path: str  # R2 path (e.g., "snapshots/snap_xxx/")
    created_by_user_id: int
    notes: str
    created_at: datetime
```

---

## Data Flow

### 1. Dataset 조회 흐름

```
User → Frontend → Platform API → Labeler API → Labeler DB + R2
                                                      ↓
User ← Frontend ← Platform API ← Labeler API ← [Dataset List]
```

**Sequence Diagram:**
```
┌─────────┐   ┌──────────┐   ┌──────────┐   ┌─────────┐
│ Frontend│   │ Platform │   │ Labeler  │   │   R2    │
└────┬────┘   └────┬─────┘   └────┬─────┘   └────┬────┘
     │             │              │              │
     │ GET /datasets/available    │              │
     │────────────>│              │              │
     │             │              │              │
     │             │ GET /api/v1/datasets        │
     │             │─────────────>│              │
     │             │              │              │
     │             │              │ List R2 datasets
     │             │              │─────────────>│
     │             │              │<─────────────│
     │             │              │              │
     │             │<─────────────│              │
     │             │ [dataset_list]              │
     │<────────────│              │              │
     │             │              │              │
```

### 2. Training Job 생성 흐름 (Snapshot 포함)

```
User → Frontend → Platform API
                      ↓
                  1. Labeler.get_dataset(id)
                  2. Labeler.check_permission(id, user_id)
                  3. Labeler.create_snapshot(id, version_tag)
                      ↓
                  Create TrainingJob (with snapshot_id)
                      ↓
                  Training downloads dataset from R2 (presigned URL)
```

**Sequence Diagram:**
```
┌─────────┐   ┌──────────┐   ┌─────────┐   ┌────────┐
│ Frontend│   │ Platform │   │ Labeler │   │   R2   │
└────┬────┘   └────┬─────┘   └────┬────┘   └────┬───┘
     │             │              │             │
     │ POST /training            │             │
     │────────────>│              │             │
     │             │              │             │
     │             │ 1. GET /datasets/{id}      │
     │             │─────────────>│             │
     │             │<─────────────│             │
     │             │              │             │
     │             │ 2. GET /permissions/{user_id}
     │             │─────────────>│             │
     │             │<─────────────│             │
     │             │              │             │
     │             │ 3. POST /snapshots         │
     │             │─────────────>│             │
     │             │              │ Copy to snapshots/
     │             │              │────────────>│
     │             │              │<────────────│
     │             │<─────────────│             │
     │             │ {snapshot_id}              │
     │             │              │             │
     │    Insert TrainingJob     │             │
     │    (dataset_id, snapshot_id)            │
     │<────────────│              │             │
     │             │              │             │
```

### 3. 권한 체크 흐름

```
User → Platform → Labeler.check_permission(dataset_id, user_id)
                      ↓
                  [403 if denied, 200 if allowed]
```

---

## API Integration

### Platform LabelerClient Implementation

**파일**: `platform/backend/app/clients/labeler_client.py`

```python
from typing import List, Optional
import httpx
from app.core.config import settings

class LabelerClient:
    """Client for Labeler Backend API"""

    def __init__(self):
        self.base_url = settings.LABELER_API_URL
        self.headers = {
            "Authorization": f"Bearer {settings.LABELER_SERVICE_KEY}",
        }
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=30.0
        )

    async def get_dataset(self, dataset_id: str) -> dict:
        """단일 dataset 조회"""
        response = await self.client.get(f"/api/v1/datasets/{dataset_id}")
        response.raise_for_status()
        return response.json()

    async def list_datasets(
        self,
        user_id: Optional[int] = None,
        visibility: Optional[str] = None,
        labeled: Optional[bool] = None,
        page: int = 1,
        limit: int = 20
    ) -> dict:
        """Dataset 목록 조회"""
        params = {"page": page, "limit": limit}
        if user_id:
            params["user_id"] = user_id
        if visibility:
            params["visibility"] = visibility
        if labeled is not None:
            params["labeled"] = labeled

        response = await self.client.get("/api/v1/datasets", params=params)
        response.raise_for_status()
        return response.json()

    async def create_snapshot(
        self,
        dataset_id: str,
        version_tag: str,
        user_id: int,
        notes: Optional[str] = None
    ) -> dict:
        """Dataset snapshot 생성"""
        payload = {
            "version_tag": version_tag,
            "created_by_user_id": user_id,
            "notes": notes
        }
        response = await self.client.post(
            f"/api/v1/datasets/{dataset_id}/snapshots",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def check_permission(self, dataset_id: str, user_id: int) -> bool:
        """사용자 접근 권한 확인"""
        try:
            response = await self.client.get(
                f"/api/v1/datasets/{dataset_id}/permissions/{user_id}"
            )
            if response.status_code == 404:
                return False
            response.raise_for_status()
            return response.json()["has_access"]
        except httpx.HTTPError:
            return False

# Singleton instance
labeler_client = LabelerClient()
```

**환경 변수:**
```bash
# .env
LABELER_API_URL=http://localhost:8020  # Development
# LABELER_API_URL=https://labeler.railway.app  # Production
LABELER_SERVICE_KEY=<strong-secret-key>
```

### Platform API Endpoints (Updated)

**1. GET /api/v1/datasets/available**
```python
@router.get("/available", response_model=List[DatasetInfo])
async def list_available_datasets(
    current_user: User = Depends(get_current_user),
    visibility: Optional[str] = None,
    labeled: Optional[bool] = None
):
    """List available datasets from Labeler service"""
    try:
        result = await labeler_client.list_datasets(
            user_id=current_user.id,
            visibility=visibility,
            labeled=labeled
        )
        return result["datasets"]
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch datasets from Labeler: {str(e)}"
        )
```

**2. POST /api/v1/training (with dataset validation)**
```python
@router.post("/training", response_model=TrainingJobResponse)
async def create_training_job(
    config: TrainingConfigCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validate dataset exists
    dataset = await labeler_client.get_dataset(config.dataset_id)

    # Check permission
    has_access = await labeler_client.check_permission(
        config.dataset_id,
        current_user.id
    )
    if not has_access:
        raise HTTPException(status_code=403, detail="No access to dataset")

    # Create snapshot for reproducibility
    snapshot = await labeler_client.create_snapshot(
        dataset_id=config.dataset_id,
        version_tag=f"training-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
        user_id=current_user.id,
        notes=f"Snapshot for training job"
    )

    # Create training job
    job = TrainingJob(
        owner_id=current_user.id,
        dataset_id=config.dataset_id,
        dataset_snapshot_id=snapshot["snapshot_id"],
        ...
    )
    db.add(job)
    db.commit()
    return job
```

---

## Migration Strategy

### Phase 1: Analysis & Documentation (Completed ✅)

**완료 항목:**
- [x] Platform DB Dataset FK 분석 (`analyze_dataset_usage.py`)
- [x] R2 bucket 실제 데이터 확인 (`check_r2_datasets.py`)
- [x] Labeler API 요구사항 문서 작성 (`LABELER_DATASET_API_REQUIREMENTS.md`)
- [x] Phase 11 계획에 Stage 2.5 추가
- [x] Architecture 문서 작성 (이 문서)

### Phase 2: Labeler API Implementation (Labeler Team)

**Labeler 팀 작업:**
- [ ] 6개 API 엔드포인트 구현
  - GET /api/v1/datasets/{id}
  - GET /api/v1/datasets (with filters)
  - POST /api/v1/datasets/{id}/download-url
  - GET /api/v1/datasets/{id}/permissions/{user_id}
  - POST /api/v1/datasets/batch
  - (1 additional endpoint for batch permissions check)
- [ ] Service-to-Service 인증 구현
- [ ] Rate limiting 설정
- [ ] 통합 테스트 환경 구축

**예상 기간:** 3-4일 (엔드포인트 축소로 단축)

### Phase 3: Platform Integration (Platform Team)

**Platform 팀 작업:**
- [ ] LabelerClient 구현 (`app/clients/labeler_client.py`)
- [ ] Snapshot Service 구현 (`app/services/snapshot_service.py`)
  - R2에서 직접 snapshot 생성 (dual_storage 활용)
  - Platform DB에 `dataset_snapshots` 테이블 추가
- [ ] Platform API 엔드포인트 수정
  - GET /api/v1/datasets/available → Labeler proxy
  - GET /api/v1/datasets/{id} → Labeler proxy
  - POST /api/v1/training → Platform snapshot 생성 로직 추가
- [ ] Platform DB Schema 마이그레이션
  - datasets 테이블에 `is_legacy` flag 추가
  - `dataset_snapshots` 테이블 신규 생성
- [ ] 환경 변수 설정 (LABELER_API_URL, LABELER_SERVICE_KEY)

**예상 기간:** 5-6일 (snapshot 관리 추가로 증가)

### Phase 4: Integration Testing

**통합 테스트 시나리오:**
1. Dataset 목록 조회 (Platform → Labeler → R2)
2. Training job 생성 with snapshot
3. 권한 체크 (403 forbidden 테스트)
4. 성능 검증 (p95 < 500ms)

**예상 기간:** 2일

### Phase 5: Production Deployment

**배포 순서:**
1. Labeler API Production 배포
2. Platform LabelerClient 환경 변수 설정
3. Platform API Production 배포
4. E2E 테스트 재실행
5. 모니터링 대시보드 확인

**예상 기간:** 1일

### Rollback Plan

**Rollback Trigger:**
- Labeler API 장애가 1시간 이상 지속
- Dataset 조회 성공률 < 95%

**Rollback 절차:**
```bash
# 1. Platform API를 legacy Platform DB 조회로 롤백
git revert <labeler-integration-commit>

# 2. Platform DB에 R2 dataset 임시 등록
python platform/backend/register_r2_dataset.py

# 3. Frontend 재배포 (API 변경 없음)

# 4. Labeler 팀에 이슈 리포트
```

---

## Implementation Checklist

### Labeler Team Tasks

**API Implementation:**
- [ ] Dataset CRUD endpoints (GET, POST, PUT, DELETE)
- [ ] Permission check endpoints
- [ ] Download URL generation endpoints
- [ ] Batch query endpoints

**Infrastructure:**
- [ ] Service-to-Service JWT authentication
- [ ] Rate limiting (1000 req/min per service)
- [ ] Error handling (404, 403, 500)
- [ ] Logging and monitoring

**Testing:**
- [ ] Unit tests (coverage > 80%)
- [ ] Integration tests
- [ ] Performance tests (p95 < 500ms)

### Platform Team Tasks

**Backend:**
- [ ] LabelerClient implementation
- [ ] Snapshot Service implementation (R2 직접 접근)
- [ ] Platform DB schema migration
  - datasets 테이블에 `is_legacy` flag
  - `dataset_snapshots` 테이블 신규 생성
- [ ] Platform API proxy endpoints
- [ ] Dataset validation in training job creation
- [ ] Snapshot 생성 로직 (POST /training)

**Frontend:**
- [ ] No changes required (API interface unchanged)

**Testing:**
- [ ] E2E test update (`test_e2e.py`)
- [ ] Integration tests with Labeler API
- [ ] Rollback procedure test

**Documentation:**
- [x] Architecture document (this document)
- [x] Labeler API requirements (LABELER_DATASET_API_REQUIREMENTS.md)
- [x] Phase 11 plan update (Stage 2.5)
- [ ] API integration guide

### Collaboration Tasks

**Staging Environment:**
- [ ] Labeler API staging deployment
- [ ] Platform → Labeler integration test
- [ ] Performance benchmark

**Production Deployment:**
- [ ] Labeler API production deployment
- [ ] Platform production deployment
- [ ] Monitoring dashboard setup
- [ ] Incident response plan

---

## Performance Requirements

### SLA Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Availability | 99.9% | Monthly uptime |
| Response Time (p50) | < 200ms | Dataset query |
| Response Time (p95) | < 500ms | Dataset query |
| Response Time (p99) | < 1s | Dataset query |
| Error Rate | < 0.1% | 4xx/5xx errors |

### Expected Traffic (Monthly)

| Operation | Volume | Avg Size |
|-----------|--------|----------|
| Dataset 조회 | ~100K requests | 5KB response |
| Permission 체크 | ~50K requests | 0.5KB response |
| Download URL 생성 | ~10K requests | 0.5KB response |
| Batch query | ~5K requests | 50KB response |

### Performance Optimization

**Caching Strategy:**
- Dataset metadata: 5분 TTL (Redis cache)
- Permission check: 1분 TTL (Redis cache)
- Download URL: No cache (presigned URL expires in 1h)

**Batch Operations:**
- Use `/datasets/batch` for bulk queries
- Reduce N+1 query problem

---

## Security Considerations

### Service-to-Service Authentication

**JWT Token Management:**
```bash
# Generate strong service key
LABELER_SERVICE_KEY=$(openssl rand -base64 32)

# Platform stores key in environment variables
LABELER_SERVICE_KEY=<base64-encoded-key>
```

**Request Headers:**
```python
headers = {
    "Authorization": f"Bearer {LABELER_SERVICE_KEY}",
    "X-Request-ID": str(uuid.uuid4()),  # For tracing
}
```

### Rate Limiting

**Per Service:**
- 1000 requests/minute (Platform → Labeler)
- Burst limit: 1500 requests/minute

**Per User:**
- 100 requests/minute (User → Platform → Labeler)
- Burst limit: 150 requests/minute

### Access Control

**Dataset Visibility:**
- `public`: All authenticated users
- `private`: Owner only
- `organization`: Organization members only

**Permission Levels:**
- `read_only`: View metadata, download dataset
- `read_write`: + Upload, update metadata
- `admin`: + Delete, manage permissions

---

## Monitoring & Observability

### Metrics to Track

**Platform Metrics:**
- Labeler API call success rate
- Labeler API response time (p50, p95, p99)
- Dataset query cache hit rate
- Training job creation with snapshot success rate

**Labeler Metrics:**
- API endpoint response time
- R2 object list/get latency
- Snapshot creation success rate
- Permission check cache hit rate

### Alerts

**Critical:**
- Labeler API availability < 99%
- Response time p95 > 1s
- Error rate > 1%

**Warning:**
- Response time p95 > 500ms
- Error rate > 0.1%
- Cache hit rate < 80%

### Logging

**Structured Logs (JSON):**
```json
{
  "timestamp": "2025-11-27T10:00:00Z",
  "service": "platform",
  "action": "labeler_api_call",
  "method": "GET",
  "endpoint": "/api/v1/datasets/ds_abc123",
  "status_code": 200,
  "duration_ms": 150,
  "user_id": 42,
  "request_id": "uuid-1234"
}
```

---

## Success Criteria

### Phase 2 Complete (Labeler API)
- ✅ 10개 API 엔드포인트 구현 완료
- ✅ 모든 API 테스트 통과 (unit + integration)
- ✅ 성능 목표 달성 (p95 < 500ms)

### Phase 3 Complete (Platform Integration)
- ✅ LabelerClient 구현 및 테스트 통과
- ✅ Platform API 엔드포인트 수정 완료
- ✅ Platform DB Schema 마이그레이션 완료

### Phase 4 Complete (Integration Testing)
- ✅ 모든 통합 테스트 시나리오 통과
- ✅ E2E 테스트 업데이트 및 통과
- ✅ 성능 벤치마크 달성

### Phase 5 Complete (Production Deployment)
- ✅ Labeler API Production 배포 성공
- ✅ Platform Production 배포 성공
- ✅ 모니터링 대시보드 정상 작동
- ✅ 24시간 안정성 검증 완료

---

## Related Documents

**Requirements & Specifications:**
- `docs/cowork/LABELER_DATASET_API_REQUIREMENTS.md` - Labeler API 명세 (레이블팀 전달용)

**Planning & Roadmap:**
- `docs/planning/PHASE_11_RAILWAY_DEPLOYMENT_PLAN.md` - Stage 2.5 Dataset Service Integration

**Testing:**
- `docs/testing/PHASE_12_5_E2E_TEST_REPORT.md` - E2E 테스트 리포트

**Implementation Progress:**
- `docs/todo/IMPLEMENTATION_TO_DO_LIST.md` - Phase 11 진행 상황

**Analysis Scripts:**
- `platform/backend/analyze_dataset_usage.py` - Platform DB FK 분석
- `platform/backend/check_r2_datasets.py` - R2 bucket 확인
- `platform/backend/check_datasets.py` - Platform DB datasets 조회

---

## Appendix: Migration Timeline

```
Week 1-2: Dataset Service Integration
├─ Day 1: Analysis (Complete ✅)
│  └─ Platform DB FK analysis
│  └─ R2 bucket verification
│
├─ Day 2-3: Documentation (Complete ✅)
│  └─ Labeler API requirements
│  └─ Architecture design
│
├─ Day 4-8: Implementation (Labeler Team)
│  └─ 10 API endpoints
│  └─ Authentication & rate limiting
│  └─ Unit & integration tests
│
├─ Day 9-12: Integration (Platform Team)
│  └─ LabelerClient implementation
│  └─ Platform API update
│  └─ DB schema migration
│
└─ Day 13-14: Testing & Deployment
   └─ Integration tests
   └─ E2E tests update
   └─ Production deployment
```

**Current Status (2025-11-27):** Day 3 Complete (Documentation Phase)

**Next Steps:**
1. Labeler 팀에 API 요구사항 문서 전달
2. Labeler 팀 API 구현 착수 확인
3. Platform 팀 LabelerClient 구현 준비
