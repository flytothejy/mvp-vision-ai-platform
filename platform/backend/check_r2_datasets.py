"""Check R2 bucket for actual datasets"""
import os
from dotenv import load_dotenv
import asyncio

# Load .env
load_dotenv()

from app.utils.dual_storage import dual_storage

async def main():
    print(f"External Storage Type: {dual_storage.external_storage_type}")
    print(f"External Endpoint: {dual_storage.external_endpoint}")
    print(f"External Bucket: {dual_storage.external_bucket_datasets}\n")

    # List objects in R2 datasets bucket
    try:
        response = dual_storage.external_client.list_objects_v2(
            Bucket=dual_storage.external_bucket_datasets,
            Prefix='datasets/',
            Delimiter='/'
        )

        print("=== R2 Bucket Contents (datasets/) ===\n")

        # List directories (dataset IDs)
        if 'CommonPrefixes' in response:
            print(f"Found {len(response['CommonPrefixes'])} dataset folders:\n")
            for prefix in response['CommonPrefixes']:
                folder = prefix['Prefix']
                print(f"  - {folder}")

                # List contents of each dataset folder
                folder_response = dual_storage.external_client.list_objects_v2(
                    Bucket=dual_storage.external_bucket_datasets,
                    Prefix=folder,
                    MaxKeys=10
                )

                if 'Contents' in folder_response:
                    print(f"    Files: {folder_response.get('KeyCount', 0)} items")
                    for obj in folder_response['Contents'][:5]:  # Show first 5
                        print(f"      {obj['Key']} ({obj['Size']} bytes)")
                print()
        else:
            print("No dataset folders found in R2 bucket")

        # Also check root level
        if 'Contents' in response:
            print(f"\nRoot level files: {len(response['Contents'])}")
            for obj in response['Contents'][:10]:
                print(f"  {obj['Key']} ({obj['Size']} bytes)")

    except Exception as e:
        print(f"Error listing R2 bucket: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
