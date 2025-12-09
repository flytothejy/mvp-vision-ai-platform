# Platform Infrastructure

Vision AI Training Platform의 개발 환경 인프라 구성.

이 디렉토리는 두 가지 인프라 설정 방법을 제공합니다:
1. **Docker Compose** (권장): 빠른 로컬 개발을 위한 간단한 설정
2. **Kubernetes (Kind)**: 프로덕션과 유사한 환경 테스트

---

## Option 1: Docker Compose (권장)

### 개요

Docker Compose를 사용한 빠르고 간단한 로컬 개발 환경입니다.

**장점:**
- ✅ 빠른 시작 (~30초)
- ✅ 낮은 리소스 사용 (~1.5GB RAM)
- ✅ 간단한 설정 및 관리
- ✅ Windows/Mac/Linux 모두 지원

**서비스 구성:**
- PostgreSQL (Platform DB, User DB)
- Redis (Cache, WebSocket State)
- Temporal (Workflow Orchestration)
- MinIO (Object Storage)
- ClearML, MLflow, Grafana (선택적)

### Quick Start

#### Windows

```powershell
# Core 서비스만 시작
.\start-infra.ps1

# Observability 포함 시작
.\start-infra.ps1 -WithObservability

# 정지
.\start-infra.ps1 -Stop
```

#### Linux/Mac

```bash
# 실행 권한 부여 (최초 1회)
chmod +x start-infra.sh

# Core 서비스만 시작
./start-infra.sh

# Observability 포함 시작
./start-infra.sh --with-obs

# 정지
./start-infra.sh --stop
```

### 서비스 구성

#### Core Services (필수)

| Service | Port | Description |
|---------|------|-------------|
| PostgreSQL | 5432 | 통합 DB (platform, users, labeler) |
| Redis | 6379 | 캐시 & Pub/Sub |
| Temporal | 7233, 8233 | 워크플로우 오케스트레이션 |
| MinIO (Datasets) | 9000, 9001 | 데이터셋 저장소 |
| MinIO (Results) | 9002, 9003 | 결과물 저장소 |

#### Observability Services (선택적)

| Service | Port | Description |
|---------|------|-------------|
| ClearML API | 8008 | 실험 추적 API |
| ClearML Web UI | 8080 | 웹 인터페이스 |
| MLflow | 5000 | 대안 실험 추적 |
| Grafana | 3200 | 시각화 |

### 접속 정보

- **Temporal UI**: http://localhost:8233
- **MinIO Console (Datasets)**: http://localhost:9001 (minioadmin/minioadmin)
- **MinIO Console (Results)**: http://localhost:9003 (minioadmin/minioadmin)
- **ClearML Web UI**: http://localhost:8080
- **MLflow**: http://localhost:5000
- **Grafana**: http://localhost:3200 (admin/admin)

### 수동 관리

```bash
# Core 서비스만
docker-compose up -d

# Observability 포함
docker-compose -f docker-compose.yml -f docker-compose.observability.yml up -d

# 정지
docker-compose down

# 정지 및 데이터 삭제 (주의!)
docker-compose down -v
```

### 트러블슈팅

```bash
# 로그 확인
docker-compose logs -f [service-name]

# 서비스 재시작
docker-compose restart [service-name]

# 상태 확인
docker-compose ps
```

**자세한 문서**: Docker Compose 사용법, 트러블슈팅, 데이터 관리 등은 파일 맨 아래 [Docker Compose 상세 가이드](#docker-compose-상세-가이드) 섹션을 참고하세요.

---

## Option 2: Kubernetes (Kind)

### 개요

프로덕션과 유사한 Kubernetes 환경 테스트를 위한 설정입니다.

**장점:**
- ✅ 프로덕션 환경과 동일한 구조
- ✅ Helm Charts 기반 배포
- ✅ 프로덕션 이전 테스트 가능

**단점:**
- ❌ 높은 리소스 사용 (~3GB RAM)
- ❌ 복잡한 설정
- ❌ 느린 시작 (~2분)

## 아키텍처

**3-Tier 개발 전략:**
- **Tier 1 (Current)**: Kind 클러스터 (모든 인프라) + 로컬 서버 (Backend, Frontend, Training subprocess)
- **Tier 2**: Kind 클러스터 (모든 인프라 + Training as K8s Job)
- **Tier 3**: Production Kubernetes (모든 서비스)

## 기술 스택

### Kubernetes 환경
- **Kind**: Local Kubernetes cluster
- **Helm**: Package manager for Kubernetes

### 인프라 서비스 (Helm Charts)
- **PostgreSQL** (bitnami/postgresql): 주 데이터베이스
- **Redis** (bitnami/redis): 캐시 및 메시지 큐
- **MinIO** (minio/minio): S3-compatible 객체 스토리지
- **kube-prometheus-stack**: Prometheus + Grafana + AlertManager
- **Loki** (grafana/loki): 로그 수집
- **Temporal** (temporalio/temporal): Workflow 오케스트레이션

## 디렉토리 구조

```
platform/infrastructure/
├── README.md                           # 이 파일
├── kind-config.yaml                    # Kind cluster 설정
├── scripts/
│   ├── setup-kind-cluster.ps1          # Kind cluster 생성
│   ├── create-namespaces.ps1           # Namespace 생성
│   ├── cleanup-raw-manifests.ps1       # 기존 배포 제거
│   └── deploy-helm-all.ps1             # Helm 전체 배포
├── helm/
│   ├── postgres-values.yaml            # PostgreSQL Helm values
│   ├── redis-values.yaml               # Redis Helm values
│   ├── minio-values.yaml               # MinIO Helm values
│   ├── kube-prometheus-stack-values.yaml  # Observability Helm values
│   └── temporal-values.yaml            # Temporal Helm values
└── k8s/
    ├── platform/
    │   ├── nodeports.yaml              # Platform NodePort services
    │   ├── backend-config.yaml         # Backend ConfigMap
    │   ├── backend-secrets.yaml        # Backend Secrets
    │   ├── backend.yaml                # Backend Deployment (for future)
    │   └── frontend.yaml               # Frontend Deployment (for future)
    ├── observability/
    │   └── nodeports.yaml              # Observability NodePort services
    └── temporal/
        └── nodeports.yaml              # Temporal NodePort services
```

## 빠른 시작

### 1. 사전 요구사항

```powershell
# Docker Desktop 실행 (필수)

# Kind 설치
winget install Kubernetes.kind

# kubectl 설치
winget install Kubernetes.kubectl

# Helm 설치
winget install Helm.Helm
```

### 2. Kind 클러스터 생성

```powershell
cd platform/infrastructure
.\scripts\setup-kind-cluster.ps1
```

### 3. Namespace 생성

```powershell
.\scripts\create-namespaces.ps1
```

### 4. (기존 배포 제거 - 필요시)

```powershell
.\scripts\cleanup-raw-manifests.ps1
```

### 5. Helm으로 모든 서비스 배포

**⚠️ 새 PowerShell 터미널에서 실행 (Helm PATH 적용 후):**

```powershell
cd platform/infrastructure
.\scripts\deploy-helm-all.ps1
```

## 수동 배포 (단계별)

Helm repo 추가:
```powershell
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add temporalio https://go.temporal.io/helm-charts
helm repo add minio https://charts.min.io/
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

각 서비스 배포:
```powershell
# PostgreSQL
helm upgrade --install postgresql bitnami/postgresql `
  --namespace platform --create-namespace `
  --values helm/postgres-values.yaml --wait

# Redis
helm upgrade --install redis bitnami/redis `
  --namespace platform `
  --values helm/redis-values.yaml --wait

# MinIO
helm upgrade --install minio minio/minio `
  --namespace platform `
  --values helm/minio-values.yaml --wait

# kube-prometheus-stack
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack `
  --namespace observability --create-namespace `
  --values helm/kube-prometheus-stack-values.yaml --wait --timeout 10m

# Loki
helm upgrade --install loki grafana/loki `
  --namespace observability `
  --set loki.auth_enabled=false `
  --set loki.commonConfig.replication_factor=1 `
  --set singleBinary.replicas=1 --wait

# Temporal
helm upgrade --install temporal temporalio/temporal `
  --namespace temporal --create-namespace `
  --values helm/temporal-values.yaml --wait --timeout 10m

# NodePort Services
kubectl apply -f k8s/platform/nodeports.yaml
kubectl apply -f k8s/observability/nodeports.yaml
kubectl apply -f k8s/temporal/nodeports.yaml
```

## 접속 정보

### 인프라 서비스

| 서비스 | 내부 DNS | 외부 접속 | 인증 |
|--------|---------|----------|------|
| **PostgreSQL** | `postgresql.platform:5432` | `localhost:30543` | admin / devpass |
| **Redis** | `redis-master.platform:6379` | `localhost:30679` | (인증 없음) |
| **MinIO API** | `minio.platform:9000` | `http://localhost:30900` | minioadmin / minioadmin |
| **MinIO Console** | `minio.platform:9001` | `http://localhost:30901` | minioadmin / minioadmin |

### 모니터링

| 서비스 | 내부 DNS | 외부 접속 | 인증 |
|--------|---------|----------|------|
| **Prometheus** | `prometheus-operated.observability:9090` | `http://localhost:30090` | (없음) |
| **Grafana** | `kube-prometheus-stack-grafana.observability:80` | `http://localhost:30030` | admin / prom-operator |
| **Loki** | `loki.observability:3100` | `http://localhost:30100` | (없음) |

### 오케스트레이션

| 서비스 | 내부 DNS | 외부 접속 | 인증 |
|--------|---------|----------|------|
| **Temporal gRPC** | `temporal-frontend.temporal:7233` | `localhost:30700` | (없음) |
| **Temporal UI** | `temporal-web.temporal:8080` | `http://localhost:30233` | (없음) |

## Helm 관리

### 배포 상태 확인

```powershell
# 모든 Helm releases 확인
helm list --all-namespaces

# 특정 namespace의 releases
helm list -n platform
helm list -n observability
helm list -n temporal
```

### 서비스 업그레이드

```powershell
# values 파일 수정 후
helm upgrade postgresql bitnami/postgresql `
  -n platform `
  --values helm/postgres-values.yaml

# 또는 특정 값만 override
helm upgrade postgresql bitnami/postgresql `
  -n platform `
  --reuse-values `
  --set auth.password=newpassword
```

### 서비스 제거

```powershell
# 특정 release 제거
helm uninstall postgresql -n platform

# 모든 platform services 제거
helm uninstall postgresql redis minio -n platform
helm uninstall kube-prometheus-stack loki -n observability
helm uninstall temporal -n temporal
```

### 트러블슈팅

```powershell
# Release 상태 확인
helm status postgresql -n platform

# Release history
helm history postgresql -n platform

# 이전 버전으로 rollback
helm rollback postgresql 1 -n platform

# Values 확인 (실제 적용된 값)
helm get values postgresql -n platform

# Manifest 확인 (실제 배포된 YAML)
helm get manifest postgresql -n platform
```

## 로컬 개발 워크플로우

1. **Kind 클러스터**: 인프라만 실행
2. **로컬 터미널**: Backend, Frontend 실행
   ```powershell
   # Terminal 1: Backend
   cd platform/backend
   venv\Scripts\activate
   uvicorn app.main:app --reload --port 8000

   # Terminal 2: Frontend
   cd platform/frontend
   npm run dev
   ```

3. **Training**: Subprocess 방식으로 host에서 실행

## 업그레이드 경로

### Tier 1 → Tier 2
- Backend, Frontend를 Docker image로 빌드
- Kind 클러스터에 Deployment 추가
- Training을 K8s Job으로 변경

### Tier 2 → Tier 3
- Production Kubernetes 클러스터로 동일한 Helm charts 배포
- Secrets을 Kubernetes Secrets 또는 Vault로 관리
- Ingress, SSL/TLS 설정
- HA (High Availability) 설정

## 참고 자료

- [Kind Documentation](https://kind.sigs.k8s.io/)
- [Helm Documentation](https://helm.sh/docs/)
- [Bitnami Charts](https://github.com/bitnami/charts)
- [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
- [Temporal Helm Charts](https://github.com/temporalio/helm-charts)

## License

Copyright © 2025 Vision AI Platform Team


---

## Docker Compose 상세 가이드

### 파일 구조

```
platform/infrastructure/
├── docker-compose.yml                 # Core services (필수)
├── docker-compose.observability.yml   # Observability services (선택적)
├── start-infra.ps1                   # Windows 시작 스크립트
├── start-infra.sh                    # Linux/Mac 시작 스크립트
└── temporal/
    └── dynamicconfig/
        └── development.yaml          # Temporal 설정
```

### 서비스 상세

#### PostgreSQL (Unified Instance)

```yaml
Port: 5432
User: admin
Password: devpass
Databases:
  - platform  # Platform metadata
  - users     # User authentication (shared)
  - labeler   # Dataset annotations (Labeler team)
```

**아키텍처**: 하나의 PostgreSQL 인스턴스에 3개의 독립적인 데이터베이스
- **리소스 효율성**: PostgreSQL 프로세스 1개 (기존 대비 ~66% 메모리 절감)
- **관리 간소화**: 단일 컨테이너, 단일 백업/복원
- **논리적 격리**: 데이터베이스 간 직접 쿼리 불가

**데이터베이스별 용도**:
1. **platform**: Platform 팀 관리 - training jobs, experiments, metrics, export jobs
2. **users**: Platform 팀 관리 - user authentication, organizations (Labeler와 공유)
3. **labeler**: Labeler 팀 관리 - datasets, annotations (스키마 독립 관리)

**접속 테스트**:
```bash
# Platform database
docker exec -it platform-postgres psql -U admin -d platform

# Users database
docker exec -it platform-postgres psql -U admin -d users

# Labeler database
docker exec -it platform-postgres psql -U admin -d labeler

# List all databases
docker exec -it platform-postgres psql -U admin -c "\l"
```

**자세한 내용**: [DATABASE_MANAGEMENT.md](../../docs/infrastructure/DATABASE_MANAGEMENT.md)

#### Redis

```yaml
Port: 6379
Password: (없음)
```

**용도**: Session store, Pub/Sub, WebSocket state, Caching

**접속 테스트**:
```bash
docker exec -it platform-redis redis-cli ping
# 출력: PONG
```

#### Temporal

```yaml
gRPC Port: 7233
Web UI Port: 8233
```

**용도**: 워크플로우 오케스트레이션, 학습 라이프사이클 관리

**Web UI**: http://localhost:8233

#### MinIO (Datasets)

```yaml
API Port: 9000
Console Port: 9001
Access Key: minioadmin
Secret Key: minioadmin
```

**용도**: 학습 데이터셋, 사용자 업로드

**Buckets**:
- `training-datasets`

#### MinIO (Results)

```yaml
API Port: 9002
Console Port: 9003
Access Key: minioadmin
Secret Key: minioadmin
```

**용도**: 체크포인트, 가중치, config schemas

**Buckets**:
- `model-weights`
- `training-checkpoints`
- `config-schemas`
- `training-results`

### Observability Services

#### ClearML

**Services**:
- API Server: 8008
- Web UI: 8080
- File Server: 8081

**Dependencies** (자동 시작):
- Elasticsearch: 9200
- MongoDB: 27018
- Redis: 6380

**용도**: 실험 추적, 모델 레지스트리

**Web UI**: http://localhost:8080

#### MLflow

```yaml
Port: 5000
Backend Store: PostgreSQL (platform DB)
Artifact Root: MinIO (s3://mlflow-artifacts)
```

**용도**: 대안 실험 추적 도구

#### Loki & Grafana

**Loki**:
- Port: 3100
- 용도: 로그 수집

**Grafana**:
- Port: 3200
- Login: admin/admin
- 용도: 로그 & 메트릭 시각화

### 환경 변수 설정

Backend `.env` 파일에서 서비스 연결 정보 설정:

```bash
# Database (single PostgreSQL instance, multiple databases)
DATABASE_URL=postgresql://admin:devpass@localhost:5432/platform
USER_DATABASE_URL=postgresql://admin:devpass@localhost:5432/users

# Redis
REDIS_URL=redis://localhost:6379/0

# Temporal
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=default

# MinIO
EXTERNAL_STORAGE_ENDPOINT=http://localhost:9000
EXTERNAL_STORAGE_ACCESS_KEY=minioadmin
EXTERNAL_STORAGE_SECRET_KEY=minioadmin

INTERNAL_STORAGE_ENDPOINT=http://localhost:9002
INTERNAL_STORAGE_ACCESS_KEY=minioadmin
INTERNAL_STORAGE_SECRET_KEY=minioadmin

# Observability (선택)
OBSERVABILITY_BACKENDS=database  # 또는 clearml,database

CLEARML_API_HOST=http://localhost:8008
CLEARML_WEB_HOST=http://localhost:8080
CLEARML_FILES_HOST=http://localhost:8081

MLFLOW_TRACKING_URI=http://localhost:5000
```

### 데이터 관리

#### 백업

```bash
# PostgreSQL 백업
docker exec platform-postgres pg_dump -U admin platform > backup_$(date +%Y%m%d).sql

# 복구
docker exec -i platform-postgres psql -U admin platform < backup_20250105.sql

# MinIO 백업 (mc 도구 필요)
mc alias set myminio http://localhost:9000 minioadmin minioadmin
mc mirror myminio/training-datasets ./backup/datasets
```

#### 데이터 초기화

```bash
# 주의: 모든 데이터가 삭제됩니다!
docker-compose down -v

# 특정 볼륨만 삭제
docker volume rm platform_postgres_platform_data
```

### 리소스 사용량

**Core Services Only**:
- 메모리: ~1.5GB
- CPU: 5-10%
- 디스크: ~500MB (데이터 제외)
- 시작 시간: ~30초

**With Observability (ClearML + MLflow)**:
- 메모리: ~4GB
- CPU: 15-25%
- 디스크: ~2GB (데이터 제외)
- 시작 시간: ~2분

### 고급 사용법

#### 특정 서비스만 시작

```bash
# ClearML만 시작
docker-compose -f docker-compose.observability.yml up -d \
  clearml-elasticsearch clearml-mongo clearml-redis \
  clearml-apiserver clearml-webserver clearml-fileserver

# MLflow만 시작
docker-compose -f docker-compose.observability.yml up -d mlflow
```

#### 로그 모니터링

```bash
# 모든 서비스 로그 (실시간)
docker-compose logs -f

# 특정 서비스 로그
docker-compose logs -f postgres

# 마지막 100줄만
docker-compose logs --tail=100 temporal
```

#### 서비스 재시작

```bash
# 모든 서비스
docker-compose restart

# 특정 서비스만
docker-compose restart postgres redis

# 설정 변경 후 재생성
docker-compose up -d --force-recreate postgres
```

### 트러블슈팅

#### 포트 충돌

다른 서비스가 포트를 사용 중인 경우 `docker-compose.yml`에서 포트 변경:

```yaml
# 예: PostgreSQL 포트 변경
ports:
  - "15432:5432"  # 5432 → 15432
```

#### 서비스 시작 실패

```bash
# 로그 확인
docker-compose logs [service-name]

# 컨테이너 상태 확인
docker-compose ps

# 헬스체크 확인
docker inspect platform-postgres | grep Health -A 10
```

#### 데이터베이스 연결 실패

```bash
# PostgreSQL 재시작
docker-compose restart postgres

# 연결 테스트
docker exec -it platform-postgres psql -U admin -d platform -c "SELECT 1;"
```

#### MinIO 버킷 없음

```bash
# 버킷 생성 컨테이너 재실행
docker-compose up -d minio-setup

# 수동 생성
docker exec -it platform-minio-datasets mc mb /data/training-datasets
```

### Production 고려사항

Docker Compose는 로컬 개발용입니다. 프로덕션 배포 시:

1. **시크릿 변경**: 모든 기본 비밀번호 변경
2. **리소스 제한**: `deploy.resources` 설정 추가
3. **영구 볼륨**: 외부 볼륨 또는 클라우드 스토리지 사용
4. **Managed Services**: PostgreSQL (RDS), Redis (ElastiCache), S3 사용 고려

