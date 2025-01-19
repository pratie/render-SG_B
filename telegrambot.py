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
    PRIMARY_DB_PATH = Path("/data/reddit_analysis.db")
    FALLBACK_DB_PATH = Path("/opt/render/project/data/reddit_analysis.db")
    
    # Check which path to use
    if PRIMARY_DB_PATH.exists() and os.access(str(PRIMARY_DB_PATH), os.R_OK):
        DB_PATH = str(PRIMARY_DB_PATH)
        logger.info("Using mounted volume database")
    else:
        DB_PATH = str(FALLBACK_DB_PATH)
        logger.info("Using fallback database path")
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reddit_analysis.db')
    logger.info("Using development database")

logger.info(f"Using database path: {DB_PATH}")
logger.info(f"Environment: {ENV}")

# Convert chat ID to integer and ensure it's positive
try:
    TELEGRAM_CHAT_ID = str(abs(int(TELEGRAM_CHAT_ID))) if TELEGRAM_CHAT_ID else None
except (ValueError, TypeError):
    logger.error("Invalid chat ID format")
    TELEGRAM_CHAT_ID = None

# Debug credentials
logger.info(f"Bot token present: {'Yes' if TELEGRAM_BOT_TOKEN else 'No'}")
logger.info(f"Chat ID present: {'Yes' if TELEGRAM_CHAT_ID else 'No'}")
if TELEGRAM_BOT_TOKEN:
    logger.info(f"Token length: {len(TELEGRAM_BOT_TOKEN)}")
    logger.info(f"Token format correct: {':' in TELEGRAM_BOT_TOKEN}")
if TELEGRAM_CHAT_ID:
    logger.info(f"Using chat ID: {TELEGRAM_CHAT_ID}")

def check_db_path():
    """Check database path and log relevant information."""
    try:
        if os.path.exists(DB_PATH):
            st = os.stat(DB_PATH)
            logger.info(f"Database file exists. Size: {st.st_size} bytes")
            logger.info(f"File permissions: {oct(st.st_mode)[-3:]}")
            logger.info(f"UID/GID: {st.st_uid}/{st.st_gid}")
            return True
        else:
            logger.error(f"Database file not found at: {DB_PATH}")
            if ENV == "production":
                logger.info("Checking database paths...")
                if PRIMARY_DB_PATH.exists():
                    logger.info(f"Primary database exists at: {PRIMARY_DB_PATH}")
                if FALLBACK_DB_PATH.exists():
                    logger.info(f"Fallback database exists at: {FALLBACK_DB_PATH}")
            return False
    except Exception as e:
        logger.error(f"Error checking database path: {e}")
        return False

async def get_db_connection():
    """Get database connection with retry logic."""
    max_retries = 3
    retry_delay = 5  # seconds
    
    if not check_db_path():
        return None
    
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            
            # Test the connection
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            
            logger.info("Successfully connected to database")
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

            # Calculate conversion rate safely
            conversion_rate = f"{(paid_users/total_users)*100:.1f}%" if total_users > 0 else "N/A"

            # Format message
            message = f"""🔔 Database Update ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

📊 Last 30 Minutes Activity:
- New Users: {len(new_users)}
{chr(10).join(f"  • {user['email']} (joined: {user['created_at']})" for user in new_users) if new_users else "  • No new users"}

👥 Overall Statistics:
- Total Users: {total_users:,}
- Paid Users: {paid_users:,}
- Conversion Rate: {conversion_rate}

💰 Recent Paid Conversions:
{chr(10).join(f"  • {user['email']} (paid: {user['payment_date']})" for user in recent_paid_users) if recent_paid_users else "  • No recent paid users"}

🔧 System Info:
- Environment: {ENV}
- Database: {DB_PATH}"""

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
    """Send message to Telegram with retry logic and timeout."""
    max_retries = 3
    retry_delay = 5  # seconds
    timeout = 30  # seconds
    
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
            
            # Use a session for better connection handling
            with requests.Session() as session:
                response = session.post(
                    telegram_url,
                    json=payload,
                    timeout=timeout,
                    verify=True  # Ensure SSL verification
                )
            
            if response.status_code == 200:
                logger.info("Telegram alert sent successfully")
                return
            else:
                logger.error(f"Failed to send Telegram alert. Status code: {response.status_code}")
                logger.error(f"Response: {response.text}")
                
        except requests.exceptions.Timeout:
            logger.error(f"Timeout error on attempt {attempt + 1}")
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error on attempt {attempt + 1}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error on attempt {attempt + 1}: {str(e)}")
        
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
    # Check database path before starting
    if check_db_path():
        job()
    else:
        logger.error("Cannot start alert service - database not accessible")