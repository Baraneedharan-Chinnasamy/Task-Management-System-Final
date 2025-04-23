import os
import urllib.parse
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

# Load environment variables
load_dotenv()

DB_USER = urllib.parse.quote_plus(os.getenv("DB_USER"))
DB_PASSWORD = urllib.parse.quote_plus(os.getenv("DB_PASSWORD"))
DB_HOST = os.getenv("DB_HOST")

# Database connection URL (Fixed for employeee_task)
DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/employeee_task"

# Create the engine and session maker
engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=5)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Function to get the database session (for FastAPI)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Function to get the database session dynamically (without yield)
def get_dynamic_db():
    db = SessionLocal()  # Create session
    try:
        return db  # Return the session directly
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")
