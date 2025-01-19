import os
import sqlite3
import requests
import asyncio
from dotenv import load_dotenv
import logging
from pathlib import Path
from datetime import datetime

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get Telegram credentials from environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Get environment
ENV = os.getenv("ENV", "development")

# Set database path based on environment
if ENV == "production":
    DB_PATH = "/data/reddit_analysis.db"
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.path.join(BASE_DIR, 'reddit_analysis.db')

logger.info(f"Using database path: {DB_PATH}")
logger.info(f"Environment: {ENV}")

# Convert chat ID to integer and ensure it's positive
try:
    TELEGRAM_CHAT_ID = str(abs(int(TELEGRAM_CHAT_ID))) if TELEGRAM_CHAT_ID else None
except (ValueError, TypeError):
    logger.error("Invalid chat ID format")
    TELEGRAM_CHAT_ID = None

# Debug credentials (don't log the full token in production)
logger.info(f"Bot token present: {'Yes' if TELEGRAM_BOT_TOKEN else 'No'}")
logger.info(f"Chat ID present: {'Yes' if TELEGRAM_CHAT_ID else 'No'}")

async def get_db_connection():
    """Get database connection with retry logic."""
    max_retries = 3
    retry_delay = 5  # seconds
    
    for attempt in range(max_retries):
        try:
            if not os.path.exists(DB_PATH):
                logger.error(f"Database file not found at: {DB_PATH}")
                if ENV == "production":
                    logger.info("Checking Render disk mount...")
                    logger.info(f"Directory contents of /data: {os.listdir('/data')}")
                return None
                
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # Enable row factory for named columns
            return conn
            
        except sqlite3.Error as e:
            logger.error(f"Database connection attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Max retries reached. Could not connect to database.")
                return None

async def get_stats():
    """Get statistics from database."""
    try:
        conn = await get_db_connection()
        if not conn:
            return None

        cursor = conn.cursor()

        try:
            # Get new users with their emails
            cursor.execute("""
                SELECT email, created_at FROM users 
                WHERE created_at > datetime('now', '-30 minute')
                ORDER BY created_at DESC
            """)
            new_users = cursor.fetchall()
            
            # Get basic stats
            cursor.execute("SELECT COUNT(*) as count FROM users")
            total_users = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM users WHERE has_paid = 1")
            paid_users = cursor.fetchone()['count']

            # Get latest paid users with emails
            cursor.execute("""
                SELECT email, payment_date 
                FROM users 
                WHERE has_paid = 1 
                ORDER BY payment_date DESC 
                LIMIT 5
            """)
            recent_paid_users = cursor.fetchall()

            # Format message with more detailed information
            message = f"""🔔 Database Update ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

📊 Last 30 Minutes Activity:
- New Users: {len(new_users)}
{chr(10).join(f"  • {user['email']} (joined: {user['created_at']})" for user in new_users) if new_users else "  • No new users"}

👥 Overall Statistics:
- Total Users: {total_users:,}
- Paid Users: {paid_users:,}
- Conversion Rate: {(paid_users/total_users)*100:.1f}% if total_users > 0 else "N/A"}

💰 Recent Paid Conversions:
{chr(10).join(f"  • {user['email']} (paid: {user['payment_date']})" for user in recent_paid_users) if recent_paid_users else "  • No recent paid users"}

🔧 System Info:
- Environment: {ENV}
- Database: {DB_PATH}
"""
            return message

        except sqlite3.Error as e:
            logger.error(f"SQL query error: {str(e)}")
            return None
        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return None

async def send_telegram_message(message: str):
    """Send message to Telegram with retry logic."""
    max_retries = 3
    retry_delay = 5  # seconds
    
    for attempt in range(max_retries):
        try:
            if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
                logger.error("Missing Telegram credentials")
                return

            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            
            payload = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'HTML'
            }
            
            logger.info(f"Sending message to Telegram (attempt {attempt + 1})...")
            response = requests.post(telegram_url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info("Telegram alert sent successfully")
                return
            else:
                logger.error(f"Failed to send Telegram alert. Status code: {response.status_code}")
                logger.error(f"Response: {response.text}")
                
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                
        except Exception as e:
            logger.error(f"Error sending Telegram message (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)

async def send_alerts():
    """Main function to send alerts to Telegram."""
    try:
        stats = await get_stats()
        if stats:
            await send_telegram_message(stats)
    except Exception as e:
        logger.error(f"Error in send_alerts: {str(e)}")

def job():
    """Wrapper function for the alert job."""
    try:
        asyncio.run(send_alerts())
    except Exception as e:
        logger.error(f"Critical error in job execution: {str(e)}")

if __name__ == "__main__":
    logger.info(f"Starting alert service in {ENV} environment...")
    job()