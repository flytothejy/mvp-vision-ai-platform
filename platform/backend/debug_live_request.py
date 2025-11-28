"""
Live Request Debug

Platform이 Labeler에 실제로 보내는 HTTP 요청을 상세하게 확인하는 스크립트.
"""

import sys
from pathlib import Path
import httpx
import asyncio

# Add backend directory to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

# Load environment
from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(env_path)

from app.core.service_jwt import ServiceJWT
from app.core.config import settings
import jwt

async def debug_live_request():
    """Debug actual request to Labeler"""

    print("=" * 80)
    print("  Live Request Debug - Platform → Labeler")
    print("=" * 80)

    # Generate token
    print("\n[Step 1] Generating JWT token...")
    token = ServiceJWT.create_service_token(
        user_id=1,
        service_name="platform",
        scopes=["labeler:read"],
        expires_minutes=5
    )

    # Decode token (without verification) to see payload
    decoded = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256"])

    print(f"\nToken Details:")
    print(f"  Full Token: {token}")
    print(f"\n  Payload:")
    for key, value in decoded.items():
        if key in ['iat', 'exp', 'nbf']:
            # Convert timestamp to readable format
            from datetime import datetime
            dt = datetime.utcfromtimestamp(value)
            print(f"    {key}: {value} ({dt.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
        else:
            print(f"    {key}: {value}")

    # Build headers
    print(f"\n[Step 2] Building HTTP headers...")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    print(f"  Headers:")
    for key, value in headers.items():
        if key == "Authorization":
            print(f"    {key}: Bearer {value[7:57]}... (length: {len(value)})")
        else:
            print(f"    {key}: {value}")

    # Make request
    print(f"\n[Step 3] Sending request to Labeler...")
    labeler_url = settings.LABELER_API_URL
    endpoint = f"{labeler_url}/api/v1/datasets?page=1&limit=20"

    print(f"  URL: {endpoint}")
    print(f"  Method: GET")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                endpoint,
                headers=headers,
                timeout=10.0
            )

            print(f"\n[Step 4] Response received:")
            print(f"  Status Code: {response.status_code}")
            print(f"  Response Headers:")
            for key, value in response.headers.items():
                print(f"    {key}: {value}")

            print(f"\n  Response Body:")
            print(f"    {response.text}")

            if response.status_code == 200:
                print("\n" + "=" * 80)
                print("  SUCCESS! JWT Authentication Working!")
                print("=" * 80)
                data = response.json()
                print(f"\n  Datasets returned: {data.get('total', 0)}")
                return True

            elif response.status_code == 401:
                print("\n" + "=" * 80)
                print("  FAILED - 401 Unauthorized")
                print("=" * 80)

                # Try to extract error details
                try:
                    error_data = response.json()
                    detail = error_data.get('detail', '')
                    print(f"\n  Error Detail: {detail}")

                    if "Signature verification failed" in detail:
                        print("\n  Diagnosis: SECRET mismatch")
                        print("  Action: Ask Labeler team to restart backend after SECRET change")
                        print(f"  Expected SECRET: {settings.SERVICE_JWT_SECRET}")

                    elif "Not enough segments" in detail:
                        print("\n  Diagnosis: Token format issue")
                        print("  Action: Check Authorization header parsing")

                    elif "expired" in detail.lower():
                        print("\n  Diagnosis: Token expired")
                        print("  Action: Check system time sync")

                except:
                    pass

                # Suggest curl command
                print("\n  Debug with curl:")
                print(f"  curl -X GET '{endpoint}' \\")
                print(f"    -H 'Authorization: Bearer {token}' \\")
                print(f"    -H 'Content-Type: application/json' \\")
                print(f"    -v")

                return False

            else:
                print(f"\n  Unexpected status code: {response.status_code}")
                return False

        except httpx.ConnectError as e:
            print(f"\n  [ERROR] Cannot connect to Labeler: {e}")
            print(f"  Is Labeler running on {labeler_url}?")
            return False

        except Exception as e:
            print(f"\n  [ERROR] Request failed: {e}")
            return False

    print("=" * 80)


async def test_with_labeler_team():
    """Labeler 팀이 로그에서 볼 수 있는 정보 출력"""

    print("\n" + "=" * 80)
    print("  Information for Labeler Team")
    print("=" * 80)

    print("\nLabeler 팀이 backend 로그에서 확인해야 할 사항:")
    print("-" * 80)
    print("""
1. 요청 로그:
   - Authorization 헤더가 들어오는지 확인
   - "Bearer " 접두사가 있는지 확인

2. JWT 검증 코드에 로그 추가:
   ```python
   def verify_service_jwt(authorization: str = Header(...)):
       print(f"[DEBUG] Received Authorization: {authorization[:50]}...")

       if not authorization.startswith("Bearer "):
           print(f"[DEBUG] Missing 'Bearer ' prefix")
           raise HTTPException(401, "Invalid header")

       token = authorization.replace("Bearer ", "")
       print(f"[DEBUG] Extracted token: {token[:50]}...")

       try:
           # SECRET 로그 (production에서는 제거!)
           print(f"[DEBUG] Using SECRET: {SERVICE_JWT_SECRET[:20]}...")

           payload = jwt.decode(token, SERVICE_JWT_SECRET, algorithms=["HS256"])
           print(f"[DEBUG] JWT verified! Payload: {payload}")
           return payload

       except jwt.InvalidSignatureError as e:
           print(f"[DEBUG] Signature verification failed: {e}")
           print(f"[DEBUG] Check if SECRET matches Platform")
           raise HTTPException(401, "Signature verification failed")

       except Exception as e:
           print(f"[DEBUG] JWT decode failed: {type(e).__name__}: {e}")
           raise HTTPException(401, str(e))
   ```

3. Backend 재시작 확인:
   - .env 파일 수정 후 backend를 재시작했는지 확인
   - FastAPI의 경우: 서버 재시작 또는 reload 필요

4. SECRET 확인:
   - config.py나 settings에서 SERVICE_JWT_SECRET 로드 확인
   - 실제 사용되는 값 로그로 출력해서 확인
    """)
    print("=" * 80)


if __name__ == "__main__":
    success = asyncio.run(debug_live_request())

    if not success:
        asyncio.run(test_with_labeler_team())
