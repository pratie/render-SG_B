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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get Telegram credentials from environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Convert chat ID to integer and ensure it's positive
try:
    TELEGRAM_CHAT_ID = str(abs(int(TELEGRAM_CHAT_ID))) if TELEGRAM_CHAT_ID else None
except (ValueError, TypeError):
    logger.error("Invalid chat ID format")
    TELEGRAM_CHAT_ID = None

# Debug credentials (don't log the full token in production)
logger.info(f"Bot token present: {'Yes' if TELEGRAM_BOT_TOKEN else 'No'}")
logger.info(f"Chat ID present: {'Yes' if TELEGRAM_CHAT_ID else 'No'}")
if TELEGRAM_BOT_TOKEN:
    logger.info(f"Token length: {len(TELEGRAM_BOT_TOKEN)}")
    logger.info(f"Token format correct: {':' in TELEGRAM_BOT_TOKEN}")
if TELEGRAM_CHAT_ID:
    logger.info(f"Using chat ID: {TELEGRAM_CHAT_ID}")

# Database path - using absolute path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'reddit_analysis.db')

async def get_stats():
    """Get statistics from database."""
    try:
        if not os.path.exists(DB_PATH):
            logger.error(f"Database file not found at: {DB_PATH}")
            return None

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            # Get new users with their emails
            cursor.execute("""
                SELECT email FROM users 
                WHERE created_at > datetime('now', '-30 minute')
                ORDER BY created_at DESC
            """)
            new_user_emails = cursor.fetchall()
            
            # Get basic stats
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE has_paid = 1")
            paid_users = cursor.fetchone()[0]

            # Get latest paid users with emails
            cursor.execute("""
                SELECT email, payment_date 
                FROM users 
                WHERE has_paid = 1 
                ORDER BY payment_date DESC 
                LIMIT 5
            """)
            recent_paid_users = cursor.fetchall()

            # Format message
            message = f"""🔔 Database Update ({datetime.now().strftime('%H:%M')})

📊 Last 30 Minutes:
- New Users: {len(new_user_emails)}
  {chr(10).join(f"  • {email[0]}" for email in new_user_emails) if new_user_emails else "  • No new users"}

👥 Overall Stats:
- Total Users: {total_users}
- Paid Users: {paid_users}

💰 Recent Paid Users:
{chr(10).join(f"  • {email} (paid on {payment_date})" for email, payment_date in recent_paid_users) if recent_paid_users else "  • No recent paid users"}
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
    """Send message to Telegram."""
    try:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.error("Missing Telegram credentials")
            return

        # Telegram API URL
        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        
        # Send message
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message
        }
        
        logger.info("Sending message to Telegram...")
        response = requests.post(telegram_url, json=payload)
        
        if response.status_code == 200:
            logger.info("Telegram alert sent successfully")
        else:
            logger.error(f"Failed to send Telegram alert. Status code: {response.status_code}")

    except Exception as e:
        logger.error(f"Error sending Telegram message: {str(e)}")

async def send_alerts():
    """Send alerts to Telegram."""
    try:
        # Get stats message
        stats = await get_stats()
        if stats:
            # Send to Telegram
            await send_telegram_message(stats)
    except Exception as e:
        logger.error(f"Error in send_alerts: {str(e)}")

def job():
    asyncio.run(send_alerts())

if __name__ == "__main__":
    print("Starting alert service...")
    # Run the job once when script is executed
    job()