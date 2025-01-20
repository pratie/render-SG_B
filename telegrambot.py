import os
import sqlite3
import requests
import asyncio
from dotenv import load_dotenv
import logging
from pathlib import Path
from datetime import datetime
import shutil

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
    PRIMARY_DB_PATH = Path("/var/data/reddit_analysis.db")
    FALLBACK_DB_PATH = Path("/opt/render/project/src/reddit_analysis.db") 
    
    # Enhanced debugging for disk and database access
    logger.info("=== Checking Disk Mount ===")
    try:
        logger.info(f"Contents of /var/data:")
        logger.info(os.listdir('/var/data'))
        
        # Check disk space
        total, used, free = shutil.disk_usage("/var/data")
        logger.info(f"Disk space - Total: {total // (2**30)}GB, Used: {used // (2**30)}GB, Free: {free // (2**30)}GB")
    except Exception as e:
        logger.error(f"Error accessing /var/data: {e}")

    logger.info("=== Database Path Check ===")
    logger.info(f"Primary path exists: {PRIMARY_DB_PATH.exists()}")
    logger.info(f"Primary path readable: {os.access(str(PRIMARY_DB_PATH), os.R_OK)}")
    logger.info(f"Primary path writable: {os.access(str(PRIMARY_DB_PATH), os.W_OK)}")
    logger.info(f"Fallback path exists: {FALLBACK_DB_PATH.exists()}")
    logger.info(f"Fallback path readable: {os.access(str(FALLBACK_DB_PATH), os.R_OK)}")
    
    # Check which path to use
    if PRIMARY_DB_PATH.exists() and os.access(str(PRIMARY_DB_PATH), os.R_OK):
        DB_PATH = str(PRIMARY_DB_PATH)
        logger.info("Using mounted volume database")
    else:
        DB_PATH = str(FALLBACK_DB_PATH)
        logger.info("Using fallback database path")
        
    # Log file permissions
    try:
        if PRIMARY_DB_PATH.exists():
            st = os.stat(str(PRIMARY_DB_PATH))
            logger.info(f"Primary DB permissions: {oct(st.st_mode)[-3:]}")
            logger.info(f"Primary DB UID/GID: {st.st_uid}/{st.st_gid}")
    except Exception as e:
        logger.error(f"Error checking primary DB permissions: {e}")
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reddit_analysis.db')
    logger.info("Using development database")

logger.info(f"Final database path: {DB_PATH}")
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
            
            # Test file operations
            logger.info("Testing file operations...")
            try:
                with open(DB_PATH, 'rb') as f:
                    _ = f.read(1)
                logger.info("File is readable")
                # Test SQLite connection
                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                logger.info("SQLite connection test successful")
            except Exception as e:
                logger.error(f"Database access test failed: {e}")
            
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
            logger.info("=== Executing Database Queries ===")
            
            # Get new users with their emails
            cursor.execute("""
                SELECT email, created_at FROM users 
                WHERE created_at > datetime('now', '-30 minute')
                ORDER BY created_at DESC
            """)
            new_users = cursor.fetchall()
            logger.info(f"Found {len(new_users)} new users")
            
            # Get recent logins
            cursor.execute("""
                SELECT email, last_login 
                FROM users 
                WHERE last_login IS NOT NULL
                AND last_login > datetime('now', '-30 minute')
                ORDER BY last_login DESC
            """)
            recent_logins = cursor.fetchall()
            logger.info(f"Found {len(recent_logins)} recent logins")
            
            # Get basic stats
            cursor.execute("SELECT COUNT(*) as count FROM users")
            total_users = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM users WHERE has_paid = 1")
            paid_users = cursor.fetchone()['count']
            
            # Get active projects count
            cursor.execute("SELECT COUNT(DISTINCT brand_id) as count FROM reddit_mentions")
            active_projects = cursor.fetchone()['count']

            # Get latest paid users with emails
            cursor.execute("""
                SELECT email, payment_date 
                FROM users 
                WHERE has_paid = 1 
                ORDER BY payment_date DESC 
                LIMIT 5
            """)
            recent_paid_users = cursor.fetchall()

            logger.info("=== Database Queries Completed ===")

            # Calculate conversion rate safely
            conversion_rate = f"{(paid_users/total_users)*100:.1f}%" if total_users > 0 else "N/A"

            # Format message
            message = f"""🔔 Database Update ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

📊 Last 30 Minutes Activity:
- New Users: {len(new_users)}
{chr(10).join(f"  • {user['email']} (joined: {user['created_at']})" for user in new_users) if new_users else "  • No new users"}

🔐 Recent Logins:
- Active Users: {len(recent_logins)}
{chr(10).join(f"  • {user['email']} (last login: {user['last_login']})" for user in recent_logins) if recent_logins else "  • No recent logins"}

👥 Overall Statistics:
- Total Users: {total_users:,}
- Paid Users: {paid_users:,}
- Conversion Rate: {conversion_rate}
- Active Projects: {active_projects:,}

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
        logger.info("=== Starting Alert Job ===")
        asyncio.run(send_alerts())
        logger.info("=== Alert Job Completed ===")
    except Exception as e:
        logger.error(f"Critical error in job execution: {str(e)}")

if __name__ == "__main__":
    logger.info(f"=== Starting Alert Service ===")
    logger.info(f"Environment: {ENV}")
    # Check database path before starting
    if check_db_path():
        job()
    else:
        logger.error("Cannot start alert service - database not accessible")