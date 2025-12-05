# Vision AI Training Platform

> 자연어로 Vision 모델을 학습하는 AI 플랫폼

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Node](https://img.shields.io/badge/node-20.x-green.svg)](https://nodejs.org/)

## 🎯 개요

Vision AI Training Platform은 개발자가 자연어로 대화하듯 Vision 모델을 학습할 수 있는 플랫폼입니다.

**주요 기능:**
- 🗣️ 자연어 기반 모델 설정
- 🚀 다양한 모델 아키텍처 지원 (timm, Ultralytics YOLO 등)
- 📊 실시간 학습 모니터링 (ClearML, MLflow, W&B, Database - 선택 가능)
- 🔄 Temporal 워크플로우 오케스트레이션
- 🔌 원클릭 추론 API 생성
- 🎨 직관적인 UI/UX

**현재 상태:**
- ✅ **MVP 완료** - 자연어 기반 학습, 실시간 모니터링, Kubernetes 학습 실행
- ⏳ **Platform 개발 진행 중** - 3-tier 환경 격리, 프로덕션 배포 준비

## 🏗️ 아키텍처

### MVP 아키텍처 (완료)
```
Frontend (Next.js) ←→ Backend (FastAPI) ←→ Training Service
                          ↓                      ↓
                    PostgreSQL           Kubernetes Jobs
                          ↓                      ↓
                     MLflow API          MLflow Tracking
```

### Platform 아키텍처 (개발 중)
```
3-Tier Isolated Environment:
┌─────────────────────────────────────────────────┐
│ Tier 1: Subprocess (Local Dev)                 │
│   - Training in subprocess                     │
│   - MinIO (local), MLflow (local)              │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│ Tier 2: Kind (K8s Dev)                         │
│   - Training in Kubernetes Jobs               │
│   - MinIO (cluster), MLflow (cluster)          │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│ Tier 3: Production (AWS/GCP)                   │
│   - Training in Kubernetes Jobs               │
│   - S3/R2, MLflow (production)                 │
└─────────────────────────────────────────────────┘
```

[Platform 아키텍처 상세 →](platform/docs/architecture/)

## 🚀 Quick Start

### MVP 개발 환경 시작

> **처음 시작하시나요?** [MVP 시작 가이드](mvp/docs/guides/GETTING_STARTED.md)를 참고하세요.

**Prerequisites:**
```bash
- Docker Desktop 4.26+
- Kind (Kubernetes in Docker)
- kubectl 1.28+
```

**설치 (Windows):**
```powershell
# Kind 설치
winget install -e --id Kubernetes.kind

# kubectl 설치
winget install -e --id Kubernetes.kubectl
```

**개발 환경 시작:**
```powershell
# 1. 레포지토리 클론
git clone https://github.com/your-org/mvp-vision-ai-platform.git
cd mvp-vision-ai-platform

# 2. MVP 개발 환경 시작
cd mvp
.\dev-start.ps1

# 완료! 다음 서비스에 접근 가능:
# - MLflow:     http://localhost:30500
# - Grafana:    http://localhost:30030 (admin/admin)
# - Prometheus: http://localhost:30090
# - MinIO:      http://localhost:30901 (minioadmin/minioadmin)
```

[MVP 개발 워크플로우 →](mvp/docs/guides/DEV_WORKFLOW.md)

### Platform 개발 환경

Platform 개발은 3-tier 환경 격리 전략을 따릅니다:

```powershell
# Tier 1: Subprocess 모드 (가장 빠른 개발)
python platform/backend/main.py --mode subprocess

# Tier 2: Kind 클러스터 (Kubernetes 테스트)
.\platform\scripts\kind-setup.ps1

# Tier 3: Production (AWS/GCP)
# See platform/docs/deployment/
```

[3-Tier 개발 가이드 →](platform/docs/development/3_TIER_DEVELOPMENT.md)

## 📦 프로젝트 구조

```
mvp-vision-ai-platform/
├── mvp/                      # ✅ MVP 구현 (완료, 유지 모드)
│   ├── backend/              # FastAPI backend
│   ├── frontend/             # Next.js frontend
│   ├── training/             # Training scripts (timm, ultralytics)
│   ├── infrastructure/       # Docker Compose, K8s manifests
│   ├── scripts/              # Dev scripts (dev-*.ps1)
│   └── docs/                 # MVP 문서
│
├── platform/                 # ⏳ Platform 구현 (개발 중)
│   ├── backend/              # Platform backend (3-tier support)
│   ├── training-services/    # Framework-specific services
│   ├── infrastructure/       # Production K8s, Terraform
│   └── docs/                 # Platform 설계 문서
│
├── docs/                     # 프로젝트 공용 문서
│   └── CONVERSATION_LOG.md   # 개발 히스토리
│
└── README.md                 # 현재 파일
```

## 🛠️ 기술 스택

**MVP Stack:**
- Frontend: Next.js 14, React 18, TailwindCSS, Zustand
- Backend: FastAPI, Python 3.11, PostgreSQL, SQLite
- Training: PyTorch, timm, Ultralytics YOLO
- Monitoring: MLflow, Prometheus, Grafana
- Infrastructure: Docker Compose, Kind (Kubernetes)

**Platform Stack (추가):**
- Framework Services: timm-service, ultralytics-service, huggingface-service
- Storage: S3/R2, MinIO (all tiers)
- Orchestration: Temporal (production-ready)
- Observability: ClearML, MLflow, Weights & Biases (multi-backend support)
- Deployment: Terraform, AWS/GCP Kubernetes

[전체 기술 스택 →](platform/docs/architecture/BACKEND_DESIGN.md)

## 📖 문서

### MVP 문서 (완료)
- [MVP 문서 인덱스](mvp/docs/README.md)
- [시작 가이드](mvp/docs/guides/GETTING_STARTED.md)
- [개발 워크플로우](mvp/docs/guides/DEV_WORKFLOW.md)
- [MVP 아키텍처](mvp/docs/architecture/)
- [LLM 통합](mvp/docs/llm/)

### Platform 문서 (개발 중)
- [Platform 문서 인덱스](platform/docs/README.md)
- [Platform 아키텍처](platform/docs/architecture/)
- [3-Tier 개발](platform/docs/development/3_TIER_DEVELOPMENT.md)
- [에러 핸들링](platform/docs/architecture/ERROR_HANDLING_DESIGN.md)
- [운영 가이드](platform/docs/architecture/OPERATIONS_RUNBOOK.md)
- [설계 리뷰](platform/docs/reviews/)

### 공용 문서
- [개발 히스토리](docs/CONVERSATION_LOG.md)

## 🎯 사용 예시

### 자연어로 모델 학습

```
User: "YOLO11n으로 객체 탐지 모델 만들어줘. 클래스는 person, car, dog"

AI: 알겠습니다! 다음 설정으로 진행할게요:
    - Model: yolo11n
    - Task: Object Detection
    - Classes: person, car, dog (3개)
    - Epochs: 100 (권장)
    - Image Size: 640x640

    데이터셋 경로를 알려주세요. (YOLO format)

User: "data/coco-subset"

AI: 학습을 시작합니다! 🚀
    MLflow Run: http://localhost:30500/#/experiments/1/runs/abc123
```

### 실시간 모니터링

- 📊 Epoch 진행률, Loss/mAP 실시간 업데이트
- 💻 GPU/메모리 사용량 모니터링 (Prometheus + Grafana)
- 📈 Training Metrics 시각화 (MLflow)
- 🔔 학습 완료 WebSocket 알림

### 추론 API 생성 (planned)

학습 완료 후 원클릭으로 REST API 생성:

```bash
curl -X POST https://api.vision-platform.com/inference/{job_id}/predict \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "image=@sample.jpg"

# Response
{
  "predictions": [
    {"class": "person", "confidence": 0.95, "bbox": [10, 20, 100, 200]},
    {"class": "car", "confidence": 0.87, "bbox": [150, 30, 300, 250]}
  ]
}
```

## 🤝 기여하기

기여를 환영합니다! [CONTRIBUTING.md](CONTRIBUTING.md)를 참고해주세요.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📊 개발 현황

### ✅ MVP Phase (완료)
- [x] 기본 UI/UX (Chat 기반 인터페이스)
- [x] 자연어 파싱 (Gemini LLM)
- [x] timm 모델 지원 (ResNet, EfficientNet)
- [x] Ultralytics YOLO 지원 (Detection, Segmentation, Pose)
- [x] Kubernetes 학습 실행 (Kind)
- [x] 실시간 모니터링 (MLflow + Prometheus + Grafana)
- [x] 콜백 기반 학습 상태 업데이트

### ✅ Platform Phase (진행 중)
- [x] 3-Tier 환경 격리 설계
- [x] 에러 핸들링 설계
- [x] 통합 실패 처리 설계
- [x] 운영 가이드 작성
- [x] Framework-specific Training Services (Ultralytics, timm)
- [x] Temporal 워크플로우 통합 (Phase 12)
- [x] Observability 멀티백엔드 지원 (Phase 13: ClearML, MLflow, W&B, Database)
- [x] 데이터셋 최적화 및 캐싱 (Phase 12.9)
- [ ] 프로덕션 배포 (AWS/GCP)
- [ ] Auto-scaling
- [ ] Multi-tenancy

### 🔮 Future (계획)
- [ ] HuggingFace Transformers 지원
- [ ] MMDetection/MMSegmentation 지원
- [ ] 분산 학습 (multi-GPU, multi-node)
- [ ] Cost optimization
- [ ] Enterprise 기능

## 📄 라이선스

MIT License - [LICENSE](LICENSE) 파일 참고

## 📧 문의

- 이슈: [GitHub Issues](https://github.com/your-org/mvp-vision-ai-platform/issues)
- 이메일: team@vision-platform.com

## 🙏 감사의 말

이 프로젝트는 다음 오픈소스 프로젝트들의 도움을 받았습니다:

- [PyTorch](https://pytorch.org/)
- [timm](https://github.com/huggingface/pytorch-image-models)
- [Ultralytics YOLO](https://github.com/ultralytics/ultralytics)
- [MLflow](https://mlflow.org/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [Next.js](https://nextjs.org/)
- [Prometheus](https://prometheus.io/)
- [Grafana](https://grafana.com/)

---

Made with ❤️ by Vision AI Team
