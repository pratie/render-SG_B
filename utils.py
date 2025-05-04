# utils.py
import os
import logging
from sqlalchemy.orm import Session
from database import SessionLocal, engine, Base
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_db_session():
    """Dependency to get DB session for background tasks."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
