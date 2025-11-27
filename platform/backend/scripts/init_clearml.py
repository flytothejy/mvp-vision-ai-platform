"""
ClearML Initialization Script

Initializes ClearML connection and generates credentials.
This creates a clearml.conf file with API credentials.

Usage:
    python scripts/init_clearml.py
"""

import os
import sys

# Point to our clearml.conf file
clearml_conf_path = os.path.abspath("clearml.conf")
os.environ['CLEARML_CONFIG_FILE'] = clearml_conf_path

print(f"Using ClearML config file: {clearml_conf_path}")
print()

from clearml import Task

print("="*70)
print("ClearML Initialization")
print("="*70)
print()

try:
    # Initialize a test task
    task = Task.init(
        project_name="Test Project",
        task_name="Initial Connection Test",
        task_type=Task.TaskTypes.testing,
        reuse_last_task_id=False
    )

    # Log a test metric
    task.logger.report_scalar(
        title="test",
        series="connection",
        value=1.0,
        iteration=0
    )

    task.mark_completed()

    print(f"[OK] ClearML connection successful!")
    print(f"     Task ID: {task.id}")
    print(f"     Web UI: http://localhost:8080/projects/*/experiments/{task.id}")
    print()
    print("="*70)
    print("Configuration")
    print("="*70)
    print()
    print("ClearML config file location:")
    from clearml.config import config_obj
    print(f"  {config_obj.get_config_file()}")
    print()
    print("Add these to platform/backend/.env:")
    print()
    print("# ClearML Configuration")
    print("CLEARML_API_HOST=http://localhost:8008")
    print("CLEARML_WEB_HOST=http://localhost:8080")
    print("CLEARML_FILES_HOST=http://localhost:8081")
    print("CLEARML_API_ACCESS_KEY=")
    print("CLEARML_API_SECRET_KEY=")
    print()
    print("Note: Open-source ClearML server does not require credentials.")
    print("      Leave ACCESS_KEY and SECRET_KEY empty.")
    print()

except Exception as e:
    print(f"[ERROR] ClearML connection failed: {e}")
    print()
    print("Troubleshooting:")
    print("1. Check if ClearML server is running:")
    print("   docker-compose -f infrastructure/docker-compose.clearml.yaml ps")
    print()
    print("2. Verify API server health:")
    print("   curl http://localhost:8008/debug.ping")
    print()
    print("3. Check Web UI:")
    print("   Open http://localhost:8080 in browser")
    print()
