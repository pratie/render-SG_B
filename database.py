from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
import logging
import pathlib

# Load environment variables
load_dotenv()

# Get environment (development or production)
ENV = os.getenv("ENV", "development")

# Configure database URL based on environment
if ENV == "production":
    DB_PATH = pathlib.Path("/data/reddit_analysis.db")
    DATABASE_URL = f"sqlite:///{DB_PATH}"
else:
    DB_PATH = pathlib.Path("./reddit_analysis.db")
    DATABASE_URL = "sqlite:///./reddit_analysis.db"

# Ensure the database directory exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

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
        
        # Create an empty database file if it doesn't exist
        if not DB_PATH.exists():
            DB_PATH.touch()
            if ENV == "production":
                os.chmod(DB_PATH, 0o666)
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        logging.info(f"Database initialized at {DB_PATH}")
    except Exception as e:
        logging.error(f"Error initializing database: {str(e)}")
        raise