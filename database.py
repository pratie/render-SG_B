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

# Get environment (development or production)
ENV = os.getenv("ENV", "development")

# Configure SQLite for different environments
if ENV == "production":
    DB_PATH = Path("/data/reddit_analysis.db")
    FALLBACK_DB_PATH = Path("/opt/render/project/data/reddit_analysis.db")
    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:////{DB_PATH.absolute()}?mode=ro")
else:
    DB_PATH = Path("./reddit_analysis.db")
    DATABASE_URL = "sqlite:///./reddit_analysis.db"
    # In development, ensure directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Log database configuration
logger.info(f"Database path: {DB_PATH}")
logger.info(f"Database URL: {DATABASE_URL}")
logger.info(f"Environment: {ENV}")

def check_file_permissions(path):
    """Check and log file and directory permissions."""
    try:
        if path.exists():
            # Log file permissions
            result = subprocess.run(['ls', '-la', str(path)], capture_output=True, text=True)
            logger.info(f"File permissions for {path}:\n{result.stdout}")
            
            # Log parent directory permissions
            result = subprocess.run(['ls', '-la', str(path.parent)], capture_output=True, text=True)
            logger.info(f"Parent directory permissions for {path}:\n{result.stdout}")
            
            # Try to get file stats
            stats = path.stat()
            logger.info(f"File stats for {path} - mode: {oct(stats.st_mode)}, uid: {stats.st_uid}, gid: {stats.st_gid}")
            return True
    except Exception as e:
        logger.error(f"Error checking permissions for {path}: {e}")
    return False

def wait_for_db():
    """Wait for database file to be accessible."""
    max_retries = 30
    retry_interval = 1
    
    for attempt in range(max_retries):
        logger.info(f"Checking database file (attempt {attempt + 1}/{max_retries})...")
        
        # First try primary path
        if DB_PATH.exists():
            logger.info(f"Found database at primary path: {DB_PATH}")
            check_file_permissions(DB_PATH)
            try:
                with open(DB_PATH, 'rb') as f:
                    f.seek(0)
                    logger.info(f"Successfully opened database file at {DB_PATH}")
                    return True
            except IOError as e:
                logger.warning(f"Cannot read primary database: {e}")
        else:
            logger.warning(f"Primary database path does not exist: {DB_PATH}")
            
            # In production, check fallback path
            if ENV == "production" and FALLBACK_DB_PATH.exists():
                logger.info(f"Checking fallback path: {FALLBACK_DB_PATH}")
                check_file_permissions(FALLBACK_DB_PATH)
                try:
                    # Try to copy from fallback location
                    subprocess.run(['cp', '-f', str(FALLBACK_DB_PATH), str(DB_PATH)], check=True)
                    subprocess.run(['chmod', '777', str(DB_PATH)], check=True)
                    logger.info("Successfully copied database from fallback location")
                    continue  # Retry with the copied file
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to copy from fallback location: {e}")
        
        # Check parent directories
        logger.info("Checking parent directories...")
        if not DB_PATH.parent.exists():
            logger.warning(f"Parent directory {DB_PATH.parent} does not exist")
            try:
                DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created parent directory {DB_PATH.parent}")
            except Exception as e:
                logger.error(f"Failed to create parent directory: {e}")
        
        time.sleep(retry_interval)
    
    raise RuntimeError(f"Database file not accessible after {max_retries} attempts")

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
        
        # Wait for database file to be accessible
        wait_for_db()
        
        # Verify database is readable
        with engine.connect() as conn:
            conn.execute("SELECT 1")
            logger.info("Database connection test successful")
            
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise