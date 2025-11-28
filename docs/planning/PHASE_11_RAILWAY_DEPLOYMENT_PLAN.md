# Phase 11 Railway Deployment Plan

Vision AI Training Platform의 단계적 Railway 배포 계획.

**목표**: Labeler 팀과의 협업 포인트를 최소화하면서 효율적으로 Railway 배포 완료

**전략**: 공유 리소스 우선 배포 → 독립 개발 → 최종 통합 배포

---

## 전체 타임라인 (예상 5-6주)

```
Week 1: Shared Resources 배포 (Labeler 협업)
  ├─ User DB Railway 배포 (3일)
  └─ Cloudflare R2 연동 (2일)

Week 1-2: Dataset Service Integration (Labeler 협업)
  ├─ Platform DB Dataset 의존성 분석 (1일)
  ├─ Labeler API 요구사항 정의 (2일)
  ├─ Platform LabelerClient 구현 (2일)
  ├─ Platform API 수정 (2일)
  ├─ DB Schema 마이그레이션 (1일)
  └─ 통합 테스트 (2일)

Week 3-4: Platform 독립 개발 (Labeler 독립)
  ├─ 로컬 환경에서 Phase 10, 8, 1 등 개발
  └─ 기능 구현 완료

Week 5-6: Platform Railway 배포 (Labeler 독립)
  ├─ Backend 배포 (2일)
  ├─ Frontend 배포 (1일)
  └─ Infrastructure 통합 (2일)
```

---

## Stage 1: Shared User DB Railway 배포 (Week 1, Day 1-3)

### 목표
Platform과 Labeler가 공유하는 User DB를 Railway에 배포하고 양쪽 서비스 연동 완료.

### 작업 순서

#### 1.1 Railway PostgreSQL 인스턴스 생성 (Day 1 오전)

**Platform 팀 작업:**
```bash
# Railway CLI 설치 (if not installed)
npm install -g @railway/cli

# Railway 로그인
railway login

# 새 프로젝트 생성
railway init

# PostgreSQL 추가
railway add postgresql
```

**설정값:**
- Database Name: `vision_platform_users`
- Plan: Starter ($5/month, 100GB transfer)
- Region: US West (또는 가장 가까운 region)

**출력값 (Labeler 팀과 공유):**
```bash
# Railway에서 자동 생성된 DATABASE_URL 확인
railway variables

# 예시:
# DATABASE_URL=postgresql://postgres:xxx@containers-us-west-123.railway.app:5432/railway
```

#### 1.2 User DB Schema 초기화 (Day 1 오후)

**Platform 팀 작업:**
```bash
# 로컬에서 Railway DB에 연결하여 스키마 생성
export USER_DATABASE_URL="postgresql://postgres:xxx@containers-us-west-123.railway.app:5432/railway"

# User DB 스키마 생성
cd platform/backend
python scripts/phase11/init_railway_user_db.py
```

**스크립트 내용:**
- User, Organization, Invitation, ProjectMember 테이블 생성
- UserRole enum 생성 (lowercase values)
- 초기 admin 계정 생성

**검증:**
```bash
# Railway dashboard에서 확인
railway connect postgres

# 또는 psql로 확인
\dt
# users, organizations, invitations, project_members 테이블 확인
```

#### 1.3 로컬 데이터 마이그레이션 (Day 1 오후)

**Platform 팀 작업:**
```bash
# 기존 로컬 PostgreSQL User DB → Railway User DB 마이그레이션
export SOURCE_DB="postgresql://admin:devpass@localhost:5433/users"
export TARGET_DB="postgresql://postgres:xxx@containers-us-west-123.railway.app:5432/railway"

python scripts/phase11/migrate_sqlite_to_postgresql.py
```

**마이그레이션 내용:**
- Organizations: 2 rows
- Users: 5 rows
- Invitations: 0 rows
- Project_members: 0 rows

#### 1.4 Platform Backend 연동 테스트 (Day 2 오전)

**Platform 팀 작업:**
```bash
# 로컬 .env 업데이트
USER_DATABASE_URL=postgresql://postgres:xxx@containers-us-west-123.railway.app:5432/railway

# Backend 재시작
cd platform/backend
python -m uvicorn app.main:app --reload

# 로그 확인
# [CONFIG] Using shared PostgreSQL User DB: postgresql:***@containers-us-west-123.railway.app:5432/railway
# [STARTUP] Found 5 existing user(s) in Shared User DB
```

**테스트 시나리오:**
1. 로그인 (POST /api/v1/auth/login) - 200 OK
2. 사용자 조회 (GET /api/v1/auth/me) - 200 OK
3. 프로젝트 목록 (GET /api/v1/projects) - 200 OK

#### 1.5 Labeler Backend 연동 (Day 2 오후 ~ Day 3)

**협업 포인트:**

**Platform 팀 → Labeler 팀 전달:**
1. Railway User DB 접속 정보
   ```
   USER_DATABASE_URL=postgresql://postgres:xxx@containers-us-west-123.railway.app:5432/railway
   ```

2. 데이터베이스 스키마 정보
   - 테이블: users, organizations, invitations, project_members
   - Enum: UserRole (admin, manager, advanced_engineer, standard_engineer, guest)

3. 참고 코드
   - `platform/backend/app/db/database.py` - 2-DB 패턴 구현
   - `platform/backend/app/api/auth.py` - User DB 사용 예시
   - `platform/backend/app/utils/dependencies.py` - get_current_user 구현

**Labeler 팀 작업:**
1. Labeler backend `.env`에 USER_DATABASE_URL 추가
2. User 관련 query를 User DB로 변경
3. 인증/인가 로직 테스트

**통합 테스트 (Platform + Labeler):**
- Platform에서 생성한 사용자로 Labeler 로그인 가능 확인
- Labeler에서 생성한 사용자로 Platform 로그인 가능 확인
- Organization 공유 확인

### 1.6 문서화 및 마무리 (Day 3)

**Platform 팀 작업:**
- Railway User DB 운영 가이드 작성
- Backup/Restore 절차 문서화
- 모니터링 설정 (Railway dashboard)

---

## Stage 2: Cloudflare R2 Storage 연동 (Week 1, Day 4-5)

### 목표
Dataset 저장소를 MinIO (External, 9000) → Cloudflare R2로 이동.

### 배경
- **Internal Storage (9002)**: Training checkpoints, weights, configs (Platform 전용)
- **External Storage (9000)**: Datasets, raw images (Platform + Labeler 공유)

### 작업 분담

#### 2.1 Cloudflare R2 Setup (Day 4 오전 - Labeler 팀 주도)

**Labeler 팀 작업:**
1. Cloudflare R2 bucket 생성
   - Bucket name: `vision-platform-datasets`
   - Region: Auto (global distribution)

2. R2 API 토큰 생성
   - Permissions: Read + Write
   - Token 생성 후 Platform 팀과 공유

3. CORS 설정
   ```json
   [
     {
       "AllowedOrigins": ["*"],
       "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
       "AllowedHeaders": ["*"],
       "ExposeHeaders": ["ETag"],
       "MaxAgeSeconds": 3600
     }
   ]
   ```

**출력값 (Platform 팀과 공유):**
```bash
R2_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=xxx
R2_SECRET_ACCESS_KEY=xxx
R2_BUCKET=vision-platform-datasets
```

#### 2.2 Platform External Storage 마이그레이션 (Day 4 오후 - Platform 팀)

**Platform 팀 작업:**

**Step 1: 기존 MinIO 데이터 백업**
```bash
# MinIO에서 모든 dataset 다운로드
cd platform/backend
python scripts/backup_minio_datasets.py
# → ./backups/datasets/ 에 저장
```

**Step 2: Cloudflare R2로 업로드**
```bash
# R2 자격증명 설정
export R2_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
export R2_ACCESS_KEY_ID=xxx
export R2_SECRET_ACCESS_KEY=xxx
export R2_BUCKET=vision-platform-datasets

# 데이터셋 업로드
python scripts/upload_to_r2.py ./backups/datasets/
```

**Step 3: .env 업데이트**
```bash
# Before (MinIO External)
EXTERNAL_STORAGE_ENDPOINT=http://localhost:9000
EXTERNAL_STORAGE_ACCESS_KEY=minioadmin
EXTERNAL_STORAGE_SECRET_KEY=minioadmin
EXTERNAL_BUCKET_DATASETS=training-datasets

# After (Cloudflare R2)
EXTERNAL_STORAGE_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
EXTERNAL_STORAGE_ACCESS_KEY=xxx
EXTERNAL_STORAGE_SECRET_KEY=xxx
EXTERNAL_BUCKET_DATASETS=vision-platform-datasets
```

**Step 4: Dual Storage 코드 업데이트 (필요시)**
```python
# app/utils/dual_storage.py
# R2 endpoint는 https이므로 SSL 검증 활성화
# MinIO처럼 endpoint_url 사용하지만 region_name 추가 필요할 수 있음
```

#### 2.3 통합 테스트 (Day 5 - Platform + Labeler)

**Platform 팀 테스트:**
1. Dataset 업로드 (POST /api/v1/datasets/upload)
2. Dataset 목록 조회 (GET /api/v1/datasets)
3. Training job 생성 시 R2에서 dataset 다운로드 확인

**Labeler 팀 테스트:**
1. Labeler에서 dataset annotation
2. Annotated dataset R2에 업로드
3. Platform에서 annotated dataset으로 training 가능 확인

**성능 검증:**
- Dataset 업로드 속도: MinIO vs R2 비교
- Dataset 다운로드 속도: Training 시작 시간 비교
- 비용: R2 무료 tier 10GB/month 확인

### 2.4 문서화 및 마무리 (Day 5)

**Platform 팀 작업:**
- R2 연동 가이드 작성
- MinIO → R2 마이그레이션 스크립트 문서화
- Rollback 절차 정리 (R2 → MinIO 복원 방법)

---

## Stage 2.5: Dataset Management Migration to Labeler (Week 1-2)

### 목표
Dataset 관리 책임을 Platform에서 Labeler로 완전히 이전하고, Platform이 Labeler API를 통해 Dataset 정보를 조회하도록 구조 변경.

### 배경 및 결정 사항

**Problem Statement:**
- 기존에 Platform DB의 `datasets` 테이블에서 dataset 메타데이터 관리
- Labeler가 별도로 dataset annotation 관리
- 데이터 중복 및 동기화 문제 발생

**Architecture Decision:**
- **Dataset 관리 책임**: Platform → Labeler로 완전 이전
- **Single Source of Truth**: Labeler가 모든 dataset 메타데이터 소유
- **Platform 역할**: Labeler API를 쿼리하여 dataset 정보 조회
- **Platform DB**: dataset_id(UUID)만 FK로 저장, 메타데이터는 저장하지 않음

**Reference**: `docs/cowork/LABELER_DATASET_API_REQUIREMENTS.md`

### 2.5.1 Platform DB Dataset 의존성 분석 (Day 1)

**분석 목적:**
Platform DB에서 Dataset 테이블을 참조하는 모든 FK 관계 파악.

**분석 결과:**
```python
# Foreign Key Dependencies
1. TrainingJob.dataset_id → datasets.id
2. TrainingJob.dataset_snapshot_id → datasets.id
3. Invitation.dataset_id → datasets.id (협업 초대 시 dataset 공유)
4. DatasetPermission.dataset_id → datasets.id
5. User.owned_datasets → datasets (relationship)
```

**분석 스크립트:**
```bash
cd platform/backend
python analyze_dataset_usage.py

# Output:
# === Foreign Key Relationships ===
# Tables referencing 'datasets' table: 4
#   training_jobs
#     Columns: ['dataset_id', 'dataset_snapshot_id'] -> datasets.['id']
#   invitations
#     Columns: ['dataset_id'] -> datasets.['id']
#   dataset_permissions
#     Columns: ['dataset_id'] -> datasets.['id']
```

**기존 Platform DB 데이터:**
```
Total datasets in DB: 3
- sample-det-coco32: Storage Type = minio (legacy)
- sample-det-coco128: Storage Type = minio (legacy)
- det-mvtec-ad: Storage Type = minio (legacy)
```

**R2 실제 데이터:**
```
Total datasets in R2: 1
- ds_c75023ca76d7448b: mvtec-bottle-detection (1000 images, managed by Labeler)
```

### 2.5.2 Labeler API 요구사항 정의 (Day 2-3)

**Labeler 팀에 전달할 API 명세:**

#### Essential Endpoints

**1. GET /api/v1/datasets/{dataset_id}**
단일 dataset 메타데이터 조회.

```json
// Response
{
  "id": "ds_c75023ca76d7448b",
  "name": "mvtec-bottle-detection",
  "description": "MVTec AD bottle detection dataset",
  "format": "coco",
  "labeled": true,
  "storage_type": "r2",
  "storage_path": "datasets/ds_c75023ca76d7448b/",
  "visibility": "public",
  "owner_id": 1,
  "num_classes": 2,
  "num_images": 1000,
  "class_names": ["broken", "normal"],
  "tags": ["mvtec", "bottle", "detection"],
  "created_at": "2025-11-20T10:00:00Z",
  "updated_at": "2025-11-25T15:30:00Z"
}
```

**2. GET /api/v1/datasets**
Dataset 목록 조회 (필터링 지원).

```python
# Query Parameters
- user_id: int (optional) - 특정 사용자 소유 dataset만
- visibility: str (optional) - public, private, organization
- labeled: bool (optional) - annotation 완료 여부
- tags: List[str] (optional) - 태그 필터
- format: str (optional) - coco, yolo, voc 등
- page: int = 1
- limit: int = 20
```

**3. POST /api/v1/datasets/{dataset_id}/snapshots**
Dataset snapshot 생성 (training job 재현성 보장).

```json
// Request
{
  "version_tag": "v1.0-training-20251127",
  "created_by_user_id": 42,
  "notes": "Snapshot for Training Job #123"
}

// Response
{
  "snapshot_id": "snap_abc123",
  "dataset_id": "ds_c75023ca76d7448b",
  "version_tag": "v1.0-training-20251127",
  "created_at": "2025-11-27T10:00:00Z",
  "storage_path": "snapshots/snap_abc123/"
}
```

**4. POST /api/v1/datasets/{dataset_id}/download-url**
Presigned download URL 생성.

```json
// Request
{
  "expires_in": 3600,  // seconds
  "user_id": 42
}

// Response
{
  "download_url": "https://r2.cloudflarestorage.com/...?signature=...",
  "expires_at": "2025-11-27T11:00:00Z"
}
```

**5. GET /api/v1/datasets/{dataset_id}/permissions/{user_id}**
사용자 접근 권한 확인.

```json
// Response
{
  "has_access": true,
  "permission_level": "read_write",  // read_only, read_write, admin
  "granted_at": "2025-11-20T10:00:00Z"
}
```

**6. POST /api/v1/datasets/batch**
Bulk metadata 조회 (성능 최적화).

```json
// Request
{
  "dataset_ids": ["ds_abc", "ds_def", "ds_ghi"]
}

// Response
{
  "datasets": [
    { "id": "ds_abc", "name": "...", ... },
    { "id": "ds_def", "name": "...", ... }
  ],
  "not_found": ["ds_ghi"]
}
```

#### Authentication & Security

**Service-to-Service Authentication:**
```python
# Platform → Labeler 요청
headers = {
    "Authorization": f"Bearer {LABELER_SERVICE_KEY}",
    "X-Request-ID": str(uuid.uuid4())
}
```

**Rate Limiting:**
- Per service: 1000 req/min
- Per user: 100 req/min

**Error Handling:**
```json
// 404 Not Found
{
  "error": "dataset_not_found",
  "message": "Dataset ds_xyz does not exist",
  "dataset_id": "ds_xyz"
}

// 403 Forbidden
{
  "error": "permission_denied",
  "message": "User does not have access to this dataset",
  "required_permission": "read"
}
```

### 2.5.3 Platform Backend LabelerClient 구현 (Day 4-5)

**목표**: Platform에서 Labeler API를 호출하는 클라이언트 wrapper 구현.

**구현 파일**: `platform/backend/app/clients/labeler_client.py`

```python
from typing import List, Optional
import httpx
from app.core.config import settings

class LabelerClient:
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

    async def get_download_url(self, dataset_id: str, user_id: int) -> str:
        """Presigned download URL 생성"""
        payload = {"expires_in": 3600, "user_id": user_id}
        response = await self.client.post(
            f"/api/v1/datasets/{dataset_id}/download-url",
            json=payload
        )
        response.raise_for_status()
        return response.json()["download_url"]

    async def check_permission(self, dataset_id: str, user_id: int) -> bool:
        """사용자 접근 권한 확인"""
        response = await self.client.get(
            f"/api/v1/datasets/{dataset_id}/permissions/{user_id}"
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return response.json()["has_access"]

# Singleton instance
labeler_client = LabelerClient()
```

**환경 변수 설정:**
```bash
# .env
LABELER_API_URL=http://localhost:8020  # 로컬
# LABELER_API_URL=https://labeler.railway.app  # Production
LABELER_SERVICE_KEY=<strong-secret-key>
```

### 2.5.4 Platform API 엔드포인트 수정 (Day 6-7)

**수정 필요한 엔드포인트:**

**1. GET /api/v1/datasets/available**
기존: Platform DB에서 직접 조회
변경: Labeler API 프록시

```python
# platform/backend/app/api/datasets.py

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

**2. GET /api/v1/datasets/{dataset_id}**
```python
@router.get("/{dataset_id}", response_model=DatasetInfo)
async def get_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get dataset metadata from Labeler service"""
    # Check permission
    has_access = await labeler_client.check_permission(dataset_id, current_user.id)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied")

    # Fetch metadata
    try:
        return await labeler_client.get_dataset(dataset_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Dataset not found")
        raise
```

**3. POST /api/v1/training (TrainingJob 생성 시 dataset validation)**
```python
@router.post("/training", response_model=TrainingJobResponse)
async def create_training_job(
    config: TrainingConfigCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validate dataset exists and user has access
    dataset = await labeler_client.get_dataset(config.dataset_id)
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

    # Create training job with snapshot_id
    job = TrainingJob(
        owner_id=current_user.id,
        project_id=config.project_id,
        dataset_id=config.dataset_id,
        dataset_snapshot_id=snapshot["snapshot_id"],
        ...
    )
    db.add(job)
    db.commit()
    return job
```

### 2.5.5 Platform DB Schema 마이그레이션 (Day 8)

**목표**: Platform DB의 Dataset 테이블을 legacy로 마킹하고, FK 관계만 유지.

**Option 1: Dataset 테이블 유지 (권장)**
- FK 관계 유지를 위해 테이블은 남겨둠
- 더 이상 신규 데이터 추가하지 않음
- 메타데이터 컬럼은 nullable로 변경 (향후 삭제 가능)

```python
# Migration script
from alembic import op
import sqlalchemy as sa

def upgrade():
    # Make metadata columns nullable
    op.alter_column('datasets', 'name', nullable=True)
    op.alter_column('datasets', 'format', nullable=True)
    op.alter_column('datasets', 'storage_type', nullable=True)

    # Add migration flag
    op.add_column('datasets', sa.Column('is_legacy', sa.Boolean(), default=True))

    # Mark existing datasets as legacy
    op.execute("UPDATE datasets SET is_legacy = true")
```

**Option 2: Dataset 테이블 완전 제거 (고급)**
- FK 제약조건을 모두 해제
- dataset_id는 String(UUID)로만 저장 (FK 아님)
- Labeler에서 dataset 삭제 시 Platform에서 orphan 레코드 발생 가능

### 2.5.6 통합 테스트 (Day 9-10)

**테스트 시나리오:**

**1. Dataset 조회 흐름**
```bash
# Frontend → Platform API → Labeler API → R2
GET /api/v1/datasets/available
→ Platform calls Labeler GET /api/v1/datasets
→ Labeler queries metadata from DB + R2
→ Returns dataset list to Platform
→ Platform returns to Frontend
```

**2. Training Job 생성 흐름**
```bash
# Dataset snapshot 생성 후 training
POST /api/v1/training
→ Platform calls Labeler GET /api/v1/datasets/{id}
→ Platform calls Labeler POST /api/v1/datasets/{id}/snapshots
→ Platform creates TrainingJob with snapshot_id
→ Training downloads dataset from R2 using presigned URL
```

**3. 권한 체크 흐름**
```bash
# User가 private dataset 접근 시도
GET /api/v1/datasets/{private_dataset_id}
→ Platform calls Labeler GET /api/v1/datasets/{id}/permissions/{user_id}
→ Labeler checks DatasetPermission table
→ Returns 403 if no permission
```

**성능 검증:**
- Dataset 목록 조회 시간: < 500ms (20개 기준)
- Single dataset 조회 시간: < 200ms
- Snapshot 생성 시간: < 1s
- Presigned URL 생성 시간: < 100ms

**에러 처리 검증:**
- Labeler API 응답 없음 → 500 error with retry logic
- Dataset not found → 404 error
- Permission denied → 403 error

### 2.5.7 문서화 및 Labeler 팀 전달 (Day 10)

**전달 문서:**
1. `docs/cowork/LABELER_DATASET_API_REQUIREMENTS.md` (이미 작성 완료)
2. Platform-Labeler 통합 테스트 결과
3. 예상 트래픽 및 SLA 요구사항

**SLA 요구사항:**
- Availability: 99.9% (월 43분 다운타임 허용)
- Response time p95: < 500ms
- Error rate: < 0.1%

**예상 트래픽 (월):**
- Dataset 조회: ~100K requests
- Snapshot 생성: ~5K requests
- Permission 체크: ~50K requests

### 2.5.8 롤백 계획

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

### 2.5.9 Migration Checklist

**Labeler 팀 작업:**
- [ ] Labeler API 6개 엔드포인트 구현 (snapshot 제외, Platform 관리)
- [ ] Service-to-Service 인증 구현
- [ ] Rate limiting 설정
- [ ] 통합 테스트 환경 구축
- [ ] Production 배포

**Platform 팀 작업:**
- [x] Platform DB Dataset FK 분석 완료
- [x] Labeler API 요구사항 문서 작성
- [ ] LabelerClient 구현
- [ ] Snapshot Service 구현 (R2 직접 접근, Platform DB에 snapshot 저장)
- [ ] Platform API 엔드포인트 수정
- [ ] Platform DB Schema 마이그레이션
  - datasets 테이블에 `is_legacy` flag
  - `dataset_snapshots` 테이블 신규 생성
- [ ] 통합 테스트 실행
- [ ] E2E 테스트 업데이트

**협업 작업:**
- [ ] Staging 환경에서 통합 테스트
- [ ] 성능 검증
- [ ] Production 배포 계획 수립
- [ ] 모니터링 대시보드 설정

---

## Stage 3: Platform 독립 개발 (Week 2-3)

### 목표
Labeler 팀과 독립적으로 Platform 기능 개발 완료.

### 전제 조건
- ✅ User DB Railway 배포 완료 (Shared)
- ✅ Cloudflare R2 연동 완료 (Shared)
- ✅ Labeler 팀과 독립 작업 가능

### 개발 환경
```
┌────────────────────────────────────┐
│  로컬 개발 환경                      │
├────────────────────────────────────┤
│ Frontend: localhost:3000           │
│ Backend: localhost:8000            │
│                                    │
│ ┌─ Shared (Railway/R2) ──────────┐│
│ │ User DB: Railway PostgreSQL    ││
│ │ External Storage: Cloudflare R2││
│ └────────────────────────────────┘│
│                                    │
│ ┌─ Local (Docker) ───────────────┐│
│ │ Platform DB: PostgreSQL :5432  ││
│ │ Internal Storage: MinIO :9002  ││
│ │ Redis: :6379                   ││
│ │ MLflow: :5000                  ││
│ │ Prometheus: :9090              ││
│ │ Grafana: :3200                 ││
│ └────────────────────────────────┘│
└────────────────────────────────────┘
```

### 개발 우선순위

#### 3.1 Phase 10: Training SDK Frontend (Week 2)

**목표**: Training SDK UI 완성

**작업 목록:**
1. **Log Viewer Panel** (2일)
   - TrainingPanel에 "Logs" 탭 추가
   - WebSocket 실시간 로그 스트리밍
   - 로그 레벨 필터 (DEBUG, INFO, WARNING, ERROR)
   - 로그 검색 기능

2. **Basic/Advanced Config UI** (2일)
   - Config 입력 폼 분리 (Basic vs Advanced)
   - Framework별 Advanced config 동적 생성
   - Config validation 및 피드백

3. **Real-time Training Monitoring** (1일)
   - WebSocket 메트릭 업데이트
   - 진행률 바, ETA 표시
   - GPU/메모리 사용률 차트

#### 3.2 Phase 8: E2E Testing (Week 2-3)

**목표**: 테스트 커버리지 확대

**작업 목록:**
1. **Export Feature Tests** (2일)
   - ONNX export (모든 opset 버전)
   - TensorRT export (FP16, INT8)
   - CoreML, TFLite, TorchScript export

2. **Training Feature Tests** (2일)
   - 다양한 hyperparameter 조합
   - 모든 model/task type 조합
   - Checkpoint 저장/로드

3. **API Schema Consistency Tests** (1일)
   - Frontend request ↔ Backend schema 일치 검증
   - 모든 endpoint response 검증

#### 3.3 Phase 1: Permission System (Week 3)

**목표**: Role 기반 접근 제어

**작업 목록:**
1. **API Permission Middleware** (2일)
   - Role별 endpoint 접근 제어
   - Permission decorator 구현
   - 관리자 전용 기능 보호

2. **Frontend Permission UI** (1일)
   - Role 기반 메뉴 표시/숨김
   - 버튼 활성화/비활성화
   - 권한 없음 메시지

3. **Testing** (1일)
   - 각 Role별 접근 권한 테스트
   - 관리자 기능 보호 검증

#### 3.4 기타 개선 작업 (Week 3)

**선택적 작업 (시간 여유 시):**
- Phase 4: Experiment 비교 기능
- Phase 6: Platform Inference Endpoint 개선
- Documentation 업데이트
- Bug fixes 및 refactoring

---

## Stage 4: Platform Railway 배포 (Week 4)

### 목표
Platform Backend, Frontend, Infrastructure를 Railway에 배포하여 완전한 프로덕션 환경 구축.

### 전제 조건
- ✅ User DB Railway 배포 완료 (Stage 1)
- ✅ Cloudflare R2 연동 완료 (Stage 2)
- ✅ Platform 기능 개발 완료 (Stage 3)

### 4.1 Platform DB Railway 배포 (Day 1)

#### 4.1.1 PostgreSQL 인스턴스 생성

```bash
# Railway에 Platform DB 추가
railway add postgresql

# Database name 설정
# vision_platform_db
```

**설정값:**
- Database Name: `vision_platform_db`
- Plan: Starter ($5/month)
- Region: US West (User DB와 동일 region)

#### 4.1.2 Platform DB Schema 초기화

```bash
# 환경변수 설정
export DATABASE_URL="postgresql://postgres:xxx@containers-us-west-456.railway.app:5432/railway"

# 스키마 생성
cd platform/backend
python scripts/setup/init_db.py
```

**테이블 생성:**
- Projects, Datasets, TrainingJobs, Experiments
- ExportJobs, Deployments, InferenceJobs
- DatasetPermissions, ExperimentStars, etc.

#### 4.1.3 로컬 데이터 마이그레이션

```bash
# 로컬 Platform DB → Railway Platform DB
export SOURCE_DB="postgresql://admin:devpass@localhost:5432/platform"
export TARGET_DB="postgresql://postgres:xxx@containers-us-west-456.railway.app:5432/railway"

python scripts/migrate_platform_db.py
```

### 4.2 Redis Railway 배포 (Day 1)

```bash
# Railway에 Redis 추가
railway add redis

# Connection URL 확인
railway variables
# REDIS_URL=redis://default:xxx@containers-us-west-789.railway.app:6379
```

**용도:**
- Session storage (Phase 5에서 구현됨)
- Cache (future)
- Celery queue (future)

### 4.3 Backend Railway 배포 (Day 2)

#### 4.3.1 Dockerfile 준비

```dockerfile
# platform/backend/Dockerfile (이미 존재)
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Start server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### 4.3.2 Railway 환경변수 설정

```bash
# Railway dashboard에서 설정
# Settings → Variables

# Databases
DATABASE_URL=postgresql://postgres:xxx@containers-us-west-456.railway.app:5432/railway
USER_DATABASE_URL=postgresql://postgres:xxx@containers-us-west-123.railway.app:5432/railway
REDIS_URL=redis://default:xxx@containers-us-west-789.railway.app:6379

# Storage
INTERNAL_STORAGE_ENDPOINT=<Railway MinIO or R2>
INTERNAL_STORAGE_ACCESS_KEY=xxx
INTERNAL_STORAGE_SECRET_KEY=xxx
INTERNAL_BUCKET_WEIGHTS=model-weights
INTERNAL_BUCKET_CHECKPOINTS=training-checkpoints

EXTERNAL_STORAGE_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
EXTERNAL_STORAGE_ACCESS_KEY=xxx
EXTERNAL_STORAGE_SECRET_KEY=xxx
EXTERNAL_BUCKET_DATASETS=vision-platform-datasets

# LLM
GOOGLE_API_KEY=xxx
LLM_MODEL=gemini-2.5-flash-lite

# Security
JWT_SECRET=<생성된 강력한 시크릿>
JWT_ALGORITHM=HS256

# CORS
CORS_ORIGINS=https://your-frontend.railway.app

# MLflow (선택적 - 별도 서비스로 배포 권장)
MLFLOW_TRACKING_URI=https://your-mlflow.railway.app
```

#### 4.3.3 배포

```bash
# Railway에 배포
railway up

# 로그 확인
railway logs

# 헬스체크
curl https://your-backend.railway.app/health
# {"status": "healthy"}
```

### 4.4 Frontend Railway 배포 (Day 3)

#### 4.4.1 Dockerfile 준비

```dockerfile
# platform/frontend/Dockerfile (이미 존재)
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm && pnpm install

# Copy application code
COPY . .

# Build
RUN pnpm build

# Production image
FROM node:20-alpine

WORKDIR /app

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

EXPOSE 3000

CMD ["pnpm", "start"]
```

#### 4.4.2 Railway 환경변수 설정

```bash
# Railway dashboard → Frontend service → Variables

NEXT_PUBLIC_API_URL=https://your-backend.railway.app/api/v1
NEXT_PUBLIC_WS_URL=wss://your-backend.railway.app/ws
NEXT_PUBLIC_ENVIRONMENT=production
```

#### 4.4.3 배포

```bash
# Railway에 배포
railway up

# 확인
curl https://your-frontend.railway.app
```

### 4.5 Internal Storage 선택 및 배포 (Day 3-4)

**옵션 1: Railway MinIO**
```bash
# 별도 Railway 프로젝트로 MinIO 배포
# (복잡하므로 권장하지 않음)
```

**옵션 2: Cloudflare R2 (권장)**
```bash
# Internal storage도 R2 사용
# 별도 bucket 생성: vision-platform-internal
# training-checkpoints, model-weights, config-schemas 등
```

**옵션 3: AWS S3**
```bash
# S3 bucket 생성
aws s3 mb s3://vision-platform-internal
```

### 4.6 MLflow 배포 (선택적, Day 4)

**옵션 1: Railway 별도 서비스**
```bash
# MLflow Dockerfile
FROM python:3.11-slim

RUN pip install mlflow psycopg2-binary boto3

CMD ["mlflow", "server", \
     "--backend-store-uri", "${BACKEND_STORE_URI}", \
     "--default-artifact-root", "${ARTIFACT_ROOT}", \
     "--host", "0.0.0.0", \
     "--port", "5000"]
```

**옵션 2: Managed MLflow (MLflow Cloud)**
- 추가 비용 발생
- 관리 편의성 증가

### 4.7 통합 테스트 및 검증 (Day 5)

#### E2E 테스트 시나리오

**1. Authentication Flow**
```bash
# Railway User DB 사용
1. 회원가입 → Railway User DB에 저장 확인
2. 로그인 → JWT 토큰 발급 확인
3. 사용자 정보 조회 → Railway User DB에서 조회 확인
```

**2. Dataset Management Flow**
```bash
# Cloudflare R2 사용
1. Dataset 업로드 → R2에 저장 확인
2. Dataset 목록 조회 → R2에서 메타데이터 조회
3. Dataset 다운로드 → R2에서 파일 다운로드
```

**3. Training Flow**
```bash
# Railway Platform DB + R2 + Internal Storage
1. Training job 생성 → Railway Platform DB에 저장
2. Dataset R2에서 다운로드 → Training 시작
3. Checkpoint Internal Storage에 저장
4. Training 완료 → Railway Platform DB 업데이트
```

**4. Export & Deployment Flow**
```bash
# Internal Storage + MLflow
1. Export job 생성 → ONNX 변환
2. Exported model Internal Storage에 저장
3. Deployment 생성 → Platform endpoint 활성화
4. Inference 테스트 → 정상 동작 확인
```

#### 성능 검증

**Metrics:**
- API 응답 시간 (p50, p95, p99)
- Database query 성능
- Storage I/O 속도
- Frontend 로딩 시간

**목표:**
- API p95 < 500ms
- Database query p95 < 100ms
- Dataset 업로드 > 5MB/s
- Frontend FCP < 2s

#### 모니터링 설정

**Railway Dashboard:**
- CPU/Memory 사용률 모니터링
- Request 수 추적
- Error rate 추적

**Sentry (선택적):**
- Frontend/Backend 에러 추적
- Performance monitoring

**Prometheus + Grafana (선택적):**
- 별도 Railway 서비스로 배포
- Custom metrics 수집

---

## Stage 5: 롤백 및 장애 대응 계획

### 5.1 롤백 시나리오

#### Scenario 1: User DB 문제

**증상:**
- 로그인 실패
- 사용자 조회 에러

**롤백 절차:**
```bash
# 1. 로컬 User DB로 전환
USER_DATABASE_URL=postgresql://admin:devpass@localhost:5433/users

# 2. Backend 재시작
railway restart

# 3. Railway User DB 디버깅
railway logs
```

#### Scenario 2: R2 연결 문제

**증상:**
- Dataset 업로드 실패
- Training 시작 실패

**롤백 절차:**
```bash
# 1. MinIO로 전환
EXTERNAL_STORAGE_ENDPOINT=http://localhost:9000
EXTERNAL_STORAGE_ACCESS_KEY=minioadmin
EXTERNAL_STORAGE_SECRET_KEY=minioadmin

# 2. R2 → MinIO 데이터 복원
python scripts/restore_from_r2.py
```

#### Scenario 3: Railway Backend 장애

**증상:**
- API 응답 없음
- 500 에러 발생

**롤백 절차:**
```bash
# 1. Railway 이전 버전으로 rollback
railway rollback

# 2. 로컬 Backend로 임시 전환 (frontend .env 수정)
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

### 5.2 백업 전략

#### User DB 백업 (일 1회)
```bash
# Railway PostgreSQL → S3 백업
railway run pg_dump | aws s3 cp - s3://backups/user-db-$(date +%Y%m%d).sql
```

#### Platform DB 백업 (일 1회)
```bash
railway run pg_dump | aws s3 cp - s3://backups/platform-db-$(date +%Y%m%d).sql
```

#### R2 Dataset 백업 (주 1회)
```bash
# R2 → S3 Glacier (cold storage)
rclone sync r2:vision-platform-datasets s3-glacier:backups/datasets
```

---

## 비용 예측 (월간)

### Railway 비용

| 리소스 | Plan | 비용 | 비고 |
|--------|------|------|------|
| User DB (PostgreSQL) | Starter | $5 | 100GB transfer |
| Platform DB (PostgreSQL) | Starter | $5 | 100GB transfer |
| Redis | Starter | $5 | 100GB transfer |
| Backend (Web Service) | Pro | $20 | 8GB RAM, 4 vCPU |
| Frontend (Web Service) | Pro | $20 | 8GB RAM, 4 vCPU |
| MLflow (선택적) | Pro | $20 | 8GB RAM, 4 vCPU |
| **합계** | | **$55-75** | MLflow 포함 시 $75 |

### Cloudflare R2 비용

| 항목 | 무료 티어 | 초과 시 비용 |
|------|----------|-------------|
| Storage | 10GB/month | $0.015/GB |
| Class A Operations | 1M/month | $4.50/million |
| Class B Operations | 10M/month | $0.36/million |
| Egress | 무제한 | $0 |

**예상 사용량 (월):**
- Storage: ~50GB → $0.60
- Operations: ~5M Class A, ~20M Class B → $25
- **합계**: ~$26

### 총 비용

| 항목 | 비용 |
|------|------|
| Railway | $55-75 |
| Cloudflare R2 | $26 |
| Domain (선택적) | $12/year |
| **월 합계** | **$81-101** |

---

## 협업 체크리스트

### Labeler 팀에게 필요한 정보

**Stage 1 완료 후 공유:**
- [x] Railway User DB 접속 정보 (DATABASE_URL)
- [x] User DB 스키마 정보 (테이블, enum)
- [x] 참고 코드 (database.py, auth.py, dependencies.py)
- [x] 통합 테스트 시나리오

**Stage 2 완료 후 공유:**
- [x] Cloudflare R2 접속 정보 (endpoint, credentials)
- [x] R2 bucket 이름 및 구조
- [x] Dataset 업로드/다운로드 예시 코드
- [x] 통합 테스트 시나리오

**Stage 2.5 완료 후 공유:**
- [x] Labeler API 요구사항 문서 (`docs/cowork/LABELER_DATASET_API_REQUIREMENTS.md`)
- [x] Platform DB Dataset FK 분석 결과
- [ ] Platform LabelerClient 참고 구현
- [ ] 통합 테스트 시나리오
- [ ] 예상 트래픽 및 SLA 요구사항

### Platform 팀 독립 작업 확인

**Stage 3 시작 조건:**
- [x] User DB Railway 배포 완료
- [x] Labeler 팀 User DB 연동 완료 확인
- [x] Cloudflare R2 연동 완료
- [x] Labeler 팀 R2 연동 완료 확인

**독립 작업 가능:**
- [x] 로컬 Platform DB 사용
- [x] 로컬 Internal Storage (MinIO 9002) 사용
- [x] Railway User DB 사용 (Shared)
- [x] Cloudflare R2 사용 (Shared)

---

## 성공 기준

### Stage 1 성공 기준
- ✅ Railway User DB 정상 동작
- ✅ Platform 로그인/사용자 조회 성공
- ✅ Labeler 로그인/사용자 조회 성공
- ✅ Platform-Labeler 사용자 공유 확인

### Stage 2 성공 기준
- ✅ Cloudflare R2 데이터셋 업로드/다운로드 성공
- ✅ Platform Training job R2 dataset 사용 성공
- ✅ Labeler annotation R2 업로드 성공
- ✅ MinIO 대비 성능 차이 < 20%

### Stage 2.5 성공 기준
- ✅ Platform DB Dataset FK 분석 완료
- ✅ Labeler API 요구사항 문서 작성 완료
- ✅ Labeler 팀 API 구현 완료 (6개 엔드포인트, snapshot은 Platform 관리)
- ✅ Platform LabelerClient 구현 및 테스트 통과
- ✅ Platform Snapshot Service 구현 완료 (R2 직접 접근)
- ✅ Platform API 엔드포인트 Labeler API 프록시로 전환 완료
- ✅ 통합 테스트 모두 통과
- ✅ 성능 목표 달성 (Dataset 조회 p95 < 500ms)

### Stage 3 성공 기준
- ✅ Phase 10 Frontend 완료 (Training SDK UI)
- ✅ Phase 8 E2E Testing 완료 (커버리지 > 80%)
- ✅ Phase 1 Permission System 완료
- ✅ 모든 테스트 통과

### Stage 4 성공 기준
- ✅ Railway Backend 배포 성공
- ✅ Railway Frontend 배포 성공
- ✅ E2E 테스트 모두 통과
- ✅ 성능 목표 달성 (API p95 < 500ms)

---

## Next Steps

**현재 위치**: Stage 1 시작 전

**즉시 실행 가능:**
1. Railway CLI 설치 및 로그인
2. Railway PostgreSQL 인스턴스 생성 (User DB)
3. `scripts/phase11/init_railway_user_db.py` 작성
4. User DB 스키마 초기화

**준비 사항:**
- [x] Railway 계정 생성
- [x] Railway CLI 설치
- [ ] Cloudflare 계정 생성 (R2 사용)
- [ ] 백업 스크립트 준비

**협업 준비:**
- [ ] Labeler 팀에 Stage 1 시작 알림
- [ ] Labeler 팀 작업 일정 확인
- [ ] 통합 테스트 시간 조율
