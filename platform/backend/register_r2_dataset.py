"""Register R2 dataset to database"""
import os
from dotenv import load_dotenv
from datetime import datetime

# Load .env
load_dotenv()

from app.db.database import SessionLocal
from app.db.models import Dataset
from app.utils.dual_storage import dual_storage

def count_images_in_r2(dataset_path):
    """Count images in R2 dataset folder"""
    try:
        response = dual_storage.external_client.list_objects_v2(
            Bucket=dual_storage.external_bucket_datasets,
            Prefix=f"{dataset_path}images/"
        )

        if 'Contents' in response:
            # Count only image files
            image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}
            image_count = sum(1 for obj in response['Contents']
                            if any(obj['Key'].lower().endswith(ext) for ext in image_extensions))
            return image_count
        return 0
    except Exception as e:
        print(f"Error counting images: {e}")
        return 0

def main():
    db = SessionLocal()

    # R2 dataset info
    dataset_id = "ds_c75023ca76d7448b"
    dataset_name = "mvtec-bottle-detection"
    storage_path = f"datasets/{dataset_id}/"

    # Check if already exists
    existing = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if existing:
        print(f"Dataset {dataset_id} already exists in database")
        print(f"  Name: {existing.name}")
        print(f"  Storage Type: {existing.storage_type}")
        db.close()
        return

    # Count images in R2
    print(f"Counting images in R2: {storage_path}...")
    num_images = count_images_in_r2(storage_path)
    print(f"Found {num_images} images")

    # Create dataset record
    new_dataset = Dataset(
        id=dataset_id,
        name=dataset_name,
        description="MVTec Bottle Detection Dataset from R2",
        format="coco",  # Has annotations_detection.json
        labeled=True,
        storage_type="r2",  # Cloudflare R2
        storage_path=storage_path,
        visibility="public",
        owner_id=1,  # admin user
        num_classes=2,  # Assuming broken/normal
        num_images=num_images,
        class_names=["broken", "normal"],
        tags=["mvtec", "bottle", "detection", "r2"],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.add(new_dataset)
    db.commit()
    db.refresh(new_dataset)

    print(f"\n✅ Successfully registered R2 dataset:")
    print(f"  ID: {new_dataset.id}")
    print(f"  Name: {new_dataset.name}")
    print(f"  Storage Type: {new_dataset.storage_type}")
    print(f"  Storage Path: {new_dataset.storage_path}")
    print(f"  Images: {new_dataset.num_images}")
    print(f"  Format: {new_dataset.format}")

    db.close()

if __name__ == "__main__":
    main()
