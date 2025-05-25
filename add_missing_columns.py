import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from database import DATABASE_URL, Base, engine
from models import Brand
import logging
from contextlib import contextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@contextmanager
def get_db_connection():
    """Context manager for database connection."""
    connection = engine.connect()
    try:
        yield connection
    finally:
        connection.close()

def add_missing_columns():
    """Add missing columns to the database."""
    logger.info("Starting to add missing columns to the database...")
    
    with get_db_connection() as connection:
        try:
            # Check if the columns already exist
            logger.info("Checking if columns already exist...")
            
            # Check SQLite system table for column existence
            result = connection.execute(text("PRAGMA table_info(brands)"))
            columns = [row[1] for row in result.fetchall()]
            
            # Add last_analyzed column if it doesn't exist
            if 'last_analyzed' not in columns:
                logger.info("Adding 'last_analyzed' column to 'brands' table...")
                connection.execute(
                    text("ALTER TABLE brands ADD COLUMN last_analyzed DATETIME")
                )
                connection.commit()
                logger.info("Successfully added 'last_analyzed' column.")
            else:
                logger.info("'last_analyzed' column already exists.")
            
            # Add subreddit_last_analyzed column if it doesn't exist
            if 'subreddit_last_analyzed' not in columns:
                logger.info("Adding 'subreddit_last_analyzed' column to 'brands' table...")
                connection.execute(
                    text("ALTER TABLE brands ADD COLUMN subreddit_last_analyzed TEXT DEFAULT '{}'")
                )
                connection.commit()
                logger.info("Successfully added 'subreddit_last_analyzed' column.")
            else:
                logger.info("'subreddit_last_analyzed' column already exists.")
            
            logger.info("Database schema updated successfully!")
            
        except Exception as e:
            logger.error(f"Error updating database schema: {e}")
            raise

if __name__ == "__main__":
    add_missing_columns()
