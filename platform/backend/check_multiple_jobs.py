import requests

API_URL = "http://localhost:8000"

# Login
r = requests.post(f"{API_URL}/api/v1/auth/login",
                 data={"username": "admin@example.com", "password": "admin123"},
                 headers={"Content-Type": "application/x-www-form-urlencoded"})
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Check jobs 78, 81
for job_id in [78, 81]:
    print(f"\n{'='*80}")
    print(f"Job {job_id}")
    print('='*80)

    r = requests.get(f"{API_URL}/api/v1/training/jobs/{job_id}", headers=headers)
    if r.status_code == 200:
        job = r.json()
        print(f"Status: {job['status']}")
        print(f"Workflow ID: {job.get('workflow_id', 'NONE')}")
        print(f"Snapshot ID: {job.get('dataset_snapshot_id', 'NONE')}")
        print(f"Dataset Path: {job.get('dataset_path', 'N/A')}")
        print(f"Experiment: {job.get('experiment_name', 'N/A')}")
        print(f"Created: {job.get('created_at', 'N/A')}")
        print(f"Started: {job.get('started_at', 'N/A')}")
        print(f"Completed: {job.get('completed_at', 'N/A')}")

        if job['status'] == 'completed':
            print(f"Final Accuracy: {job.get('final_accuracy', 'N/A')}")
            print(f"Best Checkpoint: {job.get('best_checkpoint_path', 'N/A')}")
        elif job['status'] == 'failed':
            print(f"Error: {job.get('error_message', 'N/A')}")
    else:
        print(f"Failed to get job: {r.status_code}")

print(f"\n{'='*80}")
print("Summary:")
print(f"  Both jobs should have workflow_id and dataset_snapshot_id")
print(f"  This validates Phase 12.6 metadata-only snapshot feature")
print('='*80)
