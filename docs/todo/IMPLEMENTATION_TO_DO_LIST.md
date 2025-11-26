# Implementation To-Do List

Vision AI Training Platform 구현 진행 상황 추적 문서.

**총 진행률**: 98% (238/253 tasks)
**최종 업데이트**: 2025-11-24 (Phase 11 Tier 1-2 완료: PostgreSQL User DB 마이그레이션)

---

## Progress Summary

| Phase | Status | Progress | Reference |
|-------|--------|----------|-----------|
| 0. Infrastructure | 🔄 95% | 주요 완료, Backend K8s 배포 대기 | [TIER0_SETUP.md](../development/TIER0_SETUP.md) |
| 1. User & Project | 🔄 75% | Organization/Role 완료, Invitation 진행중 | - |
| 2. Dataset Management | ✅ 85% | Split/Snapshot 완료 | - |
| 3. Training Services | ✅ 88% | Phase 3.1-3.6 완료 | [Phase 3 References](#phase-3-references) |
| 4. Experiment & MLflow | 🔄 86% | 기본 통합 완료, UI 대기 | - |
| 5. Analytics | ⬜ 0% | 미시작 | - |
| 6. Model Deployment & Serving | ⬜ 0% | Triton 기반 고도화 배포 계획 완료 | [Phase 6 Details](#phase-6-model-deployment--serving-0) |
| 7. Trainer Marketplace | ⬜ 0% | 계획 완료 | [TRAINER_MARKETPLACE_VISION.md](../planning/TRAINER_MARKETPLACE_VISION.md) |
| 8. E2E Testing | 🔄 25% | Inference/Export E2E 완료 | [E2E_TEST_REPORT_20251120.md](reference/E2E_TEST_REPORT_20251120.md) |
| 9. Thin SDK | ✅ 85% | 핵심 기능 완료, 리팩토링 필요 | [THIN_SDK_DESIGN.md](references/THIN_SDK_DESIGN.md) |
| 10. Training SDK | ✅ 90% | 핵심 기능 완료, 환경변수 업데이트 완료 | [E2E Test Report](reference/TRAINING_SDK_E2E_TEST_REPORT.md) |
| 11. Microservice Separation | 🔄 67% | Tier 1-2 완료, Tier 3-4 대기 | [PHASE_11_MICROSERVICE_SEPARATION.md](../planning/PHASE_11_MICROSERVICE_SEPARATION.md) |
| 12. Backend Refactoring & ClearML | ⬜ 0% | 리팩토링 및 MLOps 플랫폼 전환 | [CLEARML_MIGRATION_PLAN.md](reference/CLEARML_MIGRATION_PLAN.md) |

---

## Phase 0: Infrastructure Setup (95%)

### 0.1 Kind Cluster Setup ✅
- [x] Kind config 생성
- [x] Namespace 생성 (platform, training, monitoring, temporal)
- [x] Helm charts 배포 (PostgreSQL, Redis, MinIO, Prometheus, Grafana, Loki, Temporal)

### 0.2 Platform Services 🔄 (60%)
- [x] PostgreSQL, Redis, MinIO, Monitoring Stack 배포 완료
- [ ] Backend ConfigMap/Secret 생성
- [ ] Backend Dockerfile 작성
- [ ] Backend Deployment/Service 배포
- [ ] Frontend Dockerfile 작성
- [ ] Frontend Deployment/Service 배포

### 0.3 MLflow Service ✅
- [x] MLflow K8s manifest 작성
- [x] MLflow 배포 및 UI 접근 확인 (http://localhost:30500)

### 0.4 Observability Stack ✅
- [x] kube-prometheus-stack 배포
- [x] Loki 배포
- [x] Grafana datasource 설정

### 0.5 Temporal Orchestration ✅
- [x] Temporal Server 배포
- [x] Temporal UI 접근 확인 (http://localhost:30233)
- [ ] Backend에 Temporal Worker 코드 추가

### 0.6 Backend Training Mode 🔄
- [x] Subprocess executor 구현 (`training_subprocess.py`)
- [ ] K8s executor 구현 (`k8s_executor.py`)
- [ ] TrainingManager 추상화

### 0.7 Scripts & Documentation ✅
- [x] Helm 배포 스크립트
- [x] 개발 환경 시작 스크립트
- [x] QUICK_START.md

### 0.8 Migration to Tier 2 ⬜
- [ ] Trainer Docker 이미지 빌드
- [ ] K8s Job training 테스트

### 0.9 Real-time Updates (WebSocket) 🔄 (80%)
현재 polling 방식을 WebSocket으로 전환하여 실시간 업데이트 구현.

**문제점**: 현재 프론트엔드가 3초 간격으로 polling하여 서버 부하 및 지연 발생

**목표**: CLAUDE.md 원칙 준수 - "Real-time updates MUST go through WebSocket, not polling"

**Backend**:
- [x] WebSocket 엔드포인트 구현 (`/api/v1/ws/training`)
- [x] WebSocket Manager 구현 (broadcast, job/session subscription)
- [x] Job 상태 변경 시 WebSocket broadcast
- [x] Export job 상태 변경 시 WebSocket broadcast
- [x] Redis 통합 (RedisManager + Session Store) - Phase 5 완료, Pub/Sub는 필요시 추가

**Frontend**:
- [x] WebSocket 연결 관리 훅 (`useTrainingMonitor`)
- [x] Training job 상태 실시간 업데이트
- [x] Training metrics 실시간 스트리밍
- [x] Export job 상태 실시간 업데이트
- [~] Inference job 상태 - 단기 작업이므로 polling 유지 (2초 간격, 최대 2분)

**Polling 제거 완료**:
- [x] `ExportJobList.tsx` - 3초 폴링 제거, refreshKey 패턴 적용
- [x] `TrainingPanel` - metrics 폴링 제거, WebSocket onMetrics 콜백 적용
- [x] `MLflowMetricsCharts.tsx` - 5초 폴링 제거, refreshKey 패턴 적용
- [~] `TestInferencePanel` - 단기 작업 polling 유지 (적절한 패턴)

**구현 파일**:
- `platform/backend/app/api/websocket.py` - WebSocket router
- `platform/backend/app/services/websocket_manager.py` - Connection manager
- `platform/frontend/hooks/useTrainingMonitor.ts` - WebSocket hook

**Reference**: [ARCHITECTURE.md](../architecture/ARCHITECTURE.md) - WebSocket Message Types 섹션

**Reference**: [TIER0_SETUP.md](../development/TIER0_SETUP.md)

---

## Phase 1: User & Project (75%)

### 1.1 Organization & Role System ✅
- [x] Organization/UserRole 모델
- [x] 마이그레이션
- [x] 회원가입 시 Organization 자동 생성
- [ ] API Permission 체크 적용
- [ ] Role 기반 UI 권한 제어

### 1.2 Experiment Model & MLflow ✅
- [x] Experiment/ExperimentStar/ExperimentNote 모델
- [x] MLflowService 클래스
- [x] Experiment API endpoints
- [ ] TrainingJob-Experiment 자동 연결
- [ ] Frontend Experiment UI

### 1.3 Invitation System 🔄
- [x] Invitation 모델 및 마이그레이션
- [x] Email Service 구현
- [x] Invitation API endpoints
- [x] Password reset 기능
- [ ] Frontend Invitation 페이지
- [ ] Email 검증 페이지

### 1.4 Audit Log System ⬜
- [ ] AuditLog 모델
- [ ] AuditLogger 서비스
- [ ] API 통합

---

## Phase 2: Dataset Management (85%)

### 2.1 Dataset Split Strategy ✅
- [x] 3-Level Priority split 구현
- [x] Split ratio 설정

### 2.2 Snapshot Management ✅
- [x] Snapshot API
- [x] Dataset 버전 추적

### 2.3 Version Management & Download ⬜
- [ ] Dataset versioning
- [ ] Download API

### 2.4 Organization-level Datasets ⬜
- [ ] Organization 공유 데이터셋

### 2.5 Dataset Metrics & Statistics ⬜
- [ ] 데이터셋 통계 API

---

## Phase 3: Training Services (88%)

### 3.1 Trainer Architecture ✅
- [x] Ultralytics trainer 분리
- [x] Convention-based export design
- [x] CLI interface 표준화

**Reference**: [EXPORT_CONVENTION.md](../EXPORT_CONVENTION.md)

### 3.1.1 Checkpoint Management ✅
- [x] best.pt/last.pt 저장
- [x] checkpoint_best_path/checkpoint_last_path 필드 추가
- [x] 프론트엔드 체크포인트 선택 UI

**Reference**: [PHASE_3_1_1_CHECKPOINT_UPDATE.md](../planning/PHASE_3_1_1_CHECKPOINT_UPDATE.md)

### 3.2 Advanced Config Schema ✅
- [x] 동적 config schema 시스템
- [x] Hyperparameter validation
- [x] 트레이너별 config 분리

**Reference**: [ADVANCED_CONFIG_SCHEMA.md](../ADVANCED_CONFIG_SCHEMA.md)

### 3.3 Dual Storage Architecture ✅
- [x] Internal MinIO (9002) / External MinIO (9000) 분리
- [x] Dataset/inference 버킷 분리

### 3.4 Additional Trainers ⬜
- [ ] timm trainer
- [ ] HuggingFace trainer
- [ ] Custom trainer support

### 3.5 Evaluation & Inference CLI ✅
- [x] predict.py CLI
- [x] Pretrained weight 지원
- [x] S3 checkpoint 다운로드

**Reference**: [PHASE_3_5_INFERENCE_PLAN.md](../planning/PHASE_3_5_INFERENCE_PLAN.md)

### 3.5.1 Quick Test Inference ✅
- [x] TestInferencePanel UI
- [x] /test_inference API

### 3.5.2 Inference Job Pattern ✅
- [x] InferenceJob 모델
- [x] Async job execution
- [x] S3 결과 저장
- [x] E2E 테스트 완료

**Reference**: [INFERENCE_JOB_PATTERN.md](../INFERENCE_JOB_PATTERN.md), [E2E_TEST_GUIDE.md](../E2E_TEST_GUIDE.md)

### 3.6 Model Export & Deployment ✅ (100%)
- [x] ExportJob/Deployment 모델
- [x] Export formats (ONNX, TensorRT, CoreML, TFLite)
- [x] Deployment types (Platform Endpoint, Edge, Container, Download)
- [x] Model Capabilities System
- [x] Frontend Export UI (CreateExportModal, DeploymentList)
- [x] Platform Inference Endpoint
- [x] Runtime Wrappers (Python, C++)

**Reference**: [PHASE_3_6_EXPORT_DEPLOYMENT_PLAN.md](../planning/PHASE_3_6_EXPORT_DEPLOYMENT_PLAN.md), [MODEL_CAPABILITIES_SYSTEM.md](../MODEL_CAPABILITIES_SYSTEM.md)

---

## Phase 4: Experiment & MLflow (86%)

- [x] MLflow tracking 통합
- [x] Experiment 모델 및 API
- [x] MLflowMetricsCharts 컴포넌트
- [ ] Frontend Experiment 관리 UI
- [ ] Experiment 비교 기능

---

## Phase 5: Analytics & Monitoring (0%)

- [ ] Usage tracking
- [ ] Cost analytics
- [ ] Performance dashboards

---

## Phase 6: Model Deployment & Serving (0%)

Production-grade 모델 서빙 인프라 구현. Export된 모델을 실제 추론 서비스로 배포.

### 6.1 Inference Server Infrastructure ⬜
**목표**: Triton Inference Server 기반 고성능 모델 서빙

- [ ] Inference Server 선택 및 아키텍처 설계
  - [ ] Triton vs ONNX Runtime vs TorchServe 비교 분석
  - [ ] 멀티 모델 서빙 전략
- [ ] Triton Inference Server 배포
  - [ ] K8s Deployment manifest
  - [ ] Model repository 구조 설계 (S3 연동)
  - [ ] 모델 버전 관리 (model versioning)
- [ ] 동적 배칭 (Dynamic Batching)
  - [ ] 배치 크기 최적화
  - [ ] 최대 지연 시간 설정
- [ ] GPU 메모리 관리
  - [ ] 모델별 메모리 할당
  - [ ] 다중 GPU 분배

### 6.2 Platform Endpoint Service ⬜
**목표**: 관리형 추론 API 제공

- [ ] Endpoint Manager 서비스
  - [ ] Deployment → Triton 모델 로딩 자동화
  - [ ] 모델 활성화/비활성화 API
  - [ ] 헬스체크 및 readiness probe
- [ ] API Gateway 연동
  - [ ] Kong/Envoy 설정
  - [ ] Rate limiting
  - [ ] Request routing (deployment_id → model)
- [ ] 인증/인가
  - [ ] API Key 생성 및 관리
  - [ ] Key rotation
  - [ ] Scope/Permission 설정
- [ ] 추론 API 구현
  - [ ] `POST /v1/infer/{deployment_id}`
  - [ ] 이미지 전처리 (base64, URL, multipart)
  - [ ] 결과 후처리 (task_type별 포맷)

### 6.3 Auto-scaling & Resource Management ⬜
**목표**: 트래픽에 따른 자동 스케일링

- [ ] Horizontal Pod Autoscaler (HPA)
  - [ ] CPU/Memory 기반 스케일링
  - [ ] Custom metrics (요청 수, 지연시간)
- [ ] Vertical Pod Autoscaler (VPA)
  - [ ] GPU 메모리 최적화
- [ ] Cluster Autoscaler
  - [ ] 노드 자동 추가/제거
- [ ] 리소스 쿼터 관리
  - [ ] Organization별 GPU 할당량
  - [ ] 동시 요청 수 제한

### 6.4 Monitoring & Observability ⬜
**목표**: 실시간 성능 모니터링 및 알림

- [ ] Prometheus 메트릭 수집
  - [ ] 요청 수 (requests/sec)
  - [ ] 지연 시간 (p50, p95, p99)
  - [ ] 처리량 (throughput)
  - [ ] GPU 사용률
  - [ ] 모델별 메트릭
- [ ] Grafana 대시보드
  - [ ] Deployment 상태 대시보드
  - [ ] 성능 트렌드 시각화
  - [ ] 에러율 모니터링
- [ ] 알림 설정
  - [ ] 지연시간 임계치 초과
  - [ ] 에러율 증가
  - [ ] 리소스 부족

### 6.5 Usage Tracking & Billing ⬜
**목표**: 사용량 추적 및 과금 기반 데이터

- [ ] 요청 로깅
  - [ ] 요청/응답 메타데이터 저장
  - [ ] 처리 시간 기록
- [ ] 사용량 집계
  - [ ] Organization별 일/월 사용량
  - [ ] Deployment별 통계
- [ ] 과금 데이터
  - [ ] GPU 시간 계산
  - [ ] 요청 수 기반 과금
  - [ ] 비용 예측

### 6.6 Edge & Container Deployment ⬜
**목표**: 자체 호스팅 배포 옵션

- [ ] Edge Package 생성
  - [ ] 경량 런타임 번들링
  - [ ] 플랫폼별 최적화 (ARM, x86)
  - [ ] 오프라인 추론 지원
- [ ] Container Image 빌드
  - [ ] Dockerfile 템플릿
  - [ ] Registry push (Docker Hub, GCR, ECR)
  - [ ] 이미지 크기 최적화
- [ ] Runtime Wrappers
  - [ ] Python SDK
  - [ ] C++ SDK
  - [ ] REST API 서버 포함 옵션

### 6.7 CI/CD Pipeline ⬜
**목표**: 자동화된 배포 파이프라인

- [ ] GitHub Actions 워크플로우
  - [ ] 테스트 자동화
  - [ ] 이미지 빌드
  - [ ] K8s 배포
- [ ] GitOps (ArgoCD)
  - [ ] 선언적 배포 관리
  - [ ] 롤백 자동화
- [ ] 카나리 배포
  - [ ] 트래픽 분할
  - [ ] 자동 롤백

**Reference**: [PHASE_3_6_EXPORT_DEPLOYMENT_PLAN.md](../planning/PHASE_3_6_EXPORT_DEPLOYMENT_PLAN.md)

---

## Phase 7: Trainer Marketplace (0%)

### 7.1 Trainer Validation Infrastructure ⬜
- [ ] Docker image validation
- [ ] API compliance testing
- [ ] Security scanning

### 7.2 Trainer Upload API ⬜
- [ ] Upload endpoint
- [ ] Registry integration
- [ ] Versioning

### 7.3 Frontend Upload UI ⬜
- [ ] Trainer 업로드 폼
- [ ] Validation 결과 표시

### 7.4 Marketplace ⬜
- [ ] Trainer 검색/브라우징
- [ ] Rating/Review
- [ ] Usage analytics

**Reference**: [TRAINER_MARKETPLACE_VISION.md](../planning/TRAINER_MARKETPLACE_VISION.md)

---

## Phase 8: Comprehensive E2E Testing (25%)

E2E 테스트는 프론트엔드가 보내는 모든 요청 조합을 검증해야 함.
핵심 원칙: "API가 동작하는가?"가 아니라 "프론트엔드의 모든 UI 조합이 동작하는가?"

### 8.1 Export Feature Tests ⬜

**8.1.1 ONNX Export Options**
- [ ] Basic export (opset_version only)
- [ ] With dynamic_axes enabled
- [ ] With validation_config
- [ ] Different opset versions (13, 14, 15, 16, 17, 18)
- [ ] With embed_preprocessing

**8.1.2 TensorRT Export Options**
- [ ] Basic export
- [ ] With FP16 precision
- [ ] With INT8 quantization
- [ ] Different max_batch_size values

**8.1.3 CoreML Export Options**
- [ ] Basic export
- [ ] Different minimum_deployment_target (iOS13-17)

**8.1.4 Other Formats**
- [ ] TFLite export
- [ ] TorchScript export
- [ ] OpenVINO export

**8.1.5 Export Download & Deploy Flow**
- [ ] Presigned URL generation
- [ ] Deployment creation (all types)
- [ ] Deployment activate/deactivate

### 8.2 Training Feature Tests ⬜

**8.2.1 Training Job Creation**
- [ ] Basic training config
- [ ] Custom hyperparameters (lr, epochs, batch_size)
- [ ] Different model selections
- [ ] Different task types (detection, segmentation, pose)

**8.2.2 Training Monitoring**
- [ ] Real-time metrics polling/WebSocket
- [ ] Progress tracking
- [ ] Checkpoint saving verification

**8.2.3 Training Completion**
- [ ] Best checkpoint saved
- [ ] Last checkpoint saved
- [ ] MLflow metrics logged

### 8.3 Inference Feature Tests ⬜

**8.3.1 Pretrained Model Inference**
- [x] YOLO pretrained weights
- [ ] Different image formats (jpg, png, webp)
- [ ] Batch inference

**8.3.2 Checkpoint Inference**
- [x] Custom trained checkpoint
- [ ] Best vs Last checkpoint selection

**8.3.3 Inference Results**
- [ ] Result visualization
- [ ] S3 result storage
- [ ] Result download

### 8.4 Dataset Management Tests ⬜

**8.4.1 Dataset Upload**
- [ ] Zip file upload
- [ ] Auto-format detection (YOLO, COCO, ImageFolder)
- [ ] Split ratio configuration

**8.4.2 Dataset Operations**
- [ ] Snapshot creation
- [ ] Dataset listing
- [ ] Dataset deletion

### 8.5 Deployment Feature Tests ⬜

**8.5.1 Platform Endpoint**
- [ ] Endpoint creation
- [ ] API key generation
- [ ] Inference via endpoint

**8.5.2 Other Deployment Types**
- [ ] Edge package creation
- [ ] Container image creation
- [ ] Direct download

### 8.6 API Schema Consistency Tests ⬜

**핵심: Frontend 요청 ↔ Backend 스키마 일치 검증**

- [ ] Export capabilities response (`supported_formats` vs `formats`)
- [ ] Export job request (all fields match schema)
- [ ] Deployment request (all fields match schema)
- [ ] Training job request (all fields match schema)
- [ ] Inference request (all fields match schema)

### 8.7 Error Handling Tests ⬜

- [ ] Invalid training_job_id handling
- [ ] Missing required fields handling
- [ ] Authentication errors
- [ ] File not found errors
- [ ] Network timeout handling

### 8.8 Test Infrastructure ⬜

- [ ] Test fixtures (sample datasets, checkpoints)
- [ ] CI/CD integration
- [ ] Test coverage reporting
- [ ] Automated regression testing

**References**:
- [E2E_TEST_GUIDE.md](../E2E_TEST_GUIDE.md)
- [EXPORT_DEPLOY_E2E_TEST_REPORT.md](./reference/EXPORT_DEPLOY_E2E_TEST_REPORT.md)

---

## Phase 9: Thin SDK Implementation (85%)

Trainer-Platform 통신 표준화를 위한 SDK 구현. 의존성 격리와 통일된 callback 스키마 제공.

**설계 문서**: [THIN_SDK_DESIGN.md](references/THIN_SDK_DESIGN.md)

**핵심 원칙**:
- 최소 의존성 (httpx, boto3, yaml만)
- Backend-proxied observability (MLflow/Loki/Prometheus는 Backend에서 처리)
- Fallback 없는 공격적 마이그레이션

### 9.1 SDK Core Development ⬜

**9.1.1 기본 구조**
- [ ] `trainer_sdk.py` 파일 생성
- [ ] 환경변수 로딩 (CALLBACK_URL, JOB_ID, storage credentials)
- [ ] HTTP client 설정 (httpx with retry)
- [ ] S3 client 설정 (boto3 dual storage)

**9.1.2 Lifecycle Functions (4개)**
- [ ] `report_started()` - 작업 시작 알림
- [ ] `report_progress()` - 학습 진행 보고 (epoch, metrics)
- [ ] `report_completed()` - 작업 완료 (checkpoints, final_metrics)
- [ ] `report_failed()` - 작업 실패 (error_type, message, traceback)

**9.1.3 Inference & Export Functions (2개)**
- [ ] `report_inference_completed()` - 추론 결과 보고
- [ ] `report_export_completed()` - 내보내기 결과 보고

**9.1.4 Storage Functions (4개)**
- [ ] `upload_checkpoint()` - 체크포인트 업로드
- [ ] `download_checkpoint()` - 체크포인트 다운로드
- [ ] `download_dataset()` - 데이터셋 다운로드
- [ ] `upload_file()` - 일반 파일 업로드

**9.1.5 Logging Function (1개)**
- [ ] `log_event()` - 구조화된 이벤트 로깅 (Backend → Loki)

**9.1.6 Data Utility Functions (5개)**
- [ ] `convert_dataset()` - 데이터셋 포맷 변환 (DICE→YOLO, COCO→YOLO)
- [ ] `create_data_yaml()` - YOLO data.yaml 생성
- [ ] `split_dataset()` - train/val/test 분할
- [ ] `validate_dataset()` - 데이터셋 검증
- [ ] `clean_dataset_cache()` - 캐시 파일 정리

### 9.2 Ultralytics Migration ⬜

**9.2.1 train.py 마이그레이션**
- [ ] CallbackClient → SDK lifecycle functions
- [ ] DualStorageClient → SDK storage functions
- [ ] MLflow 직접 호출 제거 (Backend에서 처리)
- [ ] convert_diceformat_to_yolo → SDK convert_dataset

**9.2.2 predict.py 마이그레이션**
- [ ] CallbackClient → SDK report_inference_completed

**9.2.3 export.py 마이그레이션**
- [ ] 직접 HTTP 호출 → SDK report_export_completed
- [ ] Metadata 생성 표준화

**9.2.4 utils.py 정리**
- [ ] CallbackClient 클래스 제거
- [ ] DualStorageClient 클래스 제거
- [ ] SDK로 이전된 함수 제거

### 9.3 Backend Callback Handler Update ⬜

**9.3.1 Observability 통합**
- [ ] Progress callback → MLflow log_metrics
- [ ] Progress callback → Prometheus gauge 업데이트
- [ ] Completion callback → MLflow end_run
- [ ] Log event callback → Loki push

**9.3.2 Callback API 표준화**
- [ ] 새 callback 엔드포인트: `/training/jobs/{job_id}/callback/log`
- [ ] SDK 스키마에 맞게 기존 엔드포인트 업데이트
- [ ] 에러 타입 기반 처리 로직

### 9.4 Testing & Validation ⬜

**9.4.1 Unit Tests**
- [ ] SDK 함수별 unit test
- [ ] Mock backend로 callback 검증
- [ ] Storage 함수 테스트

**9.4.2 Integration Tests**
- [ ] Training lifecycle E2E (started → progress → completed)
- [ ] Inference lifecycle E2E
- [ ] Export lifecycle E2E

**9.4.3 실제 학습 테스트**
- [ ] Ultralytics detection 학습
- [ ] Ultralytics segmentation 학습
- [ ] Export 및 inference 테스트

---

## Phase 10: Training SDK Implementation (90%)

Training 파이프라인 전체 구현을 위한 SDK 개발. Dataset 처리, Config 로딩, Lifecycle 콜백, 로깅 시스템을 포함.

**설계 문서**: [TRAINING_PIPELINE_DESIGN.md](reference/TRAINING_PIPELINE_DESIGN.md)
**E2E 테스트 리포트**: [TRAINING_SDK_E2E_TEST_REPORT.md](reference/TRAINING_SDK_E2E_TEST_REPORT.md)

**핵심 목표**:
- DICE format 데이터셋 처리 및 변환
- Basic/Advanced Config 환경변수 로딩
- 완전한 Training lifecycle 콜백 시스템
- 실시간 로그 수집 및 표시

### 10.1 Dataset Handling ✅

**10.1.1 DICE Format Support**
- [x] Task별 annotation 파일 선택 (`annotations_detection.json`, `annotations_classification.json`)
- [x] SDK `download_dataset(dataset_id, task_type)` 메서드
- [x] S3에서 DICE format 데이터셋 다운로드
- [x] task_type에 따른 annotation 파일 자동 선택

**10.1.2 Format Conversion**
- [x] DICE → YOLO format 변환 (Ultralytics)
- [ ] DICE → ImageFolder format 변환 (timm)
- [x] data.yaml 자동 생성
- [x] 클래스 정보 추출 (classes 배열에서)

**10.1.3 Dataset Query API**
- [ ] `GET /api/v1/datasets` - task_type 필터 지원
- [ ] `GET /api/v1/datasets/{id}` - annotation 파일 정보 포함
- [ ] annotations 섹션에 task별 파일 경로 및 클래스 정보

### 10.2 Config Loading ✅

**10.2.1 Basic Config (공통)**
- [x] Backend → Trainer 환경변수 주입 (`CONFIG_IMGSZ`, `CONFIG_EPOCHS`, etc.)
- [x] SDK `get_basic_config()` 메서드
- [x] 기본값 처리 및 타입 변환
- [x] 필수 파라미터 검증

**10.2.2 Advanced Config (Framework별)**
- [x] `ADVANCED_CONFIG` 환경변수 (JSON 문자열)
- [x] SDK `get_advanced_config()` 메서드
- [x] JSON 파싱 및 default 값 처리
- [ ] Framework별 파라미터 문서화 (Ultralytics, timm, HuggingFace)

**10.2.3 Full Config Interface**
- [x] SDK `get_full_config()` 메서드 (basic + advanced)
- [x] SDK properties: `model_name`, `dataset_id`, `task_type`, `framework`
- [ ] Config 파일 방식 지원 (대규모 config용)

### 10.3 Training Lifecycle Callbacks ✅

**10.3.1 Started Callback**
- [x] `POST /api/v1/training/jobs/{id}/callback/progress` (uses TrainingProgressCallback format)
- [x] SDK `report_started(operation_type, total_epochs)` 메서드
- [x] 상태 변경: pending → running
- [x] WebSocket broadcast

**10.3.2 Progress Callback**
- [x] `POST /api/v1/training/jobs/{id}/callback/progress`
- [x] SDK `report_progress(epoch, total_epochs, metrics)` 메서드
- [x] DB 업데이트 (`current_epoch`)
- [x] MLflow epoch marker 로깅

**10.3.3 Metrics Callback**
- [x] SDK `report_progress()` with `TrainingCallbackMetrics`
- [x] 메트릭 테이블 저장
- [x] MLflow log_metrics
- [ ] Early stopping 조건 체크

**10.3.4 Checkpoint Callback**
- [x] SDK `upload_checkpoint(local_path, checkpoint_type, is_best)` 메서드
- [x] `checkpoint_best_path`, `checkpoint_last_path` 업데이트
- [ ] MLflow artifact 로깅

**10.3.5 Completion Callback**
- [x] `POST /api/v1/training/jobs/{id}/callback/completed`
- [x] SDK `report_completed(best_epoch, best_metric_value, checkpoints)` 메서드
- [x] 상태 변경: running → completed
- [x] MLflow run 종료

**10.3.6 Failed Callback** ✅
- [x] `POST /api/v1/training/jobs/{id}/callback/completion` (status='failed')
- [x] SDK `report_failed(error_message, error_type, traceback)` 메서드
- [x] 상태 변경: running → failed
- [x] 에러 정보 저장 (error_message, traceback, exit_code)
- [x] ErrorType 클래스 (8가지 구조화된 에러 타입)

**10.3.7 Error Handling 강화** 🔄 (50%)
- [x] SDK ErrorType 정의 (DATASET_ERROR, CONFIG_ERROR, RESOURCE_ERROR, etc.)
- [x] SDK report_failed() 구현
- [x] Backend failed callback 처리
- [x] 기본 Unit 테스트 (test_sdk_integration.py)
- [ ] E2E 에러 핸들링 테스트 (각 ErrorType별 실제 실패 시나리오)
- [ ] SDK callback 재시도 로직 (exponential backoff, 최대 3회)
- [ ] 에러 모니터링 구성 (Grafana 대시보드, Loki 쿼리)
- [ ] Frontend 에러 표시 UI 테스트

### 10.4 Logging System ✅

**10.4.1 Log Callback API**
- [x] `POST /api/v1/training/jobs/{id}/callback/log`
- [x] 단일 로그 전송 (`LogEventCallback` format)
- [x] Log levels: DEBUG, INFO, WARNING, ERROR

**10.4.2 SDK Log Methods**
- [x] `sdk.log(message, level, **metadata)` - 기본 메서드
- [x] `sdk.log_info()`, `sdk.log_warning()`, `sdk.log_error()`, `sdk.log_debug()`
- [x] `sdk.flush_logs()` - 버퍼 flush

**10.4.3 Log Storage**
- [x] `training_logs` 테이블 생성
- [x] 인덱스 설정 (job_id, timestamp, level)
- [x] metadata JSONB 필드

**10.4.4 Log Query API**
- [x] `GET /api/v1/training/jobs/{id}/logs`
- [x] 필터: level, limit, offset, since, until
- [x] 페이지네이션 지원

**10.4.5 Log Buffering**
- [x] SDK 내 로그 버퍼 (50개)
- [x] ERROR 레벨 즉시 전송
- [x] 자동 flush 로직

**10.4.6 Real-time Streaming**
- [ ] WebSocket log 메시지 타입
- [ ] Frontend 실시간 로그 수신
- [ ] 로그 레벨별 색상 표시

### 10.5 Backend Updates ✅

**10.5.1 Training Job Creation** ✅ (2025-11-20 완료)
- [x] `config` + `advanced_config` 분리 저장
- [x] 환경변수 주입 로직 업데이트 - **COMPLETE**
  - [x] `training_subprocess.py` 업데이트
    - [x] `TASK_TYPE`, `FRAMEWORK`, `DATASET_ID` 환경변수 추가
    - [x] `EPOCHS`, `BATCH_SIZE`, `LEARNING_RATE` 환경변수 추가
    - [x] `IMGSZ`, `DEVICE` 환경변수 추가
    - [x] `CONFIG` JSON 직렬화 (advanced_config, primary_metric 등)
  - [x] SDK 환경변수 이름 통일 (우선순위 기반 지원)
    - [x] `EPOCHS` (새) 우선, `CONFIG_EPOCHS` (구) 백워드 호환
    - [x] `BATCH_SIZE` (새) 우선, `CONFIG_BATCH` (구) 백워드 호환
    - [x] `LEARNING_RATE` (새) 우선, `CONFIG_LR0` (구) 백워드 호환
  - [x] SDK에 CONFIG JSON 파싱 로직 추가
    - [x] `get_basic_config()` 우선순위: 개별 env var > CONFIG JSON > CONFIG_ env var > 기본값
    - [x] `get_advanced_config()` CONFIG JSON 'advanced_config' 필드 파싱
  - [x] 테스트 호환성 유지 (기존 CONFIG_ 환경변수 백워드 호환)

**10.5.2 Callback Endpoints**
- [ ] 모든 lifecycle callback API 구현
- [ ] Log callback API 구현
- [ ] WebSocket broadcast 통합

**10.5.3 WebSocket Updates**
- [ ] `log` 메시지 타입 추가
- [ ] timestamp 필드 추가
- [ ] 실시간 로그 streaming

**10.5.4 Database Updates**
- [ ] `training_logs` 테이블 마이그레이션
- [ ] TrainingJob에 `advanced_config` 컬럼 추가

### 10.6 Ultralytics Trainer Migration ⬜

**10.6.1 train.py 업데이트**
- [ ] SDK config 로딩 (`get_basic_config`, `get_advanced_config`)
- [ ] Dataset 다운로드 및 YOLO 변환
- [ ] Lifecycle callbacks 통합
- [ ] 로깅 시스템 적용

**10.6.2 Callback Integration**
- [ ] YOLO 콜백에서 SDK 호출
- [ ] Epoch 시작/종료 progress 전송
- [ ] Step별 metrics 전송
- [ ] Checkpoint 저장 시 콜백

### 10.7 Frontend Updates ⬜

**10.7.1 Log Viewer Panel**
- [ ] TrainingPanel에 Log 탭 추가
- [ ] 실시간 로그 스트리밍
- [ ] 로그 레벨 필터
- [ ] 로그 검색

**10.7.2 Training Config UI**
- [ ] Basic/Advanced config 분리 UI
- [ ] Framework별 advanced config 폼
- [ ] Config 검증 피드백

### 10.8 Testing ✅

**10.8.1 SDK Unit Tests** (`test_sdk_features.py`)
- [x] SDK Properties 테스트
- [x] Config 로딩 테스트 (basic, advanced, full)
- [x] Log 버퍼링 테스트
- [x] Task-specific annotation 선택 테스트
- [x] Fallback annotation 테스트

**10.8.2 Integration Tests** (`test_sdk_integration.py`)
- [x] Training lifecycle E2E (started → progress → metrics → checkpoint → completed)
- [x] Log 수집 및 조회 테스트
- [ ] WebSocket 실시간 업데이트 테스트

**10.8.3 E2E Tests** (`test_training_e2e.py`)
- [x] Ultralytics detection training E2E - **PASS**
- [ ] Ultralytics segmentation training E2E
- [x] Config 적용 검증
- [x] Dataset download/convert 검증
- [x] All SDK callbacks 검증

**Test Report**: [TRAINING_SDK_E2E_TEST_REPORT.md](reference/TRAINING_SDK_E2E_TEST_REPORT.md)

---

## Phase 11: Microservice Separation (33%)

Platform-Labeler 마이크로서비스 분리를 위한 데이터베이스 격리 작업. 3-tier 전략으로 단계적 마이그레이션.

**설계 문서**: [PHASE_11_MICROSERVICE_SEPARATION.md](../planning/PHASE_11_MICROSERVICE_SEPARATION.md)

**3-Tier 전략**:
- **Tier 1 (Local)**: SQLite 기반 Shared User DB (Platform/Labeler 공유)
- **Tier 2 (Railway)**: PostgreSQL 기반 User DB (프로덕션 프리뷰)
- **Tier 3 (K8s)**: 완전한 마이크로서비스 분리 (독립 DB, service mesh)

### 11.1 Tier 1: Shared User DB (Local SQLite) ✅

**목표**: 로컬 개발에서 Platform DB와 User DB 분리

**11.1.1 Database Configuration** ✅
- [x] `USER_DATABASE_URL` 설정 추가 (config.py)
- [x] 기본값: Windows `C:/temp/shared_users.db`, Linux `/tmp/shared_users.db`
- [x] `.env.example` 문서화

**11.1.2 Database Refactoring** ✅
- [x] 2-DB 엔진 분리 (`platform_engine`, `user_engine`)
- [x] SessionLocal 분리 (`PlatformSessionLocal`, `UserSessionLocal`)
- [x] `get_db()` - Platform DB dependency
- [x] `get_user_db()` - Shared User DB dependency
- [x] Backward compatibility aliases (`SessionLocal`, `engine`)
- [x] `init_db()`, `init_user_db()` 분리

**11.1.3 Migration Script** ✅
- [x] `scripts/phase11/init_shared_user_db.py` 생성
- [x] User 관련 테이블 복사 (users, organizations, invitations, project_members, sessions)
- [x] FK 관계 순서 고려한 마이그레이션

**11.1.4 API Endpoint Updates** ✅
- [x] `auth.py` - 모든 엔드포인트 `get_user_db()` 사용
- [x] `dependencies.py` - `get_current_user()` User DB 조회
- [x] `admin.py` - 2-DB 패턴, application-level join 구현
- [x] `invitations.py` - 2-DB 패턴 적용
- [x] `projects.py` - `get_user_db` import 추가
- [x] 기타 user 참조 엔드포인트 업데이트

**11.1.5 Platform DB Cleanup** ✅
- [x] `scripts/phase11/cleanup_platform_db_user_tables.py` 생성
- [x] 16개 FK 제약조건 제거 (user_id, owner_id, created_by 참조)
- [x] 5개 User 관련 테이블 삭제 (users, organizations, invitations, project_members, sessions)
- [x] `init_db()` User 테이블 재생성 방지
- [x] Admin user 생성을 User DB로 이동

**11.1.6 Backend Startup** ✅
- [x] `main.py` startup event 업데이트
- [x] Platform DB, User DB 분리 초기화
- [x] Admin user 생성을 `UserSessionLocal()` 사용
- [x] Startup log 메시지 개선

**11.1.7 Bug Fixes** ✅
- [x] UserRole enum `values_callable` 추가 (value 기반 매핑)
- [x] SessionLocal import 에러 해결 (backward compatibility)
- [x] invitations.py duplicate parameter 제거
- [x] Frontend utility files 복원 (cn.ts, avatarColors.ts, etc.)
- [x] .gitignore 업데이트 (`!**/frontend/lib/`)

**11.1.8 Testing** ✅
- [x] Backend 시작 검증
- [x] Login API 테스트 (POST /api/v1/auth/login)
- [x] User 조회 테스트 (GET /api/v1/auth/me)
- [x] Admin 엔드포인트 테스트
- [x] Platform DB User 테이블 부재 확인
- [x] User DB 5명 사용자 확인

**완료일**: 2025-11-23

### 11.2 Tier 2: Local Docker PostgreSQL User DB ✅

**목표**: 로컬 개발에서 프로덕션 환경과 동일한 PostgreSQL 사용

**11.2.1 Docker Compose Setup** ✅
- [x] `docker-compose.tier0.yaml`에 postgres-user 서비스 추가 (port 5433)
- [x] Volume 설정: `C:/platform-data/postgres-user`
- [x] Health check 구성
- [x] Platform DB (5432) + User DB (5433) 완전 분리

**11.2.2 Migration Script** ✅
- [x] `scripts/phase11/migrate_sqlite_to_postgresql.py` 생성
- [x] SQLite → PostgreSQL 데이터 마이그레이션 (7 rows)
- [x] FK 순서 고려 (organizations → users → invitations → project_members)
- [x] Idempotent migration (SQLAlchemy merge 사용)
- [x] Sessions 테이블 제외 (Phase 5에서 Redis로 마이그레이션됨)

**11.2.3 PostgreSQL Enum Fix** ✅
- [x] UserRole enum 재생성 (lowercase values)
- [x] `CREATE TYPE userrole AS ENUM ('admin', 'manager', 'advanced_engineer', 'standard_engineer', 'guest')`
- [x] Enum value mapping 수정 (`values_callable` 추가)

**11.2.4 Environment Configuration** ✅
- [x] `.env` 업데이트: `USER_DATABASE_URL=postgresql://admin:devpass@localhost:5433/users`
- [x] Config documentation 업데이트

**11.2.5 K8s PVC Preparation** ✅
- [x] `platform-postgres-pvc.yaml` 생성 (10Gi)
- [x] `user-postgres-pvc.yaml` 생성 (5Gi)
- [x] Retain reclaim policy 설정
- [x] K8s PVC 문서화 (backup/resize/monitoring)

**11.2.6 Testing** ✅
- [x] Backend 시작 검증
- [x] Login API 테스트 (200 OK)
- [x] User 조회 테스트 (200 OK)
- [x] Platform DB에 User 테이블 없음 확인
- [x] User DB에 5명 사용자 확인

**11.2.7 PR & Merge** ✅
- [x] PR #38 생성 및 merge
- [x] Merge conflict 해결
- [x] main 브랜치 업데이트

**완료일**: 2025-11-24

### 11.3 Tier 3: Railway PostgreSQL User DB ⬜

**목표**: Railway 환경에서 프로덕션 프리뷰 테스트

**11.3.1 Railway User DB Setup** ⬜
- [ ] Railway PostgreSQL 인스턴스 생성 (User DB 전용)
- [ ] `USER_DATABASE_URL` 환경변수 설정
- [ ] Platform DB와 User DB 분리 확인

**11.3.2 Migration to Railway** ⬜
- [ ] User 데이터 Railway PostgreSQL로 마이그레이션
- [ ] Application-level join 성능 테스트
- [ ] 프로덕션 동작 검증

**11.3.3 Testing** ⬜
- [ ] Railway 환경 E2E 테스트
- [ ] 성능 벤치마크 (application-level join)
- [ ] 에러 케이스 검증

### 11.4 Tier 4: K8s Microservice Separation ⬜

**목표**: 완전한 마이크로서비스 분리 (Labeler 서비스 독립 실행)

**11.4.1 Labeler Service** ⬜
- [ ] Labeler 독립 FastAPI 서비스 생성
- [ ] User DB 연결 (Shared User DB)
- [ ] Labeler-specific 기능 분리

**11.4.2 Service Mesh** ⬜
- [ ] Istio/Linkerd 설정
- [ ] Service discovery
- [ ] mTLS 인증

**11.4.3 K8s Deployment** ⬜
- [ ] Platform Service Deployment
- [ ] Labeler Service Deployment
- [ ] Shared User DB (PostgreSQL Operator)
- [ ] PVC 적용 (platform-postgres-pvc, user-postgres-pvc)

**11.4.4 Testing** ⬜
- [ ] 독립 서비스 동작 검증
- [ ] Cross-service 인증 테스트
- [ ] 장애 격리 테스트

## Phase 12: Backend Refactoring & ClearML Migration (0%)

Backend 코드 품질 개선 및 MLOps 플랫폼을 MLflow에서 ClearML로 전환.

**목표**:
1. Legacy 코드 제거 및 패턴 통일
2. ClearML로의 완전한 마이그레이션
3. 코드베이스 단순화 및 유지보수성 향상

**예상 기간**: 7-8일
**Reference**: [BACKEND_REFACTORING_PLAN.md](BACKEND_REFACTORING_PLAN.md), [CLEARML_MIGRATION_PLAN.md](reference/CLEARML_MIGRATION_PLAN.md)

---

### 12.1 Dead Code 제거 (Day 1) ⬜

**목표**: 사용되지 않는 Training Manager 코드 제거

**12.1.1 Training Manager Cleanup**
- [ ] `app/utils/training_client.py` 제거 (115 lines)
- [ ] `app/utils/training_manager.py` 제거
- [ ] `app/utils/training_manager_k8s.py` 제거
- [ ] Import 확인 및 정리

**12.1.2 Verification**
- [ ] 모든 테스트 통과 확인
- [ ] Backend 정상 실행 확인
- [ ] Training job 생성/실행 정상 동작

**예상 시간**: 0.5일
**위험도**: ⭕ Low (사용되지 않는 코드)

---

### 12.2 MLflow → ClearML Migration (Day 2-4) ⬜

**목표**: MLflow를 ClearML로 완전히 교체

**12.2.1 ClearML Setup**
- [ ] ClearML Server 배포 (Docker Compose / Kind)
  - [ ] `docker-compose.tier0.yaml`에 clearml-server 추가
  - [ ] API Server, Web UI, File Server 구성
  - [ ] PostgreSQL, MongoDB, Elasticsearch 연동
- [ ] ClearML 환경변수 설정
  - [ ] `CLEARML_API_HOST`, `CLEARML_WEB_HOST`, `CLEARML_FILES_HOST`
  - [ ] `CLEARML_API_ACCESS_KEY`, `CLEARML_API_SECRET_KEY`
- [ ] Kind에 ClearML Helm chart 배포

**12.2.2 ClearML Service 구현**
- [ ] `app/services/clearml_service.py` 생성
  - [ ] Task 생성/조회/업데이트
  - [ ] Metrics 로깅
  - [ ] Artifacts 업로드
  - [ ] Experiment/Project 관리
- [ ] TrainingJob ↔ ClearML Task 매핑
  - [ ] `clearml_task_id` 필드 추가
  - [ ] Task 자동 생성 로직
  - [ ] Status 동기화

**12.2.3 Backend API Updates**
- [ ] `training.py` - MLflowService → ClearMLService 교체
  - [ ] `get_mlflow_client()` 제거 (4 locations)
  - [ ] `MLflowService` → `ClearMLService` 전환
  - [ ] Metrics API 업데이트
- [ ] `experiments.py` - ClearML Project/Experiment 연동
  - [ ] MLflow Experiment → ClearML Project 마이그레이션
  - [ ] Experiment CRUD API 업데이트

**12.2.4 Training SDK Updates**
- [ ] SDK `report_progress()` - ClearML Task.current_task() 사용
- [ ] Metrics 로깅 방식 변경
  - [ ] MLflow `log_metrics()` → ClearML `task.logger.report_scalar()`
  - [ ] Step-based logging 지원
- [ ] Checkpoint 업로드
  - [ ] MLflow artifacts → ClearML task.upload_artifact()

**12.2.5 Database Migration**
- [ ] `clearml_task_id` 컬럼 추가 (TrainingJob, InferenceJob, ExportJob)
- [ ] `experiments` 테이블 업데이트
  - [ ] `mlflow_experiment_id` → `clearml_project_id`
  - [ ] 기존 데이터 마이그레이션 스크립트

**12.2.6 Frontend Updates**
- [ ] MLflow 메트릭 차트 → ClearML Web UI 임베드
- [ ] Experiment 페이지 UI 업데이트
- [ ] ClearML Task ID 표시

**12.2.7 MLflow Cleanup**
- [ ] MLflow 관련 코드 제거
  - [ ] `app/utils/mlflow_client.py` 제거
  - [ ] `app/services/mlflow_service.py` 제거
  - [ ] MLflow 관련 import 정리
- [ ] Docker Compose에서 MLflow 제거
- [ ] Environment variables 정리

**예상 시간**: 3일
**위험도**: ⚠️ High (핵심 기능 변경)

**Reference**: [CLEARML_MIGRATION_PLAN.md](reference/CLEARML_MIGRATION_PLAN.md)

---

### 12.3 Storage 클라이언트 통일 (Day 5-6) ⬜

**목표**: Storage 접근 방식을 `dual_storage` 싱글톤으로 통일

**12.3.1 Pattern Analysis**
- [ ] 현재 storage 사용 패턴 분석
  - [ ] `storage_utils.get_storage_client()` - 5회
  - [ ] `dual_storage` (싱글톤) - 3회
  - [ ] `DualStorageClient` (클래스) - 2회
  - [ ] `s3_storage` (싱글톤) - 1회

**12.3.2 Migration**
- [ ] `app/api/export.py` - dual_storage 싱글톤으로 통일
- [ ] `app/api/inference.py` - dual_storage 싱글톤으로 통일
- [ ] `app/api/datasets.py` - dual_storage 싱글톤으로 통일
- [ ] `app/api/training.py` - dual_storage 싱글톤으로 통일

**12.3.3 Cleanup**
- [ ] `storage_utils.py` deprecation 또는 제거
- [ ] Import 정리

**12.3.4 Verification**
- [ ] Export E2E 테스트
- [ ] Inference E2E 테스트
- [ ] Dataset upload 테스트
- [ ] Training checkpoint upload 테스트

**예상 시간**: 2일
**위험도**: ⚠️ Low-Medium

---

### 12.4 Callback 로직 리팩토링 (Day 7-8) ⬜

**목표**: 3개 callback endpoint의 공통 로직 추출

**12.4.1 TrainingCallbackService 생성**
- [ ] `app/services/training_callback_service.py` 생성
- [ ] 공통 메서드 구현
  - [ ] `_get_job_or_404(job_id)` - Job 조회
  - [ ] `handle_progress(job_id, callback)` - Progress callback
  - [ ] `handle_completion(job_id, callback)` - Completion callback
  - [ ] `handle_log(job_id, callback)` - Log callback
- [ ] ClearML 통합
  - [ ] Progress → ClearML metrics 로깅
  - [ ] Completion → ClearML task 종료
  - [ ] Log → ClearML console 로깅

**12.4.2 training.py Endpoint 간소화**
- [ ] `/jobs/{job_id}/callback/progress` - TrainingCallbackService 사용
- [ ] `/jobs/{job_id}/callback/completion` - TrainingCallbackService 사용
- [ ] `/jobs/{job_id}/callback/log` - TrainingCallbackService 사용
- [ ] 중복 코드 제거 (50+ lines → 10 lines per endpoint)

**12.4.3 WebSocket 통합**
- [ ] `TrainingCallbackService`에서 WebSocket broadcast
- [ ] 일관된 메시지 포맷

**12.4.4 Testing**
- [ ] Unit tests for TrainingCallbackService
- [ ] Integration tests for callback endpoints
- [ ] E2E training lifecycle test

**예상 시간**: 2일
**위험도**: ⭕ Low

---

### 12.5 Testing & Validation ⬜

**목표**: 모든 리팩토링 검증

**12.5.1 Unit Tests**
- [ ] ClearMLService unit tests
- [ ] TrainingCallbackService unit tests
- [ ] Storage 함수 테스트

**12.5.2 Integration Tests**
- [ ] Training lifecycle with ClearML
- [ ] Metrics logging 검증
- [ ] Checkpoint upload/download

**12.5.3 E2E Tests**
- [ ] Complete training flow (create → progress → complete)
- [ ] Export with ClearML logging
- [ ] Inference with ClearML tracking

**12.5.4 Performance Tests**
- [ ] ClearML vs MLflow 성능 비교
- [ ] Storage operation 성능 측정

---

### 12.6 Documentation Updates ⬜

**목표**: 변경사항 문서화

- [ ] ARCHITECTURE.md - ClearML 통합 섹션 업데이트
- [ ] API_SPECIFICATION.md - Experiment API 업데이트
- [ ] DEVELOPMENT.md - ClearML 설정 가이드
- [ ] TIER0_SETUP.md - ClearML Server 설정
- [ ] Migration guide 작성 (MLflow → ClearML)

---

## Phase 12 Success Criteria

**리팩토링 완료 기준**:
- [ ] 모든 Dead code 제거 (~500 lines)
- [ ] MLflow 완전히 제거, ClearML로 100% 전환
- [ ] Storage 패턴 100% 통일 (dual_storage 싱글톤)
- [ ] Callback 로직 집중화 (TrainingCallbackService)
- [ ] 모든 E2E 테스트 통과
- [ ] 성능 저하 없음 (또는 개선)

**ClearML 마이그레이션 성공 기준**:
- [ ] ClearML Web UI에서 모든 Training/Inference/Export job 조회 가능
- [ ] 실시간 metrics 업데이트
- [ ] Artifacts (checkpoints, models) 자동 업로드
- [ ] Experiment 비교 기능 사용 가능
- [ ] 기존 MLflow 데이터 마이그레이션 완료

**코드 품질 기준**:
- [ ] No deprecated warnings
- [ ] 패턴 일관성 100%
- [ ] 테스트 커버리지 85%+
- [ ] 문서 업데이트 완료


---

## Phase 3 References

| Document | Description |
|----------|-------------|
| [EXPORT_CONVENTION.md](../EXPORT_CONVENTION.md) | Export convention for trainers |
| [ADVANCED_CONFIG_SCHEMA.md](../ADVANCED_CONFIG_SCHEMA.md) | Dynamic config schema system |
| [PHASE_3_5_INFERENCE_PLAN.md](../planning/PHASE_3_5_INFERENCE_PLAN.md) | Inference feature design |
| [PHASE_3_6_EXPORT_DEPLOYMENT_PLAN.md](../planning/PHASE_3_6_EXPORT_DEPLOYMENT_PLAN.md) | Export & deployment system |
| [MODEL_CAPABILITIES_SYSTEM.md](../MODEL_CAPABILITIES_SYSTEM.md) | Model capabilities design |
| [INFERENCE_JOB_PATTERN.md](../INFERENCE_JOB_PATTERN.md) | InferenceJob async pattern |
| [E2E_TEST_GUIDE.md](../E2E_TEST_GUIDE.md) | E2E testing principles |

---

## Quick Links

- **Main Checklist**: [MVP_TO_PLATFORM_CHECKLIST.md](../planning/MVP_TO_PLATFORM_CHECKLIST.md) (상세 진행 로그)
- **Migration Guide**: [MVP_TO_PLATFORM_MIGRATION.md](../planning/MVP_TO_PLATFORM_MIGRATION.md)
- **Session Logs**: [CONVERSATION_LOG.md](../CONVERSATION_LOG.md)
