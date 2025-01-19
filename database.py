from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
import logging
from pathlib import Path

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment (development or production)
ENV = os.getenv("ENV", "development")

# Configure SQLite for different environments
if ENV == "production":
    DB_PATH = Path("/data/reddit_analysis.db")
    DATABASE_URL = f"sqlite:///{DB_PATH}"
else:
    DB_PATH = Path("./reddit_analysis.db")
    DATABASE_URL = "sqlite:///./reddit_analysis.db"

# In development, ensure directory exists
if ENV == "development":
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Create SQLAlchemy engine with connection pooling and retry settings
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
    pool_recycle=3600,
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
    """Initialize the database and create all tables."""
    try:
        # Import models here to avoid circular imports
        from models import Base
        
        # Create database tables
        Base.metadata.create_all(bind=engine)
        logger.info(f"Database initialized successfully at {DB_PATH}")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise