# Phase 11: Microservice Separation - User & Dataset DB Migration

**작성일**: 2025-11-23
**단계**: Phase 11 - Production Architecture Migration
**목적**: 플랫폼 아키텍처를 모놀리식에서 마이크로서비스로 전환하여 확장성과 유지보수성 향상

---

## 개요

현재 Platform Backend가 User와 Dataset 데이터를 직접 관리하고 있으나, 프로덕션 환경에서는 다음과 같은 문제가 발생:

1. **User DB**: Platform과 Labeler 양쪽에서 동일한 사용자 정보 필요
2. **Dataset DB**: Labeler에서 데이터셋 관리 기능을 담당하며 이미 DB 구축 완료

이를 해결하기 위해 마이크로서비스 아키텍처로 전환하되, **3단계 점진적 마이그레이션** 전략 사용:
- **Tier 1 (Local)**: SQLite로 빠른 개념 검증 및 개발
- **Tier 2 (Railway)**: PostgreSQL 상시 가동으로 프로덕션 검증
- **Tier 3 (On-Prem K8s)**: 전체 시스템 on-premise 배포

### 3-Tier Migration Strategy

```
Tier 1: Local Development (SQLite)
  ↓ 검증 완료
Tier 2: Railway Production (PostgreSQL)
  ↓ 안정화
Tier 3: On-Prem K8s (PostgreSQL StatefulSet)
```

**핵심 원칙**:
- ✅ 각 단계에서 동일한 코드 사용 (환경 변수만 변경)
- ✅ 단계별 검증 후 다음 단계로 이동
- ✅ 롤백 가능한 구조 유지

---

## Tier 1: Local Development (SQLite)

### 목표
- ✅ **빠른 개념 검증**: SQLite로 DB 분리 로직 구현 및 테스트
- ✅ **개발 환경 구축**: 로컬에서 Platform + Labeler 동시 실행
- ✅ **코드 검증**: Railway 배포 전 버그 수정

### Architecture (Tier 1)

```
┌──────────────────────────────────────────────┐
│    Shared User DB (SQLite)                    │
│    File: /tmp/shared_users.db                │
└──────────────────────────────────────────────┘
     ▲                            ▲
     │ File Access                │ File Access
     │                            │
┌────┴──────────┐        ┌────────┴──────────┐
│  Platform     │        │  Labeler          │
│  Backend      │───────→│  Backend          │
│  :8000        │ HTTP   │  :8020            │
│  (SQLite)     │        │  (SQLite)         │
└───────────────┘        └───────────────────┘
```

### Implementation

#### Step 1: Shared User DB 파일 생성 (Day 1)

**파일 위치**:
```bash
# 개발 환경
/tmp/shared_users.db  # Linux/Mac
C:\temp\shared_users.db  # Windows
```

**초기 데이터베이스 생성**:
```bash
# Platform에서 기존 User 데이터 export
cd platform/backend
sqlite3 platform.db ".dump users organizations invitations project_members" > users_export.sql

# Shared DB 생성 및 데이터 import
sqlite3 /tmp/shared_users.db < users_export.sql
```

#### Step 2: 환경 변수 설정 (Day 1)

**Platform Backend** (`platform/backend/.env`):
```bash
# Platform DB (projects, training_jobs, etc.)
DATABASE_URL=sqlite:///./platform.db

# Shared User DB (users, organizations, etc.)
USER_DATABASE_URL=sqlite:////tmp/shared_users.db

# JWT Configuration (Labeler와 동일)
JWT_SECRET_KEY=local-dev-secret-key-change-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

**Labeler Backend** (`labeler/backend/.env`):
```bash
# Labeler DB (datasets, annotations, etc.)
DATABASE_URL=sqlite:///./labeler.db

# Shared User DB (Platform과 동일)
USER_DATABASE_URL=sqlite:////tmp/shared_users.db

# JWT Configuration (Platform과 동일)
JWT_SECRET_KEY=local-dev-secret-key-change-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

#### Step 3: Platform Backend 코드 수정 (Day 2-3)

**Database connection 분리**:
```python
# platform/backend/app/db/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Platform DB engine
platform_engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)
PlatformSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=platform_engine)

# Shared User DB engine
user_engine = create_engine(
    settings.USER_DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.USER_DATABASE_URL else {}
)
UserSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=user_engine)

def get_db():
    """Platform DB 세션"""
    db = PlatformSessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user_db():
    """Shared User DB 세션"""
    db = UserSessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**API 엔드포인트 수정 예시**:
```python
# platform/backend/app/api/projects.py
from app.db.database import get_db, get_user_db

@router.get("/projects/{project_id}")
def get_project(
    project_id: int,
    db: Session = Depends(get_db),          # Platform DB
    user_db: Session = Depends(get_user_db),  # Shared User DB
    current_user: User = Depends(get_current_active_user)
):
    # Project는 Platform DB에서
    project = db.query(Project).filter(Project.id == project_id).first()

    # User는 Shared User DB에서
    owner = user_db.query(User).filter(User.id == project.user_id).first()

    return {**project.__dict__, "owner": owner}
```

#### Step 4: Labeler Backend 구현 (Day 3-4)

**User 모델 추가**:
```python
# labeler/backend/app/db/models.py
# Platform의 User 모델 복사 (동일하게 유지)
from app.db.database import Base

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    ADVANCED_ENGINEER = "advanced_engineer"
    STANDARD_ENGINEER = "standard_engineer"
    GUEST = "guest"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    # ... Platform과 동일한 필드
```

**인증 로직 추가**:
```python
# labeler/backend/app/utils/auth.py
# Platform의 auth.py와 동일

from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})

    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
```

**Database 연결**:
```python
# labeler/backend/app/db/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Shared User DB
user_engine = create_engine(settings.USER_DATABASE_URL, ...)
UserSessionLocal = sessionmaker(bind=user_engine)

def get_user_db():
    db = UserSessionLocal()
    try:
        yield db
    finally:
        db.close()
```

#### Step 5: 테스트 (Day 4-5)

**테스트 시나리오**:
```bash
# 1. Platform에서 회원가입
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "password123"}'

# 2. SQLite 확인
sqlite3 /tmp/shared_users.db "SELECT id, email FROM users WHERE email='test@example.com';"

# 3. Labeler에서 동일 계정 로그인
curl -X POST http://localhost:8020/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "password123"}'

# 4. Platform 토큰으로 Labeler 접근 테스트
```

### Success Criteria (Tier 1)
- ✅ Platform과 Labeler가 `/tmp/shared_users.db` 공유
- ✅ Platform에서 생성한 사용자를 Labeler에서 로그인 가능
- ✅ 동일한 JWT secret으로 토큰 상호 호환
- ✅ 사용자 정보 수정 시 양쪽 서비스에 즉시 반영
- ✅ 모든 기능 테스트 통과

---

## Tier 2: Railway Production (PostgreSQL)

### 목표
- ✅ **프로덕션 검증**: Railway PostgreSQL로 실제 운영 환경 테스트
- ✅ **상시 가동**: Platform과 Labeler가 Railway DB 사용
- ✅ **성능 확인**: 네트워크 레이턴시 및 동시성 테스트

### Architecture (Tier 2)

```
┌──────────────────────────────────────────────┐
│     Railway PostgreSQL (Shared User DB)      │
│  Host: containers-us-west-xxx.railway.app   │
│  Port: 5432                                   │
│  Database: railway                            │
└──────────────────────────────────────────────┘
     ▲                            ▲
     │ Internet                   │ Internet
     │ (SSL)                      │ (SSL)
┌────┴──────────┐        ┌────────┴──────────┐
│  Platform     │        │  Labeler          │
│  Backend      │───────→│  Backend          │
│  (Local/Railway)│ HTTP  │  (Railway)        │
└───────────────┘        └───────────────────┘
```

### Implementation

#### Step 1: Railway User DB 생성 (Day 1)

**Railway Dashboard**:
1. New Project → "Shared User Database"
2. Add PostgreSQL Service
3. 자동 생성된 DATABASE_URL 복사:
   ```
   postgresql://postgres:xxx@containers-us-west-xxx.railway.app:5432/railway
   ```

#### Step 2: 데이터 마이그레이션 (Day 1)

**SQLite → PostgreSQL 마이그레이션**:
```bash
# 1. SQLite에서 SQL dump 생성
sqlite3 /tmp/shared_users.db .dump > users_export.sql

# 2. PostgreSQL 호환 형식으로 변환 (수동 편집)
# - AUTOINCREMENT → SERIAL
# - 타입 변환 (TEXT → VARCHAR)
# - Default 값 조정

# 3. Railway PostgreSQL로 import
psql $RAILWAY_DATABASE_URL < users_export_pg.sql
```

**또는 Python 스크립트 사용**:
```python
# migrate_sqlite_to_railway.py
import sqlite3
import psycopg2
from app.core.config import settings

# SQLite 연결
sqlite_conn = sqlite3.connect('/tmp/shared_users.db')
sqlite_cursor = sqlite_conn.cursor()

# PostgreSQL 연결
pg_conn = psycopg2.connect(settings.RAILWAY_USER_DATABASE_URL)
pg_cursor = pg_conn.cursor()

# users 테이블 마이그레이션
sqlite_cursor.execute("SELECT * FROM users")
users = sqlite_cursor.fetchall()

for user in users:
    pg_cursor.execute(
        "INSERT INTO users (...) VALUES (...)",
        user
    )

pg_conn.commit()
print(f"Migrated {len(users)} users to Railway")
```

#### Step 3: 환경 변수 업데이트 (Day 2)

**Platform Backend** (`platform/backend/.env`):
```bash
# Platform DB (여전히 로컬 또는 별도 Railway DB)
DATABASE_URL=postgresql://...

# Shared User DB (Railway)
USER_DATABASE_URL=postgresql://postgres:xxx@containers-us-west-xxx.railway.app:5432/railway?sslmode=require

# JWT Configuration (변경 없음)
JWT_SECRET_KEY=production-secret-key-from-railway-variables
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

**Labeler Backend** (Railway 환경 변수):
```bash
# Railway Dashboard → Labeler Service → Variables
USER_DATABASE_URL=postgresql://postgres:xxx@containers-us-west-xxx.railway.app:5432/railway?sslmode=require
JWT_SECRET_KEY=production-secret-key-from-railway-variables
```

#### Step 4: 코드 변경 없음 (Day 2)

**중요**: Tier 1에서 작성한 코드를 **그대로 사용**
- `settings.USER_DATABASE_URL`만 변경
- SQLite → PostgreSQL 자동 전환 (SQLAlchemy가 처리)

**연결 확인**:
```python
# test_railway_connection.py
from sqlalchemy import create_engine
import os

DATABASE_URL = os.getenv("USER_DATABASE_URL")
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    result = conn.execute("SELECT COUNT(*) FROM users")
    print(f"✅ Railway DB connected: {result.fetchone()[0]} users")
```

#### Step 5: Railway 배포 (Day 2-3)

**Platform Backend (Local 유지 가능)**:
```bash
# Railway 환경 변수에서 USER_DATABASE_URL만 변경
cd platform/backend
uvicorn app.main:app --reload
```

**Labeler Backend (Railway 배포)**:
```bash
# Railway에서 이미 배포되어 있음
# 환경 변수만 추가하면 자동 재시작
```

#### Step 6: 테스트 (Day 3-4)

**테스트 시나리오**:
```bash
# 1. Platform(Local)에서 회원가입
curl -X POST http://localhost:8000/api/v1/auth/register \
  -d '{"email": "railway@example.com", "password": "test123"}'

# 2. Railway DB 확인
psql $RAILWAY_DATABASE_URL -c "SELECT email FROM users WHERE email='railway@example.com';"

# 3. Labeler(Railway)에서 로그인
curl -X POST https://labeler-production.up.railway.app/api/v1/auth/login \
  -d '{"email": "railway@example.com", "password": "test123"}'

# 4. 성능 테스트 (레이턴시 측정)
ab -n 1000 -c 10 https://labeler-production.up.railway.app/api/v1/auth/login
```

### Success Criteria (Tier 2)
- ✅ Railway PostgreSQL에 User 데이터 저장
- ✅ Platform(Local)과 Labeler(Railway) 양쪽에서 접근 가능
- ✅ SSL 연결 정상 작동 (`sslmode=require`)
- ✅ 평균 응답 시간 < 200ms
- ✅ 동시 접속 100명 처리 가능
- ✅ 1주일 이상 안정적 운영

---

## Tier 3: On-Prem K8s (PostgreSQL StatefulSet)

### 목표
- ✅ **완전한 On-Premise**: 모든 서비스 K8s에서 운영
- ✅ **데이터 주권**: 회사 내부 서버에서 User 데이터 관리
- ✅ **고가용성**: StatefulSet + PersistentVolume

### Architecture (Tier 3)

```
┌─────────────────────────────────────────────┐
│     K8s PostgreSQL StatefulSet              │
│  Service: user-db.platform.svc.cluster.local│
│  Port: 5432                                  │
│  PVC: 20Gi                                   │
└─────────────────────────────────────────────┘
     ▲                            ▲
     │ ClusterIP                  │ ClusterIP
     │                            │
┌────┴──────────┐        ┌────────┴──────────┐
│  Platform     │        │  Labeler          │
│  Backend      │───────→│  Backend          │
│  (K8s Pod)    │ HTTP   │  (K8s Pod)        │
└───────────────┘        └───────────────────┘
```

### Implementation

#### Step 1: K8s User DB 배포 (Day 1)

**StatefulSet 생성**:
```yaml
# k8s/platform/user-db.yaml
apiVersion: v1
kind: Service
metadata:
  name: user-db
  namespace: platform
spec:
  ports:
  - port: 5432
  clusterIP: None  # Headless service for StatefulSet
  selector:
    app: user-db
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: user-db
  namespace: platform
spec:
  serviceName: user-db
  replicas: 1
  selector:
    matchLabels:
      app: user-db
  template:
    metadata:
      labels:
        app: user-db
    spec:
      containers:
      - name: postgres
        image: postgres:16-alpine
        ports:
        - containerPort: 5432
        env:
        - name: POSTGRES_DB
          value: users
        - name: POSTGRES_USER
          value: admin
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: user-db-secret
              key: password
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 20Gi
```

**Secret 생성**:
```bash
kubectl create secret generic user-db-secret \
  --from-literal=password=$(openssl rand -base64 32) \
  -n platform
```

**배포**:
```bash
kubectl apply -f k8s/platform/user-db.yaml
kubectl wait --for=condition=ready pod/user-db-0 -n platform --timeout=300s
```

#### Step 2: 데이터 마이그레이션 (Day 1-2)

**Railway → K8s 마이그레이션**:
```bash
# 1. Railway에서 dump
pg_dump $RAILWAY_DATABASE_URL > railway_users_backup.sql

# 2. K8s PostgreSQL로 복원
kubectl exec -it user-db-0 -n platform -- \
  psql -U admin -d users < railway_users_backup.sql

# 3. 확인
kubectl exec -it user-db-0 -n platform -- \
  psql -U admin -d users -c "SELECT COUNT(*) FROM users;"
```

#### Step 3: 환경 변수 업데이트 (Day 2)

**Platform Backend ConfigMap**:
```yaml
# k8s/platform/backend-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: platform-backend-config
  namespace: platform
data:
  USER_DATABASE_URL: "postgresql://admin:password@user-db.platform.svc.cluster.local:5432/users"
  JWT_SECRET_KEY: "k8s-production-secret-key"
  JWT_ALGORITHM: "HS256"
```

**Labeler Backend ConfigMap**:
```yaml
# k8s/platform/labeler-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: labeler-backend-config
  namespace: platform
data:
  USER_DATABASE_URL: "postgresql://admin:password@user-db.platform.svc.cluster.local:5432/users"
  JWT_SECRET_KEY: "k8s-production-secret-key"  # Platform과 동일
```

#### Step 4: Backend Deployment 업데이트 (Day 3)

**Platform Backend**:
```yaml
# k8s/platform/platform-backend.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: platform-backend
  namespace: platform
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: backend
        image: platform-backend:latest
        envFrom:
        - configMapRef:
            name: platform-backend-config
        env:
        - name: USER_DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: platform-secrets
              key: user-database-url
```

**Labeler Backend**:
```yaml
# k8s/platform/labeler-backend.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: labeler-backend
  namespace: platform
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: backend
        image: labeler-backend:latest
        envFrom:
        - configMapRef:
            name: labeler-backend-config
```

#### Step 5: 테스트 (Day 3-4)

**K8s 내부 테스트**:
```bash
# 1. Test Pod 생성
kubectl run test-pod --image=curlimages/curl -it --rm -n platform -- sh

# 2. Platform Backend 테스트
curl -X POST http://platform-backend.platform.svc.cluster.local:8000/api/v1/auth/register \
  -d '{"email": "k8s@example.com", "password": "test123"}'

# 3. Labeler Backend 테스트
curl -X POST http://labeler-backend.platform.svc.cluster.local:8020/api/v1/auth/login \
  -d '{"email": "k8s@example.com", "password": "test123"}'
```

**외부 접근 테스트** (Ingress 설정 필요):
```bash
# Ingress를 통한 외부 접근
curl -X POST https://platform.yourcompany.com/api/v1/auth/login \
  -d '{"email": "k8s@example.com", "password": "test123"}'
```

### Success Criteria (Tier 3)
- ✅ K8s StatefulSet으로 User DB 운영
- ✅ PersistentVolume으로 데이터 영구 저장
- ✅ Platform과 Labeler 모두 K8s 내부에서 실행
- ✅ ClusterIP로 DB 접근 (외부 노출 없음)
- ✅ High Availability (Pod restart 시 데이터 유지)
- ✅ Backup 및 Restore 절차 확립

---

## Phase 11.1: User DB Sharing (공유 User Database)

### 현재 상태 분석

**Database Schema**:
```sql
-- platform/backend PostgreSQL
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    company VARCHAR(100),
    division VARCHAR(100),
    department VARCHAR(255),
    system_role userrole NOT NULL DEFAULT 'guest',
    badge_color VARCHAR(20),
    -- ... 기타 필드
);
```

**현재 사용처** (Platform Backend):
- `app/api/projects.py` - 프로젝트 소유자 확인, 멤버 초대
- `app/api/training.py` - 학습 작업 생성자 확인
- `app/api/datasets.py` - 데이터셋 소유자 확인
- `app/api/admin.py` - 사용자 관리
- `app/api/chat.py` - 사용자 정보 조회
- `app/main.py` - 인증/인가

**Labeler Backend 요구사항**:
- 동일한 사용자 정보로 인증/인가
- 데이터셋 소유자 확인
- 라벨링 작업 할당 시 사용자 조회

### 목표 아키텍처 (공유 DB 방식)

```
┌──────────────────────────────────────────────────────┐
│            Shared User Database                       │
│  - PostgreSQL (users, organizations, invitations)    │
│  - Host: user-db.platform.svc.cluster.local:5432     │
└──────────────────────────────────────────────────────┘
         ▲                              ▲
         │ Direct DB Connection         │ Direct DB Connection
         │ (SQLAlchemy ORM)             │ (SQLAlchemy ORM)
         │                              │
┌────────┴──────────────┐  ┌────────────┴─────────────────┐
│   Platform Backend    │  │   Labeler Backend            │
│   - User Model        │  │   - User Model (동일)         │
│   - Auth Utils        │  │   - Auth Utils (동일)         │
│   - JWT 발급/검증      │  │   - JWT 발급/검증 (동일)       │
└───────────────────────┘  └──────────────────────────────┘
```

**핵심 원칙**:
- ✅ **단일 User DB**: 모든 서비스가 동일한 PostgreSQL DB 참조
- ✅ **동일한 User 모델**: Platform과 Labeler에서 같은 스키마 사용
- ✅ **공통 인증 로직**: 동일한 JWT secret과 해싱 알고리즘 사용
- ✅ **별도 서비스 불필요**: User Service Backend 없이 DB만 공유

### 공유 Database 구성

#### Database Connection 설정

**Shared User DB 생성** (Kubernetes):
```yaml
# k8s/platform/user-db.yaml
apiVersion: v1
kind: Service
metadata:
  name: user-db
  namespace: platform
spec:
  ports:
  - port: 5432
  selector:
    app: user-db
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: user-db
  namespace: platform
spec:
  serviceName: user-db
  replicas: 1
  template:
    spec:
      containers:
      - name: postgres
        image: postgres:16
        env:
        - name: POSTGRES_DB
          value: users
        - name: POSTGRES_USER
          value: admin
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: user-db-secret
              key: password
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 20Gi
```

#### 환경 변수 설정

**Platform Backend** (`platform/backend/.env`):
```bash
# Shared User Database
USER_DATABASE_URL=postgresql://admin:password@user-db.platform.svc.cluster.local:5432/users

# JWT Configuration (Labeler와 동일하게 설정)
JWT_SECRET_KEY=your-super-secret-key-shared-across-services
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

**Labeler Backend** (`labeler/backend/.env`):
```bash
# Shared User Database (Platform과 동일)
USER_DATABASE_URL=postgresql://admin:password@user-db.platform.svc.cluster.local:5432/users

# JWT Configuration (Platform과 동일하게 설정)
JWT_SECRET_KEY=your-super-secret-key-shared-across-services
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

#### 공통 User 모델 정의

두 서비스에서 **동일한 User 모델** 사용:

```python
# platform/backend/app/db/models.py
# labeler/backend/app/db/models.py (동일)

class UserRole(str, enum.Enum):
    """5-tier user permission system"""
    ADMIN = "admin"
    MANAGER = "manager"
    ADVANCED_ENGINEER = "advanced_engineer"
    STANDARD_ENGINEER = "standard_engineer"
    GUEST = "guest"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    company = Column(String(100), nullable=True)
    division = Column(String(100), nullable=True)
    department = Column(String(255), nullable=True)
    organization_id = Column(Integer, nullable=True, index=True)
    system_role = Column(SQLEnum(UserRole, values_callable=lambda obj: [e.value for e in obj]),
                         nullable=False, default=UserRole.GUEST, index=True)
    badge_color = Column(String(20), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
```

#### 공통 인증 로직

**중요**: Platform과 Labeler에서 **완전히 동일한 인증 코드** 사용

```python
# platform/backend/app/utils/auth.py
# labeler/backend/app/utils/auth.py (동일)

from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """비밀번호 해싱 (두 서비스 동일)"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """비밀번호 검증 (두 서비스 동일)"""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    """JWT 토큰 생성 (두 서비스 동일)"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt

def decode_access_token(token: str) -> dict:
    """JWT 토큰 디코딩 (두 서비스 동일)"""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        return None
```

### Migration Plan

#### Step 1: Shared User DB 구축 (Week 1)

**Tasks**:
1. ✅ Shared User Database 생성
   ```bash
   # Kubernetes에 별도 User DB StatefulSet 배포
   kubectl apply -f k8s/platform/user-db.yaml
   ```

2. ✅ Platform DB에서 User 데이터 마이그레이션
   ```bash
   # Platform PostgreSQL에서 Shared User PostgreSQL로 데이터 이전
   pg_dump -h platform-db -U admin \
     -t users -t organizations -t invitations -t project_members \
     platform > users_backup.sql

   # Shared User DB로 복원
   psql -h user-db.platform.svc.cluster.local -U admin users < users_backup.sql
   ```

3. ✅ 환경 변수 설정
   - Platform Backend `.env`에 `USER_DATABASE_URL` 추가
   - Labeler Backend `.env`에 `USER_DATABASE_URL` 추가 (동일한 DB)
   - JWT secret 키 양쪽에서 동일하게 설정

#### Step 2: Labeler Backend 구현 (Week 2)

**Tasks**:
1. ✅ Labeler에 User 모델 추가
   ```python
   # labeler/backend/app/db/models.py
   # Platform의 User 모델 복사 (동일하게 유지)
   class User(Base):
       __tablename__ = "users"
       # ... Platform과 동일한 필드
   ```

2. ✅ Labeler에 인증 로직 추가
   ```python
   # labeler/backend/app/utils/auth.py
   # Platform의 auth.py 복사 (동일하게 유지)
   ```

3. ✅ Labeler에 인증 엔드포인트 추가
   ```python
   # labeler/backend/app/api/auth.py
   @router.post("/login")
   def login(credentials: LoginRequest, db: Session = Depends(get_db)):
       user = db.query(User).filter(User.email == credentials.email).first()
       if not user or not verify_password(credentials.password, user.hashed_password):
           raise HTTPException(status_code=401, detail="Invalid credentials")

       access_token = create_access_token(data={"sub": user.email, "user_id": user.id})
       return {"access_token": access_token, "token_type": "bearer"}
   ```

4. ✅ Database connection 설정
   ```python
   # labeler/backend/app/db/database.py
   from sqlalchemy import create_engine
   from app.core.config import settings

   # Shared User DB 연결
   engine = create_engine(settings.USER_DATABASE_URL)
   ```

#### Step 3: Platform Backend 마이그레이션 (Week 2)

**Tasks**:
1. ✅ Platform DB 구조 변경
   ```sql
   -- Alembic migration
   def upgrade():
       # Foreign key 제약조건 제거
       op.drop_constraint('projects_user_id_fkey', 'projects')
       op.drop_constraint('training_jobs_created_by_fkey', 'training_jobs')

       # users 테이블은 삭제하지 않음 (Shared DB로 이동됨)
       # 대신 Platform DB에서만 제거
   ```

2. ✅ Database connection 분리
   ```python
   # platform/backend/app/db/database.py
   from sqlalchemy import create_engine

   # Platform DB (projects, training_jobs, etc.)
   platform_engine = create_engine(settings.DATABASE_URL)

   # Shared User DB (users, organizations, etc.)
   user_engine = create_engine(settings.USER_DATABASE_URL)

   def get_db():
       """Platform DB 세션"""
       db = SessionLocal(bind=platform_engine)
       try:
           yield db
       finally:
           db.close()

   def get_user_db():
       """Shared User DB 세션"""
       db = UserSessionLocal(bind=user_engine)
       try:
           yield db
       finally:
           db.close()
   ```

3. ✅ API 엔드포인트 수정
   ```python
   # platform/backend/app/api/projects.py
   @router.get("/projects/{project_id}")
   def get_project(
       project_id: int,
       db: Session = Depends(get_db),          # Platform DB
       user_db: Session = Depends(get_user_db),  # Shared User DB
       current_user: User = Depends(get_current_active_user)
   ):
       project = db.query(Project).filter(Project.id == project_id).first()

       # User 조회는 Shared User DB에서
       owner = user_db.query(User).filter(User.id == project.user_id).first()

       return {**project.dict(), "owner": owner}
   ```

#### Step 4: 테스트 및 검증 (Week 3)

**Tasks**:
1. ✅ 양쪽 서비스에서 동일 사용자로 로그인 테스트
   - Platform에서 로그인 → JWT 토큰 발급
   - Labeler에서 동일 이메일/비밀번호로 로그인 → 동일한 user_id 확인
   - 양쪽 서비스에서 토큰 검증 및 사용자 정보 조회

2. ✅ 데이터 일관성 검증
   - Platform에서 사용자 정보 수정 → Labeler에서 즉시 반영 확인
   - Labeler에서 사용자 생성 → Platform에서 조회 가능 확인

3. ✅ 권한 확인 테스트
   - Platform에서 role 변경 → Labeler에서 권한 확인
   - 동일한 JWT secret 사용 여부 검증

---

## Phase 11.2: Dataset Service Migration to Labeler

### 현재 상태

- ✅ **Labeler Backend**: Dataset DB 구축 완료
- ✅ **데이터셋 CRUD**: Labeler에서 관리
- ❌ **Platform Backend**: 아직 자체 Dataset 모델 사용 중

### 목표 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    Labeler Backend                           │
│  - PostgreSQL (datasets, dataset_versions, labels)          │
│  - Dataset CRUD API                                          │
│  - 데이터셋 업로드/다운로드                                    │
│  - 권한 관리 (소유자, 공유 멤버)                               │
└─────────────────────────────────────────────────────────────┘
              ▲
              │ HTTP API
              │
┌─────────────┴──────────────────────────────────────────────┐
│                  Platform Backend                           │
│  - Labeler Dataset API 호출                                 │
│  - 학습 작업 생성 시 데이터셋 권한 확인                        │
│  - 데이터셋 목록 조회 (프록시)                                │
└───────────────────────────────────────────────────────────┘
```

### Labeler Dataset API Specification

**Base URL**: `http://labeler-backend:8020/api/v1`

#### Dataset Management
```http
GET /datasets
Authorization: Bearer {token}

Query Parameters:
  - owner_id: int (optional) - 소유자 필터
  - shared_with_me: bool (optional) - 공유받은 데이터셋 포함
  - task_type: str (optional) - 작업 타입 필터

Response 200 OK:
[
  {
    "id": "dataset-123",
    "name": "COCO 2017 Training",
    "owner_id": 1,
    "format": "coco",
    "num_images": 118287,
    "num_labels": 80,
    "created_at": "2025-01-01T00:00:00Z",
    "updated_at": "2025-01-15T10:30:00Z",
    "storage_path": "s3://datasets/coco-2017-train",
    "version": "v1.0"
  }
]
```

```http
GET /datasets/{dataset_id}
Authorization: Bearer {token}

Response 200 OK:
{
  "id": "dataset-123",
  "name": "COCO 2017 Training",
  "description": "COCO dataset for object detection",
  "owner_id": 1,
  "format": "coco",
  "num_images": 118287,
  "num_labels": 80,
  "labels": ["person", "car", "dog", ...],
  "storage_path": "s3://datasets/coco-2017-train",
  "shared_with": [2, 5, 10],  # user_ids
  "permissions": {
    "can_read": true,
    "can_write": false,
    "can_delete": false
  }
}
```

#### Permission Check
```http
POST /datasets/{dataset_id}/check-permission
Authorization: Bearer {token}
Content-Type: application/json

{
  "user_id": 5,
  "permission": "read"  // read, write, delete
}

Response 200 OK:
{
  "dataset_id": "dataset-123",
  "user_id": 5,
  "permission": "read",
  "granted": true
}

Response 403 Forbidden:
{
  "detail": "Permission denied"
}
```

#### Dataset Upload
```http
POST /datasets
Authorization: Bearer {token}
Content-Type: multipart/form-data

{
  "name": "My Dataset",
  "format": "yolo",
  "files": [files...]
}

Response 201 Created:
{
  "id": "dataset-456",
  "name": "My Dataset",
  "upload_status": "processing",
  "upload_progress": 0
}
```

### Migration Plan

#### Step 1: Platform Backend 리팩토링 (Week 4)

**Tasks**:
1. ✅ Labeler Dataset Service Client 구현
   ```python
   # platform/backend/app/services/labeler_client.py
   class LabelerClient:
       def __init__(self, base_url: str):
           self.base_url = base_url
           self.session = httpx.AsyncClient(timeout=30.0)

       async def get_datasets(
           self,
           token: str,
           owner_id: Optional[int] = None,
           shared_with_me: bool = False
       ) -> List[dict]:
           params = {}
           if owner_id:
               params["owner_id"] = owner_id
           if shared_with_me:
               params["shared_with_me"] = "true"

           response = await self.session.get(
               f"{self.base_url}/datasets",
               headers={"Authorization": f"Bearer {token}"},
               params=params
           )
           response.raise_for_status()
           return response.json()

       async def get_dataset(self, dataset_id: str, token: str) -> dict:
           response = await self.session.get(
               f"{self.base_url}/datasets/{dataset_id}",
               headers={"Authorization": f"Bearer {token}"}
           )
           response.raise_for_status()
           return response.json()

       async def check_permission(
           self,
           dataset_id: str,
           user_id: int,
           permission: str,  # "read", "write", "delete"
           token: str
       ) -> bool:
           response = await self.session.post(
               f"{self.base_url}/datasets/{dataset_id}/check-permission",
               headers={"Authorization": f"Bearer {token}"},
               json={"user_id": user_id, "permission": permission}
           )
           if response.status_code == 403:
               return False
           response.raise_for_status()
           return response.json().get("granted", False)
   ```

2. ✅ Dataset API 엔드포인트를 프록시로 변경
   ```python
   # platform/backend/app/api/datasets.py
   from app.services.labeler_client import LabelerClient

   labeler = LabelerClient(settings.LABELER_SERVICE_URL)

   @router.get("/datasets")
   async def list_datasets(
       token: str = Depends(oauth2_scheme),
       current_user: dict = Depends(get_current_user)
   ):
       """Labeler Backend에서 데이터셋 목록 가져오기"""
       datasets = await labeler.get_datasets(
           token=token,
           owner_id=current_user["id"],
           shared_with_me=True
       )
       return datasets

   @router.get("/datasets/{dataset_id}")
   async def get_dataset(
       dataset_id: str,
       token: str = Depends(oauth2_scheme),
       current_user: dict = Depends(get_current_user)
   ):
       """Labeler Backend에서 데이터셋 상세 정보 가져오기"""
       dataset = await labeler.get_dataset(dataset_id, token)
       return dataset
   ```

3. ✅ Training Job 생성 시 권한 확인
   ```python
   # platform/backend/app/api/training.py
   @router.post("/training-jobs")
   async def create_training_job(
       job_data: TrainingJobCreate,
       db: Session = Depends(get_db),
       current_user: dict = Depends(get_current_user),
       token: str = Depends(oauth2_scheme)
   ):
       # 데이터셋 권한 확인
       has_permission = await labeler.check_permission(
           dataset_id=job_data.dataset_id,
           user_id=current_user["id"],
           permission="read",
           token=token
       )

       if not has_permission:
           raise HTTPException(
               status_code=403,
               detail="You don't have permission to use this dataset"
           )

       # 학습 작업 생성
       training_job = TrainingJob(
           dataset_id=job_data.dataset_id,  # Labeler의 dataset ID
           created_by=current_user["id"],
           model_name=job_data.model_name,
           # ...
       )
       db.add(training_job)
       db.commit()
       return training_job
   ```

#### Step 2: Database Schema 변경 (Week 4)

**Tasks**:
1. ✅ Platform DB에서 datasets 테이블 제거
   ```sql
   -- Alembic migration
   def upgrade():
       # 의존 테이블 Foreign key 제거
       op.drop_constraint('training_jobs_dataset_id_fkey', 'training_jobs')

       # dataset 관련 테이블 제거
       op.drop_table('dataset_snapshots')
       op.drop_table('datasets')
   ```

2. ✅ TrainingJob 모델 수정
   ```python
   # platform/backend/app/db/models.py
   class TrainingJob(Base):
       __tablename__ = "training_jobs"

       id = Column(Integer, primary_key=True)
       dataset_id = Column(String(100), nullable=False, index=True)  # Labeler dataset ID
       created_by = Column(Integer, nullable=False, index=True)  # User Service user ID

       # Relationship 제거
       # dataset = relationship("Dataset")
       # creator = relationship("User")
   ```

#### Step 3: Frontend 업데이트 (Week 5)

**Tasks**:
1. ✅ Dataset API 호출 경로 변경 (필요 시)
   - Platform API가 프록시 역할을 하므로 Frontend는 변경 불필요
   - 단, 직접 Labeler에 업로드하는 경우 경로 변경 필요

2. ✅ 데이터셋 권한 UI 업데이트
   - 공유받은 데이터셋 표시
   - 권한 수준 표시 (읽기 전용, 편집 가능 등)

---

## Phase 11.3: API Gateway & Service Mesh (Optional)

### 목표

여러 마이크로서비스 간 통신을 효율적으로 관리하기 위해 API Gateway 도입 고려.

### 아키텍처

```
┌────────────────────────────────────────────────┐
│              API Gateway (Kong)                 │
│  - Authentication (JWT)                         │
│  - Rate Limiting                                │
│  - Routing                                      │
└────────────────────────────────────────────────┘
         │              │              │
    ┌────┴───┐    ┌────┴───┐    ┌────┴────┐
    │ User   │    │Platform│    │ Labeler │
    │Service │    │Backend │    │ Backend │
    └────────┘    └────────┘    └─────────┘
```

### Kong Gateway 설정 예시

```yaml
# kong.yml
services:
  - name: user-service
    url: http://user-service:8010
    routes:
      - name: user-routes
        paths:
          - /api/v1/users
          - /api/v1/auth
    plugins:
      - name: jwt
      - name: rate-limiting
        config:
          minute: 100

  - name: platform-backend
    url: http://platform-backend:8000
    routes:
      - name: platform-routes
        paths:
          - /api/v1/projects
          - /api/v1/training
    plugins:
      - name: jwt

  - name: labeler-backend
    url: http://labeler-backend:8020
    routes:
      - name: labeler-routes
        paths:
          - /api/v1/datasets
          - /api/v1/annotations
    plugins:
      - name: jwt
```

---

## Testing Strategy

### Unit Tests
- User Service Client 단위 테스트
- Labeler Client 단위 테스트
- Mock API 응답으로 테스트

### Integration Tests
```python
# tests/integration/test_user_service_integration.py
import pytest
from app.services.user_service_client import UserServiceClient

@pytest.mark.asyncio
async def test_user_authentication_flow():
    # 1. User Service 로그인
    client = UserServiceClient("http://user-service:8010")
    login_response = await client.login("user@example.com", "password")
    assert login_response["access_token"]

    token = login_response["access_token"]

    # 2. Platform에서 토큰 검증
    verify_response = await client.verify_token(token)
    assert verify_response["valid"] is True
    assert verify_response["user_id"] == 1

    # 3. 사용자 정보 조회
    user = await client.get_user(1, token)
    assert user["email"] == "user@example.com"


@pytest.mark.asyncio
async def test_dataset_permission_flow():
    # 1. Labeler에서 데이터셋 조회
    labeler = LabelerClient("http://labeler-backend:8020")
    datasets = await labeler.get_datasets(token, owner_id=1)
    assert len(datasets) > 0

    dataset_id = datasets[0]["id"]

    # 2. 권한 확인
    has_permission = await labeler.check_permission(
        dataset_id, user_id=1, permission="read", token=token
    )
    assert has_permission is True

    # 3. Platform에서 학습 작업 생성 (권한 확인 자동)
    # ... training job creation test
```

### E2E Tests
- Frontend → Platform → User Service 전체 플로우
- Frontend → Platform → Labeler 데이터셋 조회 플로우
- 학습 작업 생성 시 권한 확인 플로우

---

## Rollback Plan

### Phase 11.1 Rollback
1. Platform과 Labeler Backend를 이전 버전으로 롤백
2. Shared User DB 데이터를 Platform DB로 역이전
   ```bash
   pg_dump -h user-db -U admin users > users_rollback.sql
   psql -h platform-db -U admin platform < users_rollback.sql
   ```
3. 환경 변수에서 USER_DATABASE_URL 제거
4. Platform과 Labeler에서 단일 DB 연결로 복구

### Phase 11.2 Rollback
1. Platform의 Dataset 프록시 API 비활성화
2. Platform DB에 datasets 테이블 복원
3. Labeler DB 데이터를 Platform DB로 복사
4. Frontend를 이전 버전으로 롤백

---

## Timeline (3-Tier Strategy)

### Tier 1: Local Development (1 week)

| Day | Task | Description |
|-----|------|-------------|
| Day 1 | SQLite User DB 생성 | Platform DB에서 User 데이터 export → `/tmp/shared_users.db` 생성 |
| Day 2-3 | Platform Backend 수정 | 2-DB 연결 구현 (`get_db()` + `get_user_db()`) |
| Day 3-4 | Labeler Backend 구현 | User 모델, 인증 로직, DB 연결 추가 |
| Day 4-5 | 테스트 & 버그 수정 | 로컬에서 Platform + Labeler 동시 실행 테스트 |

**Milestone**: 로컬 개발 환경에서 User DB 분리 완료

### Tier 2: Railway Production (1-2 weeks)

| Day | Task | Description |
|-----|------|-------------|
| Day 1 | Railway PostgreSQL 생성 | Railway Dashboard에서 User DB 생성 |
| Day 1 | 데이터 마이그레이션 | SQLite → Railway PostgreSQL 마이그레이션 |
| Day 2 | 환경 변수 업데이트 | USER_DATABASE_URL을 Railway URL로 변경 |
| Day 2-3 | Railway 배포 | Labeler Railway 환경 변수 추가, 재시작 |
| Day 3-4 | 테스트 & 성능 측정 | 레이턴시, 동시성 테스트 |
| Day 5-7 | 안정화 | 1주일 모니터링, 버그 수정 |

**Milestone**: Railway에서 Platform + Labeler 상시 가동

### Tier 3: On-Prem K8s (1-2 weeks)

| Day | Task | Description |
|-----|------|-------------|
| Day 1 | K8s User DB StatefulSet 배포 | PostgreSQL StatefulSet + PVC 생성 |
| Day 1-2 | 데이터 마이그레이션 | Railway → K8s PostgreSQL 마이그레이션 |
| Day 2 | ConfigMap/Secret 설정 | K8s 환경 변수 설정 |
| Day 3 | Backend Deployment 업데이트 | Platform & Labeler K8s 배포 |
| Day 3-4 | 테스트 | K8s 내부 및 외부 접근 테스트 |
| Day 5-7 | 고가용성 설정 | Backup, Restore 절차 확립 |

**Milestone**: 완전한 on-prem K8s 운영

### Phase 11.2: Dataset Service Migration (2-3 weeks)

Tier 2 안정화 이후 진행:

| Week | Task | Description |
|------|------|-------------|
| Week 1 | Labeler API 문서화 | Dataset API 스펙 확정 |
| Week 1-2 | Platform Labeler Client | LabelerClient 구현, 프록시 API |
| Week 2 | DB 마이그레이션 | Platform DB에서 datasets 제거 |
| Week 3 | Frontend 업데이트 | 데이터셋 권한 UI |

**Total Duration**: 4-6 weeks (3-tier 단계별 접근)

---

## Success Criteria

### Phase 11.1 Success (Shared User DB)
- ✅ Shared User DB에서 users, organizations 테이블 정상 작동
- ✅ Platform과 Labeler 양쪽에서 동일 User 모델 사용
- ✅ 동일한 JWT secret으로 토큰 발급/검증 성공
- ✅ Platform에서 로그인 → Labeler에서 토큰 사용 가능
- ✅ Labeler에서 로그인 → Platform에서 토큰 사용 가능
- ✅ 사용자 정보 수정 시 양쪽 서비스에 즉시 반영
- ✅ Platform DB에 users 테이블 없음 (Shared DB로 분리)
- ✅ 모든 E2E 테스트 통과

### Phase 11.2 Success
- ✅ Platform에서 Labeler Dataset API 호출 성공
- ✅ 학습 작업 생성 시 데이터셋 권한 확인 성공
- ✅ 데이터셋 목록 조회 시 Labeler에서 데이터 가져옴
- ✅ Platform DB에 datasets 테이블 없음
- ✅ 모든 E2E 테스트 통과

---

## References

- [Microservices Architecture Patterns](https://microservices.io/patterns/index.html)
- [API Gateway Pattern](https://microservices.io/patterns/apigateway.html)
- [FastAPI Best Practices](https://fastapi.tiangolo.com/tutorial/)
- [Kong API Gateway](https://konghq.com/products/kong-gateway)
