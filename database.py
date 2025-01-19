import os
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pathlib import Path
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment (development or production)
ENV = os.getenv("ENV", "development")

# Configure SQLite for different environments
if ENV == "production":
    DB_PATH = Path("/data/reddit_analysis.db")
    DATABASE_URL = f"sqlite:////{DB_PATH.absolute()}?mode=rw"
else:
    DB_PATH = Path("./reddit_analysis.db")
    DATABASE_URL = "sqlite:///./reddit_analysis.db"

# Log database configuration
logger.info(f"Database path: {DB_PATH}")
logger.info(f"Database URL: {DATABASE_URL}")
logger.info(f"Environment: {ENV}")

def ensure_db_exists():
    """Ensure the database file exists and is accessible."""
    try:
        if not DB_PATH.exists():
            logger.info(f"Creating database file at {DB_PATH}")
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            DB_PATH.touch(mode=0o666)  # Create with read/write permissions
            logger.info("Database file created successfully")
        return True
    except Exception as e:
        logger.error(f"Error creating database file: {e}")
        return False

def wait_for_db():
    """Wait for database file to be accessible."""
    max_retries = 30
    retry_interval = 1
    
    for attempt in range(max_retries):
        if ensure_db_exists():
            try:
                # Try to open the file for read and write
                with open(DB_PATH, 'a+b') as f:
                    # Try to write to make sure we have write permissions
                    f.seek(0, 2)  # Seek to end
                    f.write(b'')  # Try to write empty bytes
                    f.flush()     # Ensure write is committed
                    logger.info(f"Database file is accessible at {DB_PATH}")
                    return True
            except IOError as e:
                logger.warning(f"Attempt {attempt + 1}/{max_retries}: Database file exists but not writable: {e}")
        else:
            logger.warning(f"Attempt {attempt + 1}/{max_retries}: Database file creation failed")
        
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
        
        # Ensure database file exists and is accessible
        wait_for_db()
        
        # Import models here to avoid circular imports
        from models import Base
        
        # Create database tables
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
        
        # Verify database is writable
        with engine.connect() as conn:
            conn.execute("SELECT 1")
            logger.info("Database connection test successful")
            
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise