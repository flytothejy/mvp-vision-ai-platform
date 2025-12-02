# Testing Strategy & Principles

**Last Updated**: 2025-12-02
**Purpose**: 프론트엔드 동작과 정확히 매칭된 테스트를 통해 개발 속도를 극대화

---

## Core Principles

### 1. Test As You Use (실제 사용과 동일하게 테스트)

**DO:**
- ✅ 프론트엔드에서 실제 발생하는 request 그대로 사용
- ✅ 실제 데이터베이스에 저장된 데이터 사용
- ✅ 실제 S3에 업로드된 데이터셋 사용
- ✅ 실제 사용자 계정으로 로그인
- ✅ 전체 파이프라인을 끝까지 실행 (로그인 → 학습 생성 → 학습 시작 → 완료)

**DON'T:**
- ❌ 임시로 기능 테스트만 하기 (예: "캐싱만 테스트")
- ❌ 우리가 사용하지 않는 데이터 양식 사용 (예: 임의로 만든 JSON)
- ❌ 더미 데이터셋/유저 생성 (예: `test_user`, `dummy_dataset`)
- ❌ 진행 단계 건너뛰기 (예: "학습 생성 없이 직접 TrainerSDK 호출")
- ❌ 환경변수 임의 변경 (예: 테스트 전용 `TEST_MODE=true`)

**Why:**
> 테스트는 통과했는데 프론트엔드 연동하면 하나부터 열까지 다시 디버깅해야 한다면,
> 그 테스트는 아무 의미가 없다.

---

## 2. Frontend Request-Based Testing (프론트엔드 Request 기반)

### Request Capture & Replay

모든 테스트는 **프론트엔드에서 실제 발생하는 HTTP request**를 기반으로 진행합니다.

#### Step 1: Capture Real Frontend Request

프론트엔드에서 동작을 실행하고 개발자 도구(F12)로 request를 캡처:

```json
// scenarios/yolo_detection_training.json
{
  "name": "YOLO Detection Training (MVTec-AD)",
  "description": "yolo11n 모델로 MVTec-AD 데이터셋 학습",
  "steps": [
    {
      "step": 1,
      "action": "login",
      "method": "POST",
      "url": "/api/v1/auth/login",
      "data": {
        "username": "admin@example.com",
        "password": "admin123"
      },
      "expected_status": 200,
      "extract": {
        "access_token": "$.access_token"
      }
    },
    {
      "step": 2,
      "action": "create_training_job",
      "method": "POST",
      "url": "/api/v1/training/jobs",
      "headers": {
        "Authorization": "Bearer {access_token}"
      },
      "data": {
        "config": {
          "framework": "ultralytics",
          "model_name": "yolo11n",
          "task_type": "detection",
          "dataset_id": "ds_c75023ca76d7448b",
          "epochs": 3,
          "batch_size": 2,
          "learning_rate": 0.001,
          "image_size": 640
        },
        "project_id": 1
      },
      "expected_status": 200,
      "extract": {
        "job_id": "$.id"
      }
    },
    {
      "step": 3,
      "action": "start_training",
      "method": "POST",
      "url": "/api/v1/training/jobs/{job_id}/start",
      "headers": {
        "Authorization": "Bearer {access_token}"
      },
      "expected_status": 200
    },
    {
      "step": 4,
      "action": "poll_status",
      "method": "GET",
      "url": "/api/v1/training/jobs/{job_id}",
      "headers": {
        "Authorization": "Bearer {access_token}"
      },
      "poll_interval": 5,
      "poll_timeout": 300,
      "expected_final_status": "completed"
    }
  ],
  "validation": {
    "check_cache_hit": true,
    "check_selective_download": true,
    "check_metrics_saved": true
  }
}
```

#### Step 2: Save as Scenario File

시나리오를 `platform/backend/tests/scenarios/` 디렉토리에 저장:

```
platform/backend/tests/scenarios/
├── yolo_detection_training.json      # YOLO 객체 탐지 학습
├── yolo_segmentation_training.json   # YOLO 세그멘테이션 학습
├── timm_classification_training.json # timm 이미지 분류 학습
└── training_restart.json             # 학습 재시작
```

#### Step 3: Run with Unified Test Script

**동일한 테스트 스크립트**를 사용해서 모든 시나리오 실행:

```bash
# Single scenario
python tests/run_scenario.py scenarios/yolo_detection_training.json

# All scenarios
python tests/run_scenario.py scenarios/*.json

# Specific feature validation
python tests/run_scenario.py scenarios/yolo_detection_training.json --validate cache
```

---

## 3. Unified Test Script (통합 테스트 스크립트)

### Design Principles

**DO:**
- ✅ 하나의 범용 테스트 러너 사용 (`run_scenario.py`)
- ✅ 시나리오 파일만 교체해서 다양한 테스트 수행
- ✅ 공통 로직 재사용 (request 실행, 토큰 관리, polling, validation)
- ✅ 테스트 결과를 구조화된 로그로 저장

**DON'T:**
- ❌ 매번 새로운 테스트 스크립트 작성
- ❌ 시나리오마다 중복 코드 작성
- ❌ 테스트 로직이 시나리오에 하드코딩

### Test Script Structure

```
platform/backend/tests/
├── run_scenario.py              # 통합 테스트 러너 (이것만 사용)
├── lib/
│   ├── request_executor.py      # HTTP request 실행
│   ├── token_manager.py         # JWT 토큰 관리
│   ├── validator.py             # 결과 검증
│   └── logger.py                # 구조화된 로그
├── scenarios/                   # 시나리오 파일들
│   └── *.json
└── results/                     # 테스트 결과 저장
    └── {timestamp}_{scenario_name}/
        ├── request_log.json     # 모든 request/response
        ├── validation.json      # 검증 결과
        └── backend.log          # Backend 로그 복사
```

---

## 4. Development Speed Optimization (개발 속도 극대화)

### Why Frontend-Matched Testing?

**문제:**
```
개발 → 단위 테스트 통과 → 프론트엔드 연동 → 전부 안됨 → 다시 디버깅
     ↑_______________________________________________|
              시간 낭비 사이클
```

**해결:**
```
개발 → Frontend Request 기반 테스트 → 프론트엔드 연동 → 바로 작동
     ↑__________________________________________|
           빠른 피드백 사이클
```

### Testing Workflow

1. **Feature 개발**
   - Backend API 수정/추가
   - TrainerSDK 기능 추가

2. **Frontend에서 동작 확인**
   - 프론트엔드에서 한 번 실행
   - 개발자 도구로 request 캡처
   - 시나리오 파일 작성 (5분)

3. **반복 테스트**
   ```bash
   # 이후 수정할 때마다 이것만 실행
   python tests/run_scenario.py scenarios/my_feature.json
   ```
   - Frontend 실행 없이 빠른 검증
   - 실제 동작과 100% 동일 보장

4. **프론트엔드 재연동**
   - 테스트 통과했으면 프론트엔드에서도 작동 보장
   - 추가 디버깅 불필요

---

## 5. Anti-Patterns (하지 말아야 할 것들)

### ❌ Anti-Pattern 1: 테스트 통과만을 위한 테스트

```python
# BAD: 임의의 더미 데이터로 기능만 테스트
def test_caching():
    os.environ['DATASET_ID'] = 'dummy_dataset'
    os.environ['SNAPSHOT_ID'] = 'fake_snapshot'
    sdk.download_dataset_with_cache(...)
    # 통과했지만 실제로는 작동 안함
```

```python
# GOOD: 실제 Frontend request 재현
scenario = load_scenario('yolo_detection_training.json')
execute_scenario(scenario)
# 실제로 작동하는 것만 통과
```

---

### ❌ Anti-Pattern 2: 매번 새로운 테스트 스크립트 작성

```bash
# BAD: 기능마다 스크립트 생성
test_cache.py
test_selective_download.py
test_restart.py
test_yolo_training.py
# → 유지보수 지옥
```

```bash
# GOOD: 하나의 러너 + 시나리오 파일
run_scenario.py scenarios/cache_validation.json
run_scenario.py scenarios/selective_download.json
run_scenario.py scenarios/restart.json
# → 유지보수 쉬움
```

---

### ❌ Anti-Pattern 3: 진행 단계 건너뛰기

```python
# BAD: TrainerSDK를 직접 호출
sdk = TrainerSDK()
sdk.download_dataset_with_cache(...)
# 실제로는 Workflow → SubprocessManager → TrainerSDK 순서
```

```json
// GOOD: 전체 파이프라인 실행
{
  "steps": [
    {"action": "login"},
    {"action": "create_job"},
    {"action": "start_job"},    // Workflow 시작
    {"action": "poll_status"}   // 완료까지 대기
  ]
}
```

---

### ❌ Anti-Pattern 4: 우리가 사용하지 않는 데이터 양식

```python
# BAD: 임의로 만든 JSON
test_dataset = {
    "images": [{"id": 1, "file": "test.jpg"}],
    "annotations": [{"id": 1, "bbox": [0, 0, 100, 100]}]
}
```

```json
// GOOD: 실제 Labeler에서 생성된 annotations_detection.json
{
  "images": [
    {
      "id": 1,
      "file_name": "bottle/broken_large/000.png",
      "height": 900,
      "width": 900
    }
  ],
  "annotations": [
    {
      "id": 1,
      "image_id": 1,
      "category_id": 1,
      "bbox": [...]
    }
  ]
}
```

---

## 6. Validation Checklist (검증 체크리스트)

### Phase 12.9: Dataset Caching & Optimization

테스트 시나리오 실행 후 반드시 확인:

- [ ] **Cache MISS 로그 확인** (첫 번째 학습)
  ```
  [2025-12-02 10:00:00] Cache MISS: snap_xxx_12345678
  [2025-12-02 10:00:05] Selective download: 156 images
  ```

- [ ] **Cache HIT 로그 확인** (두 번째 학습, 동일 snapshot)
  ```
  [2025-12-02 10:05:00] Cache HIT: snap_xxx_12345678
  [2025-12-02 10:05:01] Symlink created: /tmp/datasets/...
  ```

- [ ] **Selective Download 확인**
  ```
  # annotations_detection.json의 이미지 수와 다운로드 수 일치
  Annotations: 156 images
  Downloaded: 156 images (not 227 total images)
  ```

- [ ] **캐시 디렉토리 확인**
  ```bash
  ls -lh /tmp/datasets/
  # snap_xxx_12345678/ 존재
  # .metadata.json 존재
  # data.yaml 존재
  ```

- [ ] **학습 완료 확인**
  ```
  Training completed: 3/3 epochs
  Best metrics saved
  Checkpoint uploaded to S3
  ```

---

## 7. Quick Reference (빠른 참조)

### 새로운 기능 개발 시

1. Backend 코드 수정
2. Frontend에서 한 번 실행 → Request 캡처
3. `scenarios/my_feature.json` 작성
4. `python tests/run_scenario.py scenarios/my_feature.json`
5. 통과할 때까지 반복
6. 프론트엔드 재연동 → 바로 작동

### 기존 기능 디버깅 시

1. 해당 시나리오 파일 찾기 (예: `yolo_detection_training.json`)
2. `python tests/run_scenario.py scenarios/yolo_detection_training.json --verbose`
3. 로그 확인: `results/{timestamp}_yolo_detection_training/`
4. 수정 후 다시 실행

### CI/CD Integration

```yaml
# .github/workflows/test.yml
- name: Run E2E Scenarios
  run: |
    python tests/run_scenario.py scenarios/*.json --ci-mode
```

---

## Summary

**핵심 원칙:**
1. ✅ 실제 사용과 동일하게 테스트
2. ✅ Frontend request 기반 테스트
3. ✅ 하나의 통합 스크립트 사용
4. ✅ 개발 속도 극대화가 목적
5. ✅ 테스트 통과 = 프론트엔드 작동 보장

**금지 사항:**
1. ❌ 더미 데이터 사용
2. ❌ 진행 단계 건너뛰기
3. ❌ 매번 새로운 테스트 스크립트
4. ❌ 테스트 통과만을 위한 테스트
5. ❌ Frontend와 다른 데이터 양식

---

**Related Documents:**
- [Testing Implementation Guide](./TESTING_IMPLEMENTATION.md)
- [Scenario File Format](./SCENARIO_FORMAT.md)
- [Development Workflow](../development/DEVELOPMENT.md)
