# Phase 12.9: Dataset Caching & Selective Download

**브랜치**: `feature/phase-12.9-dataset-optimization`

**목표**: 데이터셋 다운로드 효율화 및 캐싱 전략 구현으로 반복 학습 속도 향상

**날짜**: 2025-12-02

**예상 기간**: 1.5일 (12시간)

---

## 문제 인식

### 현재 문제점

1. **매 Job마다 전체 데이터셋 다운로드**
   - Job 91, 92, 93... 모두 같은 `ds_c75023ca76d7448b`를 각각 3분씩 다운로드
   - 10개 Job = 30분 대기 시간

2. **불필요한 이미지 다운로드**
   - 전체 `datasets/{id}/images/` prefix를 다운로드
   - MVTec-AD: 163개 labeled images vs 1000+ total images (6배 낭비)
   - Annotation 없는 이미지까지 모두 다운로드

3. **Completed/Failed Job Restart 불가**
   - `status != "pending"`이면 시작 불가
   - 반복 실험을 위해 매번 새 Job 생성 필요
   - Hyperparameter tuning 시 비효율적

4. **디스크 공간 낭비**
   - 각 Job별로 독립적인 dataset 복사본 저장
   - `/tmp/training/91/dataset`, `/tmp/training/92/dataset` ... 모두 동일 내용

### 측정된 영향

```
현재 상황 (10 Jobs, 같은 dataset):
  - 총 대기 시간: 30분 (각 3분 × 10)
  - 총 다운로드: 15GB (각 1.5GB × 10)
  - 총 디스크 사용: 15GB (중복 저장)

목표 (캐싱 적용 후):
  - 총 대기 시간: ~3분 (첫 Job 3분, 나머지 < 1초)
  - 총 다운로드: 1.5GB (캐시 1회만)
  - 총 디스크 사용: 1.5GB (공유 캐시)

개선 효과:
  - 시간: 90% 절감 (30분 → 3분)
  - 대역폭: 90% 절감 (15GB → 1.5GB)
  - 디스크: 90% 절감 (15GB → 1.5GB)
```

---

## 기술적 배경

### 현재 Snapshot 시스템 (Phase 12.6)

Phase 12.6에서 이미 완벽한 버전 관리 인프라 구축:

```python
class DatasetSnapshot(Base):
    id = Column(String(100), primary_key=True)  # snap_2b2fca921e88
    dataset_id = Column(String(100), nullable=False)  # ds_c75023ca76d7448b
    storage_path = Column(String(500), nullable=False)  # datasets/ds_c75023ca76d7448b/
    dataset_version_hash = Column(String(64), nullable=True)  # SHA256 hash
    created_at = Column(DateTime, nullable=False)
```

**Hash 계산 방식** (`snapshot_service.py:143-199`):
```python
def _calculate_dataset_hash(dataset_path: str) -> str:
    """
    Calculate SHA256 hash of metadata files only (not images).

    Files included:
    - annotations_detection.json
    - metadata.json
    - data.yaml
    - *.txt files

    Images NOT included:
    - Fast computation (no GB hashing)
    - Annotation changes are what matter
    """
```

**장점**:
- Immutable snapshot = 캐시 안전
- Hash 변경 = 데이터셋 내용 변경 자동 감지
- Collision detection: 같은 hash = 같은 내용

---

## 해결 방안

### 12.9.1 Snapshot 기반 데이터셋 캐싱

**아키텍처**: Snapshot ID + Hash 기반 공유 캐시

#### Cache Key 구조

```
Cache Key = {snapshot_id}_{dataset_version_hash[:8]}

예시:
  snap_2b2fca921e88_1bb25f37
  snap_abc123def456_3ca92d81
```

#### 디렉토리 구조

```
/tmp/datasets/  ← Shared cache directory
  snap_2b2fca921e88_1bb25f37/  ← Cached dataset
    annotations_detection.json
    images/
      images/wood/scratch/000.png
      images/zipper/good/001.png
      ...
  snap_abc123def456_3ca92d81/  ← Different version
    annotations_detection.json
    images/...

/tmp/training/  ← Job-specific directories
  91/
    dataset -> /tmp/datasets/snap_2b2fca921e88_1bb25f37  ← Symlink
  92/
    dataset -> /tmp/datasets/snap_2b2fca921e88_1bb25f37  ← Reuse
  93/
    dataset -> /tmp/datasets/snap_abc123def456_3ca92d81  ← New version
```

#### 캐싱 플로우

```python
# trainer_sdk.py

SHARED_DATASET_CACHE = Path("/tmp/datasets")
CACHE_MAX_SIZE_GB = 50  # LRU eviction

def download_dataset_with_cache(
    self,
    snapshot_id: str,
    dataset_id: str,
    dataset_version_hash: str,
    dest_dir: str
) -> str:
    """
    Download dataset with caching support.

    Args:
        snapshot_id: Snapshot ID (snap_abc123)
        dataset_id: Original dataset ID (ds_c75023ca76d7448b)
        dataset_version_hash: SHA256 hash from SnapshotService
        dest_dir: Job working directory (/tmp/training/92)

    Returns:
        Local dataset directory path
    """
    # 1. Build cache key
    cache_key = f"{snapshot_id}_{dataset_version_hash[:8]}"
    cache_dir = SHARED_DATASET_CACHE / cache_key

    # 2. Check cache
    if cache_dir.exists():
        if self._verify_cache_integrity(cache_dir, dataset_version_hash):
            logger.info(f"✅ Cache HIT: {cache_key}")
            self._update_last_accessed(cache_key)
            return self._link_to_cache(cache_dir, dest_dir)
        else:
            logger.warning(f"⚠️ Cache corrupted: {cache_key}, re-downloading")
            shutil.rmtree(cache_dir)

    # 3. Cache MISS - Download dataset
    logger.info(f"❌ Cache MISS: {cache_key}, downloading...")

    # Create cache directory
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Download dataset (selective download)
    self.download_dataset_selective(
        dataset_id=dataset_id,
        dest_dir=str(cache_dir)
    )

    # 4. Verify downloaded data
    if not self._verify_cache_integrity(cache_dir, dataset_version_hash):
        raise RuntimeError(f"Downloaded data hash mismatch for {cache_key}")

    # 5. Update cache metadata
    self._update_cache_metadata(cache_key, {
        'snapshot_id': snapshot_id,
        'dataset_id': dataset_id,
        'dataset_version_hash': dataset_version_hash,
        'created_at': datetime.utcnow().isoformat(),
        'last_accessed': datetime.utcnow().isoformat(),
        'size_bytes': self._calculate_dir_size(cache_dir)
    })

    # 6. Check cache size and evict if needed
    self._enforce_cache_size_limit()

    # 7. Link to job directory
    return self._link_to_cache(cache_dir, dest_dir)
```

#### Helper 메서드

```python
def _verify_cache_integrity(
    self,
    cache_dir: Path,
    expected_hash: str
) -> bool:
    """
    Verify cache integrity by recalculating hash.

    Matches SnapshotService logic:
    - Only hash metadata files (.json, .yaml, .txt)
    - Skip images for performance
    """
    hasher = hashlib.sha256()

    # Find all metadata files
    metadata_files = sorted([
        f for f in cache_dir.rglob('*')
        if f.is_file() and f.suffix in ['.json', '.yaml', '.yml', '.txt']
    ])

    for file_path in metadata_files:
        with open(file_path, 'rb') as f:
            hasher.update(f.read())

    calculated_hash = hasher.hexdigest()

    if calculated_hash != expected_hash:
        logger.error(
            f"Cache integrity check failed:\n"
            f"  Expected: {expected_hash}\n"
            f"  Calculated: {calculated_hash}"
        )
        return False

    return True


def _link_to_cache(self, cache_dir: Path, dest_dir: str) -> str:
    """
    Create symlink from job directory to cache.

    /tmp/training/92/dataset -> /tmp/datasets/snap_2b2fca921e88_1bb25f37
    """
    job_dataset_dir = Path(dest_dir) / "dataset"

    if job_dataset_dir.exists():
        if job_dataset_dir.is_symlink():
            job_dataset_dir.unlink()
        else:
            shutil.rmtree(job_dataset_dir)

    job_dataset_dir.symlink_to(cache_dir, target_is_directory=True)

    logger.info(f"📎 Linked: {job_dataset_dir} -> {cache_dir}")

    return str(job_dataset_dir)


def _update_cache_metadata(self, cache_key: str, metadata: dict):
    """Update cache metadata JSON file"""
    cache_metadata_file = SHARED_DATASET_CACHE / ".cache_metadata.json"

    if cache_metadata_file.exists():
        with open(cache_metadata_file) as f:
            all_metadata = json.load(f)
    else:
        all_metadata = {}

    all_metadata[cache_key] = metadata

    with open(cache_metadata_file, 'w') as f:
        json.dump(all_metadata, f, indent=2)


def _enforce_cache_size_limit(self):
    """
    Enforce cache size limit using LRU eviction.

    Strategy:
    1. Calculate total cache size
    2. If > CACHE_MAX_SIZE_GB, evict least recently used
    3. Keep evicting until under limit
    """
    cache_metadata_file = SHARED_DATASET_CACHE / ".cache_metadata.json"

    if not cache_metadata_file.exists():
        return

    with open(cache_metadata_file) as f:
        metadata = json.load(f)

    # Calculate total size
    total_size_gb = sum(
        item['size_bytes'] for item in metadata.values()
    ) / (1024 ** 3)

    if total_size_gb <= CACHE_MAX_SIZE_GB:
        return

    logger.info(
        f"Cache size ({total_size_gb:.2f} GB) exceeds limit "
        f"({CACHE_MAX_SIZE_GB} GB), evicting LRU entries"
    )

    # Sort by last accessed (oldest first)
    sorted_items = sorted(
        metadata.items(),
        key=lambda x: x[1]['last_accessed']
    )

    # Evict until under limit
    for cache_key, item in sorted_items:
        cache_dir = SHARED_DATASET_CACHE / cache_key

        if cache_dir.exists():
            logger.info(f"🗑️ Evicting cache: {cache_key}")
            shutil.rmtree(cache_dir)

        del metadata[cache_key]

        # Recalculate total size
        total_size_gb = sum(
            item['size_bytes'] for item in metadata.values()
        ) / (1024 ** 3)

        if total_size_gb <= CACHE_MAX_SIZE_GB:
            break

    # Save updated metadata
    with open(cache_metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)
```

#### Cache Metadata 구조

```json
// /tmp/datasets/.cache_metadata.json
{
  "snap_2b2fca921e88_1bb25f37": {
    "snapshot_id": "snap_2b2fca921e88",
    "dataset_id": "ds_c75023ca76d7448b",
    "dataset_version_hash": "1bb25f372b040280...",
    "created_at": "2025-12-02T08:00:00",
    "last_accessed": "2025-12-02T09:15:00",
    "size_bytes": 1572864000,  // 1.5 GB
    "num_jobs_used": 5
  },
  "snap_abc123def456_3ca92d81": {
    "snapshot_id": "snap_abc123def456",
    "dataset_id": "ds_c75023ca76d7448b",
    "dataset_version_hash": "3ca92d81e5f12abc...",
    "created_at": "2025-12-02T10:00:00",
    "last_accessed": "2025-12-02T10:05:00",
    "size_bytes": 1610612736,  // 1.6 GB
    "num_jobs_used": 1
  }
}
```

#### Backend Integration

**1. training.py: Pass hash to workflow**
```python
# training.py: start_training_job()

snapshot = db.query(DatasetSnapshot).filter(
    DatasetSnapshot.id == job.snapshot_id
).first()

await temporal_client.start_workflow(
    TrainingWorkflow.run,
    args=[{
        'job_id': job_id,
        'snapshot_id': snapshot.id,
        'dataset_id': snapshot.dataset_id,
        'dataset_version_hash': snapshot.dataset_version_hash,  # ← 추가
        'storage_path': snapshot.storage_path
    }],
    ...
)
```

**2. training_workflow.py: Forward to activity**
```python
# training_workflow.py: execute_training activity

training_result = await workflow.execute_activity(
    "execute_training",
    {
        'job_id': params['job_id'],
        'snapshot_id': params['snapshot_id'],
        'dataset_id': params['dataset_id'],
        'dataset_version_hash': params['dataset_version_hash'],  # ← 추가
        ...
    },
    ...
)
```

**3. subprocess_manager.py: Add env var**
```python
# subprocess_manager.py: start_training()

env = {
    'JOB_ID': str(job_id),
    'SNAPSHOT_ID': snapshot_id,
    'DATASET_ID': dataset_id,
    'DATASET_VERSION_HASH': dataset_version_hash,  # ← 추가
    ...
}
```

**4. train.py: Use caching**
```python
# train.py

snapshot_id = os.getenv('SNAPSHOT_ID')
dataset_id = os.getenv('DATASET_ID')
dataset_version_hash = os.getenv('DATASET_VERSION_HASH')

# Use caching
local_dataset_dir = sdk.download_dataset_with_cache(
    snapshot_id=snapshot_id,
    dataset_id=dataset_id,
    dataset_version_hash=dataset_version_hash,
    dest_dir=working_dir
)
```

#### 작업 항목

- [ ] `download_dataset_with_cache()` 메서드 구현
- [ ] `_verify_cache_integrity()` - Hash-based verification
- [ ] `_link_to_cache()` - Symlink creation
- [ ] `_update_cache_metadata()` - Metadata management
- [ ] `_enforce_cache_size_limit()` - LRU eviction
- [ ] Cache metadata JSON 파일 관리
- [ ] Backend integration (hash 전달 경로)
- [ ] Lock file for race condition (`/tmp/datasets/.lock_{cache_key}`)

#### 테스트 시나리오

```python
def test_cache_hit_miss():
    # Job 91: First run
    result = sdk.download_dataset_with_cache(
        snapshot_id="snap_2b2fca921e88",
        dataset_id="ds_c75023ca76d7448b",
        dataset_version_hash="1bb25f372b040280...",
        dest_dir="/tmp/training/91"
    )
    assert result.endswith("/tmp/training/91/dataset")
    assert cache_miss == True

    # Job 92: Same dataset
    result = sdk.download_dataset_with_cache(
        snapshot_id="snap_2b2fca921e88",
        dataset_id="ds_c75023ca76d7448b",
        dataset_version_hash="1bb25f372b040280...",
        dest_dir="/tmp/training/92"
    )
    assert cache_hit == True
    assert link_time < 2  # seconds

def test_hash_mismatch_detection():
    # Corrupt cache
    cache_dir = Path("/tmp/datasets/snap_2b2fca921e88_1bb25f37")
    (cache_dir / "annotations_detection.json").write_text("corrupted")

    # Should detect corruption and re-download
    result = sdk.download_dataset_with_cache(...)
    assert re_downloaded == True
```

---

### 12.9.2 Annotation 기반 선택적 다운로드

**현재 문제**:
```python
# trainer_sdk.py:811-825
def download_dataset(self, dataset_id: str, dest_dir: str) -> str:
    prefix = f"datasets/{dataset_id}/"
    local_dir = self.external_storage.download_directory(prefix, dest_dir)
    return local_dir
```

**문제점**:
- MVTec-AD: 163 labeled images vs 1000+ total images
- 3분 다운로드 → 30초면 충분 (6배 빠름)

**해결**:

```python
def download_dataset_selective(self, dataset_id: str, dest_dir: str) -> str:
    """
    Download only images listed in annotations.

    Flow:
    1. Download annotations_detection.json first
    2. Parse and extract image file_name list
    3. Download only those images (parallel)
    4. Return dataset directory
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Step 1: Download annotation file
    annotation_key = f"datasets/{dataset_id}/annotations_detection.json"
    annotation_local_path = Path(dest_dir) / "annotations_detection.json"
    annotation_local_path.parent.mkdir(parents=True, exist_ok=True)

    self.external_storage.download_file(
        annotation_key,
        str(annotation_local_path)
    )

    # Step 2: Parse annotation
    with open(annotation_local_path) as f:
        data = json.load(f)

    images_to_download = []
    for img in data['images']:
        images_to_download.append(img['file_name'])

    logger.info(f"Found {len(images_to_download)} images to download")

    # Step 3: Download required images only
    storage_info = data.get('storage_info', {})
    image_root = storage_info.get('image_root', f'datasets/{dataset_id}/images/')

    # Parallel download
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = []

        for file_name in images_to_download:
            s3_key = f"{image_root}{file_name}"
            local_path = Path(dest_dir) / file_name
            local_path.parent.mkdir(parents=True, exist_ok=True)

            future = executor.submit(
                self._download_single_file,
                s3_key,
                str(local_path)
            )
            futures.append((file_name, future))

        # Wait for completion with progress
        completed = 0
        for file_name, future in futures:
            try:
                future.result()
                completed += 1
                if completed % 10 == 0:
                    logger.info(f"Downloaded {completed}/{len(images_to_download)} images")
            except Exception as e:
                logger.error(f"Failed to download {file_name}: {e}")
                raise

    logger.info(f"✅ Downloaded {len(images_to_download)} images")
    return dest_dir


def _download_single_file(self, s3_key: str, local_path: str):
    """Download single file from S3"""
    self.external_storage.download_file(s3_key, local_path)
```

#### 작업 항목

- [ ] `download_dataset_selective()` 구현
- [ ] `_download_single_file()` helper 메서드
- [ ] ThreadPoolExecutor를 사용한 병렬 다운로드
- [ ] Progress logging (downloaded X / Y images)
- [ ] Error handling (partial download 복구)
- [ ] Negative sample 처리 검증 (이미 올바름, 테스트만 필요)

---

### 12.9.3 Completed/Failed Job Restart 기능

**현재 문제**:
```python
# training.py:511-515
if job.status != "pending":
    raise HTTPException(
        status_code=400,
        detail=f"Cannot start job with status '{job.status}'",
    )
```

**해결**:
```python
# training.py:start_training_job()

# Allow restart for completed/failed jobs
if job.status not in ["pending", "completed", "failed"]:
    raise HTTPException(
        status_code=400,
        detail=f"Cannot start job with status '{job.status}'. Only pending, completed, or failed jobs can be started.",
    )

# If completed/failed, reset to pending
if job.status in ["completed", "failed"]:
    logger.info(f"[JOB {job_id}] Restarting {job.status} job, resetting to pending")

    job.status = "pending"
    job.started_at = None
    job.completed_at = None
    job.error_message = None

    # Optional: Clear history if requested
    clear_history = request.query_params.get('clear_history', 'false').lower() == 'true'

    if clear_history:
        # Clear existing metrics/logs for fresh start
        # Implementation depends on metrics storage strategy
        pass

    db.commit()
    db.refresh(job)
```

#### 작업 항목

- [ ] Status 체크 로직 수정
- [ ] Job 상태 리셋 로직
- [ ] `clear_history` 옵션 구현 (선택적)
- [ ] Frontend: Restart 버튼 추가
- [ ] 테스트: Restart 후 정상 실행 확인

---

## 구현 계획

### Day 1 (8시간)

**오전 (4시간): 캐싱 인프라**
- [ ] `download_dataset_with_cache()` 구현
- [ ] `_verify_cache_integrity()` 구현
- [ ] `_link_to_cache()` 구현
- [ ] Cache metadata 관리

**오후 (4시간): Backend Integration**
- [ ] Backend hash 전달 경로 구현
- [ ] Lock file for race condition
- [ ] LRU eviction 구현
- [ ] 초기 테스트

### Day 2 (4시간)

**오전 (2시간): 선택적 다운로드**
- [ ] `download_dataset_selective()` 구현
- [ ] 병렬 다운로드 최적화

**오후 (2시간): Restart + 테스트**
- [ ] Job restart 기능 구현
- [ ] Integration testing
- [ ] Documentation

---

## 성공 기준

### 기능

- [ ] Cache hit 시 < 1초에 dataset 준비
- [ ] Cache miss 시 selective download로 6배 빠름 (3분 → 30초)
- [ ] Hash verification으로 cache corruption 감지
- [ ] LRU eviction으로 disk space 자동 관리
- [ ] Completed/Failed job restart 가능

### 성능

```
Before (10 Jobs, 같은 dataset):
  - 총 시간: 30분
  - 총 다운로드: 15GB
  - 디스크 사용: 15GB

After:
  - 총 시간: ~3분 (90% 절감)
  - 총 다운로드: 1.5GB (90% 절감)
  - 디스크 사용: 1.5GB (90% 절감)
```

### 안정성

- [ ] Hash collision 올바르게 처리
- [ ] 동시 다운로드 race condition 방지
- [ ] Cache corruption 자동 복구
- [ ] Symlink 문제 없음 (Windows/Linux)

---

## 모니터링

### Prometheus 메트릭

```python
# Cache metrics
cache_hit_total = Counter('dataset_cache_hit_total')
cache_miss_total = Counter('dataset_cache_miss_total')
cache_size_bytes = Gauge('dataset_cache_size_bytes')
cache_eviction_total = Counter('dataset_cache_eviction_total')

# Download metrics
dataset_download_duration_seconds = Histogram('dataset_download_duration_seconds')
dataset_download_files_total = Counter('dataset_download_files_total')
```

### Grafana 대시보드

- Cache hit rate (%)
- Average download time (cache hit vs miss)
- Cache size over time
- Eviction events

---

## References

- [caching_strategy.md](../../../debug/caching_strategy.md) - 상세 설계
- [problems_analysis.md](../../../debug/problems_analysis.md) - 문제 분석
- [PHASE_12_6_SNAPSHOT.md](PHASE_12_6_SNAPSHOT.md) - Snapshot 시스템
- [snapshot_service.py](../../../platform/backend/app/services/snapshot_service.py) - Hash 계산
