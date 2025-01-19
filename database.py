import os
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pathlib import Path
import logging
import time
import subprocess

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment (development or production)
ENV = os.getenv("ENV", "development")

# Configure SQLite for different environments
if ENV == "production":
    DB_PATH = Path("/data/reddit_analysis.db")
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

def check_file_permissions():
    """Check and log file and directory permissions."""
    try:
        if DB_PATH.exists():
            # Log file permissions
            result = subprocess.run(['ls', '-la', str(DB_PATH)], capture_output=True, text=True)
            logger.info(f"Database file permissions:\n{result.stdout}")
            
            # Log parent directory permissions
            result = subprocess.run(['ls', '-la', str(DB_PATH.parent)], capture_output=True, text=True)
            logger.info(f"Parent directory permissions:\n{result.stdout}")
            
            # Try to get file stats
            stats = DB_PATH.stat()
            logger.info(f"File stats - mode: {oct(stats.st_mode)}, uid: {stats.st_uid}, gid: {stats.st_gid}")
            return True
    except Exception as e:
        logger.error(f"Error checking permissions: {e}")
    return False

def wait_for_db():
    """Wait for database file to be accessible."""
    max_retries = 30
    retry_interval = 1
    
    for attempt in range(max_retries):
        logger.info(f"Checking database file (attempt {attempt + 1}/{max_retries})...")
        
        # Check if file exists
        if DB_PATH.exists():
            # Log permissions
            check_file_permissions()
            
            try:
                # Try to open the file for reading
                with open(DB_PATH, 'rb') as f:
                    f.seek(0)  # Try to seek to verify readability
                    logger.info(f"Successfully opened database file at {DB_PATH}")
                    return True
            except IOError as e:
                logger.warning(f"Attempt {attempt + 1}/{max_retries}: Database file exists but not readable: {e}")
        else:
            logger.warning(f"Database file does not exist at {DB_PATH}")
            # Check parent directory
            if DB_PATH.parent.exists():
                result = subprocess.run(['ls', '-la', str(DB_PATH.parent)], capture_output=True, text=True)
                logger.info(f"Parent directory contents:\n{result.stdout}")
            else:
                logger.warning(f"Parent directory {DB_PATH.parent} does not exist")
        
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
        
        # Wait for database file to be accessible
        wait_for_db()
        
        # Verify database is readable
        with engine.connect() as conn:
            conn.execute("SELECT 1")
            logger.info("Database connection test successful")
            
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise