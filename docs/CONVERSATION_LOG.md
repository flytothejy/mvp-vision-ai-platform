# Conversation Log

이 파일은 Claude Code 대화 세션의 타임라인을 기록합니다.
세션이 바뀌어도 이전 논의 내용을 빠르게 파악할 수 있습니다.

**사용 방법**: `/log-session` 명령어로 현재 세션 내용 추가

---

## [2025-11-05 20:30] timm Framework 구현 및 Checkpoint 경로 통일

### 논의 주제
- timm 학습 프레임워크 전체 구현 완료
- Checkpoint 저장 경로 YOLO와 통일
- 추론 API 에러 수정
- num_classes 자동 감지 구현

### 주요 결정사항

#### 1. Checkpoint 저장 경로 통일 (YOLO 구조 채택)
- **문제**: timm과 YOLO의 checkpoint 경로 구조가 달랐음
  - YOLO: `{output_dir}/job_{job_id}/weights/best.pt`
  - timm (기존): `{output_dir}/best.pt`
- **원인**: YOLO는 자체 `train()` 오버라이드, timm은 base.py 공통 메소드 사용
- **해결**:
  ```python
  # base.py:1406 - 공통 train() 메소드에서 checkpoint_dir 설정
  checkpoint_dir = os.path.join(self.output_dir, f"job_{self.job_id}", "weights")
  callbacks.on_train_end(final_metrics, checkpoint_dir=checkpoint_dir)

  # timm_adapter.py:903 - save_checkpoint에서 동일 구조 사용
  checkpoint_dir = os.path.join(self.output_dir, f"job_{self.job_id}", "weights")
  ```
- **결과**:
  - R2 경로: `checkpoints/projects/{project_id}/jobs/{job_id}/best.pt`
  - Test job: `checkpoints/test-jobs/job_{job_id}/best.pt`

#### 2. Checkpoint 업로드 전략 (YOLO 방식 채택)
- **정책**: 학습 완료 시점에 best.pt + last.pt만 업로드
- **구현**:
  ```python
  # 학습 중
  - last.pt 매 epoch 로컬 저장
  - best.pt 개선 시 로컬 저장
  - R2 업로드 안함 (per-epoch 업로드 제거)

  # 학습 완료
  - on_train_end()에서 best.pt, last.pt R2 업로드
  - DB에 R2 경로 기록
  ```
- **장점**:
  - 학습 속도 영향 없음
  - 비용 효율적 (~$0.60/month for 1000 jobs)
  - 충분함 (추론 + 재학습)

#### 3. 추론 API 에러 수정
- **문제**: Checkpoint 로드 시 classifier 키 불일치
  ```
  RuntimeError: Error(s) in loading state_dict for EfficientNet:
  Unexpected key(s) in state_dict: "classifier.weight", "classifier.bias"
  ```
- **원인**: 학습 시 classifier 구조 변경, checkpoint는 변경 전 구조
- **해결**: `strict=False` 사용 + `weights_only=False` 추가
  ```python
  # timm_adapter.py:965-985
  checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)

  missing_keys, unexpected_keys = self.model.load_state_dict(
      checkpoint['model_state_dict'], strict=False
  )
  print(f"[CHECKPOINT] Missing keys: {missing_keys}")
  print(f"[CHECKPOINT] Unexpected keys: {unexpected_keys}")
  ```

#### 4. num_classes 자동 감지 (Training Service에서 처리)
- **문제**: Backend에서 num_classes를 미리 계산해야 했음
- **해결**: Training Service에서 dataset 로드 시 자동 감지
  ```python
  # train.py:234-243 - Force auto-detection for classification
  if task_type == 'image_classification' and dataset_format in ['dice', 'imagefolder']:
      if args.num_classes and args.num_classes != 10:
          print(f"[WARNING] num_classes={args.num_classes} provided, but will auto-detect")
          final_num_classes = None  # Force auto-detection

  # timm_adapter.py:339-355 - Auto-detect from dataset
  if self.model_config.num_classes is None:
      print("[INFO] Loading dataset to auto-detect num_classes...")
      self.prepare_dataset()
      if hasattr(self.train_loader.dataset, 'classes'):
          self.model_config.num_classes = len(self.train_loader.dataset.classes)
  ```
- **장점**: Backend 부담 감소, Training Service 독립성 증가

### 구현 내용

#### 1. Platform DICE Format 지원
**`converters/dice_split_generator.py`** (새 파일):
- DICE Format → train/val split 생성 (text-file 기반)
- Stratified split 알고리즘 (클래스 불균형 방지)
- Platform 표준 구조 사용:
  ```python
  # annotations.json at root level
  {
    "classes": [{"id": 0, "name": "cat"}, ...],
    "images": [{
      "file_name": "images/000001.JPEG",
      "annotation": {"class_id": 0, "class_name": "cat"}
    }]
  }
  ```

#### 2. Classifier 자동 교체
**`timm_adapter.py:357-433`**:
- ImageNet pretrained 모델 (1000 classes) → Custom classes 자동 변경
- 2단계 접근:
  ```python
  # Method 1: reset_classifier (선호)
  if hasattr(self.model, 'reset_classifier'):
      self.model.reset_classifier(self.model_config.num_classes)

  # Method 2: Direct replacement (fallback)
  if hasattr(self.model, 'get_classifier'):
      old_classifier = self.model.get_classifier()
      in_features = old_classifier.in_features
      new_classifier = nn.Linear(in_features, self.model_config.num_classes)
      setattr(self.model, 'fc', new_classifier)
  ```

#### 3. Validation Metrics 계산
**`validators/metrics.py`** (새 파일):
- Task-agnostic validation metrics calculator
- Classification metrics:
  - Accuracy, Precision, Recall, F1-Score
  - Top-5 Accuracy
  - Per-class metrics
  - Confusion matrix
- Detection/Segmentation/Pose metrics (stub)

#### 4. Checkpoint 경로 통일
**변경 파일 (4개)**:
- `platform_sdk/base.py:8` - `import os` 추가
- `platform_sdk/base.py:1406` - checkpoint_dir 설정
- `timm_adapter.py:903` - YOLO 구조 채택
- `timm_adapter.py:835` - validation에서 경로 수정

### 테스트 결과

#### Job #21 (cls-imagenet-10)
- **Dataset**: 10 classes, DICE format
- **Model**: tf_efficientnetv2_s.in1k (timm)
- **Training**:
  - 5 epochs 완료
  - Train Loss: 0.0002 (수렴)
  - Val Accuracy: 40.0%
  - Best Val Accuracy: 40.0%
- **Checkpoint**:
  - ✅ best.pt 업로드: `r2://vision-platform-prod/checkpoints/test-jobs/job_21/best.pt`
  - ✅ last.pt 업로드: `r2://vision-platform-prod/checkpoints/test-jobs/job_21/last.pt`
  - ✅ DB 업데이트 성공 (2 checkpoint paths)

#### Project ID 이슈
- **발견**: job_id=21의 project_id가 NULL
- **원인**: Frontend에서 job 생성 시 project_id 전달 안됨
- **코드 검증**:
  - ✅ Backend → Training Service: project_id 전달 (training_manager.py:125)
  - ✅ Training Service → train.py: `--project_id` 인자 (api_server.py:130-132)
  - ✅ upload_checkpoint: conditional path logic (storage.py:591-595)
- **결론**: 코드는 올바름, DB 레코드에 project_id=NULL이 원인

### 다음 단계

#### Immediate (완료 예정)
- [x] timm framework 구현
- [x] Checkpoint 경로 통일
- [x] 추론 API 에러 수정
- [x] num_classes 자동 감지
- [ ] **추론 API 전체 테스트** (다음 우선순위)

#### Future Enhancements
- [ ] timm 모델 확장 (ResNet-18, ResNet-34, ViT 등)
- [ ] Advanced config 지원 (optimizer, scheduler, augmentation)
- [ ] Mixed precision training
- [ ] Gradient clipping

### 관련 문서
- **이전 세션**: [Checkpoint 관리 정책](../CONVERSATION_LOG.md#2025-11-05-1445-checkpoint-관리-정책-및-r2-업로드-전략-수립) (2025-11-05)
- **DICE Format**: [Platform Dataset Format](../datasets/PLATFORM_DATASET_FORMAT.md)
- **Adapter 설계**: [Adapter Design](../trainer/ADAPTER_DESIGN.md)

### 핵심 통찰 (Key Insights)

#### 1. Why Different? (timm vs YOLO)
- **YOLO**: 독자적 train() 구현 → checkpoint_dir 직접 설정
- **timm**: base.py 공통 train() 사용 → checkpoint_dir이 누락됨
- **해결**: base.py에 checkpoint_dir 설정 추가 → 모든 framework 통일

#### 2. Per-Epoch Upload의 문제
- **비용**: 50배 비쌈 ($30 vs $0.60/month)
- **성능**: 학습 속도 저하 (I/O blocking)
- **필요성**: 낮음 (best + last면 충분)

#### 3. Strict Loading의 Trade-off
- **strict=True**: 안전하지만 유연성 낮음 (classifier 변경 시 실패)
- **strict=False**: 유연하지만 위험 (missing keys 무시)
- **Best practice**: strict=False + logging으로 검증

#### 4. num_classes Auto-Detection
- **Backend 부담 감소**: DB 쿼리, 파일 파싱 불필요
- **Training Service 독립성**: 자체적으로 dataset 분석
- **정확성 향상**: 실제 데이터에서 직접 감지

### 기술 노트

#### Checkpoint Path Convention (Unified)
```
With project_id:
  Local:  {output_dir}/job_{job_id}/weights/best.pt
  R2:     checkpoints/projects/{project_id}/jobs/{job_id}/best.pt

Without project_id (test jobs):
  Local:  {output_dir}/job_{job_id}/weights/best.pt
  R2:     checkpoints/test-jobs/job_{job_id}/best.pt
```

#### Train Loop Architecture
```
base.py (공통):
  ├── train()                    # 공통 train loop
  │   ├── for epoch in epochs:
  │   │   ├── train_epoch()     # adapter 구현
  │   │   ├── validate()        # adapter 구현
  │   │   └── save_checkpoint() # adapter 구현
  │   └── on_train_end()        # upload checkpoints to R2

ultralytics_adapter.py:
  └── train()                    # 오버라이드 (YOLO API 사용)
      └── model.train()          # YOLO 내부 train loop
          └── on_train_end()     # upload checkpoints to R2

timm_adapter.py:
  ├── train_epoch()              # PyTorch train loop
  ├── validate()                 # Custom validation
  └── save_checkpoint()          # Local save (best.pt, last.pt)
```

#### DICE Split File Format
```
# splits/train.txt
images/000001.JPEG 0
images/000003.JPEG 1
images/000005.JPEG 0

# splits/val.txt
images/000002.JPEG 0
images/000004.JPEG 1

# splits/classes.txt
cat
dog
```

---

## [2025-11-05 14:45] Checkpoint 관리 정책 및 R2 업로드 전략 수립

### 논의 주제
- 추론 테스트 준비 중 체크포인트 관리 정책 누락 발견
- R2 업로드 시점 결정 (매 epoch vs 학습 완료 시)
- 학습 중단 시나리오 처리 (Ctrl+C, Error, 조기 종료)
- UI 메트릭 테이블의 체크포인트 표시 동기화

### 주요 결정사항

#### 1. 현재 상태 확인
- **로컬 저장**:
  - ✅ YOLO `save_period = -1` (best.pt + last.pt만 저장)
  - ✅ 중간 epoch checkpoint 저장 안함
  - ✅ 효율적인 로컬 관리

- **R2 업로드**:
  - ❌ `upload_checkpoint()` 함수는 구현되어 있음
  - ❌ 하지만 실제로 호출되지 않음!
  - ❌ 체크포인트가 로컬에만 남음

- **문제점**:
  - 시간이 지난 후 추론 사용 불가 (로컬 파일 삭제 가능)
  - Exception 처리에서 checkpoint_dir 누락
  - UI는 로컬 경로 기준으로 표시 (R2 업로드 상태 아님)

#### 2. R2 업로드 시점 결정 (Option 1 선택 ✅)

**고려한 옵션들**:

| 옵션 | 장점 | 단점 | 결정 |
|------|------|------|------|
| 매 epoch | 최대 안전성 | 높은 비용, 느린 학습 | ❌ |
| N epoch마다 | 균형 | 여전히 중복 업로드 | ❌ |
| 개선 시마다 | 의미있는 업로드 | 초반 = 매 epoch | ❌ |
| **완료 시 1회** | 간단, 빠름, 저렴 | 중간 백업 없음 | ✅ |

**선택 이유**:
- 대부분의 학습은 정상 완료됨
- 중단은 rare case
- 2개 파일만 업로드 (best.pt + last.pt)
- 학습 성능 영향 0
- 비용 효율적 (~$0.60/월 for 1000 jobs)

#### 3. 학습 중단 처리 (핵심 개선 사항)

**문제 발견**:
```python
# 현재 코드
try:
    results = self.model.train(**train_args)
    callbacks.on_train_end(checkpoint_dir=checkpoint_dir)  # ✅

except KeyboardInterrupt:
    callbacks.on_train_end()  # ❌ checkpoint_dir 없음!

except Exception as e:
    callbacks.on_train_end()  # ❌ checkpoint_dir 없음!
```

**해결 방안**:
```python
# checkpoint_dir를 try 블록 밖에서 정의
checkpoint_dir = os.path.join(self.output_dir, f"job_{self.job_id}", "weights")

try:
    results = self.model.train(**train_args)
except KeyboardInterrupt:
    print("[YOLO] Uploading checkpoints before exit...")
    callbacks.on_train_end(checkpoint_dir=checkpoint_dir)  # ✅
    raise
except Exception as e:
    print("[YOLO] Attempting to upload despite error...")
    callbacks.on_train_end(checkpoint_dir=checkpoint_dir)  # ✅
    raise

# 정상 완료
callbacks.on_train_end(checkpoint_dir=checkpoint_dir)
```

**중단 시나리오별 처리**:
- User 중단 (Ctrl+C): ✅ 현재까지 best/last 업로드
- 에러 발생: ✅ 업로드 시도 (파일 있으면)
- 조기 종료: ✅ 정상 완료로 처리
- 초반 중단: ✅ 파일 없으면 warning만 (non-blocking)

#### 4. DB 체크포인트 추적 전략

**현재 문제**:
```python
# ultralytics_adapter.py:1590-1602
# 학습 중 매 epoch마다 checkpoint_path 저장 (로컬 경로)
if os.path.exists(best_weights):
    checkpoint_path = best_weights  # 문제: 로컬 경로!
```

**새로운 전략**:
```python
# 학습 중
checkpoint_path = None  # DB에 저장 안함

# on_train_end()에서만
1. R2에 업로드
2. Best epoch 찾기 (highest primary_metric_value)
3. Last epoch 찾기 (max epoch)
4. DB UPDATE: 해당 epoch들의 checkpoint_path = 'r2://...'
```

**결과**:
- 학습 중: 모든 epoch checkpoint_path = NULL
- 학습 완료/중단: Best & Last epoch만 checkpoint_path = 'r2://...'
- UI: R2 업로드된 checkpoint만 체크마크 표시

### 구현 내용

#### 1. on_train_end() 확장
**파일**: `platform_sdk/base.py:1724`

```python
def on_train_end(self, final_metrics=None, checkpoint_dir=None):
    # 1. Upload best.pt to R2
    if checkpoint_dir and os.path.exists(best_pt):
        success = upload_checkpoint(best_pt, job_id, 'best.pt', project_id)
        if success:
            best_epoch = _find_best_epoch()
            r2_path = f'r2://.../{project_id}/jobs/{job_id}/best.pt'
            uploaded_checkpoints[best_epoch] = r2_path

    # 2. Upload last.pt to R2
    if checkpoint_dir and os.path.exists(last_pt):
        success = upload_checkpoint(last_pt, job_id, 'last.pt', project_id)
        if success:
            last_epoch = _find_last_epoch()
            r2_path = f'r2://.../{project_id}/jobs/{job_id}/last.pt'
            uploaded_checkpoints[last_epoch] = r2_path

    # 3. Update DB with R2 paths
    _update_checkpoint_paths(uploaded_checkpoints)

    # 4. End MLflow
    mlflow.end_run()
```

**새로운 헬퍼 메서드**:
- `_find_best_epoch()`: DB에서 highest primary_metric_value 찾기
- `_find_last_epoch()`: DB에서 max(epoch) 찾기
- `_update_checkpoint_paths()`: validation_results 테이블 UPDATE

#### 2. Exception 핸들링 수정
**파일**: `adapters/ultralytics_adapter.py:1967-1999`

```python
# Line 1995: checkpoint_dir 미리 정의
checkpoint_dir = os.path.join(self.output_dir, f"job_{self.job_id}", "weights")

try:
    results = self.model.train(**train_args)
except KeyboardInterrupt:
    callbacks.on_train_end(checkpoint_dir=checkpoint_dir)  # ✅
    raise
except Exception as e:
    callbacks.on_train_end(checkpoint_dir=checkpoint_dir)  # ✅
    raise

callbacks.on_train_end(checkpoint_dir=checkpoint_dir)
```

#### 3. 학습 중 checkpoint_path 제거
**파일**: `adapters/ultralytics_adapter.py:1590-1602`

```python
# 기존 코드 제거 (로컬 경로 할당)
# checkpoint_path = best_weights if os.path.exists(best_weights) else last_weights

# 새 코드 (간단!)
checkpoint_path = None  # R2 업로드 후에만 설정됨
```

#### 4. upload_checkpoint() 반환값 추가
**파일**: `platform_sdk/storage.py:527`

```python
def upload_checkpoint(...) -> bool:  # 반환 타입 추가
    try:
        # ... 업로드 로직 ...
        return True  # 성공
    except Exception as e:
        print(f"[R2 WARNING] Upload failed: {e}")
        return False  # 실패
```

### 비용 분석

**Storage (Cloudflare R2)**:
- 파일당: ~20MB (YOLO11s average)
- 잡당: 40MB (best.pt + last.pt)
- 1000 jobs: 40GB
- 비용: $0.015/GB/month
- **월 비용: $0.60** (affordable!)

**비교 (대안들)**:
- 매 epoch (100 epochs): 2GB/job → $30/month (50배 비쌈!)
- 10 epoch마다: 200MB/job → $3/month (5배 비쌈)
- 완료 시 1회: 40MB/job → $0.60/month ✅

**Upload 비용**:
- PUT operations: Free (10M requests/month)
- 2 uploads/job: 무시 가능

### 타임라인 동작

**100 epoch 학습 예시**:
```
Epoch 1-99:
  - DB: checkpoint_path = NULL for all epochs
  - UI: No checkmarks

Epoch 100 (완료):
  - Upload best.pt (assume epoch 85 was best)
  - Upload last.pt (epoch 100)
  - DB UPDATE:
    - epoch 85: checkpoint_path = 'r2://...best.pt'
    - epoch 100: checkpoint_path = 'r2://...last.pt'
  - UI: Checkmarks on epochs 85, 100 only
```

**Epoch 20 중단 예시**:
```
Epoch 1-19: No uploads
Epoch 20: User presses Ctrl+C
  - KeyboardInterrupt caught
  - Upload best.pt (assume epoch 18)
  - Upload last.pt (epoch 20)
  - DB UPDATE: epochs 18, 20 get R2 paths
  - UI: 2 checkmarks
```

### 문서화

**생성된 문서**: `docs/training/20251105_checkpoint_management_and_r2_upload_policy.md`

**포함 내용**:
- Background & context (문제 발견 과정)
- Current state (코드 분석 결과)
- Proposed solution (선택한 정책)
- Implementation plan (4 phases)
- Technical details (R2 경로, DB 스키마, 예시)
- Alternatives considered (4가지 옵션 비교)
- Cost analysis (storage & operations)
- Migration path (기존 job 처리)
- References (관련 파일 & 문서)

### 다음 단계

#### Immediate (구현 필요)
- [ ] `on_train_end()` 구현 (upload + DB update)
- [ ] Exception handling 수정 (checkpoint_dir 전달)
- [ ] 학습 중 checkpoint_path 할당 제거
- [ ] `upload_checkpoint()` 반환값 수정
- [ ] 테스트 (정상 완료, 중단, 에러)

#### Future Enhancements (P1-P3)
- [ ] Checkpoint download API (inference용)
- [ ] Lifecycle policy (30일 후 자동 삭제)
- [ ] Checkpoint browser UI
- [ ] Resume training from R2 checkpoint

### 관련 문서
- **설계 문서**: [docs/training/20251105_checkpoint_management_and_r2_upload_policy.md](../training/20251105_checkpoint_management_and_r2_upload_policy.md)
- **이전 세션**: [Project-Centric Checkpoint Storage](../CONVERSATION_LOG.md#2025-11-04-2130-project-centric-checkpoint-storage-구현) (2025-11-04)
- **Validation 이슈**: [YOLO Validation Metrics](../CONVERSATION_LOG.md#2025-11-05-1415-yolo-validation-metrics-이슈-조사-및-stratified-split-구현) (2025-11-05)

### 핵심 통찰 (Key Insights)

#### Cost-Benefit Analysis
- **Best + Last only**: 충분함 (추론 + 재학습)
- **매 epoch 저장**: 불필요 (50배 비용, 성능 저하)
- **중단 처리**: 필수 (partial results도 가치있음)

#### Design Principles
1. **Simplicity over Safety**: MVP는 간단함 우선
2. **Cost-Effective**: 비용 최소화 ($0.60/month)
3. **Non-Blocking**: 업로드 실패해도 학습 계속
4. **User-Friendly**: UI는 실제 R2 상태 반영

#### Exception Handling Philosophy
```
"Try to save something rather than save nothing"
- 중단되어도 best/last checkpoint 보존
- 에러 발생해도 업로드 시도
- 실패해도 warning만 (non-critical)
```

### 기술 노트

#### R2 Path Convention
```
With project_id:
  r2://vision-platform-prod/checkpoints/projects/{project_id}/jobs/{job_id}/best.pt
  r2://vision-platform-prod/checkpoints/projects/{project_id}/jobs/{job_id}/last.pt

Without project_id (test jobs):
  r2://vision-platform-prod/checkpoints/test-jobs/job_{job_id}/best.pt
  r2://vision-platform-prod/checkpoints/test-jobs/job_{job_id}/last.pt
```

#### Database Lifecycle
```sql
-- During training
validation_results.checkpoint_path = NULL

-- After upload (only for best & last epochs)
UPDATE validation_results
SET checkpoint_path = 'r2://...'
WHERE job_id = ? AND epoch IN (best_epoch, last_epoch)
```

#### Frontend Logic
```tsx
// Show checkmark only if R2 path exists
{metric.checkpoint_path?.startsWith('r2://') ? (
  <CheckCircle2 className="text-green-600" />
) : (
  <XCircle className="text-gray-300" />
)}
```

---

## [2025-11-05 14:15] YOLO Validation Metrics 이슈 조사 및 Stratified Split 구현

### 논의 주제
- YOLO 학습 중 validation metrics가 항상 0인 문제 디버깅
- 데이터셋 클래스 분포 불균형 문제 발견
- PyTorch InferenceMode 제약사항 발견
- Stratified split 알고리즘 구현

### 주요 결정사항

#### 1. Validation Metrics = 0 문제 (CANNOT FIX)
- **증상**:
  - Training loss는 정상 감소
  - Validation metrics (mAP, precision, recall) 항상 0.0
  - Confusion matrix 완전히 비어있음 (sum = 0.0)

- **Root Cause 1**: 데이터셋 클래스 분포 불균형
  - COCO32 (32 images, 43 classes): 9개 클래스가 validation set에만 존재
  - 모델이 해당 클래스를 한 번도 학습하지 못함
  - **해결**: Stratified split 구현 ✅

- **Root Cause 2**: PyTorch InferenceMode 제약
  - Ultralytics가 `torch.inference_mode()` 사용 (not `torch.no_grad()`)
  - InferenceMode는 텐서를 irreversibly 변환
  - Manual validation 후 `requires_grad` 복원 불가능
  - RuntimeError: "Setting requires_grad=True on inference tensor outside InferenceMode is not allowed"
  - **결론**: 근본적 PyTorch 설계 제약, 해결 불가 ❌

- **Root Cause 3**: Ultralytics Callback 타이밍
  - `on_fit_epoch_end` 시점에 `validator.batch = None`
  - `validator.pred = None` (예측값 없음)
  - Validation이 실행되지만 callback에서 데이터 접근 불가

#### 2. Stratified Split 구현 (✅ SOLVED)
- **배경**:
  - Random split은 작은 데이터셋에서 클래스 불균형 발생
  - 예: 32 images, 43 classes → 0.74 images/class 평균
  - 9개 클래스가 validation에만 존재 (train에 0개)

- **알고리즘** (`dice_to_yolo.py:136-212`):
  ```python
  1. Build image-to-classes mapping
  2. For rare classes (1 image): → train set (우선순위)
  3. For classes with 2+ images: → both train & val
  4. Remaining images → 80/20 ratio
  5. Verify: no validation-only classes
  ```

- **결과**:
  - Val-only classes: 9 → 0 ✅
  - 모든 validation 클래스가 training set에 존재
  - COCO32, COCO128 모두 검증 완료

#### 3. Train-Mode Validation 테스트 (부분 성공)
- **시도**: Training mode + `torch.no_grad()` 방식
  ```python
  with torch.no_grad():
      preds = model(val_batch['img'])
  optimizer.zero_grad()
  ```

- **에러**: `RuntimeError: expected scalar type Byte but found Float`
  - 원인: Validation batch images가 uint8 (0-255)
  - 모델은 float32 (0.0-1.0) 기대
  - 해결 방법: `imgs = batch['img'].float() / 255.0`

- **결론**: Train-mode validation 가능하지만 추가 구현 필요
  - 데이터 타입 변환
  - Metric 계산 로직 (mAP, confusion matrix 등)
  - 예상 작업: 1-2일

#### 4. Post-Training Validation (권장 Workaround)
- **방식**: 학습 완료 후 별도 validation 실행
  ```python
  results = model.train(...)
  val_metrics = model.val(data=data_yaml, split='val')
  ```

- **장점**:
  - 간단, 안정적
  - Full metrics 제공
  - Training 간섭 없음

- **단점**:
  - Per-epoch 모니터링 불가
  - 최종 메트릭만 확인 가능

### 구현 내용

#### Stratified Split Implementation
**`mvp/training/converters/dice_to_yolo.py:136-212`**:
```python
# 1. Image-to-classes mapping
image_classes = {}
for image in images:
    classes_in_image = set(ann['category_id'] for ann in annotations)
    image_classes[image_id] = classes_in_image

# 2. Class-to-images mapping
class_to_images = defaultdict(list)
for image in images:
    for cls in image_classes[image_id]:
        class_to_images[cls].append(image)

# 3. Stratified allocation
for cls, cls_images in sorted(class_to_images.items(), key=lambda x: len(x[1])):
    if len(cls_images) == 1:
        train_images.append(cls_images[0])  # Rare class → train
    elif len(cls_images) >= 2:
        train_images.append(cls_images[0])  # Both splits
        val_images.append(cls_images[1])

# 4. Distribute remaining (80/20)
remaining_images = [img for img in images if img not in used]
for image in remaining_images:
    if len(train_images) < target_train_size:
        train_images.append(image)
    else:
        val_images.append(image)

# 5. Verify
val_only_classes = val_classes - train_classes
if val_only_classes:
    print(f"WARNING: {len(val_only_classes)} classes only in val")
else:
    print(f"[OK] All {len(val_classes)} val classes in train")
```

#### Validation Debugging
**`mvp/training/adapters/ultralytics_adapter.py:1200-1700`**:
- Train/val dataset label count 로깅
- Confusion matrix 상세 디버깅
- Validation batch 처리 추적 callbacks
- Manual validation 시도 (3가지 접근)
- Train-mode validation 테스트

#### Issue Documentation
**`docs/issues/yolo_validation_metrics.md`** (새 파일):
- **Status**: 🔴 CANNOT FIX - PyTorch Design Limitation
- **Impact**: Medium (training works, post-training validation works)
- Root cause 분석 (3가지)
- Investigation log (4 attempts)
- Possible solutions (4 options)
- Lessons learned

#### Analysis Tool
**`analyze_class_dist.py`** (새 파일):
- Train/val split 클래스 분포 분석
- Val-only classes 탐지
- 통계 리포트 생성
- DICE annotations.json 연동

### 조사 과정 (Investigation Log)

#### Attempt 1: Callback Debugging
- 추가 callbacks: `on_val_batch_start`, `on_val_batch_end`, `on_val_end`
- 발견: `validator.batch = None`, `validator.pred = None`
- 결론: Callback 타이밍에 데이터 미접근

#### Attempt 2: Manual Validation (model.val())
- 시도: `on_fit_epoch_end`에서 `model.val()` 직접 호출
- 에러: `RuntimeError: element 0 does not require grad`
- 원인: `model.val()`이 gradient 비활성화

#### Attempt 3: State Restoration
- 시도: Parameter `requires_grad` 상태 저장 후 복원
  ```python
  original_grad_states = {name: p.requires_grad for name, p in model.named_parameters()}
  # Run validation
  for name, param in model.named_parameters():
      param.requires_grad = original_grad_states[name]  # FAILS!
  ```
- 에러: `RuntimeError: Setting requires_grad=True on inference tensor`
- 원인: PyTorch InferenceMode 제약

#### Attempt 4: Train-Mode Validation
- 시도: Training mode + `torch.no_grad()` 조합
  ```python
  with torch.no_grad():
      preds = model(val_batch['img'])
  optimizer.zero_grad()
  ```
- 에러: `RuntimeError: expected scalar type Byte but found Float`
- 원인: Data type mismatch (uint8 vs float32)
- 결론: 데이터 전처리 추가하면 가능 (추가 구현 필요)

### Git 작업

#### Commit
```
fee0630 feat(training): implement stratified dataset split for YOLO training

- Add stratified split algorithm to ensure all validation classes
  appear in training set (critical for small datasets)
- Val-only classes: 9 → 0 (COCO32 tested)
- Document PyTorch InferenceMode limitation
- Add validation debugging callbacks
- Create class distribution analysis tool

Known Issue: Validation metrics still 0 due to PyTorch InferenceMode.
Post-training validation works. See docs/issues/yolo_validation_metrics.md
```

**변경 파일 (4개)**:
- `mvp/training/converters/dice_to_yolo.py` (+140 lines)
- `mvp/training/adapters/ultralytics_adapter.py` (+338 lines)
- `docs/issues/yolo_validation_metrics.md` (+227 lines, 새 파일)
- `analyze_class_dist.py` (+90 lines, 새 파일)

### 테스트 결과

#### COCO32 Dataset
- **Images**: 32장
- **Classes**: 43개 (COCO)
- **Before stratified split**: 9 classes val-only ❌
- **After stratified split**: 0 classes val-only ✅
- **Train/Val**: 25/7 images

#### COCO128 Dataset
- **Images**: 128장
- **Classes**: 71개 (COCO)
- **Stratified split**: 0 classes val-only ✅
- **Train/Val**: 92/36 images
- **Annotations**: 929개 objects

### 다음 단계

#### Immediate (Close Issue)
- [x] Stratified split 구현
- [x] Issue 문서화
- [x] Commit 생성
- [ ] **Inference API 테스트** (다음 우선순위)

#### Future (If Needed)
- [ ] Custom validator 구현 (~1-2일)
  - Train-mode validation with proper data type handling
  - Manual mAP, precision, recall calculation
  - Confusion matrix construction
- [ ] Test other YOLO models (seg, pose, obb)
- [ ] Test timm models (ResNet, EfficientNet)

### 관련 문서
- **Issue 문서**: [docs/issues/yolo_validation_metrics.md](../issues/yolo_validation_metrics.md)
- **Converter**: mvp/training/converters/dice_to_yolo.py:136-212
- **Adapter**: mvp/training/adapters/ultralytics_adapter.py:1200-1700
- **Analysis Tool**: analyze_class_dist.py

### 핵심 통찰 (Key Insights)

#### PyTorch InferenceMode vs no_grad
| Context | Gradient | Post-restoration | Performance |
|---------|----------|------------------|-------------|
| `no_grad()` | Disabled | ✅ Possible | Slower |
| `inference_mode()` | Disabled | ❌ Impossible | Faster |

**결론**: Ultralytics는 성능을 위해 InferenceMode 선택 → Flexibility 희생

#### Small Dataset Challenge
- **0.74 images/class** (32 images, 43 classes)
- Random split은 클래스 불균형 보장
- Stratified split 필수

#### Validation Monitoring Workaround
- ✅ Training loss로 진행 상황 모니터링
- ✅ Post-training validation으로 최종 메트릭 확인
- ❌ Per-epoch validation metrics (당분간 포기)

### 기술 노트

#### Stratified Split vs Random Split
```python
# Random Split (기존 - 문제있음)
random.shuffle(images)
split_idx = int(len(images) * 0.8)
train = images[:split_idx]
val = images[split_idx:]

# Stratified Split (새로운 - 해결)
# 1. Ensure all val classes in train
# 2. Distribute remaining by ratio
# 3. Verify no val-only classes
```

#### Label Path Structure
```
DICE Dataset (Original):
  datasets/uuid-123/
    ├── images/
    │   ├── 000000000009.jpg
    │   └── ...
    └── labels/              # Single directory
        ├── 000000000009.txt
        └── ...

YOLO Split (Converted):
  datasets/uuid-123_yolo/
    ├── train.txt            # Absolute paths
    ├── val.txt              # Absolute paths
    └── data.yaml
```

**Key**: Labels stay in original DICE directory, not split into train/val subdirs.

---

## [2025-11-04 21:30] Project-Centric Checkpoint Storage 구현

### 논의 주제
- Multi-tenant 지원을 위한 체크포인트 저장 구조 개선
- 현재 경로 구조의 문제점 식별 및 해결 방안 논의
- 전체 training pipeline에 project_id 전파
- Training Service 구현 현황 문서화

### 주요 결정사항

#### 1. Project-Centric Checkpoint Storage 구조 (Option 1 선택)
- **배경**:
  - 기존: `checkpoints/job_{job_id}/` → 여러 사용자/프로젝트/실험 구분 불가
  - TrainingJob에 `project_id`, `created_by`, `session_id`, `experiment_name` 존재
  - Multi-tenant 환경에서 체크포인트 구분 필요

- **결정**: Project-centric 계층 구조 ✅
  ```
  checkpoints/
  ├── projects/
  │   └── {project_id}/
  │       └── jobs/
  │           └── {job_id}/
  │               ├── best.pt
  │               └── last.pt
  └── test-jobs/
      └── job_{job_id}/
          ├── best.pt
          └── last.pt
  ```

- **이유**:
  - 프로젝트 단위 관리 (가장 직관적)
  - 테스트/개발 job 별도 관리 (project_id = null)
  - 기존 체크포인트 마이그레이션 불필요 (사용자가 수동 삭제)

#### 2. 전체 Pipeline에 project_id 전파
- **Data Flow**:
  ```
  Backend (training_manager.py)
    → job_config.project_id
      → Training Service API (api_server.py)
        → TrainingRequest.project_id
          → train.py --project_id
            → TrainingAdapter(project_id)
              → TrainingCallbacks(project_id)
                → upload_checkpoint(project_id)
                  → R2 Storage (conditional path)
  ```

- **구현 위치** (6개 파일 수정):
  1. `storage.py:527` - upload_checkpoint() conditional path logic
  2. `base.py:378` - TrainingAdapter.__init__ accepts project_id
  3. `base.py:1488` - TrainingCallbacks.__init__ accepts project_id
  4. `base.py:1861` - _upload_checkpoints_to_r2() passes project_id
  5. `ultralytics_adapter.py:1082` - Pass project_id to callbacks
  6. `train.py:95` - Add --project_id argument
  7. `api_server.py:60` - TrainingRequest.project_id field
  8. `training_manager.py:125` - job_config includes project_id

### 구현 내용

#### Storage Layer
**`mvp/training/platform_sdk/storage.py`**:
```python
def upload_checkpoint(
    checkpoint_path: str,
    job_id: int,
    checkpoint_name: str = "best.pt",
    project_id: int = None  # 추가
):
    # Build path based on project_id
    if project_id:
        key = f'checkpoints/projects/{project_id}/jobs/{job_id}/{checkpoint_name}'
    else:
        key = f'checkpoints/test-jobs/job_{job_id}/{checkpoint_name}'
```

#### Adapter Layer
**`mvp/training/adapters/base.py`**:
```python
class TrainingAdapter:
    def __init__(
        self,
        model_config: ModelConfig,
        dataset_config: DatasetConfig,
        training_config: TrainingConfig,
        output_dir: str,
        job_id: int,
        project_id: int = None  # 추가
    ):
        self.project_id = project_id

class TrainingCallbacks:
    def __init__(
        self,
        job_id: int,
        model_config: 'ModelConfig',
        training_config: 'TrainingConfig',
        db_session=None,
        project_id: int = None  # 추가
    ):
        self.project_id = project_id

    def _upload_checkpoints_to_r2(self, checkpoint_dir: str = None):
        upload_checkpoint(
            checkpoint_path=str(checkpoint_file),
            job_id=self.job_id,
            checkpoint_name=checkpoint_name,
            project_id=self.project_id  # 전달
        )
```

#### Training Service API
**`mvp/training/api_server.py`**:
```python
class TrainingRequest(BaseModel):
    job_id: int
    framework: str
    # ... other fields
    project_id: Optional[int] = None  # 추가

def run_training(request: TrainingRequest):
    cmd = [...]
    if request.project_id is not None:
        cmd.extend(["--project_id", str(request.project_id)])
```

#### Training Script
**`mvp/training/train.py`**:
```python
def parse_args():
    parser.add_argument('--project_id', type=int, default=None,
                        help='Project ID for organizing checkpoints in R2')

adapter = adapter_class(
    model_config=model_config,
    dataset_config=dataset_config,
    training_config=training_config,
    output_dir=args.output_dir,
    job_id=args.job_id,
    project_id=args.project_id,  # 전달
    logger=logger
)
```

#### Backend
**`mvp/backend/app/utils/training_manager.py`**:
```python
job_config = {
    "job_id": job_id,
    "framework": job.framework,
    # ... other fields
    "project_id": job.project_id  # 추가
}
```

### 문서화

#### `docs/trainer/IMPLEMENTATION_STATUS.md` (새 파일)
**포함 내용**:
- Training Service 아키텍처 다이어그램
- 구현 완료 기능 (Phase 1)
  - Microservice Architecture ✅
  - R2 Storage Integration ✅
  - YOLO Training Pipeline ✅
  - DICE Dataset Format ✅
  - Project-Centric Checkpoints ✅
- 테스트 결과 (Job #11, #12, #13)
- 기술 구현 세부사항
- API 엔드포인트 문서
- 다음 단계 (Phase 2: Frontend Integration)

### Git 작업

#### Commit
```
67142e4 feat(training): implement project-centric checkpoint storage

- Add project_id parameter throughout training pipeline
- Implement conditional path logic in upload_checkpoint()
- Update all adapters and callbacks to handle project_id
- Add comprehensive implementation status document
```

**변경 파일 (7개)**:
- `mvp/training/platform_sdk/storage.py`
- `mvp/training/adapters/base.py`
- `mvp/training/adapters/ultralytics_adapter.py`
- `mvp/training/train.py`
- `mvp/training/api_server.py`
- `mvp/backend/app/utils/training_manager.py`
- `docs/trainer/IMPLEMENTATION_STATUS.md` (새 파일)

### 테스트 계획

#### Job #14 테스트 (다음 단계)
**목표**: 새로운 project-centric 경로 구조 검증

**시나리오 1**: project_id 있는 경우
- Job with project_id = 5
- Expected path: `checkpoints/projects/5/jobs/14/best.pt`

**시나리오 2**: project_id 없는 경우 (test job)
- Job with project_id = null
- Expected path: `checkpoints/test-jobs/job_14/best.pt`

**검증 사항**:
- Backend가 project_id를 Training Service에 전달
- Training Service가 train.py에 --project_id 전달
- Adapter가 Callbacks에 project_id 전달
- Callbacks가 upload_checkpoint()에 project_id 전달
- R2에 올바른 경로로 업로드

### 다음 단계

#### Phase 2: Frontend Integration (예정)
- [ ] Training Job 생성 UI
- [ ] Real-time training monitoring
- [ ] Checkpoint download interface
- [ ] Project selection in training form

#### Testing
- [ ] Job #14 실행 및 경로 검증
- [ ] Project job vs test job 경로 차이 확인
- [ ] R2 Storage에서 경로 구조 확인

### 관련 문서
- **구현 현황**: [docs/trainer/IMPLEMENTATION_STATUS.md](../trainer/IMPLEMENTATION_STATUS.md)
- **Adapter 설계**: [docs/trainer/ADAPTER_DESIGN.md](../trainer/ADAPTER_DESIGN.md)
- **이전 세션**: [2025-11-04 17:30] Training Service Microservice 인프라 구축

### 핵심 원칙 준수

1. **No Shortcuts** ✅
   - 하드코딩 없음 (project_id를 동적으로 전달)
   - 임시 방편 없음 (전체 chain 구현)

2. **Production = Local** ✅
   - 동일한 코드베이스
   - 환경변수만 차이
   - R2 Storage 공통 사용

3. **Dependency Isolation** ✅
   - Backend: project_id만 전달 (training 로직 무관)
   - Training Service: 독립적으로 checkpoint 관리

---

## [2025-11-04 17:30] Training Service Microservice 인프라 구축 및 데이터 접근 전략 수립

### 논의 주제
- Training Service Microservice 아키텍처 구현
- Framework별 독립 서비스 구성 (timm, ultralytics, huggingface)
- R2 Storage 직접 접근 전략
- DICE Format → Framework Format 변환 설계
- 데이터셋-모델 호환성 검증 전략

### 주요 결정사항

#### 1. Microservice 아키텍처 구현 (Railway 환경과 동일)
- **배경**:
  - 로컬 테스트가 subprocess 방식으로 동작
  - Railway 배포 환경은 microservice로 구성
  - 로컬과 배포 환경의 불일치 문제

- **결정**: 로컬에서도 microservice로 실행 ✅
  ```
  Backend (Port 8000)
    ↓ HTTP
  ultralytics-service (Port 8002)
  timm-service (Port 8001)
  huggingface-service (Port 8003)
  ```

- **구현 내용**:
  - Framework별 독립 venv 생성 (`venv-ultralytics`, `venv-timm`)
  - 독립 실행 스크립트 (`scripts/start-ultralytics-service.bat`)
  - Backend `.env`에 framework별 URL 설정
  - `TrainingServiceClient`가 framework 기반 라우팅 지원

#### 2. R2 Storage 직접 접근 (Option A 선택)
- **질문**: Training Service가 데이터를 어떻게 접근할 것인가?
  - Option A: Training Service가 R2 직접 접근 (추천 ✅)
  - Option B: Backend API 통해 다운로드

- **결정**: Option A - R2 직접 접근
- **이유**:
  - Microservice 철학에 맞음 (독립적 동작)
  - Backend 부담 감소
  - `platform_sdk/storage.py` 이미 구현됨
  - R2 credentials 공유 필요하지만 문제없음

- **구현 방식**:
  ```python
  # Training Service .env
  AWS_S3_ENDPOINT_URL=https://...r2.cloudflarestorage.com
  AWS_ACCESS_KEY_ID=...
  AWS_SECRET_ACCESS_KEY=...
  S3_BUCKET=vision-platform-prod

  # platform_sdk/storage.py
  get_dataset(dataset_id) → R2 다운로드 → 로컬 캐시
  ```

#### 3. Dataset ID 기반 접근 (Path 방식에서 전환)
- **현재 문제**:
  - 기존: `dataset_path` (파일 시스템 경로)
  - Frontend 흐름: User가 데이터셋 선택 (ID 기반)
  - R2 구조: `datasets/{id}/` (UUID 기반)

- **결정**: `dataset_id` 기반으로 전환
  ```python
  # Frontend → Backend
  {"dataset_id": "uuid-123"}

  # Backend → Training Service
  {"dataset_id": "uuid-123"}

  # Training Service
  dataset_path = get_dataset("uuid-123")
  # → R2: datasets/uuid-123/ 다운로드
  # → Local: /workspace/data/.cache/datasets/uuid-123/
  ```

#### 4. DICE Format 변환 전략
- **배경**:
  - R2에 DICE Format으로 저장됨 (`annotations.json`)
  - 각 framework는 고유 포맷 필요 (YOLO, COCO, ImageFolder 등)

- **변환 전략**:
  ```
  Training Service
    ↓ 1. Download
    datasets/{id}/annotations.json (DICE Format)

    ↓ 2. Convert
    dice_to_yolo()      → data.yaml, labels/*.txt
    dice_to_imagefolder() → train/class1/, val/class1/
    dice_to_coco()      → annotations/instances.json

    ↓ 3. Train
    UltralyticsAdapter(converted_path)
  ```

- **구현 위치**: `mvp/training/converters/`
  - `dice_to_yolo.py`
  - `dice_to_imagefolder.py`
  - `dice_to_coco.py`

#### 5. 데이터셋-모델 호환성 검증 (3-Tier 전략)
- **문제**:
  - Classification 데이터로 Detection 학습 불가
  - Segmentation → Detection 변환 가능
  - Detection → Classification 변환 애매

- **3-Tier 검증 전략**:
  ```
  Tier 1: Frontend (UX Hint) [P2]
    → 데이터셋 선택 시 호환성 힌트 표시

  Tier 2: Backend API (사전 검증) [P1]
    → GET /datasets/{id}/compatibility?task_type=...
    → DB 메타데이터 or annotations.json 파싱

  Tier 3: Training Service (실행 시 검증) [P0] ✅
    → prepare_dataset()에서 상세 검증
    → 변환 가능하면 변환, 불가능하면 명확한 에러
  ```

- **MVP 우선순위**: Tier 3만 구현 (필수)
  - 이유: 일단 동작하는 것 먼저, UX는 나중에

- **변환 규칙 테이블**:
  ```python
  CONVERSION_MATRIX = {
      ("instance_segmentation", "object_detection"): polygon_to_bbox,
      ("instance_segmentation", "image_classification"): use_dominant_class,
      ("object_detection", "image_classification"): use_dominant_class,
      ("image_classification", "object_detection"): None,  # ❌ 불가능
  }
  ```

### 구현 내용

#### Microservice 인프라
**스크립트 생성**:
- `mvp/scripts/setup-ultralytics-service.bat` - venv 생성 및 의존성 설치
- `mvp/scripts/start-ultralytics-service.bat` - 서비스 시작 (Port 8002)
- `mvp/scripts/setup-timm-service.bat` - timm 서비스 셋업
- `mvp/scripts/start-timm-service.bat` - timm 서비스 시작 (Port 8001)

**Backend 설정**:
```bash
# mvp/backend/.env
TIMM_SERVICE_URL=http://localhost:8001
ULTRALYTICS_SERVICE_URL=http://localhost:8002
HUGGINGFACE_SERVICE_URL=http://localhost:8003
TRAINING_SERVICE_URL=http://localhost:8001  # Fallback
```

**ultralytics-service 실행 확인**:
- ✅ Port 8002에서 정상 동작
- ✅ Health Check: `{"status":"healthy"}`
- ✅ Models API: 5개 모델 (yolo11n, yolo11n-seg, yolo11n-pose, yolo_world_v2_s, sam2_t)

#### 기존 코드 분석
**platform_sdk/storage.py**:
- ✅ `get_dataset(dataset_id)` 이미 구현됨
- ✅ 3-tier 캐싱: Local → R2 → Original source
- ✅ 자동 압축 해제 및 디렉토리 반환

**ultralytics_adapter.py**:
- ✅ `_resolve_dataset_path()` 메서드 존재
- ✅ Simple name 감지 → `get_dataset()` 호출
- ⚠️ 현재는 path 기반, dataset_id 기반으로 수정 필요

### 다음 단계 (우선순위 순)

#### Phase 1: 환경 설정 및 기본 연동
- [x] ultralytics-service venv 생성 및 의존성 설치
- [x] ultralytics-service 실행 스크립트
- [x] Backend .env 업데이트 (framework별 URL)
- [ ] Training Service .env 업데이트 (R2 credentials)
- [ ] Backend 실행 및 Training Service 연결 테스트

#### Phase 2: DICE Format 변환기 구현
- [ ] `mvp/training/converters/dice_to_yolo.py` 구현
  - annotations.json 파싱
  - Polygon → Bounding box 변환
  - data.yaml 생성
  - labels/*.txt 생성
- [ ] `platform_sdk/storage.py` 확장
  - `get_dataset_from_r2(dataset_id)` 디렉토리 다운로드
- [ ] 호환성 검증 로직
  - `check_detailed_compatibility()` 함수
  - CONVERSION_MATRIX 정의

#### Phase 3: 학습 파이프라인 E2E 테스트
- [ ] R2에 테스트 데이터셋 업로드 (sample-det-coco32)
- [ ] Backend → ultralytics-service 학습 시작
- [ ] 데이터 다운로드 → 변환 → 학습 전체 흐름 검증
- [ ] 메트릭 수집 및 로깅 확인

#### Phase 4: Checkpoint R2 저장
- [ ] `platform_sdk/storage.py`에 `upload_checkpoint()` 추가
- [ ] Adapter `save_checkpoint()` 수정
- [ ] R2 경로: `checkpoints/{job_id}/epoch_{epoch}.pth`

### 핵심 설계 원칙

1. **No Shortcuts, No Hardcoding** (CLAUDE.md)
   - ✅ 동적 모델 레지스트리 (Training Service API)
   - ✅ R2 Storage 기반 (로컬 파일시스템 의존성 제거)
   - ✅ Database 기반 메타데이터 (하드코딩 샘플 없음)

2. **Dependency Isolation**
   - ✅ Backend: PyTorch 없음
   - ✅ Training Services: Framework별 독립 venv
   - ✅ HTTP/JSON 통신만

3. **Production = Local**
   - ✅ Microservice 아키텍처 동일
   - ✅ R2 Storage 사용
   - ✅ 환경변수만 차이 (URL, credentials)

### 관련 문서
- **인프라**: [docs/planning/TRAINER_IMPLEMENTATION_PLAN.md](../planning/TRAINER_IMPLEMENTATION_PLAN.md)
- **데이터셋 설계**: [docs/datasets/DATASET_MANAGEMENT_DESIGN.md](../datasets/DATASET_MANAGEMENT_DESIGN.md)
- **DICE Format 스펙**: [docs/datasets/PLATFORM_DATASET_FORMAT.md](../datasets/PLATFORM_DATASET_FORMAT.md)
- **현재 상태**: [docs/datasets/CURRENT_STATUS.md](../datasets/CURRENT_STATUS.md)

### 기술 노트

#### R2 Storage 구조
```
vision-platform-prod/
├── datasets/
│   └── {id}/
│       ├── images/          # 원본 폴더 구조 유지
│       └── annotations.json # DICE Format v1.0
├── models/
│   └── pretrained/{framework}/{model_name}.pt
└── checkpoints/
    └── {job_id}/
        └── epoch_{n}.pth
```

#### Training Service 데이터 흐름
```
1. Backend → POST /training/start
   {"dataset_id": "uuid-123", "model_name": "yolo11n", ...}

2. Training Service → get_dataset("uuid-123")
   - Check local: /workspace/data/.cache/datasets/uuid-123/
   - Download R2: datasets/uuid-123/ → local cache
   - Return: local_path

3. DICE Format 변환
   - Parse: annotations.json
   - Check: compatibility with task_type
   - Convert: dice_to_yolo() → data.yaml + labels/
   - Return: converted_path

4. 학습 실행
   - UltralyticsAdapter(converted_path)
   - Train + Validate
   - Save checkpoint → R2
   - Log metrics → Backend
```

#### Framework별 Port 할당
```
Backend:           8000
timm-service:      8001
ultralytics-service: 8002
huggingface-service: 8003
Frontend:          3000
```

---

## [2025-11-04 16:00] 데이터셋 인증/권한 구현 및 학습 파이프라인 준비

### 논의 주제
- 데이터셋 인증 및 권한 체크 구현
- 학습 파이프라인 테스트 vs 스냅샷 구현 우선순위
- YOLO segmentation → DICE Format 변환
- 프론트엔드 UX 개선 (자동 네비게이션 제거)
- PR 생성 및 문서화

### 주요 결정사항

#### 1. 데이터셋 인증 시스템 구현
- **배경**: 데이터셋을 아무나 볼 수 있는 보안 문제 발견
- **구현 내용**:
  - Backend: 모든 dataset API에 `Depends(get_current_user)` 추가
  - Frontend: 모든 API 호출에 Bearer token 추가
  - Sidebar: 인증된 사용자만 "데이터셋", "프로젝트" 메뉴 표시
- **권한 규칙**:
  - 소유자(owner)만 삭제/업로드 가능
  - Public 데이터셋은 모든 인증 사용자 조회 가능
  - Private 데이터셋은 소유자만 접근

#### 2. 스냅샷 구현 시기 결정
- **질문**: 학습 파이프라인 테스트 전에 스냅샷 구현이 필요한가?
- **결정**: 학습 파이프라인 먼저 테스트 (Option A) ✅
- **이유**:
  - 스냅샷 없이도 학습 가능 (`dataset_snapshot_id`는 nullable)
  - 학습이 제대로 돌아가야 스냅샷도 의미 있음
  - DB 모델은 이미 준비됨 (빠른 전환 가능)
  - MVP 단계에서는 핵심 기능 검증 우선
- **위험 관리**: 초기 테스트 데이터셋은 수정하지 않기

#### 3. DICE Format 변환 준비
- **목적**: 학습 파이프라인 테스트용 데이터셋 준비
- **작업**: YOLO segmentation → DICE Format v1.0 변환
- **입력**: `C:\datasets\seg-coco32` (YOLO format)
- **출력**: `C:\datasets\dice_format\seg-coco32` (DICE format)
- **결과**:
  - 32 images, 209 annotations
  - 43 COCO classes (person, car, cup 등)
  - instance_segmentation 태스크

#### 4. 프론트엔드 UX 개선
- **문제**: 데이터셋 생성 후 상세 페이지로 자동 전환
- **해결**: 자동 네비게이션 제거, 테이블만 새로고침
- **이유**:
  - 여러 데이터셋 연속 생성 시 편리
  - 불필요한 화면 전환 감소
  - 사용자가 원하면 수동으로 클릭 가능

### 구현 내용

#### Backend (인증 추가)

**`mvp/backend/app/api/datasets.py`**:
```python
# 추가된 imports
from app.db.models import Dataset, User
from app.utils.dependencies import get_current_user

# 수정된 엔드포인트
@router.get("/available")
async def list_sample_datasets(
    current_user: User = Depends(get_current_user),  # 추가
    db: Session = Depends(get_db)
):
    # Owner OR public 필터링
    query = db.query(Dataset).filter(
        or_(
            Dataset.owner_id == current_user.id,
            Dataset.visibility == 'public'
        )
    )

@router.post("")
async def create_dataset(
    current_user: User = Depends(get_current_user),  # 추가
    ...
):
    new_dataset = Dataset(
        owner_id=current_user.id,  # 자동 설정
        ...
    )

@router.delete("/{dataset_id}")
async def delete_dataset(
    current_user: User = Depends(get_current_user),  # 추가
    ...
):
    # 소유자 확인
    if dataset.owner_id != current_user.id:
        raise HTTPException(403, "Permission denied")
```

**`mvp/backend/app/api/datasets_images.py`**:
- 모든 엔드포인트에 `current_user` 파라미터 추가
- 소유자 확인 로직 추가
- Public dataset 조회 허용 로직

**`mvp/backend/app/api/datasets_folder.py`**:
- 폴더 업로드 API에 인증 추가
- 소유자만 업로드 가능

#### Frontend (인증 토큰 추가)

**`mvp/frontend/components/Sidebar.tsx`**:
```tsx
{/* 인증된 사용자만 표시 */}
{isAuthenticated && (
  <div>
    <button onClick={onOpenDatasets}>데이터셋</button>
  </div>
)}

{isAuthenticated && (
  <div>프로젝트 목록</div>
)}
```

**`mvp/frontend/components/DatasetPanel.tsx`**:
```typescript
const fetchDatasets = async () => {
  const token = localStorage.getItem('access_token')

  if (!token) {
    console.error('No access token found')
    return
  }

  const response = await fetch(`${baseUrl}/datasets/available`, {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  })
}

const handleDeleteConfirm = async () => {
  const token = localStorage.getItem('access_token')

  const response = await fetch(`${baseUrl}/datasets/${id}`, {
    method: 'DELETE',
    headers: {
      'Authorization': `Bearer ${token}`
    }
  })
}
```

**`mvp/frontend/components/datasets/CreateDatasetModal.tsx`**:
```typescript
// useRouter import 제거
// router.push() 제거
// 성공 후 모달만 닫기
setTimeout(() => {
  handleClose()  // 네비게이션 없이 닫기만
}, 1000)
```

**기타 컴포넌트**:
- `DatasetImageUpload.tsx`: Bearer token 추가
- `DatasetImageGallery.tsx`: Bearer token 추가
- `ProjectDetail.tsx`: handleSaveEdit에 token 추가
- `datasets/[id]/page.tsx`: Bearer token 추가

#### 유틸리티 스크립트

**`mvp/backend/convert_yolo_seg_to_platform.py`** (새 파일):
- YOLO segmentation → DICE Format 변환
- Normalized coordinates → 절대 pixel coordinates
- Polygon segmentation 데이터 보존
- Bounding box 자동 계산
- Area 계산 (shoelace formula)
- Content hash 생성

### Git 작업

#### Commits (7개)
```
8996157 docs(datasets): add current status and next steps document
744fb3e chore: update gitignore for test files and database backups
99a5ef5 fix(frontend): remove auto-navigation after dataset creation
ae26d92 feat(mvp): implement authentication and authorization for datasets
ab28012 feat(datasets): enhance folder upload and add dataset deletion
d527411 feat(datasets): implement Create-then-Upload architecture
b1677fd feat(datasets): add individual image management with R2 presigned URLs
```

#### Pull Request
- **PR #12**: "feat(datasets): implement Dataset Entity with R2 Storage and Authentication"
- **Base**: main
- **28 commits** total in this feature branch
- **Status**: Ready for review

### 생성된 문서

#### `docs/datasets/CURRENT_STATUS.md` (새 파일)
**목적**: 다음 세션을 위한 종합 상태 문서

**포함 내용**:
- ✅ 완료된 기능 (Phase 1 & 2)
  - Core Infrastructure
  - Backend API (CRUD, Images, Folder)
  - Frontend Components
  - DICE Format v2.0
  - Training Integration
  - Authentication

- ⏳ 남은 작업 (Phase 3 & 4)
  - Sprint 1: 버전닝/스냅샷 (2-3일)
  - Sprint 2: UI/UX 개선 (1-2일)
  - Sprint 3: 무결성 관리 (2-3일)

- 📂 테스트 데이터셋
  - seg-coco32 (DICE Format)
  - 위치, 구조, 메타데이터, 사용법

- 🎯 다음 세션 시작 가이드
  - **Option A**: 학습 파이프라인 테스트 (추천)
  - Option B: 스냅샷 구현
  - Quick Start 명령어

- 🔍 중요 파일 경로 맵

### 테스트 데이터셋

**seg-coco32 (DICE Format v1.0)**:
- **위치**: `C:\datasets\dice_format\seg-coco32`
- **구조**:
  ```
  seg-coco32/
  ├── annotations.json    # DICE Format v1.0
  └── images/             # 32 images
  ```
- **메타데이터**:
  - Format: instance_segmentation
  - Images: 32장
  - Annotations: 209개 polygon segmentations
  - Classes: 43개 COCO 클래스
  - Avg annotations per image: 6.53개
- **Top 5 classes**: person (56), car (19), cup (15), giraffe (9), bird (8)

### 다음 단계

#### Option A: 학습 파이프라인 테스트 (추천 ✅)
**브랜치**: `feature/training-pipeline-test`

**목표**:
1. seg-coco32 데이터셋 Frontend에서 업로드
2. Training API 호출 테스트
3. Backend ↔ Training Service 통신 검증
4. 학습 시작/중지/모니터링 확인
5. MLflow 연동 확인

**Quick Start**:
```bash
# 새 브랜치 생성
git checkout main
git pull
git checkout -b feature/training-pipeline-test

# Backend 시작
cd mvp/backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Frontend 시작
cd mvp/frontend
npm run dev

# 데이터셋 업로드
# http://localhost:3000 → 로그인 → 데이터셋 → Create
# C:\datasets\dice_format\seg-coco32 폴더 선택

# 학습 시작
# 채팅: "seg-coco32 데이터셋으로 yolo11n-seg 모델 학습시작"
```

#### Option B: 스냅샷 구현
**브랜치**: `feature/dataset-snapshots`

**작업 내용**:
- POST `/datasets/{id}/snapshots` API
- 학습 시작 시 자동 스냅샷
- 스냅샷 목록 UI
- 버전 비교 뷰

### 관련 문서

- **상태 문서**: [CURRENT_STATUS.md](./datasets/CURRENT_STATUS.md)
- **설계 문서**: [DATASET_MANAGEMENT_DESIGN.md](./datasets/DATASET_MANAGEMENT_DESIGN.md)
- **구현 계획**: [IMPLEMENTATION_PLAN.md](./datasets/IMPLEMENTATION_PLAN.md)
- **포맷 스펙**: [PLATFORM_DATASET_FORMAT.md](./datasets/PLATFORM_DATASET_FORMAT.md)

### 기술 노트

#### 인증 흐름
```
User → Frontend (localStorage.getItem('access_token'))
     → Backend API (Authorization: Bearer {token})
     → Depends(get_current_user)
     → JWT 검증 및 User 객체 반환
     → 권한 체크 (owner_id 비교)
```

#### 데이터셋 권한 규칙
- **Public datasets**:
  - 모든 인증 사용자 조회 가능
  - 소유자만 수정/삭제
- **Private datasets**:
  - 소유자만 조회/수정/삭제
- **업로드/삭제**:
  - 항상 소유자만 가능

#### .gitignore 업데이트
추가된 패턴:
- `*.db.backup*` - DB 백업 파일
- `test_*.py` - 테스트 스크립트
- `convert_*.py` - 변환 유틸리티
- `migrate_*.py` - 마이그레이션 스크립트

### 핵심 파일

#### Backend
```
mvp/backend/app/
├── api/
│   ├── datasets.py              # ✅ 인증 추가
│   ├── datasets_folder.py       # ✅ 인증 추가
│   ├── datasets_images.py       # ✅ 인증 추가
│   └── training.py              # dataset_id 지원
├── utils/
│   ├── r2_storage.py
│   └── dependencies.py          # get_current_user
└── convert_yolo_seg_to_platform.py  # 새 파일 (gitignore)
```

#### Frontend
```
mvp/frontend/
├── components/
│   ├── DatasetPanel.tsx          # ✅ 토큰 추가
│   ├── Sidebar.tsx               # ✅ 조건부 렌더링
│   ├── ProjectDetail.tsx         # ✅ 토큰 추가
│   └── datasets/
│       ├── CreateDatasetModal.tsx    # ✅ 네비게이션 제거
│       ├── DatasetImageUpload.tsx    # ✅ 토큰 추가
│       └── DatasetImageGallery.tsx   # ✅ 토큰 추가
└── app/datasets/[id]/page.tsx    # ✅ 토큰 추가
```

#### Documentation
```
docs/datasets/
├── CURRENT_STATUS.md             # 새 파일 ⭐
├── DATASET_MANAGEMENT_DESIGN.md
├── IMPLEMENTATION_PLAN.md
└── PLATFORM_DATASET_FORMAT.md
```

---

## [2025-01-04 13:00] 데이터셋 관리 UI 통합 및 설계 논의

### 논의 주제
- 데이터셋 UI 레이아웃 통합 문제
- 하드코딩 데이터 제거
- 데이터셋 업로드 방식 설계
- 버전닝 전략
- 무결성 관리

### 주요 결정사항

#### 1. UI 레이아웃 통합
- **문제**: 데이터셋 버튼 클릭 시 전체 화면으로 나와서 기존 레이아웃(사이드바, 채팅, 작업공간) 무시
- **해결**:
  - 새 `DatasetPanel` 컴포넌트 생성 (컴팩트 테이블 디자인)
  - `app/page.tsx`에 상태 관리 추가
  - Sidebar에서 라우팅 대신 핸들러 호출
- **결과**: AdminProjectsPanel과 동일한 패턴으로 작업공간에 통합

#### 2. 하드코딩 데이터 제거
- **문제**: DB에 6개 샘플 데이터셋 하드코딩됨 (cls-imagenet-10 등)
- **원칙 위반**: CLAUDE.md - "no shortcut, no hardcoding, no dummy data"
- **해결**: DB에서 모든 샘플 데이터 삭제
- **결과**: 실제 업로드한 데이터만 표시

#### 3. task_type은 데이터셋 속성이 아니다
- **핵심 통찰**: 같은 이미지를 classification, detection, segmentation 등 다양하게 활용 가능
- **결정**:
  - ❌ Dataset.task_type 삭제
  - ✅ TrainingJob.task_type 추가
  - 데이터셋은 이미지 저장소, 학습 작업이 용도 결정

#### 4. 폴더 구조 유지
- **결정**: 업로드 시 폴더 구조 항상 유지
- **R2 경로**: `datasets/{id}/images/{original_path}`
- **이유**:
  - 원본 구조 보존
  - 파일명 충돌 방지
  - 유연성 확보

#### 5. labeled의 정의
- **정의**: `labeled = annotation.json 존재 여부`
- **규칙**:
  - labeled 업로드는 폴더만 가능 (annotation.json 필요)
  - unlabeled는 폴더/개별 파일 모두 가능
  - labeled 데이터셋에 labeled 폴더 병합 **금지**

#### 6. meta.json 생성 시점
- **unlabeled**: meta.json 없음 (DB만)
- **labeled 전환**: annotation.json + meta.json 함께 생성
- **export**: 항상 meta.json 포함
- **Single Source of Truth**: DB

#### 7. 버전닝 전략: Mutable + Snapshot
- **원칙**:
  - 데이터셋은 기본적으로 가변(mutable)
  - 학습 시작 시 자동 스냅샷 생성
  - 사용자가 명시적 버전 생성 가능 (v1, v2...)
- **효율성**:
  - 이미지는 모든 버전이 공유
  - 스냅샷은 annotation.json만 저장
  - 저장 공간 99% 절약 (10GB + 10MB + 10MB vs 30GB)

#### 8. 이미지 삭제 허용 + 무결성 관리
- **이미지 삭제**: 허용
- **영향받는 스냅샷 처리**:
  - 옵션 A: Broken 표시 (재현 불가)
  - 옵션 B: 자동 복구 (annotation 수정)
- **주기적 무결성 체크**: Celery task로 구현

### 구현 내용

#### Frontend
- `components/DatasetPanel.tsx`: 컴팩트 테이블 UI (새 파일)
  - 검색, 정렬 기능
  - 확장 가능한 행 (이미지 갤러리)
  - 이미지 업로드/조회

- `app/page.tsx`: 상태 관리 추가
  - `showDatasets` state
  - `handleOpenDatasets()` 핸들러
  - 작업공간에 DatasetPanel 렌더링

- `components/Sidebar.tsx`: 라우팅 제거
  - `router.push('/datasets')` → `onOpenDatasets()` 호출

#### Backend
- 기존 개별 이미지 업로드 API 유지
  - POST `/datasets/{id}/images`
  - GET `/datasets/{id}/images`

#### Database
- 하드코딩된 6개 샘플 데이터셋 삭제

### 관련 문서

- **설계 문서**: [DATASET_MANAGEMENT_DESIGN.md](./datasets/DATASET_MANAGEMENT_DESIGN.md)
  - 데이터 모델
  - 스토리지 구조
  - 12가지 업로드 시나리오
  - 버전닝 전략
  - 무결성 관리

- **기존 문서**:
  - [DICE_FORMAT_v2.md](./datasets/DICE_FORMAT_v2.md)
  - [STORAGE_ACCESS_PATTERNS.md](./datasets/STORAGE_ACCESS_PATTERNS.md)

### 다음 단계

#### Phase 2: 폴더 업로드 (다음 구현)
- [ ] 폴더 구조 유지 업로드 (`webkitdirectory`)
- [ ] labeled 데이터셋 생성 (annotation.json 포함)
- [ ] DB 모델 확장 (labeled, class_names, is_snapshot 등)

#### Phase 3: 버전닝
- [ ] 학습 시 자동 스냅샷
- [ ] 명시적 버전 생성
- [ ] 스냅샷 목록 UI

#### Phase 4: 무결성 관리
- [ ] 이미지 삭제 시 영향 분석
- [ ] Broken/복구 로직
- [ ] 주기적 무결성 체크

### 기술 스택
- Frontend: Next.js 14, TypeScript, Tailwind CSS
- Backend: FastAPI, Python, SQLAlchemy
- Storage: Cloudflare R2 (S3-compatible)
- Database: SQLite (local), PostgreSQL (production)

### 핵심 파일
- `mvp/frontend/components/DatasetPanel.tsx` (새로 생성)
- `mvp/frontend/app/page.tsx` (수정)
- `mvp/frontend/components/Sidebar.tsx` (수정)
- `mvp/backend/app/api/datasets_images.py` (기존)
- `mvp/backend/app/utils/r2_storage.py` (기존)

---

