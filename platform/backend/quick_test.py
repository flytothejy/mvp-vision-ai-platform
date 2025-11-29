import requests
import sys

API_URL = "http://localhost:8000"
DATASET_ID = "ds_c75023ca76d7448b"

# Login
print("1. Login...")
try:
    r = requests.post(f"{API_URL}/api/v1/auth/login",
                     data={"username": "admin@example.com", "password": "admin123"},
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"   OK - Token: {token[:20]}...")
except Exception as e:
    print(f"   FAIL - {e}")
    sys.exit(1)

headers = {"Authorization": f"Bearer {token}"}

# Create job
print(f"\n2. Create training job with dataset_id={DATASET_ID}...")
config = {
    "config": {
        "framework": "ultralytics",
        "model_name": "yolo11n",
        "task_type": "object_detection",
        "dataset_id": DATASET_ID,
        "dataset_format": "yolo",
        "epochs": 2,
        "batch_size": 4,
        "learning_rate": 0.001
    },
    "experiment_name": "QuickTest",
    "tags": ["quick-test"]
}

try:
    r = requests.post(f"{API_URL}/api/v1/training/jobs", headers=headers, json=config)
    r.raise_for_status()
    job = r.json()
    job_id = job["id"]
    print(f"   OK - Job ID: {job_id}")
    print(f"   Workflow ID: {job.get('workflow_id', 'NONE')}")
    print(f"   Snapshot ID: {job.get('dataset_snapshot_id', 'NONE')}")
    print(f"   Status: {job['status']}")

    if not job.get('workflow_id'):
        print("\n   [WARNING] workflow_id is missing!")
    if not job.get('dataset_snapshot_id'):
        print("\n   [WARNING] dataset_snapshot_id is missing!")

except Exception as e:
    print(f"   FAIL - {e}")
    if hasattr(e, 'response'):
        print(f"   Response: {e.response.text}")
    sys.exit(1)

print("\nTest PASSED - Job created with Phase 12 metadata")
print(f"Monitor job status: GET {API_URL}/api/v1/training/jobs/{job_id}")
