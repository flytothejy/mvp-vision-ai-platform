"""Check datasets in database"""
import os
from dotenv import load_dotenv

# Load .env BEFORE importing app modules
load_dotenv()

from app.db.database import SessionLocal
from app.db.models import Dataset

db = SessionLocal()
datasets = db.query(Dataset).all()

print(f'Total datasets in DB: {len(datasets)}\n')
for ds in datasets:
    print(f'Name: {ds.name}')
    print(f'  ID: {ds.id}')
    print(f'  Storage Type: {ds.storage_type}')
    print(f'  Storage Path: {ds.storage_path}')
    print(f'  Format: {ds.format}')
    print(f'  Images: {ds.num_images}')
    print(f'  Visibility: {ds.visibility}')
    print()

db.close()
