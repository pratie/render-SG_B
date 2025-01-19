from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Get environment (development or production)
ENV = os.getenv("ENV", "development")

# Configure database URL based on environment
if ENV == "production":
    DATABASE_URL = "sqlite:////data/reddit_analysis.db"
else:
    DATABASE_URL = "sqlite:///./reddit_analysis.db"

# Configure SQLite to handle concurrent requests properly
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
    pool_recycle=3600
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize database tables."""
    try:
        # Import models here to avoid circular imports
        from models import Base
        Base.metadata.create_all(bind=engine)
        logging.info("Database initialized")
    except Exception as e:
        logging.error(f"Error initializing database: {str(e)}")
        raise