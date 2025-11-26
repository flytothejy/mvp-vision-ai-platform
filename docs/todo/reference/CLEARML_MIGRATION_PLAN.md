# ClearML Migration Plan

**작성일**: 2025-11-27
**목표**: MLflow에서 ClearML로 완전 전환하여 더 강력한 MLOps 플랫폼 구축

---

## 📋 Executive Summary

### Why ClearML?

**MLflow의 한계**:
- 제한적인 실험 비교 기능
- UI/UX가 데이터 과학자 중심 (엔지니어링 팀에게 불친절)
- 모델 레지스트리 기능 부족
- 분산 학습 지원 미흡
- 파이프라인 오케스트레이션 없음

**ClearML의 장점**:
- 🎯 **완전한 실험 추적**: 자동 Git/dependency 추적, 하이퍼파라미터 비교
- 🚀 **강력한 모델 레지스트리**: 모델 버전 관리, 메타데이터, lineage 추적
- 📊 **풍부한 시각화**: 실시간 메트릭, 이미지/비디오 로깅, 커스텀 플롯
- 🔄 **파이프라인 오케스트레이션**: ClearML Pipelines로 ML workflow 자동화
- 🌐 **멀티 클라우드/하이브리드**: 온프레미스 + 클라우드 동시 지원
- 🎨 **직관적인 UI**: 엔지니어와 데이터 과학자 모두를 위한 설계
- 🔌 **오픈소스 + 엔터프라이즈**: Self-hosted 가능, 상용 기능 확장 가능

---

## 🎯 Migration Goals

### Primary Objectives
1. ✅ **Zero Data Loss**: 모든 기존 MLflow 실험 데이터를 ClearML로 마이그레이션
2. ✅ **Zero Downtime**: 단계적 마이그레이션으로 서비스 중단 없음
3. ✅ **Enhanced Features**: ClearML의 고급 기능 활용 (모델 레지스트리, 파이프라인)

### Success Metrics
- 모든 Training/Inference/Export Job이 ClearML Task로 추적됨
- 실시간 메트릭 업데이트 (<5초 지연)
- Checkpoint 자동 업로드 (100% 성공률)
- 사용자 만족도 증가 (더 나은 UI/UX)

---

## 🏗️ ClearML Architecture

### Components

```
ClearML Server (Self-hosted)
├── API Server (port 8008)       - REST API for Task management
├── Web UI (port 8080)            - User interface
├── File Server (port 8081)       - Artifact storage
├── PostgreSQL                    - Metadata storage
├── MongoDB                       - Experiment data
└── Elasticsearch                 - Search and analytics
```

### Integration with Platform

```
Training Job
    ↓
Backend (creates ClearML Task)
    ↓
Trainer Container
    ↓
Training SDK (ClearML Task.current_task())
    ↓
ClearML Task (logs metrics, artifacts)
    ↓
ClearML Server (stores and displays)
    ↓
Web UI / API (query and visualize)
```

---

## 📅 Migration Phases

### Phase 1: ClearML Setup (Day 1-2)

**Goal**: ClearML Server 배포 및 기본 구성

#### 1.1 Local Development (Docker Compose)

```yaml
# infrastructure/docker-compose.tier0.yaml 업데이트
services:
  clearml-apiserver:
    image: allegroai/clearml:latest
    container_name: clearml-apiserver
    restart: unless-stopped
    volumes:
      - C:/platform-data/clearml/logs:/var/log/clearml
      - C:/platform-data/clearml/config:/opt/clearml/config
    depends_on:
      - postgres
      - mongo
      - elasticsearch
    environment:
      CLEARML_HOST_IP: localhost
      CLEARML_WEB_HOST: http://localhost:8080
      CLEARML_API_HOST: http://localhost:8008
      CLEARML_FILES_HOST: http://localhost:8081
    ports:
      - "8008:8008"

  clearml-webserver:
    image: allegroai/clearml:latest
    container_name: clearml-webserver
    restart: unless-stopped
    depends_on:
      - clearml-apiserver
    environment:
      CLEARML_SERVER_API_HOST: http://clearml-apiserver:8008
    ports:
      - "8080:80"

  clearml-fileserver:
    image: allegroai/clearml:latest
    container_name: clearml-fileserver
    restart: unless-stopped
    volumes:
      - C:/platform-data/clearml/fileserver:/mnt/fileserver
    ports:
      - "8081:8081"

  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:7.17.9
    container_name: clearml-elastic
    restart: unless-stopped
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
    volumes:
      - C:/platform-data/clearml/elasticsearch:/usr/share/elasticsearch/data
    ports:
      - "9200:9200"

  mongo:
    image: mongo:7.0
    container_name: clearml-mongo
    restart: unless-stopped
    volumes:
      - C:/platform-data/clearml/mongo:/data/db
    ports:
      - "27018:27017"  # Avoid conflict with existing MongoDB
```

**Configuration**:
```bash
# platform/backend/.env 업데이트
CLEARML_API_HOST=http://localhost:8008
CLEARML_WEB_HOST=http://localhost:8080
CLEARML_FILES_HOST=http://localhost:8081
CLEARML_API_ACCESS_KEY=<generated-key>
CLEARML_API_SECRET_KEY=<generated-secret>
```

#### 1.2 Kind Kubernetes

```yaml
# infrastructure/kind/clearml/values.yaml
clearml:
  apiserver:
    service:
      type: LoadBalancer
      port: 8008
  webserver:
    service:
      type: LoadBalancer
      port: 8080
  fileserver:
    service:
      type: LoadBalancer
      port: 8081

  elasticsearch:
    enabled: true
    volumeClaimTemplate:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi

  mongodb:
    enabled: true
    persistence:
      size: 10Gi
```

```bash
# 배포
helm repo add allegroai https://allegroai.github.io/clearml-helm-charts
helm install clearml allegroai/clearml -f infrastructure/kind/clearml/values.yaml -n platform
```

#### 1.3 Access Configuration

```bash
# ClearML Web UI 접속
http://localhost:8080

# API 키 생성
1. Web UI 로그인 (admin/admin)
2. Settings → Workspace → Create new credentials
3. Access Key + Secret Key 복사
4. .env에 설정
```

**Checklist**:
- [ ] Docker Compose로 ClearML Server 실행
- [ ] Web UI 접속 확인 (http://localhost:8080)
- [ ] API 키 생성 및 .env 설정
- [ ] Kind에 ClearML Helm chart 배포
- [ ] Health check 확인

---

### Phase 2: ClearMLService Implementation (Day 2-3)

**Goal**: Backend ClearML 서비스 구현

#### 2.1 Service Class

```python
# platform/backend/app/services/clearml_service.py
from typing import Optional, Dict, List, Any
from clearml import Task, Model
from sqlalchemy.orm import Session
from app.db import models
from app.core.config import settings

class ClearMLService:
    """ClearML integration service for experiment tracking"""

    def __init__(self, db: Session):
        self.db = db
        self.api_host = settings.CLEARML_API_HOST
        self.web_host = settings.CLEARML_WEB_HOST
        self.files_host = settings.CLEARML_FILES_HOST

    def create_task(
        self,
        job_id: int,
        task_name: str,
        task_type: str,
        project_name: str = "Platform Training"
    ) -> Optional[str]:
        """Create ClearML task for training job"""
        try:
            task = Task.init(
                project_name=project_name,
                task_name=task_name,
                task_type=task_type,  # 'training', 'testing', 'inference', 'data_processing'
                reuse_last_task_id=False,
                auto_connect_frameworks=False  # Manual logging for full control
            )

            # Store task ID in database
            job = self.db.query(models.TrainingJob).filter(
                models.TrainingJob.id == job_id
            ).first()
            if job:
                job.clearml_task_id = task.id
                self.db.commit()

            return task.id
        except Exception as e:
            print(f"Failed to create ClearML task: {e}")
            return None

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get ClearML task by ID"""
        try:
            return Task.get_task(task_id=task_id)
        except Exception as e:
            print(f"Failed to get ClearML task: {e}")
            return None

    def log_metrics(
        self,
        task_id: str,
        metrics: Dict[str, float],
        iteration: int
    ):
        """Log metrics to ClearML task"""
        try:
            task = self.get_task(task_id)
            if task:
                for metric_name, value in metrics.items():
                    # Parse metric name (e.g., "train/loss" -> series="train", title="loss")
                    parts = metric_name.split('/')
                    if len(parts) == 2:
                        series, title = parts
                    else:
                        series = "metrics"
                        title = metric_name

                    task.logger.report_scalar(
                        title=title,
                        series=series,
                        value=value,
                        iteration=iteration
                    )
        except Exception as e:
            print(f"Failed to log metrics: {e}")

    def upload_artifact(
        self,
        task_id: str,
        artifact_name: str,
        artifact_object: Any,
        metadata: Optional[Dict] = None
    ):
        """Upload artifact (checkpoint, model, etc.)"""
        try:
            task = self.get_task(task_id)
            if task:
                task.upload_artifact(
                    name=artifact_name,
                    artifact_object=artifact_object,
                    metadata=metadata
                )
        except Exception as e:
            print(f"Failed to upload artifact: {e}")

    def mark_completed(self, task_id: str, status: str = "completed"):
        """Mark task as completed"""
        try:
            task = self.get_task(task_id)
            if task:
                task.mark_completed()
        except Exception as e:
            print(f"Failed to mark task completed: {e}")

    def mark_failed(self, task_id: str, status_reason: str):
        """Mark task as failed"""
        try:
            task = self.get_task(task_id)
            if task:
                task.mark_failed(status_reason=status_reason)
        except Exception as e:
            print(f"Failed to mark task failed: {e}")

    def get_task_metrics(self, task_id: str) -> Dict[str, List]:
        """Get all metrics from task"""
        try:
            task = self.get_task(task_id)
            if task:
                metrics = task.get_last_scalar_metrics()
                return metrics
            return {}
        except Exception as e:
            print(f"Failed to get task metrics: {e}")
            return {}

    def register_model(
        self,
        task_id: str,
        model_path: str,
        model_name: str,
        tags: Optional[List[str]] = None
    ) -> Optional[str]:
        """Register model in ClearML Model Repository"""
        try:
            task = self.get_task(task_id)
            if task:
                output_model = Model(
                    task=task,
                    name=model_name,
                    tags=tags or [],
                    framework="PyTorch"  # or detect automatically
                )
                output_model.update_weights(
                    weights_filename=model_path,
                    auto_delete_file=False
                )
                return output_model.id
            return None
        except Exception as e:
            print(f"Failed to register model: {e}")
            return None
```

**Checklist**:
- [ ] ClearMLService 클래스 구현
- [ ] Task 생성/조회 메서드
- [ ] Metrics 로깅 메서드
- [ ] Artifact 업로드 메서드
- [ ] Model registration 메서드
- [ ] Unit tests 작성

#### 2.2 Database Schema Update

```python
# Migration: add clearml_task_id column
def upgrade():
    op.add_column('training_jobs', sa.Column('clearml_task_id', sa.String(255), nullable=True))
    op.add_column('inference_jobs', sa.Column('clearml_task_id', sa.String(255), nullable=True))
    op.add_column('export_jobs', sa.Column('clearml_task_id', sa.String(255), nullable=True))

    # Add index for faster lookups
    op.create_index('ix_training_jobs_clearml_task_id', 'training_jobs', ['clearml_task_id'])
    op.create_index('ix_inference_jobs_clearml_task_id', 'inference_jobs', ['clearml_task_id'])
    op.create_index('ix_export_jobs_clearml_task_id', 'export_jobs', ['clearml_task_id'])

def downgrade():
    op.drop_index('ix_export_jobs_clearml_task_id', 'export_jobs')
    op.drop_index('ix_inference_jobs_clearml_task_id', 'inference_jobs')
    op.drop_index('ix_training_jobs_clearml_task_id', 'training_jobs')

    op.drop_column('export_jobs', 'clearml_task_id')
    op.drop_column('inference_jobs', 'clearml_task_id')
    op.drop_column('training_jobs', 'clearml_task_id')
```

**Checklist**:
- [ ] Migration script 작성
- [ ] 테스트 환경에서 migration 실행
- [ ] 롤백 테스트
- [ ] Production migration 계획

---

### Phase 3: Backend API Migration (Day 4-5)

**Goal**: MLflowService를 ClearMLService로 교체

#### 3.1 Training API Updates

```python
# platform/backend/app/api/training.py (Before)
from app.utils.mlflow_client import get_mlflow_client

@router.get("/jobs/{job_id}")
def get_training_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(404)

    # Get MLflow metrics
    mlflow_client = get_mlflow_client()
    mlflow_run = mlflow_client.get_run_by_job_id(job_id)
    # ...

# platform/backend/app/api/training.py (After)
from app.services.clearml_service import ClearMLService

@router.get("/jobs/{job_id}")
def get_training_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(404)

    # Get ClearML metrics
    clearml_service = ClearMLService(db)
    if job.clearml_task_id:
        metrics = clearml_service.get_task_metrics(job.clearml_task_id)
    # ...
```

**변경 위치**:
1. `get_training_job()` - Line ~332
2. `get_mlflow_metrics()` → `get_clearml_metrics()` - Line ~834
3. `get_mlflow_summary()` → `get_clearml_summary()` - Line ~864
4. Training job 생성 시 ClearML Task 생성

#### 3.2 Experiments API Updates

```python
# platform/backend/app/api/experiments.py
# MLflow Experiment → ClearML Project 매핑

@router.post("/experiments")
def create_experiment(
    request: schemas.ExperimentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Create ClearML project (replaces MLflow experiment)
    clearml_service = ClearMLService(db)
    project_id = clearml_service.create_project(
        project_name=request.name,
        description=request.description
    )

    experiment = models.Experiment(
        name=request.name,
        description=request.description,
        clearml_project_id=project_id,  # Was: mlflow_experiment_id
        created_by=current_user.id
    )
    db.add(experiment)
    db.commit()
    return experiment
```

**Checklist**:
- [ ] `training.py` 4곳 업데이트
- [ ] `experiments.py` ClearML Project 연동
- [ ] API response schema 업데이트
- [ ] Integration tests 업데이트

---

### Phase 4: Training SDK Updates (Day 6)

**Goal**: Trainer에서 ClearML Task 사용

#### 4.1 SDK Metrics Logging

```python
# platform/trainers/ultralytics/trainer_sdk.py (Before)
def report_progress(self, epoch: int, total_epochs: int, metrics: TrainingCallbackMetrics):
    """Report training progress to backend"""
    # Callback to backend
    callback_data = {
        "operation_type": "training",
        "epoch": epoch,
        "total_epochs": total_epochs,
        "metrics": metrics.dict()
    }
    response = self.http_client.post(
        f"{self.callback_url}/progress",
        json=callback_data
    )

# platform/trainers/ultralytics/trainer_sdk.py (After)
from clearml import Task

def report_progress(self, epoch: int, total_epochs: int, metrics: TrainingCallbackMetrics):
    """Report training progress to backend and ClearML"""
    # Callback to backend (for DB update, WebSocket)
    callback_data = {
        "operation_type": "training",
        "epoch": epoch,
        "total_epochs": total_epochs,
        "metrics": metrics.dict()
    }
    response = self.http_client.post(
        f"{self.callback_url}/progress",
        json=callback_data
    )

    # Log to ClearML (if task exists)
    task = Task.current_task()
    if task:
        for metric_name, value in metrics.dict().items():
            if value is not None:
                # Parse metric name (e.g., "train_loss" -> series="train", title="loss")
                if "_" in metric_name:
                    series, title = metric_name.split("_", 1)
                else:
                    series = "metrics"
                    title = metric_name

                task.logger.report_scalar(
                    title=title,
                    series=series,
                    value=value,
                    iteration=epoch
                )
```

#### 4.2 Checkpoint Upload

```python
# platform/trainers/ultralytics/trainer_sdk.py
def upload_checkpoint(self, local_path: str, checkpoint_type: str, is_best: bool = False):
    """Upload checkpoint to S3 and register in ClearML"""
    # 1. Upload to S3 (existing logic)
    s3_key = f"checkpoints/{self.job_id}/{checkpoint_type}.pt"
    self.internal_storage.upload_file(local_path, s3_key)

    # 2. Register in ClearML
    task = Task.current_task()
    if task:
        task.upload_artifact(
            name=f"checkpoint_{checkpoint_type}",
            artifact_object=local_path,
            metadata={
                "checkpoint_type": checkpoint_type,
                "is_best": is_best,
                "s3_key": s3_key
            }
        )

        # If best checkpoint, register as output model
        if is_best:
            from clearml import Model
            output_model = Model(task=task)
            output_model.update_weights(weights_filename=local_path)

    # 3. Callback to backend
    # ... (existing callback logic)
```

**Checklist**:
- [ ] SDK에 ClearML Task 통합
- [ ] Metrics logging 구현
- [ ] Checkpoint upload 구현
- [ ] Model registration 구현
- [ ] train.py에서 Task.init() 호출 추가

#### 4.3 Trainer Script Update

```python
# platform/trainers/ultralytics/train.py
from clearml import Task
from trainer_sdk import TrainerSDK

def main():
    sdk = TrainerSDK()

    # Initialize ClearML Task
    task = Task.init(
        project_name=f"Project {sdk.project_id}",
        task_name=f"Training Job {sdk.job_id}",
        task_type=Task.TaskTypes.training,
        reuse_last_task_id=False
    )

    # Connect configuration
    task.connect_configuration(sdk.get_full_config())

    # Training loop
    for epoch in range(total_epochs):
        # ... training logic ...

        # Report progress (to backend + ClearML)
        sdk.report_progress(epoch, total_epochs, metrics)

    # Complete
    sdk.report_completed(...)
    task.mark_completed()
```

---

### Phase 5: MLflow Data Migration (Day 7)

**Goal**: 기존 MLflow 데이터를 ClearML로 마이그레이션

#### 5.1 Migration Script

```python
# scripts/clearml/migrate_mlflow_to_clearml.py
import mlflow
from clearml import Task
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db import models

def migrate_training_job(job: models.TrainingJob, db: Session):
    """Migrate single training job from MLflow to ClearML"""
    print(f"Migrating Job {job.id}...")

    # 1. Get MLflow run
    if not job.mlflow_run_id:
        print(f"  No MLflow run for Job {job.id}, skipping")
        return

    mlflow_client = mlflow.tracking.MlflowClient()
    try:
        run = mlflow_client.get_run(job.mlflow_run_id)
    except Exception as e:
        print(f"  Failed to get MLflow run: {e}")
        return

    # 2. Create ClearML task
    task = Task.create(
        project_name=f"Project {job.project_id}",
        task_name=f"Training Job {job.id} (Migrated)",
        task_type=Task.TaskTypes.training
    )

    # 3. Migrate metrics
    metrics = mlflow_client.get_metric_history(run.info.run_id, "train/loss")
    for metric in metrics:
        task.logger.report_scalar(
            title="loss",
            series="train",
            value=metric.value,
            iteration=metric.step
        )

    # 4. Migrate artifacts (checkpoints)
    artifacts = mlflow_client.list_artifacts(run.info.run_id)
    for artifact in artifacts:
        local_path = mlflow_client.download_artifacts(run.info.run_id, artifact.path)
        task.upload_artifact(
            name=artifact.path,
            artifact_object=local_path
        )

    # 5. Update database
    job.clearml_task_id = task.id
    db.commit()

    # 6. Mark task as completed
    task.mark_completed()

    print(f"  ✓ Migrated to ClearML Task {task.id}")

def main():
    db = SessionLocal()

    # Get all training jobs with MLflow runs
    jobs = db.query(models.TrainingJob).filter(
        models.TrainingJob.mlflow_run_id.isnot(None)
    ).all()

    print(f"Found {len(jobs)} jobs to migrate")

    for job in jobs:
        try:
            migrate_training_job(job, db)
        except Exception as e:
            print(f"  ✗ Failed to migrate Job {job.id}: {e}")
            continue

    db.close()
    print("\nMigration complete!")

if __name__ == "__main__":
    main()
```

**Checklist**:
- [ ] Migration script 작성
- [ ] 테스트 환경에서 실행
- [ ] 데이터 무결성 검증
- [ ] Production migration 실행

---

### Phase 6: Frontend Updates (Day 8)

**Goal**: ClearML Web UI 통합

#### 6.1 Embedded ClearML UI

```typescript
// platform/frontend/components/training/ClearMLPanel.tsx
import { useState, useEffect } from 'react';

interface ClearMLPanelProps {
  taskId: string;
}

export function ClearMLPanel({ taskId }: ClearMLPanelProps) {
  const clearmlWebHost = process.env.NEXT_PUBLIC_CLEARML_WEB_HOST || 'http://localhost:8080';
  const iframeUrl = `${clearmlWebHost}/projects/*/experiments/${taskId}`;

  return (
    <div className="clearml-panel h-full">
      <iframe
        src={iframeUrl}
        className="w-full h-full border-0"
        title="ClearML Task View"
      />
    </div>
  );
}
```

#### 6.2 Metrics Chart Update

```typescript
// platform/frontend/components/training/MetricsChart.tsx
// Replace MLflow metrics API with ClearML API

const fetchMetrics = async (taskId: string) => {
  const response = await fetch(`/api/v1/training/clearml/${taskId}/metrics`);
  const data = await response.json();

  // Transform ClearML metrics format to chart format
  // ...
};
```

**Checklist**:
- [ ] ClearMLPanel 컴포넌트 생성
- [ ] TrainingPanel에 ClearML UI 탭 추가
- [ ] Metrics chart ClearML API 연동
- [ ] Experiment 페이지 UI 업데이트

---

### Phase 7: MLflow Cleanup (Day 9)

**Goal**: MLflow 완전히 제거

#### 7.1 Code Removal

```bash
# Remove MLflow files
rm platform/backend/app/utils/mlflow_client.py
rm platform/backend/app/services/mlflow_service.py

# Update imports
grep -r "mlflow" platform/backend/app/ --include="*.py" | cut -d: -f1 | sort -u
# Manually review and remove each import
```

#### 7.2 Infrastructure Cleanup

```yaml
# infrastructure/docker-compose.tier0.yaml
# Remove MLflow service
services:
  # mlflow:  # REMOVE THIS
  #   image: ghcr.io/mlflow/mlflow:v2.9.2
  #   ...
```

```bash
# Kind cleanup
kubectl delete deployment mlflow -n platform
kubectl delete service mlflow -n platform
```

#### 7.3 Database Cleanup

```python
# Migration: remove mlflow columns
def upgrade():
    # Keep columns for backward compatibility, but mark as deprecated
    # Can be removed in future version after all data migrated
    pass

def downgrade():
    pass
```

**Checklist**:
- [ ] MLflow 코드 파일 제거
- [ ] Import 정리
- [ ] Docker Compose에서 MLflow 제거
- [ ] Kind에서 MLflow 제거
- [ ] 환경변수 정리

---

## 🧪 Testing Strategy

### Unit Tests
- [ ] ClearMLService 모든 메서드 테스트
- [ ] Task 생성/조회/업데이트 테스트
- [ ] Metrics logging 테스트
- [ ] Artifact upload 테스트

### Integration Tests
- [ ] Training lifecycle with ClearML (create → progress → complete)
- [ ] Inference job ClearML 통합
- [ ] Export job ClearML 통합
- [ ] Callback endpoint ClearML 연동

### E2E Tests
- [ ] Complete training flow
- [ ] Metrics visualization in ClearML Web UI
- [ ] Checkpoint download from ClearML
- [ ] Model registration and deployment

### Performance Tests
- [ ] ClearML API response time (<100ms)
- [ ] Metrics logging latency (<50ms)
- [ ] Artifact upload speed (>10MB/s)

---

## 📊 Rollback Plan

### If Migration Fails

**Immediate Rollback**:
```bash
# 1. Revert code changes
git revert <migration-commit-hash>

# 2. Restore MLflow service
docker-compose -f infrastructure/docker-compose.tier0.yaml up -d mlflow

# 3. Database rollback
alembic downgrade -1

# 4. Restart backend
docker-compose restart backend
```

**Data Recovery**:
- MLflow data는 삭제하지 않고 보관 (최소 3개월)
- ClearML 실패 시 MLflow로 폴백 가능
- Dual-write 기간 동안 두 시스템 모두 데이터 기록

---

## 📋 Success Criteria Checklist

### Infrastructure
- [ ] ClearML Server 안정적으로 실행 (99.9% uptime)
- [ ] Web UI 접근 가능 (<500ms 로딩)
- [ ] API 응답 시간 <100ms

### Backend
- [ ] ClearMLService 모든 기능 구현
- [ ] 모든 API 엔드포인트 ClearML 연동
- [ ] MLflow 코드 100% 제거

### Trainer SDK
- [ ] ClearML Task 자동 생성
- [ ] 실시간 metrics logging
- [ ] Checkpoint 자동 업로드 및 등록

### Data Migration
- [ ] 모든 기존 MLflow 데이터 ClearML로 마이그레이션
- [ ] 데이터 무결성 100% 검증
- [ ] Zero data loss

### Frontend
- [ ] ClearML Web UI 임베드
- [ ] Metrics 차트 정상 작동
- [ ] Experiment 페이지 업데이트

### Testing
- [ ] 모든 Unit tests 통과
- [ ] 모든 Integration tests 통과
- [ ] 모든 E2E tests 통과
- [ ] Performance tests 통과

### Documentation
- [ ] ARCHITECTURE.md 업데이트
- [ ] API_SPECIFICATION.md 업데이트
- [ ] DEVELOPMENT.md ClearML 가이드 추가
- [ ] Migration guide 작성

---

## 🎯 Post-Migration Enhancements

**ClearML 고급 기능 활용** (Phase 13 이후):

1. **ClearML Pipelines**
   - Training → Evaluation → Export → Deployment 자동화
   - 파이프라인 버전 관리
   - 조건부 실행 (accuracy > 0.9 → auto-deploy)

2. **ClearML Agents**
   - GPU 자동 할당
   - 분산 학습 지원
   - Queue 기반 작업 스케줄링

3. **Model Registry**
   - 모델 버전 관리
   - Lineage tracking (어떤 데이터로 학습되었는지)
   - A/B testing 지원

4. **Advanced Monitoring**
   - 커스텀 대시보드
   - 이미지/비디오 로깅
   - 3D plot 지원

---

## 📝 Notes

### ClearML vs MLflow 비교

| Feature | MLflow | ClearML | Winner |
|---------|--------|---------|--------|
| 실험 추적 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ClearML |
| 모델 레지스트리 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ClearML |
| UI/UX | ⭐⭐ | ⭐⭐⭐⭐ | ClearML |
| 파이프라인 | ❌ | ⭐⭐⭐⭐⭐ | ClearML |
| 분산 학습 | ⭐ | ⭐⭐⭐⭐ | ClearML |
| 커뮤니티 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | MLflow |
| 오픈소스 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | MLflow |
| Self-hosting | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ClearML |

### Migration Risks

**High Risk**:
- ClearML Server 안정성 (신규 도입)
- 데이터 마이그레이션 실패

**Mitigation**:
- Staging 환경에서 충분한 테스트
- Rollback plan 철저히 준비
- Dual-write 기간 설정 (2주)

**Medium Risk**:
- Frontend UI 변경에 따른 사용자 적응

**Mitigation**:
- 사용자 가이드 작성
- 점진적 롤아웃 (admin → all users)

---

**작성자**: Claude
**검토 필요**: Phase 2 ClearMLService 구현 검증
**다음 단계**: Phase 1 실행 승인 대기
