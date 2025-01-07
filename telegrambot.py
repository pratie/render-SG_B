import os
import sqlite3
import requests
import asyncio
from dotenv import load_dotenv
import logging
from pathlib import Path
from datetime import datetime
import schedule
import time

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

async def send_telegram_alert():
    """Send alert to Telegram channel."""
    try:
        # Verify credentials
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.error("Missing Telegram credentials")
            return

        # Test Telegram bot token
        test_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
        logger.info("Testing bot token...")
        test_response = requests.get(test_url)
        logger.info(f"Test response: {test_response.text}")
        if test_response.status_code != 200:
            logger.error(f"Bot token test failed: {test_response.text}")
            return
        logger.info("Bot token test successful")

        # Send test message first
        test_message = "🔄 Bot Test: Successfully connected!"
        test_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        test_payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': test_message
        }
        test_send = requests.post(test_url, json=test_payload)
        if test_send.status_code != 200:
            logger.error(f"Test message failed: {test_send.text}")
            return
        logger.info("Test message sent successfully")

        # Ensure database path exists
        logger.info(f"Using database at: {DB_PATH}")
        if not os.path.exists(DB_PATH):
            logger.error(f"Database file not found at: {DB_PATH}")
            return

        # Connect to database
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            # Get new users and mentions
            cursor.execute("""
                SELECT COUNT(*) FROM users 
                WHERE created_at > datetime('now', '-30 minute')
            """)
            new_users = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) FROM reddit_mentions 
                WHERE created_at > datetime('now', '-30 minute')
            """)
            new_mentions = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE has_paid = 1")
            paid_users = cursor.fetchone()[0]
        except sqlite3.Error as e:
            logger.error(f"SQL query error: {str(e)}")
            return
        
        # Format message
        message = f"""🔔 Database Update ({datetime.now().strftime('%H:%M')})

📊 Last 30 Minutes:
- New Users: {new_users}
- New Mentions: {new_mentions}

👥 Overall Stats:
- Total Users: {total_users}
- Paid Users: {paid_users}
"""
        
        # Telegram API URL
        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        
        # Send message
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message
        }
        
        logger.info("Sending message to Telegram...")
        logger.info(f"Using chat ID: {TELEGRAM_CHAT_ID}")
        response = requests.post(telegram_url, json=payload)
        
        if response.status_code == 200:
            logger.info("Telegram alert sent successfully")
        else:
            logger.error(f"Failed to send Telegram alert. Status code: {response.status_code}")
            logger.error(f"Response: {response.text}")

    except sqlite3.Error as e:
        logger.error(f"Database error: {str(e)}")
    except requests.RequestException as e:
        logger.error(f"Telegram API error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
    finally:
        if 'conn' in locals():
            conn.close()

def job():
    asyncio.run(send_telegram_alert())

if __name__ == "__main__":
    print("Starting Telegram alert service...")
    # Run first alert immediately
    job()
    
    # Schedule future alerts
    schedule.every(30).minutes.do(job)
    
    while True:
        schedule.run_pending()
        time.sleep(1)