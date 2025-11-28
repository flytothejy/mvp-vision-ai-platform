# Collaboration Documents (협업 문서)

이 디렉토리는 **Platform 팀과 다른 팀(Labeler, Training Services 등) 간의 협업을 위한 문서**를 포함합니다.

## 문서 카테고리

### 1. API 요구사항 & 명세

다른 팀에 전달하는 API 요구사항 및 명세 문서:

- **[LABELER_DATASET_API_REQUIREMENTS.md](./LABELER_DATASET_API_REQUIREMENTS.md)**
  - Labeler 팀에 전달하는 Dataset API 명세
  - Platform이 Labeler로부터 조회할 dataset 메타데이터 정의
  - 6개 API 엔드포인트 명세 (list, get, permissions, download URL 등)

### 2. 인증 & 보안

마이크로서비스 간 인증 방식 및 보안 가이드:

- **[MICROSERVICE_AUTHENTICATION_ANALYSIS.md](./MICROSERVICE_AUTHENTICATION_ANALYSIS.md)**
  - 5가지 마이크로서비스 인증 방식 비교 분석
  - Hybrid JWT 방식 선정 근거
  - 업계 사례 (Google, Stripe, Airbnb)
  - 프로젝트 적용 전략

- **[LABELER_AUTHENTICATION_GUIDE.md](./LABELER_AUTHENTICATION_GUIDE.md)**
  - Labeler 팀을 위한 JWT 검증 구현 가이드
  - 전체 검증 코드 (복사 가능)
  - FastAPI 엔드포인트 예제
  - 에러 처리 & 테스트 방법
  - 보안 Best Practices

### 3. 완료 요약 & 진행 상황

각 단계별 완료 요약 및 협업 체크리스트:

- **[PHASE_11_5_6_COMPLETION_SUMMARY.md](./PHASE_11_5_6_COMPLETION_SUMMARY.md)**
  - Phase 11.5.6 Hybrid JWT 인증 구현 완료 요약
  - Platform 측 구현 내역
  - Labeler 팀 작업 항목 (체크리스트)
  - 통합 테스트 결과

## 문서 사용 가이드

### Platform 팀이 새로운 협업 문서를 작성할 때

1. **문서 유형 결정**:
   - API 요구사항 → `*_API_REQUIREMENTS.md`
   - 인증/보안 가이드 → `*_AUTHENTICATION_GUIDE.md`
   - 완료 요약 → `PHASE_*_COMPLETION_SUMMARY.md`
   - 분석/의사결정 → `*_ANALYSIS.md`

2. **문서 작성 규칙**:
   - 명확한 제목 & Executive Summary
   - 실행 가능한 예제 코드 포함
   - 체크리스트 형태로 작업 항목 명시
   - 관련 문서 상호 참조

3. **배치 위치**: `docs/cowork/`

### 다른 팀이 문서를 활용할 때

1. **API 명세 문서** (`*_API_REQUIREMENTS.md`):
   - 엔드포인트 정의 확인
   - Request/Response 스키마 확인
   - 에러 케이스 처리 방법 확인

2. **가이드 문서** (`*_GUIDE.md`):
   - 코드 예제 복사하여 사용
   - 단계별 체크리스트 따라 구현
   - 테스트 방법 참고

3. **분석 문서** (`*_ANALYSIS.md`):
   - 의사결정 배경 이해
   - 대안 비교 참고
   - 적용 전략 검토

## 관련 문서

- **아키텍처 설계**: `docs/architecture/` - Platform 내부 설계 문서
- **개발 가이드**: `docs/development/` - 개발 환경 설정, 코딩 컨벤션
- **계획 문서**: `docs/planning/` - 로드맵, 배포 계획
- **테스트**: `docs/testing/` - 테스트 리포트, E2E 시나리오

## 문서 업데이트 정책

- **작성**: 새로운 협업 포인트 발생 시 Platform 팀이 작성
- **검토**: 관련 팀과 리뷰 후 확정
- **업데이트**: API 변경 시 즉시 문서 업데이트
- **버전 관리**: Git 커밋으로 변경 이력 추적

## 협업 플로우

```
Platform 팀
    ↓ 1. 요구사항 분석
    ↓ 2. API 명세 작성 (docs/cowork/)
    ↓ 3. 가이드 문서 작성
    ↓
다른 팀 (Labeler, etc.)
    ↓ 4. 문서 리뷰
    ↓ 5. 구현
    ↓ 6. 통합 테스트
    ↓
Platform 팀
    ↓ 7. 완료 요약 작성 (docs/cowork/)
    ✅ 협업 완료
```

## 문서 작성 예시

### API 요구사항 문서

```markdown
# [Service Name] API Requirements

## Overview
- 목적: ...
- 제공 팀: ...
- 사용 팀: ...

## API Endpoints

### 1. [Endpoint Name]
- **Method**: GET/POST/PUT/DELETE
- **URL**: `/api/v1/...`
- **Request**: ...
- **Response**: ...
- **Errors**: ...
```

### 가이드 문서

```markdown
# [Feature Name] Implementation Guide

## Quick Start
1. Step 1
2. Step 2
3. Step 3

## Code Examples
[복사 가능한 코드]

## Testing
[테스트 방법]

## Troubleshooting
[자주 발생하는 문제]
```

## 문의

- Platform 팀 협업 관련 문의: (담당자 정보)
- Labeler 팀 연락처: (Labeler 팀 정보)
