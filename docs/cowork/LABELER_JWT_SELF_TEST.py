"""
Labeler JWT Self-Test Script

Labeler 팀이 자체적으로 JWT 검증 구현을 테스트할 수 있는 스크립트.
Platform이 생성한 실제 토큰으로 검증 테스트를 수행합니다.

Usage:
    1. Labeler backend 디렉토리에 이 파일 복사
    2. python LABELER_JWT_SELF_TEST.py
"""

import jwt
from datetime import datetime, timedelta

# Platform에서 사용하는 설정
PLATFORM_SECRET = "8f7e6d5c4b3a29180716253e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a"
ALGORITHM = "HS256"

def test_jwt_verification():
    """JWT 검증 로직 테스트"""

    print("=" * 70)
    print("  Labeler JWT Self-Test")
    print("=" * 70)

    # Step 1: Platform과 동일한 방식으로 토큰 생성
    print("\n[Step 1] Generating test token (Platform 방식)...")

    now = datetime.utcnow()
    test_payload = {
        "sub": "1",                    # User ID
        "service": "platform",          # Service name
        "scopes": ["labeler:read"],     # Scopes
        "type": "service",              # Token type
        "iat": now,                     # Issued at
        "exp": now + timedelta(minutes=5),  # Expires in 5min
        "nbf": now                      # Not before
    }

    test_token = jwt.encode(test_payload, PLATFORM_SECRET, algorithm=ALGORITHM)
    print(f"Generated token: {test_token[:50]}...")

    # Step 2: Labeler의 SECRET으로 검증
    print("\n[Step 2] Verifying with Labeler's SECRET...")
    print("ACTION REQUIRED: Labeler 팀은 아래 코드에 자신의 SECRET을 입력하세요")
    print("-" * 70)

    # TODO: Labeler 팀이 여기에 자신의 SECRET 입력
    LABELER_SECRET = "YOUR_SECRET_HERE"  # <-- 여기에 Labeler의 SERVICE_JWT_SECRET 입력

    if LABELER_SECRET == "YOUR_SECRET_HERE":
        print("[ERROR] Labeler SECRET을 입력해주세요!")
        print("위 코드에서 LABELER_SECRET 변수를 수정하세요.")
        return

    print(f"Labeler SECRET (first 20): {LABELER_SECRET[:20]}...")
    print(f"Platform SECRET (first 20): {PLATFORM_SECRET[:20]}...")

    if LABELER_SECRET == PLATFORM_SECRET:
        print("[OK] SECRET이 Platform과 일치합니다!")
    else:
        print("[ERROR] SECRET이 Platform과 다릅니다!")
        print("\nLabeler SECRET:")
        print(f"  {LABELER_SECRET}")
        print("\nPlatform SECRET (정답):")
        print(f"  {PLATFORM_SECRET}")
        print("\n해결: Labeler의 .env 또는 config에서 SERVICE_JWT_SECRET을 Platform과 동일하게 설정")
        return

    # Step 3: JWT 검증 테스트
    print("\n[Step 3] Testing JWT verification...")

    try:
        decoded = jwt.decode(
            test_token,
            LABELER_SECRET,
            algorithms=[ALGORITHM]
        )
        print("[SUCCESS] JWT 검증 성공!")
        print(f"\nDecoded payload:")
        for key, value in decoded.items():
            print(f"  {key}: {value}")

    except jwt.ExpiredSignatureError:
        print("[ERROR] 토큰이 만료되었습니다")
        print("해결: 토큰 만료 시간을 확인하세요")

    except jwt.InvalidSignatureError:
        print("[ERROR] Signature 검증 실패!")
        print("원인: SECRET이 다르거나 알고리즘이 다릅니다")
        print(f"  Labeler Algorithm: {ALGORITHM} 확인 필요")

    except Exception as e:
        print(f"[ERROR] 예상치 못한 에러: {e}")

    # Step 4: Platform의 실제 토큰으로 테스트
    print("\n[Step 4] Testing with real Platform token...")
    print("\nACTION: 아래 curl 명령으로 Platform이 생성한 실제 토큰을 테스트하세요:")
    print("-" * 70)

    # 실제 Platform 토큰 생성 (5분 유효)
    real_token = jwt.encode(test_payload, PLATFORM_SECRET, algorithm=ALGORITHM)

    print(f"""
curl -X GET "http://localhost:8011/api/v1/datasets?page=1&limit=20" \\
  -H "Authorization: Bearer {real_token}" \\
  -H "Content-Type: application/json"
    """)
    print("-" * 70)
    print("\n예상 결과:")
    print("  - 200 OK: JWT 검증 성공! (datasets 반환)")
    print("  - 401 Unauthorized: JWT 검증 실패 (위 Step 1-3 다시 확인)")

    # Step 5: Labeler 코드 확인사항
    print("\n[Step 5] Labeler 코드 확인사항")
    print("-" * 70)
    print("""
1. PyJWT 설치 확인:
   pip list | grep PyJWT
   # 없으면: pip install pyjwt

2. SECRET 설정 확인 (.env 또는 config.py):
   SERVICE_JWT_SECRET = "8f7e6d5c4b3a29180716253e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a"

3. JWT 검증 코드 예시:
   ```python
   import jwt
   from fastapi import HTTPException, Header

   SERVICE_JWT_SECRET = "8f7e6d5c4b3a29180716253e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a"

   def verify_service_jwt(authorization: str = Header(...)):
       if not authorization.startswith("Bearer "):
           raise HTTPException(401, "Invalid header")

       token = authorization.replace("Bearer ", "")

       try:
           payload = jwt.decode(token, SERVICE_JWT_SECRET, algorithms=["HS256"])
           return payload
       except jwt.ExpiredSignatureError:
           raise HTTPException(401, "Token expired")
       except jwt.InvalidSignatureError:
           raise HTTPException(401, "Invalid signature")
   ```

4. FastAPI 엔드포인트 적용:
   ```python
   from fastapi import Depends

   @router.get("/api/v1/datasets")
   async def list_datasets(auth: dict = Depends(verify_service_jwt)):
       user_id = auth.get("sub")  # User ID
       # ... 권한 체크 및 데이터 반환
   ```
    """)

    print("=" * 70)
    print("  Self-Test Complete")
    print("=" * 70)
    print("\nNext Steps:")
    print("1. 위 Step 2에서 LABELER_SECRET 입력 후 다시 실행")
    print("2. SECRET이 일치하는지 확인")
    print("3. Step 4의 curl 명령으로 실제 API 테스트")
    print("4. 401 에러 발생 시 Step 5의 코드 확인사항 검토")
    print("=" * 70)


if __name__ == "__main__":
    test_jwt_verification()
