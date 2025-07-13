import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from database import DATABASE_URL, Base, engine
from models import User
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

def update_free_plans_to_none():
    """Update all users with 'free' subscription_plan to 'none' since there's no free tier."""
    logger.info("Updating subscription plans from 'free' to 'none'...")
    
    with get_db_connection() as connection:
        try:
            with connection.begin():
                # Update any users with 'free' plan to 'none'
                result = connection.execute(
                    text("UPDATE users SET subscription_plan = 'none' WHERE subscription_plan = 'free'")
                )
                updated_count = result.rowcount
                logger.info(f"Updated {updated_count} users from 'free' to 'none' plan")
                
                # Also update default value for new users
                logger.info("Database updated successfully!")
                logger.info("No free tier - users must choose from $9, $39, or $69 plans")
                
        except Exception as e:
            logger.error(f"Error updating database: {e}")
            raise

if __name__ == "__main__":
    update_free_plans_to_none()