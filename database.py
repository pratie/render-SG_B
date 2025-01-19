import os
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pathlib import Path
import logging
import time
import subprocess
import sys

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment variables
ENV = os.getenv("ENV", "development")
IS_RENDER = os.getenv("RENDER", "false").lower() == "true"

# Log system information
logger.info(f"Current working directory: {os.getcwd()}")
logger.info(f"Python executable: {os.sys.executable}")
logger.info(f"Process UID/GID: {os.getuid()}/{os.getgid()}")

# Initialize DB_PATH and DATABASE_URL based on environment
if ENV == "production" or IS_RENDER:
    # Always use absolute path in production
    DB_PATH = Path("/var/data/reddit_analysis.db").resolve()
    DATABASE_URL = f"sqlite:////{DB_PATH.absolute()}"
    logger.info(f"Using production database on Render at {DB_PATH}")
else:
    # Use relative path for local development
    DB_PATH = Path("./reddit_analysis.db")
    DATABASE_URL = "sqlite:///./reddit_analysis.db"
    logger.info("Using local development database")

# Override DATABASE_URL if explicitly provided in environment
if os.getenv("DATABASE_URL"):
    DATABASE_URL = os.getenv("DATABASE_URL")
    logger.info("Using DATABASE_URL from environment variables")

# Ensure database directory exists
try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Ensured database directory exists: {DB_PATH.parent}")
    
    # Set directory permissions in production
    if ENV == "production" or IS_RENDER:
        os.chmod(DB_PATH.parent, 0o777)
        logger.info(f"Set directory permissions to 777")
    
    # Log directory permissions
    permissions = oct(DB_PATH.parent.stat().st_mode)[-3:]
    logger.info(f"Directory permissions: {permissions}")
    
except Exception as e:
    logger.error(f"Error with database directory: {e}")

# Log configuration
logger.info("=== Database Configuration ===")
logger.info(f"Environment: {ENV}")
logger.info(f"Running on Render: {IS_RENDER}")
logger.info(f"Database URL: {DATABASE_URL}")
logger.info(f"Database Path (absolute): {DB_PATH.absolute()}")
logger.info(f"Database directory exists: {DB_PATH.parent.exists()}")
logger.info(f"Database directory is writable: {os.access(DB_PATH.parent, os.W_OK)}")
logger.info("===========================")

# Check if we can access the database directory
try:
    if not DB_PATH.parent.exists():
        logger.error(f"Database directory does not exist: {DB_PATH.parent}")
    else:
        logger.info(f"Database directory exists: {DB_PATH.parent}")
        logger.info(f"Directory permissions: {oct(DB_PATH.parent.stat().st_mode)[-3:]}")
except Exception as e:
    logger.error(f"Error checking database directory: {e}")

print("\n=== Database Configuration ===")
print(f"Environment: {ENV}")
print(f"Running on Render: {IS_RENDER}")
print(f"Database URL: {DATABASE_URL}")
print("===========================\n")

logger.info(f"Database URL: {DATABASE_URL}")
logger.info(f"Environment: {ENV}")
logger.info(f"Running on Render: {IS_RENDER}")

def check_file_permissions(path):
    """Check and log file and directory permissions."""
    try:
        if path.exists():
            st = os.stat(path)
            logger.info(f"File exists. Size: {st.st_size} bytes")
            logger.info(f"File permissions: {oct(st.st_mode)[-3:]}")
            logger.info(f"UID/GID: {st.st_uid}/{st.st_gid}")
            return True
        else:
            logger.error(f"File not found: {path}")
            return False
    except Exception as e:
        logger.error(f"Error checking file permissions: {e}")
        return False

def wait_for_db():
    """Wait for database file to be accessible."""
    max_retries = 30
    retry_interval = 1
    
    for attempt in range(max_retries):
        logger.info(f"Checking database file (attempt {attempt + 1}/{max_retries})...")
        
        try:
            # Try to connect to database
            with engine.connect() as conn:
                conn.execute("SELECT 1")
                logger.info("Successfully connected to database")
                return True
        except Exception as e:
            logger.warning(f"Database connection attempt {attempt + 1} failed: {e}")
            
            # Check file permissions if in production
            if ENV == "production":
                if Path("/var/data/reddit_analysis.db").exists():
                    check_file_permissions(Path("/var/data/reddit_analysis.db"))
        
        time.sleep(retry_interval)
    
    raise RuntimeError(f"Database not accessible after {max_retries} attempts")

# Create SQLAlchemy engine with optimized settings for SQLite
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "uri": True
    }
)

# Configure SQLite for better performance
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.close()
        logger.info("SQLite PRAGMA settings applied successfully")
    except Exception as e:
        logger.error(f"Error setting SQLite PRAGMA: {e}")

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False
)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize the database and create all tables."""
    try:
        logger.info("Starting database initialization...")
        logger.info(f"Current working directory: {os.getcwd()}")
        logger.info(f"Python executable: {sys.executable}")
        logger.info(f"Process UID/GID: {os.getuid()}/{os.getgid()}")
        
        # Wait for database to be accessible
        wait_for_db()
        logger.info("Database initialization completed successfully")
            
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise