# Backend Service

FastAPI 기반의 Vision AI Training Platform 백엔드 서비스입니다.

## 🏗️ 아키텍처

### 디렉토리 구조

```
platform/backend/
├── app/
│   ├── adapters/           # Observability 어댑터 (Phase 13)
│   │   ├── base.py        # ObservabilityAdapter 베이스 클래스
│   │   ├── clearml.py     # ClearML 어댑터
│   │   ├── mlflow.py      # MLflow 어댑터
│   │   ├── wandb.py       # Weights & Biases 어댑터
│   │   └── database.py    # Database-only 어댑터
│   ├── api/               # REST API 엔드포인트
│   │   ├── chat.py        # 자연어 기반 학습 설정
│   │   ├── training.py    # 학습 작업 관리
│   │   ├── projects.py    # 프로젝트 및 세션 관리
│   │   ├── datasets.py    # 데이터셋 관리
│   │   ├── export.py      # 모델 Export 작업
│   │   └── deployments.py # 모델 배포 관리
│   ├── core/              # 핵심 비즈니스 로직
│   │   ├── llm/           # LLM 기반 자연어 파싱 (Gemini)
│   │   ├── training/      # 학습 프로세스 관리
│   │   └── websocket/     # WebSocket 연결 관리
│   ├── db/                # 데이터베이스
│   │   ├── models.py      # SQLAlchemy ORM 모델
│   │   └── session.py     # DB 세션 관리
│   ├── schemas/           # Pydantic 스키마
│   │   ├── chat.py        # Chat API 스키마
│   │   ├── training.py    # Training API 스키마
│   │   ├── export.py      # Export API 스키마
│   │   └── deployment.py  # Deployment API 스키마
│   ├── workflows/         # Temporal 워크플로우
│   │   ├── training_workflow.py  # 학습 라이프사이클 오케스트레이션
│   │   └── worker.py             # Temporal Worker
│   ├── utils/             # 유틸리티 함수
│   └── main.py            # FastAPI 애플리케이션 엔트리포인트
├── tests/                 # 테스트 코드
│   ├── unit/              # 단위 테스트
│   ├── integration/       # 통합 테스트
│   └── observability/     # Observability 테스트 (Phase 13)
├── .env.example           # 환경 변수 템플릿
├── requirements.txt       # Python 의존성
└── README.md              # 현재 파일
```

### 주요 기능

#### 1. 자연어 기반 학습 설정 (Chat API)
- **Gemini LLM** 기반 Intent 파싱
- 모델, 하이퍼파라미터, 데이터셋 자동 추출
- Multi-turn 대화 지원

#### 2. Temporal 워크플로우 오케스트레이션 (Phase 12)
- 학습 라이프사이클 자동 관리
- 에러 시 자동 재시도 (exponential backoff)
- 타임아웃 및 하트비트 모니터링
- Graceful 취소 지원

#### 3. Observability 멀티백엔드 (Phase 13)
- **Adapter Pattern** 기반 설계
- 지원 백엔드:
  - **ClearML**: 실험 추적, 모델 레지스트리
  - **MLflow**: 실험 추적, 아티팩트 관리
  - **Weights & Biases**: 클라우드 기반 추적
  - **Database**: 최소 의존성 모드 (Platform DB만 사용)
- 환경 변수로 백엔드 선택 (`OBSERVABILITY_BACKENDS`)
- 실시간 Metrics 수집 및 WebSocket 브로드캐스트

#### 4. 데이터셋 최적화 (Phase 12.9)
- **캐싱**: 이미 다운로드한 데이터셋 재사용
- **선택적 다운로드**: 필요한 subset만 다운로드
- **Job 재시작**: 실패한 학습 작업 재시작

#### 5. 모델 Export & Deployment (Phase 9-10)
- **Export Formats**: ONNX, TensorRT, TorchScript, CoreML, TFLite
- **Deployment Types**:
  - Platform Endpoint (관리형 API)
  - Edge Package (모바일/임베디드)
  - Container (Docker)
  - Direct Download
- **Inference API**: RESTful API로 추론 요청

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **Poetry** (의존성 관리)
- **Docker & Docker Compose** (인프라)

### 환경 설정

```bash
# 1. .env 파일 생성
cp .env.example .env

# 2. 필수 환경 변수 설정
# GOOGLE_API_KEY - Gemini API 키 (https://aistudio.google.com/app/apikey)
# DATABASE_URL - PostgreSQL URL
# REDIS_URL - Redis URL
# TEMPORAL_HOST - Temporal 서버 주소
```

### 인프라 시작 (Docker Compose)

```bash
cd platform/infrastructure
docker-compose up -d

# 서비스 확인:
# - PostgreSQL:  localhost:5432
# - Redis:       localhost:6379
# - Temporal:    localhost:7233
# - MinIO:       localhost:9000 (datasets), 9002 (results)
# - ClearML:     localhost:8080 (Web UI)
```

### Backend 서버 실행

```bash
cd platform/backend

# 의존성 설치
poetry install

# 또는 pip 사용
pip install -r requirements.txt

# DB 초기화 (새 환경인 경우)
python init_db.py

# 개발 서버 실행
poetry run uvicorn app.main:app --reload --port 8000

# 또는 직접 실행
uvicorn app.main:app --reload --port 8000
```

### Temporal Worker 실행

```bash
# 별도 터미널에서 실행
cd platform/backend
poetry run python -m app.workflows.worker
```

### API 문서 확인

서버 실행 후 다음 URL에서 API 문서 확인:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 📊 Observability 설정

### 1. Database-only 모드 (권장: 로컬 개발)

```bash
# .env
OBSERVABILITY_BACKENDS=database
```

**특징:**
- 외부 의존성 없음 (Platform DB만 사용)
- 빠른 시작 및 테스트
- Metrics API 및 차트 지원

### 2. ClearML 모드 (권장: 프로덕션)

```bash
# .env
OBSERVABILITY_BACKENDS=clearml,database

# ClearML 서버 (오픈소스)
CLEARML_API_HOST=http://localhost:8008
CLEARML_WEB_HOST=http://localhost:8080
CLEARML_FILES_HOST=http://localhost:8081

# 인증 (빈값: 오픈소스 서버)
CLEARML_API_ACCESS_KEY=
CLEARML_API_SECRET_KEY=
```

**특징:**
- 강력한 실험 추적 및 비교
- 모델 레지스트리 내장
- 웹 UI 제공 (http://localhost:8080)

### 3. MLflow 모드 (선택적)

```bash
# .env
OBSERVABILITY_BACKENDS=mlflow,database
MLFLOW_TRACKING_URI=http://localhost:5000
```

### 4. Weights & Biases 모드 (선택적)

```bash
# .env
OBSERVABILITY_BACKENDS=wandb,database
WANDB_API_KEY=your-wandb-api-key
WANDB_PROJECT=vision-ai-platform
```

### 5. 멀티백엔드 모드

```bash
# 동시에 여러 백엔드 사용 (쉼표로 구분)
OBSERVABILITY_BACKENDS=clearml,mlflow,wandb,database
```

## 🧪 테스트

### 단위 테스트

```bash
# 전체 테스트 실행
poetry run pytest tests/unit -v

# 특정 모듈 테스트
poetry run pytest tests/unit/test_adapters.py -v

# 커버리지 포함
poetry run pytest tests/unit --cov=app --cov-report=html
```

### 통합 테스트

```bash
# Redis 및 PostgreSQL 필요
poetry run pytest tests/integration -v
```

### Observability 테스트 (Phase 13)

```bash
# Adapter 기능 테스트
poetry run pytest tests/observability/test_adapters.py -v

# SDK 콜백 테스트
poetry run pytest tests/observability/test_sdk_callbacks.py -v
```

## 🔧 개발 가이드

### 새로운 API 엔드포인트 추가

```python
# app/api/my_feature.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db

router = APIRouter(prefix="/my-feature", tags=["MyFeature"])

@router.get("/")
def list_items(db: Session = Depends(get_db)):
    # 비즈니스 로직
    return {"items": []}

# app/main.py에 라우터 추가
app.include_router(my_feature.router)
```

### Observability Adapter 추가

```python
# app/adapters/my_backend.py
from app.adapters.base import ObservabilityAdapter

class MyBackendAdapter(ObservabilityAdapter):
    @property
    def is_available(self) -> bool:
        try:
            import my_backend
            return True
        except ImportError:
            return False

    def initialize_run(self, job_id: int, config: Dict) -> str:
        # Run 초기화 로직
        return f"run_{job_id}"

    def log_metrics(self, run_id: str, metrics: Dict, step: int):
        # Metrics 로깅 로직
        pass

# app/adapters/__init__.py에 등록
ADAPTER_REGISTRY["my_backend"] = MyBackendAdapter
```

### Temporal Workflow 추가

```python
# app/workflows/my_workflow.py
import temporalio.workflow as workflow

@workflow.defn
class MyWorkflow:
    @workflow.run
    async def run(self, input: Dict) -> Dict:
        # Workflow 로직
        result = await workflow.execute_activity(
            my_activity,
            input,
            start_to_close_timeout=timedelta(seconds=60)
        )
        return result
```

## 🐛 트러블슈팅

### 1. Temporal 연결 실패

```bash
# Temporal 서버 상태 확인
docker ps | grep temporal

# Temporal UI 접속
http://localhost:8233
```

### 2. ClearML 연결 실패

```bash
# ClearML 서버 로그 확인
docker logs clearml-apiserver

# Web UI 접속
http://localhost:8080
```

### 3. 데이터베이스 마이그레이션 오류

```bash
# DB 초기화 (개발 환경만!)
python init_db.py --reset

# 또는 Docker 볼륨 삭제
docker-compose down -v
docker-compose up -d
```

### 4. Redis 연결 오류

```bash
# Redis 서버 확인
redis-cli ping

# 출력: PONG이면 정상
```

## 📚 추가 문서

- **아키텍처 설계**: [../docs/architecture/](../docs/architecture/)
- **API 스펙**: Swagger UI 참고 (http://localhost:8000/docs)
- **Observability 가이드**: [../docs/todo/reference/PHASE_13_OBSERVABILITY_EXTENSIBILITY.md](../docs/todo/reference/PHASE_13_OBSERVABILITY_EXTENSIBILITY.md)
- **Temporal 워크플로우**: [app/workflows/training_workflow.py](app/workflows/training_workflow.py)
- **Export & Deployment**: [../trainers/ultralytics/EXPORT_GUIDE.md](../trainers/ultralytics/EXPORT_GUIDE.md)

## 🔒 보안 고려사항

### API 키 관리

```bash
# .env 파일은 절대 커밋하지 마세요!
echo ".env" >> .gitignore

# 프로덕션에서는 환경 변수 또는 시크릿 관리 도구 사용
# - Railway: Environment Variables
# - Kubernetes: Secrets
# - AWS: Secrets Manager
```

### CORS 설정

```bash
# .env
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# 프로덕션에서는 실제 도메인 사용
CORS_ORIGINS=https://your-app.com,https://www.your-app.com
```

### JWT 시크릿

```bash
# 강력한 시크릿 생성
openssl rand -hex 32

# .env에 설정
JWT_SECRET=generated-hex-string-here
SERVICE_JWT_SECRET=another-generated-hex-string-here
```

## 📈 성능 최적화

### Database Connection Pooling

```python
# app/db/session.py에서 설정
engine = create_engine(
    DATABASE_URL,
    pool_size=20,          # 최대 연결 수
    max_overflow=10,       # 추가 연결 허용
    pool_pre_ping=True,    # 연결 유효성 확인
)
```

### Redis Caching

```python
# app/core/cache.py
from redis import Redis

redis_client = Redis.from_url(REDIS_URL)

# 캐싱 예시
def get_model_list():
    cached = redis_client.get("model_list")
    if cached:
        return json.loads(cached)

    models = fetch_models_from_trainer()
    redis_client.setex("model_list", 3600, json.dumps(models))
    return models
```

## 🤝 기여하기

1. Feature branch 생성 (`git checkout -b feature/amazing-feature`)
2. 변경사항 커밋 (`git commit -m 'feat: add amazing feature'`)
3. Branch push (`git push origin feature/amazing-feature`)
4. Pull Request 생성

**코드 스타일:**
- Black formatter 사용
- Type hints 작성
- Docstring 추가 (Google style)

**테스트 필수:**
- 단위 테스트 작성
- 통합 테스트 추가 (API 엔드포인트)
- Coverage 80% 이상 유지

---

**Last Updated**: 2025-12-05
**Maintainer**: Vision AI Platform Team
