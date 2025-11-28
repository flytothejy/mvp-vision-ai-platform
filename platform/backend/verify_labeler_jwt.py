"""
Labeler JWT Verification Test

Labeler 팀이 JWT 검증을 올바르게 구현했는지 테스트하는 스크립트.
Platform이 생성한 토큰을 Labeler API로 직접 전송해봅니다.
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

async def test_labeler_jwt():
    """Test JWT authentication with Labeler API"""

    print("=" * 60)
    print("  Labeler JWT Verification Test")
    print("=" * 60)

    # Step 1: Generate token
    print("\n[1/4] Generating Platform service token...")
    token = ServiceJWT.create_service_token(
        user_id=1,
        service_name="platform",
        scopes=["labeler:read"]
    )
    print(f"Token (first 50 chars): {token[:50]}...")
    print(f"Token length: {len(token)} characters")

    # Step 2: Show secret
    print(f"\n[2/4] Platform SECRET configuration:")
    secret = settings.SERVICE_JWT_SECRET
    print(f"  First 20 chars: {secret[:20]}...")
    print(f"  Last 20 chars: ...{secret[-20:]}")
    print(f"  Full SECRET: {secret}")

    # Step 3: Test health endpoint (no auth)
    print(f"\n[3/4] Testing Labeler health endpoint (no auth)...")
    labeler_url = settings.LABELER_API_URL
    print(f"  URL: {labeler_url}")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{labeler_url}/health", timeout=5.0)
            if response.status_code == 200:
                print(f"  [OK] Health check passed: {response.json()}")
            else:
                print(f"  [ERROR] Health check failed: {response.status_code}")
                return
        except Exception as e:
            print(f"  [ERROR] Cannot connect to Labeler: {e}")
            return

    # Step 4: Test authenticated endpoint
    print(f"\n[4/4] Testing authenticated endpoint with JWT...")
    print(f"  Endpoint: GET /api/v1/datasets")
    print(f"  Authorization: Bearer <token>")

    async with httpx.AsyncClient() as client:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            response = await client.get(
                f"{labeler_url}/api/v1/datasets?page=1&limit=20",
                headers=headers,
                timeout=10.0
            )

            print(f"\n  Response Status: {response.status_code}")

            if response.status_code == 200:
                print("  [SUCCESS] JWT authentication working!")
                data = response.json()
                print(f"  Datasets found: {data.get('total', 0)}")
            elif response.status_code == 401:
                print("  [ERROR] 401 Unauthorized")
                print(f"  Response: {response.text}")
                print("\n  Possible issues:")
                print("  1. Labeler's SERVICE_JWT_SECRET is different")
                print("  2. Labeler is using wrong algorithm (not HS256)")
                print("  3. Labeler's JWT verification logic has bugs")
            else:
                print(f"  [ERROR] Unexpected status code: {response.status_code}")
                print(f"  Response: {response.text}")

        except httpx.HTTPError as e:
            print(f"  [ERROR] HTTP error: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("  Test Summary")
    print("=" * 60)
    print("\nIf you see 401 error, ask Labeler team to verify:")
    print(f"1. SERVICE_JWT_SECRET = {secret}")
    print("2. Algorithm = HS256")
    print("3. PyJWT library installed (pip install pyjwt)")
    print("\nTest command for Labeler team:")
    print("  python -c \"import jwt; print(jwt.decode('TOKEN', 'SECRET', algorithms=['HS256']))\"")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_labeler_jwt())
