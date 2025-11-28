"""
Debug JWT Token Generation

Platform이 Labeler에 전송하는 JWT 토큰을 확인하는 스크립트.
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

# Load environment
from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(env_path)

from app.core.service_jwt import ServiceJWT
import jwt

def debug_token():
    """Generate and decode token for debugging"""

    print("=" * 60)
    print("  JWT Token Debug")
    print("=" * 60)

    # Generate token
    print("\n1. Generating service token...")
    token = ServiceJWT.create_service_token(
        user_id=1,
        service_name="platform",
        scopes=["labeler:read"]
    )

    print(f"\nGenerated Token (first 50 chars):")
    print(f"{token[:50]}...")
    print(f"\nFull Token Length: {len(token)} characters")

    # Decode without verification (to see payload)
    print("\n2. Decoding token (without verification)...")
    payload = ServiceJWT.decode_token_unsafe(token)

    if payload:
        print("\nToken Payload:")
        for key, value in payload.items():
            print(f"  {key}: {value}")

    # Verify token (should succeed)
    print("\n3. Verifying token with Platform's SECRET...")
    try:
        verified = ServiceJWT.verify_token(token, required_scopes=["labeler:read"])
        print("[OK] Token verified successfully!")
        print(f"User ID: {verified.get('sub')}")
        print(f"Service: {verified.get('service')}")
    except Exception as e:
        print(f"[ERROR] Verification failed: {e}")

    # Check configuration
    print("\n4. Configuration Check...")
    from app.core.config import settings

    secret = settings.SERVICE_JWT_SECRET
    print(f"\nSERVICE_JWT_SECRET (first 20 chars): {secret[:20]}...")
    print(f"SERVICE_JWT_SECRET (last 20 chars): ...{secret[-20:]}")
    print(f"SECRET Length: {len(secret)} characters")
    print(f"Algorithm: HS256")

    # Test with wrong secret
    print("\n5. Testing with wrong secret (should fail)...")
    try:
        wrong_payload = jwt.decode(
            token,
            "wrong-secret-key",
            algorithms=["HS256"]
        )
        print("[ERROR] Should have failed but didn't!")
    except jwt.InvalidSignatureError:
        print("[OK] Correctly rejected with wrong secret")

    print("\n" + "=" * 60)
    print("Debug Complete")
    print("=" * 60)

    print("\n📋 Send this to Labeler team:")
    print("-" * 60)
    print(f"SERVICE_JWT_SECRET: {secret}")
    print(f"Algorithm: HS256")
    print(f"Example Token: {token[:100]}...")
    print("-" * 60)

if __name__ == "__main__":
    debug_token()
