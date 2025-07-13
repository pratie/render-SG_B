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

def add_subscription_columns():
    """Add subscription-related columns to the users table."""
    logger.info("Starting to add subscription columns to the users table...")
    
    with get_db_connection() as connection:
        try:
            # Use connection.begin() for a transaction block
            with connection.begin(): # This will handle commit/rollback
                logger.info("Checking if subscription columns already exist...")
                
                result = connection.execute(text("PRAGMA table_info(users)"))
                columns = [row[1] for row in result.fetchall()]
                
                if 'subscription_plan' not in columns:
                    logger.info("Adding 'subscription_plan' column to 'users' table...")
                    connection.execute(
                        text("ALTER TABLE users ADD COLUMN subscription_plan TEXT DEFAULT 'free' NOT NULL")
                    )
                    logger.info("Successfully added 'subscription_plan' column.")
                else:
                    logger.info("'subscription_plan' column already exists.")
                
                # Re-fetch column info to ensure accuracy for subsequent checks in the same transaction
                current_columns_result = connection.execute(text("PRAGMA table_info(users)"))
                current_columns = [row[1] for row in current_columns_result.fetchall()]

                if 'plan_expires_at' not in current_columns:
                    logger.info("Adding 'plan_expires_at' column to 'users' table...")
                    connection.execute(
                        text("ALTER TABLE users ADD COLUMN plan_expires_at DATETIME")
                    )
                    logger.info("Successfully added 'plan_expires_at' column.")
                else:
                    logger.info("'plan_expires_at' column already exists (re-checked).")

            logger.info("Database schema updated successfully!")
            logger.info("New pricing structure is now ready!")
            logger.info("Remember to add these environment variables:")
            logger.info("  - DODO_MONTHLY_PRODUCT_ID (for $9/month plan)")
            logger.info("  - DODO_6MONTH_PRODUCT_ID (for $39/6 months plan)")
            logger.info("  - DODO_ANNUAL_PRODUCT_ID (for $69/year plan)")
            
        except Exception as e:
            logger.error(f"Error updating database schema: {e}")
            raise

if __name__ == "__main__":
    add_subscription_columns()