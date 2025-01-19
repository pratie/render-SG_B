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
from sqlalchemy.pool import StaticPool
import os
from dotenv import load_dotenv

load_dotenv()

# Get environment (development or production)
ENV = os.getenv("ENV", "development")

# Set database path based on environment
if ENV == "production":
    # Use Render's persistent disk mount path
    DATABASE_URL = "sqlite:////data/reddit_analysis.db"
else:
    # Use local path for development
    DATABASE_URL = "sqlite:///./reddit_analysis.db"

# Create database engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool if DATABASE_URL.startswith("sqlite") else None
)

# Create SessionLocal class for database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Base class for declarative models
Base = declarative_base()

# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()