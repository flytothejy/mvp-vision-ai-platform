from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://admin:devpass@localhost:5432/platform"
engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    conn.execute(text("ALTER TABLE training_jobs ADD COLUMN IF NOT EXISTS clearml_task_id VARCHAR(255)"))
    print("Added clearml_task_id column")
