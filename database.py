# # app/database.py
# from sqlalchemy import create_engine
# from sqlalchemy.ext.declarative import declarative_base
# from sqlalchemy.orm import sessionmaker
# from sqlalchemy.pool import StaticPool
# import os
# from dotenv import load_dotenv

# load_dotenv()

# # Get database URL from environment variable
# DATABASE_URL = os.getenv(
#     "DATABASE_URL",
#     "postgresql://postgres:postgres@localhost:5432/reddit_analyzer"
# )

# # Create database engine
# engine = create_engine(
#     DATABASE_URL,
#     connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
#     poolclass=StaticPool if DATABASE_URL.startswith("sqlite") else None
# )

# # Create SessionLocal class for database sessions
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# # Create Base class for declarative models
# Base = declarative_base()

# # Dependency to get database session
# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()


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
    # Ensure the data directory exists in production
    os.makedirs("/data", exist_ok=True)
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
        # Create database directory if it doesn't exist
        if ENV == "production":
            os.makedirs("/data", exist_ok=True)
            if not os.path.exists("/data/reddit_analysis.db"):
                # Create an empty file with proper permissions
                with open("/data/reddit_analysis.db", "w") as f:
                    pass
                os.chmod("/data/reddit_analysis.db", 0o666)
        
        Base.metadata.create_all(bind=engine)
        logging.info("Database initialized")
    except Exception as e:
        logging.error(f"Error initializing database: {str(e)}")
        raise