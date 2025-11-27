"""Analyze Dataset table usage in Platform DB"""
import os
from dotenv import load_dotenv
from sqlalchemy import inspect, MetaData, Table

load_dotenv()

from app.db.database import platform_engine, SessionLocal
from app.db.models import Dataset, TrainingJob

def analyze_fk_relationships():
    """Check foreign key relationships involving Dataset table"""
    inspector = inspect(platform_engine)

    print("=== Foreign Key Relationships ===\n")

    # Get all table names
    all_tables = inspector.get_table_names()

    dataset_references = []

    for table_name in all_tables:
        fks = inspector.get_foreign_keys(table_name)
        for fk in fks:
            if fk['referred_table'] == 'datasets':
                dataset_references.append({
                    'table': table_name,
                    'columns': fk['constrained_columns'],
                    'referred_columns': fk['referred_columns']
                })

    if dataset_references:
        print(f"Tables referencing 'datasets' table: {len(dataset_references)}\n")
        for ref in dataset_references:
            print(f"  {ref['table']}")
            print(f"    Columns: {ref['columns']} -> datasets.{ref['referred_columns']}")
    else:
        print("No foreign key references to 'datasets' table found\n")

    return dataset_references

def analyze_dataset_data():
    """Analyze actual data in Dataset table"""
    db = SessionLocal()

    print("\n=== Dataset Table Data ===\n")

    datasets = db.query(Dataset).all()
    print(f"Total datasets: {len(datasets)}\n")

    for ds in datasets:
        print(f"ID: {ds.id}")
        print(f"  Name: {ds.name}")
        print(f"  Storage Type: {ds.storage_type}")
        print(f"  Storage Path: {ds.storage_path}")
        print(f"  Owner ID: {ds.owner_id}")
        print(f"  Created: {ds.created_at}")
        print()

    db.close()
    return datasets

def analyze_training_job_usage():
    """Check how TrainingJob uses Dataset"""
    db = SessionLocal()

    print("\n=== TrainingJob → Dataset Usage ===\n")

    # Check TrainingJob model fields
    from sqlalchemy import inspect as sqla_inspect
    mapper = sqla_inspect(TrainingJob)

    dataset_fields = []
    for column in mapper.columns:
        if 'dataset' in column.name.lower():
            dataset_fields.append({
                'name': column.name,
                'type': str(column.type),
                'nullable': column.nullable
            })

    print("TrainingJob fields related to Dataset:")
    for field in dataset_fields:
        print(f"  {field['name']}: {field['type']} (nullable={field['nullable']})")

    # Check actual TrainingJob records
    jobs = db.query(TrainingJob).all()
    print(f"\nTotal TrainingJob records: {len(jobs)}")

    if jobs:
        print("\nSample TrainingJob dataset references:")
        for job in jobs[:5]:
            print(f"  Job ID {job.id}:")
            if hasattr(job, 'dataset_id'):
                print(f"    dataset_id: {job.dataset_id}")
            if hasattr(job, 'dataset_path'):
                print(f"    dataset_path: {job.dataset_path}")

    db.close()

if __name__ == "__main__":
    print("=" * 70)
    print("Platform DB - Dataset Table Usage Analysis")
    print("=" * 70)
    print()

    # Analyze FK relationships
    refs = analyze_fk_relationships()

    # Analyze data
    datasets = analyze_dataset_data()

    # Analyze TrainingJob usage
    analyze_training_job_usage()

    print("\n" + "=" * 70)
    print("Analysis Complete")
    print("=" * 70)
