import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from database import DATABASE_URL, Base, engine
from models import Brand
import logging
from contextlib import contextmanager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
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
            # Use connection.begin() for a transaction block
            with connection.begin(): # This will handle commit/rollback
                logger.info("Checking if columns already exist...")
                
                result = connection.execute(text("PRAGMA table_info(brands)"))
                columns = [row[1] for row in result.fetchall()]
                
                if 'last_analyzed' not in columns:
                    logger.info("Adding 'last_analyzed' column to 'brands' table...")
                    connection.execute(
                        text("ALTER TABLE brands ADD COLUMN last_analyzed DATETIME")
                    )
                    logger.info("Successfully added 'last_analyzed' column.")
                else:
                    logger.info("'last_analyzed' column already exists.")
                
                # Re-fetch column info to ensure accuracy for subsequent checks in the same transaction
                current_columns_result = connection.execute(text("PRAGMA table_info(brands)"))
                current_columns = [row[1] for row in current_columns_result.fetchall()]

                if 'subreddit_last_analyzed' not in current_columns:
                    logger.info("Adding 'subreddit_last_analyzed' column to 'brands' table...")
                    connection.execute(
                        text("ALTER TABLE brands ADD COLUMN subreddit_last_analyzed TEXT DEFAULT '{}'")
                    )
                    logger.info("Successfully added 'subreddit_last_analyzed' column.")
                else:
                    logger.info("'subreddit_last_analyzed' column already exists (re-checked).")

            logger.info("Database schema updated successfully!")
            
        except Exception as e:
            logger.error(f"Error updating database schema: {e}")
            raise

if __name__ == "__main__":
    add_missing_columns()
