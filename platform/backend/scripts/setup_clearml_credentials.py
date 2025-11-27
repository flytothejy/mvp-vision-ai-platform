"""
ClearML Credentials Setup Script

Generates API credentials for local ClearML server.
This script should be run once after ClearML server is started.

Usage:
    python scripts/setup_clearml_credentials.py
"""

import requests
import json
import sys
from datetime import datetime

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

CLEARML_API_HOST = "http://localhost:8008"
CLEARML_WEB_HOST = "http://localhost:8080"
CLEARML_FILES_HOST = "http://localhost:8081"


def create_user():
    """Create initial user account"""
    url = f"{CLEARML_API_HOST}/auth.create_user"

    payload = {
        "name": "Platform Backend",
        "company": "clearml",
        "email": "platform@localhost",
        "family_name": "Platform",
        "given_name": "Vision AI"
    }

    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            result = response.json()
            if result.get("meta", {}).get("result_code") == 200:
                user_id = result.get("data", {}).get("id")
                print(f"✓ User created successfully")
                print(f"  User ID: {user_id}")
                return user_id
            else:
                print(f"  User may already exist: {result.get('meta', {}).get('result_msg')}")
                return None
        else:
            print(f"✗ Failed to create user: HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"✗ Error creating user: {e}")
        return None


def create_credentials():
    """Create API credentials using the tests user (default in ClearML)"""
    url = f"{CLEARML_API_HOST}/auth.create_credentials"

    # ClearML creates a 'tests' user by default during initialization
    # We'll use that user to create credentials
    payload = {}

    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            result = response.json()
            if result.get("meta", {}).get("result_code") == 200:
                data = result.get("data", {})
                credentials = data.get("credentials", {})
                access_key = credentials.get("access_key")
                secret_key = credentials.get("secret_key")

                print(f"\n{'='*70}")
                print(f"✓ ClearML API Credentials Generated Successfully!")
                print(f"{'='*70}")
                print(f"\nAdd these to platform/backend/.env:\n")
                print(f"# ClearML Configuration")
                print(f"CLEARML_API_HOST={CLEARML_API_HOST}")
                print(f"CLEARML_WEB_HOST={CLEARML_WEB_HOST}")
                print(f"CLEARML_FILES_HOST={CLEARML_FILES_HOST}")
                print(f"CLEARML_API_ACCESS_KEY={access_key}")
                print(f"CLEARML_API_SECRET_KEY={secret_key}")
                print(f"\n{'='*70}\n")

                # Save to file
                env_path = "platform/backend/.env.clearml"
                with open(env_path, "w") as f:
                    f.write(f"# ClearML Configuration\n")
                    f.write(f"# Generated: {datetime.now().isoformat()}\n")
                    f.write(f"CLEARML_API_HOST={CLEARML_API_HOST}\n")
                    f.write(f"CLEARML_WEB_HOST={CLEARML_WEB_HOST}\n")
                    f.write(f"CLEARML_FILES_HOST={CLEARML_FILES_HOST}\n")
                    f.write(f"CLEARML_API_ACCESS_KEY={access_key}\n")
                    f.write(f"CLEARML_API_SECRET_KEY={secret_key}\n")

                print(f"✓ Credentials also saved to: {env_path}")
                print(f"  Copy these lines to your .env file\n")

                return {
                    "access_key": access_key,
                    "secret_key": secret_key
                }
            else:
                error_msg = result.get("meta", {}).get("result_msg", "Unknown error")
                print(f"✗ Failed to create credentials: {error_msg}")
                print(f"  Response: {json.dumps(result, indent=2)}")
                return None
        else:
            print(f"✗ Failed to create credentials: HTTP {response.status_code}")
            print(f"  Response: {response.text}")
            return None
    except Exception as e:
        print(f"✗ Error creating credentials: {e}")
        return None


def test_connection(access_key, secret_key):
    """Test the generated credentials"""
    url = f"{CLEARML_API_HOST}/auth.login"

    payload = {
        "expiration_sec": 86400  # 24 hours
    }

    try:
        response = requests.post(
            url,
            json=payload,
            auth=(access_key, secret_key)
        )

        if response.status_code == 200:
            result = response.json()
            if result.get("meta", {}).get("result_code") == 200:
                print(f"✓ Credentials verified successfully!")
                return True
            else:
                print(f"✗ Credential verification failed: {result.get('meta', {}).get('result_msg')}")
                return False
        else:
            print(f"✗ Credential verification failed: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Error verifying credentials: {e}")
        return False


def main():
    print(f"\nClearML Credentials Setup")
    print(f"{'='*70}\n")

    # Check if ClearML server is running
    try:
        response = requests.get(f"{CLEARML_API_HOST}/debug.ping")
        if response.status_code != 200:
            print(f"✗ ClearML server is not responding at {CLEARML_API_HOST}")
            print(f"  Please start ClearML server first:")
            print(f"  cd infrastructure && docker-compose -f docker-compose.clearml.yaml up -d")
            return
    except Exception as e:
        print(f"✗ Cannot connect to ClearML server: {e}")
        print(f"  Please start ClearML server first:")
        print(f"  cd infrastructure && docker-compose -f docker-compose.clearml.yaml up -d")
        return

    print(f"✓ ClearML server is running at {CLEARML_API_HOST}\n")

    # Create credentials
    print(f"Creating API credentials...\n")
    creds = create_credentials()

    if creds:
        print(f"\nVerifying credentials...\n")
        test_connection(creds["access_key"], creds["secret_key"])

        print(f"\n{'='*70}")
        print(f"Setup Complete!")
        print(f"{'='*70}")
        print(f"\nNext steps:")
        print(f"1. Copy the credentials to platform/backend/.env")
        print(f"2. Test ClearML connection with:")
        print(f"   cd platform/backend")
        print(f"   python -c \"from clearml import Task; print('ClearML OK')\"")
        print(f"\nClearML Web UI: {CLEARML_WEB_HOST}")
        print(f"")
    else:
        print(f"\n✗ Failed to generate credentials")
        print(f"  You can try creating credentials manually in the Web UI:")
        print(f"  1. Go to {CLEARML_WEB_HOST}")
        print(f"  2. Settings → Workspace → Create new credentials")


if __name__ == "__main__":
    main()
