# Phase 13: Observability Extensibility (관측성 확장성)

**목표**: 사용자가 원하는 관측 도구를 선택적으로 사용할 수 있는 확장 가능한 관측성 시스템 구축

**브랜치**: `feature/phase-13-observability-extensibility`

**예상 기간**: 5일 (Day 1-5)

---

## 배경 및 필요성

### 현재 상태
- ✅ Trainer → SDK → Backend callback 동작 중
- ✅ Backend → DB 저장 중 (TrainingMetric 테이블)
- ✅ WebSocketManager 이미 구현됨
- ✅ ClearML 통합 (hardcoded)
- ❌ 사용자가 도구 선택 불가
- ❌ 프론트엔드 WebSocket 클라이언트 미구현 (현재 polling 여부 확인 필요)

### 문제점
1. **Vendor Lock-in**: ClearML로 hardcoded되어 있어 다른 도구 사용 불가
2. **확장성 부족**: MLflow, TensorBoard 등 다른 도구 추가 시 코드 수정 필요
3. **실시간 업데이트 미흡**: 프론트엔드에서 polling 방식 사용 (확인 필요)

### 해결 방안
1. 🔌 **Adapter Pattern**: 다양한 관측 도구를 플러그인 방식으로 지원
2. ⚙️ **환경 변수 설정**: 사용자가 원하는 도구 선택 가능
3. 📊 **Multiple Backend**: DB (기본) + 선택적 외부 도구 (ClearML/MLflow/TensorBoard 등)
4. 🔄 **WebSocket 실시간 업데이트**: Polling 대신 WebSocket으로 프론트엔드 실시간 차트 업데이트

---

## Architecture Design

### Data Flow
```
Trainer (train.py)
    ↓ HTTP Callback
Backend (TrainingCallbackService)
    ↓ ObservabilityManager
    ├─> DatabaseAdapter (always enabled)
    ├─> ClearMLAdapter (optional)
    ├─> MLflowAdapter (optional)
    └─> TensorBoardAdapter (optional)

    ↓ WebSocket broadcast
Frontend (useTrainingWebSocket hook)
    ↓ Real-time chart update
```

### Component Hierarchy
```
ObservabilityManager
├── adapters: Dict[str, ObservabilityAdapter]
│   ├── "database": DatabaseAdapter
│   ├── "clearml": ClearMLAdapter
│   ├── "mlflow": MLflowAdapter
│   └── "tensorboard": TensorBoardAdapter
└── experiment_ids: Dict[str, str]
    ├── "database": "123" (job_id)
    ├── "clearml": "abc-def-ghi" (task_id)
    └── "mlflow": "run_xyz" (run_id)
```

---

## Detailed Implementation Plan

### 13.1 Observability Adapter Pattern (Day 1-2)

#### 13.1.1 ObservabilityAdapter Base Class

**파일**: `platform/backend/app/services/observability/base.py`

**인터페이스 정의**:
```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class ObservabilityAdapter(ABC):
    """Base class for observability backends"""

    @abstractmethod
    def initialize(self, config: Dict[str, Any]) -> None:
        """Initialize adapter with configuration"""

    @abstractmethod
    def create_experiment(self, job_id: int, project_name: str, experiment_name: str) -> str:
        """Create experiment/task and return experiment_id"""

    @abstractmethod
    def log_metrics(self, experiment_id: str, metrics: Dict[str, float], step: int) -> None:
        """Log metrics for given step"""

    @abstractmethod
    def log_parameters(self, experiment_id: str, params: Dict[str, Any]) -> None:
        """Log hyperparameters"""

    @abstractmethod
    def mark_completed(self, experiment_id: str) -> None:
        """Mark experiment as completed"""

    @abstractmethod
    def mark_failed(self, experiment_id: str, error_message: str) -> None:
        """Mark experiment as failed"""

    @abstractmethod
    def get_experiment_url(self, experiment_id: str) -> Optional[str]:
        """Get web UI URL for experiment"""
```

**구현 요구사항**:
- 모든 adapter는 이 인터페이스를 구현
- Error handling (try-except)는 ObservabilityManager에서 담당
- Adapter는 single responsibility (특정 도구만 처리)

#### 13.1.2 DatabaseAdapter Implementation

**파일**: `platform/backend/app/services/observability/database_adapter.py`

**특징**:
- Always enabled (fallback)
- TrainingMetric 테이블 사용
- experiment_id = job_id (string)

**구현 예시**:
```python
class DatabaseAdapter(ObservabilityAdapter):
    def __init__(self, db: Session):
        self.db = db

    def create_experiment(self, job_id: int, project_name: str, experiment_name: str) -> str:
        return str(job_id)

    def log_metrics(self, experiment_id: str, metrics: Dict[str, float], step: int) -> None:
        job_id = int(experiment_id)
        metric = models.TrainingMetric(
            job_id=job_id,
            epoch=step,
            loss=metrics.get('loss'),
            accuracy=metrics.get('accuracy'),
            extra_metrics=metrics
        )
        self.db.add(metric)
        self.db.commit()
```

#### 13.1.3 ClearMLAdapter Implementation

**파일**: `platform/backend/app/services/observability/clearml_adapter.py`

**리팩토링 내용**:
- 기존 ClearMLService를 ClearMLAdapter로 변환
- Graceful degradation (ClearML 실패 시 에러 던지지 않음)
- experiment_id = clearml_task_id

#### 13.1.4 MLflowAdapter Implementation (Optional)

**파일**: `platform/backend/app/services/observability/mlflow_adapter.py`

**구현 내용**:
- mlflow.create_experiment(), mlflow.start_run()
- experiment_id = mlflow_run_id
- Tracking URI 설정 (environment variable)

#### 13.1.5 TensorBoardAdapter Implementation (Optional)

**파일**: `platform/backend/app/services/observability/tensorboard_adapter.py`

**구현 내용**:
- torch.utils.tensorboard.SummaryWriter
- File-based logging
- experiment_id = f"{job_id}"
- TensorBoard.dev 또는 iframe embedding 지원

---

### 13.2 ObservabilityManager & Configuration (Day 2-3)

#### 13.2.1 ObservabilityManager Implementation

**파일**: `platform/backend/app/services/observability/manager.py`

**주요 기능**:
1. **Multiple Adapters 관리**: 여러 adapter 동시 사용
2. **Error Handling**: 하나의 adapter 실패해도 다른 adapter는 계속 동작
3. **Experiment IDs Mapping**: 각 adapter의 experiment_id 저장
4. **Parallel Execution**: 성능 최적화 (asyncio)

**구현 예시**:
```python
class ObservabilityManager:
    def __init__(self):
        self.adapters: Dict[str, ObservabilityAdapter] = {}

    def add_adapter(self, name: str, adapter: ObservabilityAdapter) -> None:
        self.adapters[name] = adapter

    def create_experiment(self, job_id: int, project_name: str, experiment_name: str) -> Dict[str, str]:
        experiment_ids = {}
        for name, adapter in self.adapters.items():
            try:
                exp_id = adapter.create_experiment(job_id, project_name, experiment_name)
                experiment_ids[name] = exp_id
            except Exception as e:
                logger.warning(f"Adapter '{name}' failed: {e}")
        return experiment_ids

    def log_metrics(self, experiment_ids: Dict[str, str], metrics: Dict[str, float], step: int) -> None:
        for name, exp_id in experiment_ids.items():
            adapter = self.adapters.get(name)
            if adapter:
                try:
                    adapter.log_metrics(exp_id, metrics, step)
                except Exception as e:
                    logger.warning(f"Adapter '{name}' failed to log metrics: {e}")
```

#### 13.2.2 Environment Variable Configuration

**파일**: `platform/backend/.env`

**환경 변수**:
```bash
# ================================
# Observability Configuration (Phase 13)
# ================================
# Comma-separated list of enabled backends
OBSERVABILITY_BACKENDS=database,clearml

# ClearML (optional)
CLEARML_API_HOST=http://localhost:8008
CLEARML_WEB_HOST=http://localhost:8080

# MLflow (optional)
MLFLOW_TRACKING_URI=http://localhost:5000
MLFLOW_ENABLED=false

# TensorBoard (optional)
TENSORBOARD_LOG_DIR=/tmp/tensorboard
TENSORBOARD_ENABLED=false
```

**Settings 클래스 업데이트**:
```python
# platform/backend/app/core/config.py
class Settings(BaseSettings):
    # Observability
    OBSERVABILITY_BACKENDS: str = "database"

    # ClearML
    CLEARML_API_HOST: Optional[str] = None
    CLEARML_WEB_HOST: Optional[str] = None

    # MLflow
    MLFLOW_TRACKING_URI: Optional[str] = None
    MLFLOW_ENABLED: bool = False

    # TensorBoard
    TENSORBOARD_LOG_DIR: str = "/tmp/tensorboard"
    TENSORBOARD_ENABLED: bool = False

    @property
    def observability_backends_list(self) -> List[str]:
        return [b.strip() for b in self.OBSERVABILITY_BACKENDS.split(',')]
```

#### 13.2.3 TrainingCallbackService Refactoring

**파일**: `platform/backend/app/services/training_callback_service.py`

**변경 사항**:
```python
# BEFORE
class TrainingCallbackService:
    def __init__(self, db: Session):
        self.clearml_service = ClearMLService(db)  # Hardcoded!

# AFTER
class TrainingCallbackService:
    def __init__(self, db: Session):
        self.obs_manager = ObservabilityManager()

        # Database adapter (always)
        self.obs_manager.add_adapter('database', DatabaseAdapter(db))

        # Optional adapters
        if 'clearml' in settings.observability_backends_list:
            self.obs_manager.add_adapter('clearml', ClearMLAdapter(db))

        if settings.MLFLOW_ENABLED:
            self.obs_manager.add_adapter('mlflow', MLflowAdapter())
```

---

### 13.3 Frontend WebSocket Integration (Day 3-4)

#### 13.3.1 WebSocket Client Hook

**파일**: `platform/frontend/hooks/useTrainingWebSocket.ts`

**구현 내용**:
```typescript
interface TrainingMetrics {
  epoch: number
  loss: number
  accuracy: number
  [key: string]: any
}

export function useTrainingWebSocket(jobId: number | null) {
  const [connected, setConnected] = useState(false)
  const [metrics, setMetrics] = useState<TrainingMetrics[]>([])
  const [status, setStatus] = useState<string>('pending')
  const ws = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!jobId) return

    const wsUrl = `ws://localhost:8001/ws/training/${jobId}`
    ws.current = new WebSocket(wsUrl)

    ws.current.onopen = () => {
      setConnected(true)
    }

    ws.current.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'training_progress' && message.metrics) {
        setMetrics(prev => [...prev, message.metrics])
        setStatus(message.status)
      }
    }

    ws.current.onerror = (error) => {
      console.error('[WebSocket] Error:', error)
    }

    ws.current.onclose = () => {
      setConnected(false)
    }

    return () => {
      ws.current?.close()
    }
  }, [jobId])

  return { connected, metrics, status }
}
```

**기능**:
- WebSocket 연결 관리
- 자동 reconnection (exponential backoff)
- Real-time metrics 수신
- Connection status tracking

#### 13.3.2 Real-time Chart Component

**파일**: `platform/frontend/components/training/MetricsChart.tsx`

**구현 내용**:
```typescript
export function MetricsChart({ jobId }: { jobId: number }) {
  const { connected, metrics, status } = useTrainingWebSocket(jobId)

  return (
    <div className="space-y-4">
      {/* Connection status */}
      <div className="flex items-center gap-2">
        <div className={`w-3 h-3 rounded-full ${connected ? 'bg-green-500' : 'bg-gray-400'}`} />
        <span>{connected ? 'Connected' : 'Disconnected'}</span>
      </div>

      {/* Real-time chart */}
      <LineChart width={600} height={300} data={metrics}>
        <Line dataKey="loss" stroke="#8884d8" />
        <Line dataKey="accuracy" stroke="#82ca9d" />
      </LineChart>
    </div>
  )
}
```

#### 13.3.3 TrainingPanel Integration

**파일**: `platform/frontend/components/training/TrainingPanel.tsx`

**변경 사항**:
```typescript
// BEFORE: Polling
useEffect(() => {
  const interval = setInterval(() => {
    fetchJob(jobId) // API call every 2 seconds
  }, 2000)
  return () => clearInterval(interval)
}, [jobId])

// AFTER: WebSocket
const { connected, metrics, status } = useTrainingWebSocket(jobId)
```

---

### 13.4 Database Schema Updates (Day 4)

#### 13.4.1 TrainingJob Model Update

**파일**: `platform/backend/app/db/models.py`

**변경 사항**:
```python
class TrainingJob(Base):
    __tablename__ = "training_jobs"

    # Existing fields...

    # Observability configuration
    observability_backends = Column(String, default="database", nullable=False)
    observability_experiment_ids = Column(JSON, default=dict, nullable=False)
    # Example: {"database": "123", "clearml": "abc-def", "mlflow": "run_xyz"}
```

#### 13.4.2 Database Migration

**파일**: `platform/backend/app/db/migrations/migration_add_observability_fields.py`

**Migration Script**:
```python
def upgrade():
    op.add_column('training_jobs', sa.Column('observability_backends', sa.String(), nullable=False, server_default='database'))
    op.add_column('training_jobs', sa.Column('observability_experiment_ids', sa.JSON(), nullable=False, server_default='{}'))

def downgrade():
    op.drop_column('training_jobs', 'observability_backends')
    op.drop_column('training_jobs', 'observability_experiment_ids')
```

---

### 13.5 Testing & Documentation (Day 5)

#### 13.5.1 Unit Tests

**테스트 범위**:
- ObservabilityAdapter implementations
- ObservabilityManager logic
- Configuration loading
- TrainingCallbackService refactored logic

**테스트 위치**: `platform/backend/tests/unit/services/observability/`

#### 13.5.2 Integration Tests

**테스트 시나리오**:
- DB + ClearML 동시 사용
- ClearML 실패 시 DB는 계속 동작
- WebSocket real-time updates
- Multiple adapters with different configurations

#### 13.5.3 E2E Tests

**E2E 시나리오**:
1. Training job 생성 (OBSERVABILITY_BACKENDS=database,clearml)
2. Training 시작 및 metrics 전송
3. Backend: DB + ClearML에 metrics 저장 확인
4. Frontend: WebSocket으로 실시간 차트 업데이트 확인
5. Training 완료 후 각 backend의 Web UI 확인

#### 13.5.4 Documentation

**문서 작성**:
- `docs/observability/OBSERVABILITY_EXTENSIBILITY_DESIGN.md` - 설계 문서
- `docs/observability/USER_GUIDE.md` - 사용자 가이드
- `.env.example` 업데이트
- README.md 업데이트

---

## Success Criteria

### Backend
- [ ] ObservabilityAdapter base class 구현
- [ ] DatabaseAdapter (default) 구현
- [ ] ClearMLAdapter 구현
- [ ] MLflowAdapter 구현 (optional)
- [ ] TensorBoardAdapter 구현 (optional)
- [ ] ObservabilityManager 구현
- [ ] TrainingCallbackService refactoring
- [ ] Environment variable configuration
- [ ] Database schema updates

### Frontend
- [ ] useTrainingWebSocket hook 구현
- [ ] Real-time MetricsChart component
- [ ] TrainingPanel WebSocket integration
- [ ] Connection status UI
- [ ] Fallback to polling on WebSocket failure

### Testing
- [ ] Unit tests for all adapters
- [ ] Integration tests for ObservabilityManager
- [ ] E2E tests for real-time WebSocket updates
- [ ] Multi-backend configuration tests

### Documentation
- [ ] Design document
- [ ] User guide
- [ ] Environment variable documentation
- [ ] README updates

---

## Expected Outcomes

**사용자 경험 개선**:
- 사용자가 환경 변수로 관측 도구 선택 가능
- DB는 항상 동작 (fallback)
- 선택한 도구의 Web UI 링크 제공
- 프론트엔드 실시간 차트 업데이트

**기술적 개선**:
- Vendor lock-in 방지
- 관측 시스템 확장성 향상
- 코드 유지보수성 향상
- 성능 개선 (polling → WebSocket)

**예상 시간**: 5일
