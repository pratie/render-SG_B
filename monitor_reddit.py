# monitor_reddit.py

import asyncio
import asyncpraw
import asyncprawcore
import os
import logging
import signal
import sys
from dotenv import load_dotenv
import certifi
import ssl
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from routers.alerts import get_all_active_alert_settings, send_telegram_alert
import json
import datetime

# Assuming database models and session management are correctly set up
from database import SessionLocal # Or use get_db_session from utils
from models import Brand, RedditMention, AlertSetting, User # Import necessary models
from sqlalchemy.orm import Session
from utils import get_db_session
# If generate_relevance_score is uncommented and needed:
# from main import generate_relevance_score 

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Reddit API Credentials
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = "RealtimeAlertMonitor/0.1 by YourUsername"

# Global flag to handle graceful shutdown
shutdown_flag = asyncio.Event()

# --- Database Interaction ---

def get_monitoring_config(db: Session):
    """Fetches necessary configuration: brands, keywords, subreddits, alert settings."""
    logger.info("Fetching monitoring configuration from database...")
    try:
        # Fetch all brands with their associated keywords and subreddits
        brands = db.query(Brand).all() # Add relationships if needed
        
        # Get only active alert settings
        alert_settings = get_all_active_alert_settings(db)
        
        # Process into a more usable format, e.g., a dict mapping subreddit to checks
        config = {}
        # { 
        #   'subreddit_name': [ 
        #       {'brand_id': 1, 'keywords': [...], 'alert_setting': <AlertSetting obj>}, 
        #       ...
        #    ], ...
        # }

        # This is a simplified example, adjust based on your actual data model and needs
        for setting in alert_settings:
            # Skip inactive alert settings
            if not setting.is_active:
                continue
                
            # Only process settings where at least one alert type is enabled
            if not (setting.enable_telegram_alerts or setting.enable_email_alerts):
                continue
                
            user_brands = db.query(Brand).filter(Brand.user_email == setting.user_email).all()
            for brand in user_brands:
                if not brand.keywords or not brand.subreddits:
                    continue # Skip brands without keywords/subreddits
                
                try:
                    # Parse keywords and subreddits from JSON strings
                    brand_keywords = json.loads(brand.keywords)
                    brand_subreddits = json.loads(brand.subreddits)
                    
                    # Clean up subreddit names
                    brand_subreddits = [sub.strip().lower().replace('r/', '') for sub in brand_subreddits if sub.strip()]
                    
                    for sub_name in brand_subreddits:
                        if sub_name not in config:
                            config[sub_name] = []
                        config[sub_name].append({
                            'brand_id': brand.id,
                            'brand_name': brand.name,
                            'keywords': brand_keywords,
                            'alert_setting': setting
                        })
                except json.JSONDecodeError:
                    logger.error(f"Error parsing JSON for brand {brand.id}: {brand.name}")
                    continue

        logger.info(f"Configuration loaded for {len(config)} subreddits.")
        return config

    except Exception as e:
        logger.error(f"Error fetching monitoring configuration: {e}", exc_info=True)
        return {}

# --- Reddit Interaction & Processing ---

# Define exceptions that asyncpraw might raise during streaming that we want to retry on
RETRYABLE_EXCEPTIONS = (
    asyncio.TimeoutError,
    aiohttp.ClientError, # Includes connection errors, etc.
    asyncprawcore.exceptions.RequestException,
    asyncprawcore.exceptions.ServerError,
    asyncprawcore.exceptions.ResponseException,
)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=5, max=60), # Exponential backoff: 5s, 10s, 20s, 40s, 60s
    retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
    before_sleep=lambda retry_state: logger.warning(f"Stream error ({retry_state.outcome.exception()}), retrying in {retry_state.next_action.sleep:.2f}s (Attempt {retry_state.attempt_number})...")
)
async def stream_subreddit(reddit, subreddit_name: str, config_for_sub: list, db_session_factory):
    """Streams submissions for a single subreddit and processes them."""
    logger.info(f"Starting stream for subreddit: r/{subreddit_name}")
    subreddit = await reddit.subreddit(subreddit_name)
    
    try:
        async for submission in subreddit.stream.submissions(skip_existing=True):
            if shutdown_flag.is_set():
                logger.info(f"Shutdown signal received, stopping stream for r/{subreddit_name}.")
                break

            # Check against configurations for this subreddit
            title_lower = submission.title.lower()
            content_lower = submission.selftext.lower() if submission.selftext else ""
            post_text = title_lower + " " + content_lower

            matched_configs = []
            for check in config_for_sub:
                # Basic keyword matching (case-insensitive)
                if any(keyword in post_text for keyword in check['keywords']):
                    matched_configs.append(check)
            
            if not matched_configs:
                continue # No keyword match for this post in this sub

            logger.info(f"Potential match found in r/{subreddit_name}: {submission.id} ({submission.title[:50]}...)")

            # Process matched configurations (scoring, alerting)
            # Use a new DB session for processing each submission to avoid session issues
            with db_session_factory() as db:
                for match_config in matched_configs:
                    alert_setting = match_config['alert_setting']
                    brand_id = match_config['brand_id']
                    brand_name = match_config['brand_name']

                    # --- Alerting --- 
                    # Send alert for any keyword match without relevance scoring
                    logger.info(f"    -> Keyword match found for Brand ID {brand_id}. Triggering alert for User {alert_setting.user_email}.")
                    # Find the matching keyword(s)
                    matched_keywords = [kw for kw in match_config['keywords'] if kw.lower() in post_text.lower()]
                    # Format posted time as readable string (Telegram expects a string, not a float)
                    posted_time = datetime.datetime.utcfromtimestamp(submission.created_utc).strftime('%Y-%m-%d %H:%M UTC')
                    # Format Telegram message with nice styles
                    message = (
                        f"🚨 <b>Reddit Brand Alert</b> 🚨\n"
                        f"<b>Brand:</b> <code>{brand_name}</code>\n"
                        f"<b>Subreddit:</b> <code>r/{subreddit_name}</code>\n"
                        f"<b>Matched Keyword(s):</b> <code>{', '.join(matched_keywords) if matched_keywords else 'N/A'}</code>\n\n"
                        f"<b>Post:</b> <a href='https://reddit.com{submission.permalink}'>{submission.title.replace('<', '').replace('>', '').replace('&', '')}</a>\n"
                        f"<b>Author:</b> <code>u/{submission.author.name if submission.author else 'unknown'}</code>\n"
                        f"<b>Posted:</b> {posted_time}\n\n"
                        f"<b>Preview:</b> {submission.selftext[:200] + ('...' if len(submission.selftext) > 200 else '') if submission.selftext else 'No text'}\n"
                    )
                    # Ensure telegram_chat_id exists
                    if alert_setting.telegram_chat_id:
                         await send_telegram_alert(message, alert_setting.telegram_chat_id)
                    else:
                        logger.warning(f"User {alert_setting.user_email} has no Telegram Chat ID configured for alerts.")
                        
                    # --- TODO: Optionally save mention to database? ---
                    # Consider if mentions found via streaming should also be saved.
                    # If so, add logic here similar to analyze_reddit_content
                    # Need to handle potential duplicates carefully.

    except asyncprawcore.exceptions.NotFound:
        logger.error(f"Subreddit r/{subreddit_name} not found or access denied. Stopping stream.")
    except asyncprawcore.exceptions.Forbidden:
        logger.error(f"Forbidden access to r/{subreddit_name}. Stopping stream.")
    except Exception as e:
        if isinstance(e, RETRYABLE_EXCEPTIONS):
             logger.error(f"Retriable error in r/{subreddit_name} stream: {type(e).__name__} - {e}")
             raise # Re-raise to trigger tenacity retry
        else:
             logger.error(f"Non-retriable error in r/{subreddit_name} stream: {type(e).__name__} - {e}", exc_info=True)
             # Decide if this task should terminate or attempt restart after a delay
    finally:
        logger.info(f"Stream stopped for r/{subreddit_name}.")

# --- Main Execution Logic ---

async def main():
    logger.info("Starting Reddit Realtime Monitor...")
    
    # Ensure credentials are set
    if not all([REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET]):
        logger.error("Reddit API credentials not found in environment variables.")
        return

    # Get initial configuration
    # Need a way to get a db session outside of FastAPI dependency injection
    db_session_factory = SessionLocal # Use the factory directly
    
    monitoring_config = {}
    with db_session_factory() as db: # Get initial config synchronously
        monitoring_config = get_monitoring_config(db)

    if not monitoring_config:
        logger.warning("No monitoring configurations found. Monitor will idle.")
        # Optionally, implement logic to periodically recheck config

    # Setup PRAW client with aiohttp session for connection pooling
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        reddit = asyncpraw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT,
            requestor_class=asyncprawcore.Requestor,
            requestor_kwargs={"session": session}
        )
        logger.info(f"Reddit client initialized for user agent: {REDDIT_USER_AGENT}")

        # Create and manage streaming tasks
        tasks = []
        for subreddit_name, config_for_sub in monitoring_config.items():
            if config_for_sub: # Only start if there's config for this sub
                task = asyncio.create_task(stream_subreddit(reddit, subreddit_name, config_for_sub, db_session_factory))
                tasks.append(task)
            else:
                logger.warning(f"Skipping subreddit {subreddit_name} as no configuration found.")

        if not tasks:
            logger.warning("No streaming tasks started based on current configuration.")
            # Consider adding a loop here to periodically check for new configurations
            # For now, it will exit if no tasks are started.

        # Wait for tasks or shutdown signal
        if tasks:
            logger.info(f"Monitoring {len(tasks)} subreddits...")
            done, pending = await asyncio.wait(
                tasks + [asyncio.create_task(shutdown_flag.wait())],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Handle completed tasks (check for errors)
            for task in done:
                if task.exception():
                    logger.error(f"Task finished with exception: {task.exception()}")
                elif not shutdown_flag.is_set():
                     logger.warning(f"A streaming task finished unexpectedly without error.") # May indicate stream ended naturally or was stopped by Reddit

            # Cancel pending tasks if shutdown was signaled
            if shutdown_flag.is_set():
                logger.info("Shutting down: Cancelling pending tasks...")
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True) # Wait for cancellations
        else:
             # Wait indefinitely if no tasks, or implement periodic config check
             await shutdown_flag.wait()

        await reddit.close()
        logger.info("Reddit client closed.")

    logger.info("Reddit Realtime Monitor stopped.")

# --- Signal Handling for Graceful Shutdown ---

def handle_shutdown_signal(sig, frame):
    logger.info(f"Received signal {sig}. Initiating graceful shutdown...")
    # Set the event which tasks can check
    asyncio.create_task(set_shutdown_flag()) # Schedule setting the flag in the event loop

async def set_shutdown_flag():
    shutdown_flag.set()

# --- Entry Point ---

if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown_signal)  # Handle Ctrl+C
    signal.signal(signal.SIGTERM, handle_shutdown_signal) # Handle termination signals

    try:
        asyncio.run(main())
    except asyncio.CancelledError:
        logger.info("Main task cancelled.")
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt caught, exiting.")
    finally:
        logger.info("Monitor script finished execution.")
