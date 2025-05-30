import os
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
import asyncio

import resend
from dotenv import load_dotenv
from sqlalchemy.orm import Session

import asyncpraw
import asyncprawcore
import aiohttp
import ssl
import certifi
import json # Added for keyword/subreddit parsing

from models import User, Brand, RedditMention, AlertSetting
from crud import UserCRUD, BrandCRUD, RedditMentionCRUD, AlertSettingCRUD
from database import get_db, init_db 

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "noreply@sneakyguy.com")

# Reddit client configuration (similar to main.py but should be managed carefully if main.py also runs PRAW)
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "digest_service_agent/1.0")

reddit_config = {
    "client_id": REDDIT_CLIENT_ID,
    "client_secret": REDDIT_CLIENT_SECRET,
    "user_agent": REDDIT_USER_AGENT
}

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY
else:
    logger.error("RESEND_API_KEY not found in .env. Email sending will FAIL.")

BRANDS_ANALYZED_THIS_RUN = set()

async def analyze_brand_for_digest_update(db: Session, brand: Brand, reddit_client: asyncpraw.Reddit):
    """Conditionally analyze a brand's subreddits if needed, updating mentions for digest."""
    # Skip if already analyzed in this run
    if brand.id in BRANDS_ANALYZED_THIS_RUN:
        logger.info(f"Brand ID {brand.id} already analyzed in this run, skipping")
        return
        
    logger.info(f"Starting conditional analysis for Brand ID {brand.id} ('{brand.name}') for digest update.")
    BRANDS_ANALYZED_THIS_RUN.add(brand.id)
    try:
        current_keywords = brand.keywords_list
        current_subreddits = brand.subreddits_list
    except json.JSONDecodeError:
        logger.error(f"analyze_brand_for_digest_update: Invalid keywords/subreddits for brand {brand.id}.")
        return

    if not current_keywords or not current_subreddits:
        logger.info(f"Brand ID {brand.id} has no keywords or subreddits defined. Skipping analysis.")
        # Update last_analyzed_at even if skipped, to prevent constant re-checks if config is empty
        brand.last_analyzed = datetime.now(timezone.utc)
        db.commit()
        return

    # Get existing mentions and create lookup by URL
    existing_mentions_db = {m.url: m for m in db.query(RedditMention).filter(RedditMention.brand_id == brand.id).all()}
    subreddit_last_analyzed_for_brand = brand.subreddit_last_analyzed_dict
    
    # Track mentions we've seen in this analysis run
    processed_urls_in_session = set()
    processed_titles_in_session = set()  # Also track by title to catch reposts
    new_mentions_this_run = 0
    updated_mentions_this_run = 0

    # Define the time window for this analysis: last 24 hours
    analysis_since_datetime = datetime.now(timezone.utc) - timedelta(hours=24)

    for subreddit_name in current_subreddits:
        clean_subreddit_name = subreddit_name.replace('r/', '').lower() # Also lowercase for consistency
        # Skip if already scanned in this run
        scan_key = f"{brand.id}:{clean_subreddit_name}" # Use clean_subreddit_name for the key
        if scan_key in SUBREDDITS_SCANNED_THIS_RUN:
            logger.info(f"Subreddit r/{clean_subreddit_name} already scanned for Brand ID {brand.id} in this run, skipping")
            continue
        
        # Add a delay before processing a new subreddit to respect Reddit API rate limits
        await asyncio.sleep(REDDIT_API_CALL_DELAY)
            
        logger.info(f"Analyzing r/{clean_subreddit_name} for Brand ID {brand.id} (last 24 hours).")
        SUBREDDITS_SCANNED_THIS_RUN.add(scan_key)
        try:
            subreddit_obj = await reddit_client.subreddit(clean_subreddit_name)
            
            # Fetch new posts
            async for post in subreddit_obj.new(limit=100): # Limit to avoid excessive calls
                if post.created_utc < analysis_since_datetime.timestamp():
                    break # Stop if posts are older than our 24-hour window
                    
                # Skip if we've seen this URL or title before
                if post.url in processed_urls_in_session or post.title in processed_titles_in_session:
                    continue
                    
                processed_urls_in_session.add(post.url)
                processed_titles_in_session.add(post.title)
                max_post_timestamp_in_subreddit = max(max_post_timestamp_in_subreddit, int(post.created_utc))

                post_text = f"{post.title} {post.selftext if post.selftext else ''}".lower()
                matching_keywords_found = [kw for kw in current_keywords if kw.lower() in post_text]

                if matching_keywords_found:
                    # Check for existing mention and update if needed
                    existing_mention = existing_mentions_db.get(post.url)
                    if existing_mention:
                        # Only update if score has changed
                        if existing_mention.score != post.score:
                            existing_mention.score = post.score
                            existing_mention.num_comments = post.num_comments  # Update comments too
                            logger.info(f"Updating existing mention: {post.title} for Brand ID {brand.id} (Score: {post.score})")
                            updated_mentions_this_run += 1
                            db.commit()  # Commit the update
                    else:
                        logger.info(f"Found new mention: {post.title} for Brand ID {brand.id} (Score: {post.score})")
                        new_mention = RedditMention(
                            brand_id=brand.id,
                            url=post.url,
                            title=post.title,
                            content=post.selftext or "",
                            subreddit=clean_subreddit_name,
                            score=post.score,
                            num_comments=post.num_comments,
                            created_at=datetime.fromtimestamp(post.created_utc, timezone.utc),
                            keyword=json.dumps(matching_keywords_found),
                            relevance_score=50  # Default score
                        )
                        db.add(new_mention)
                        existing_mentions_db[post.url] = new_mention  # Add to cache
                        new_mentions_this_run += 1
                        db.commit()  # Commit each new mention
            
            # Fetch top posts from last 24 hours
            async for post in subreddit_obj.top(time_filter='day', limit=200): # 'day' is last 24h
                if post.url in processed_urls_in_session: # Already processed by .new() or earlier .top()
                    continue
                processed_urls_in_session.add(post.url)
                max_post_timestamp_in_subreddit = max(max_post_timestamp_in_subreddit, int(post.created_utc))
                
                post_text = f"{post.title} {post.selftext if post.selftext else ''}".lower()
                matching_keywords_found = [kw for kw in current_keywords if kw.lower() in post_text]

                if matching_keywords_found:
                    existing_mention = existing_mentions_db.get(post.url)
                    if existing_mention:
                        changed = False
                        if existing_mention.score != post.score: existing_mention.score = post.score; changed = True
                        if changed:
                            logger.info(f"Updating existing mention (top posts scan): {post.title} for Brand ID {brand.id}")
                            updated_mentions_this_run += 1
                    else:
                        logger.info(f"Found new mention (top posts scan): {post.title} for Brand ID {brand.id}")
                        new_mention = RedditMention(
                            brand_id=brand.id, url=post.url, title=post.title, content=post.selftext or "",
                            subreddit=clean_subreddit_name, score=post.score, num_comments=post.num_comments,
                            created_at=datetime.fromtimestamp(post.created_utc, timezone.utc),
                            keyword=json.dumps(matching_keywords_found), relevance_score=50
                        )
                        db.add(new_mention)
                        existing_mentions_db[post.url] = new_mention
                        new_mentions_this_run += 1
            subreddit_last_analyzed_for_brand[clean_subreddit_name] = max_post_timestamp_in_subreddit

        except Exception as e:
            logger.error(f"Error analyzing r/{clean_subreddit_name} for Brand ID {brand.id}: {e}", exc_info=True)

    brand.last_analyzed = datetime.now(timezone.utc)
    brand.subreddit_last_analyzed_dict = subreddit_last_analyzed_for_brand # Uses the setter
    db.commit()
    logger.info(f"Conditional analysis finished for Brand ID {brand.id}. New: {new_mentions_this_run}, Updated: {updated_mentions_this_run}.")

def generate_digest_html_content(user: User, brands_with_mentions: Dict[Brand, List[RedditMention]], days: int) -> str:
    user_email_name = user.email.split('@')[0]
    current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    # Basic CSS for overall email body (optional, some clients might strip it)
    # More robust styling is done inline below
    html_parts = [
        "<html><body style='font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f4f4f4;'>",
        f"<div style='max-width: 700px; margin: auto; background-color: #ffffff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1);'>",
        f"<h1 style='color: #333;'>Hi {user_email_name},</h1>",
        f"<p style='color: #555;'>Here's your Reddit digest for mentions in the last {days} day(s) (as of {current_date}):</p>"
    ]

    if not brands_with_mentions or all(not mentions for mentions in brands_with_mentions.values()):
        html_parts.append(f"""
            <div style='color: #555; padding: 15px; background-color: #eef; border-radius: 4px; margin-bottom: 15px;'>
                <p style='margin: 0 0 10px 0;'>No new mentions found for your tracked brands in the last {days} day(s).</p>
                <p style='margin: 0; font-size: 0.95em;'>💡 <strong>Tip:</strong> To improve results, you can:</p>
                <ul style='margin: 5px 0 0 0;'>
                    <li>Update your keywords to cast a wider net</li>
                    <li>Add more relevant subreddits</li>
                    <li>Delete the project and create a new one with different project description</li>
                </ul>
            </div>
        """)
    else:
        for brand, mentions in brands_with_mentions.items():
            html_parts.append(f"<h2 style='color: #444; border-bottom: 2px solid #eee; padding-bottom: 5px;'>Brand: {brand.name}</h2>")
            if not mentions:
                html_parts.append(f"<p style='color: #555; font-style: italic;'>No new mentions in the last {days} day(s) for this brand.</p>")
                continue
            
            html_parts.append("<ul style='list-style-type: none; padding-left: 0;'>")
            for mention in mentions:
                mention_time_str = 'N/A'
                if hasattr(mention, 'created_at') and mention.created_at:
                     mention_time_str = mention.created_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
                
                title = getattr(mention, 'title', 'N/A')
                url = getattr(mention, 'url', '#')
                subreddit = getattr(mention, 'subreddit', 'N/A')
                score = getattr(mention, 'score', 0)
                keyword = getattr(mention, 'keyword', 'N/A')

                html_parts.append(
                    f"""
                    <li style="margin-bottom: 20px; padding: 15px; border: 1px solid #ddd; border-radius: 8px; background-color: #f9f9f9; box-shadow: 2px 2px 5px rgba(0,0,0,0.05);">
                        <h4 style="margin-top: 0; margin-bottom: 8px;">
                            <a href='{url}' style="text-decoration: none; color: #0066cc; font-size: 1.1em; font-weight: bold;">{title}</a>
                        </h4>
                        <p style="margin: 5px 0; font-size: 0.95em; color: #333;">
                            <strong>Subreddit:</strong> r/{subreddit} &nbsp;|&nbsp; 
                            <strong>Score:</strong> {score} &nbsp;|&nbsp; 
                            <strong>Matched on:</strong> <em style="color: #555;">{keyword}</em>
                        </p>
                        <p style="margin: 5px 0; font-size: 0.85em; color: #777;">
                            Posted at: {mention_time_str}
                        </p>
                    </li>
                    """
                )
            html_parts.append("</ul>")

    html_parts.append("<hr style='border: 0; border-top: 1px solid #eee; margin: 20px 0;'>")
    html_parts.append("<p style='font-size: 0.9em; color: #777;'><small>To manage your alert preferences, please visit <a href='https://www.sneakyguy.com/' style='color: #0066cc; text-decoration: none;'>your dashboard</a>.</small></p>")
    html_parts.append("<p style='font-size: 0.9em; color: #777;'><small>Need help? Connect with us on <a href='https://x.com/snow_stark17' style='color: #0066cc; text-decoration: none;'>X (Twitter)</a>.</small></p>")
    html_parts.append(f"<p style='font-size: 0.9em; color: #777;'><small>SneakyGuy SaaS - {current_date}</small></p>")
    html_parts.append("</div></body></html>")

    return "".join(html_parts)

async def send_digest_email_async(recipient_email: str, html_content: str, subject_date: str) -> bool:
    if not RESEND_API_KEY or not RESEND_FROM_EMAIL:
        logger.error("Resend API Key or From Email not configured. Cannot send email.")
        return False

    params = {
        "from": f"SneakyGuy Digest <{RESEND_FROM_EMAIL}>",
        "to": [recipient_email],
        "subject": f"Your SneakyGuy Reddit Digest - {subject_date}",
        "html": html_content
    }
    try:
        loop = asyncio.get_event_loop()
        email_response = await loop.run_in_executor(None, resend.Emails.send, params)
        
        if email_response and email_response.get("id"):
            logger.info(f"Digest email sent successfully to {recipient_email}. Email ID: {email_response['id']}")
            return True
        else:
            logger.error(f"Failed to send digest email to {recipient_email}. Response: {email_response}")
            return False
    except Exception as e:
        logger.error(f"Error sending digest email to {recipient_email}: {e}", exc_info=True)
        return False


from asyncio import sleep

# Delay between Reddit API calls to a new subreddit to avoid rate limits
REDDIT_API_CALL_DELAY = 1.0  # seconds

# Track emails sent in this run to prevent duplicates
EMAILS_SENT_THIS_RUN = set()

# Track brands analyzed in this run
BRANDS_ANALYZED_THIS_RUN = set()

# Track subreddits scanned in this run
SUBREDDITS_SCANNED_THIS_RUN = set()

# Lock to prevent concurrent runs
digest_job_lock = asyncio.Lock()

# Rate limit for email sending (2 per second as per Resend limits)
EMAIL_RATE_LIMIT = 0.5  # 500ms between emails

async def run_daily_digest_job():
    """Fetches users opted in for daily digests, conditionally analyzes brands, and sends emails."""
    if digest_job_lock.locked():
        logger.info("Daily digest job already running, skipping this run")
        return
        
    async with digest_job_lock:
        logger.info("Starting daily digest job...")
        
        # Clear tracking sets for the new run
        EMAILS_SENT_THIS_RUN.clear()
        BRANDS_ANALYZED_THIS_RUN.clear()
        SUBREDDITS_SCANNED_THIS_RUN.clear()
        
        db_gen = get_db()
        db: Session = next(db_gen)
    
    reddit_client = None
    aiohttp_session = None
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        logger.error("Reddit API credentials not configured. Cannot perform conditional analysis.")
    else:
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            aiohttp_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context))
            reddit_client = asyncpraw.Reddit(
                **reddit_config,
                requestor_class=asyncprawcore.Requestor,
                requestor_kwargs={"session": aiohttp_session}
            )
            logger.info("Async PRAW Reddit client initialized for conditional analysis.")
        except Exception as e:
            logger.error(f"Failed to initialize PRAW Reddit client: {e}", exc_info=True)
            reddit_client = None # Ensure it's None if init fails
            if aiohttp_session:
                await aiohttp_session.close()
                aiohttp_session = None
    try:
        users_for_digest = AlertSettingCRUD.get_users_for_daily_digest(db)
        if not users_for_digest:
            logger.info("No users opted in for daily digests today.")
            return

        logger.info(f"Found {len(users_for_digest)} users for daily digest.")

        if not users_for_digest:
            logger.info("No users found for daily digest.")
            db.close()
            return
        
        days_to_check = 1 # For the actual daily job, check last 1 day
        since_datetime = datetime.now(timezone.utc) - timedelta(days=days_to_check)
        current_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        for user in users_for_digest:
            # Skip users who already received digests in this run
            if user.email in EMAILS_SENT_THIS_RUN:
                logger.info(f"Skipping {user.email} - already received digest in this run")
                continue
            
            # Add to emails sent this run
            EMAILS_SENT_THIS_RUN.add(user.email)
                
            logger.info(f"Processing digest for user: {user.email}")
            user_brands = BrandCRUD.get_user_brands(db, user_email=user.email)
            
            if not user_brands:
                logger.info(f"User {user.email} has no brands. Sending a 'no brands' digest.")
                html_content_no_brands = generate_digest_html_content(user, {}, days_to_check)
                await send_digest_email_async(user.email, html_content_no_brands, current_date_str)
                continue

            # Conditional analysis for each brand
            if reddit_client:
                for brand_obj in user_brands:
                    # Ensure brand_obj.last_analyzed is timezone-aware (UTC) or handle naive datetimes
                    # Assuming last_analyzed is stored as UTC naive from datetime.utcnow
                    last_analyzed_utc_naive = brand_obj.last_analyzed
                    needs_analysis = True # Default to true if never analyzed
                    if last_analyzed_utc_naive:
                        # Make it offset-aware for comparison
                        last_analyzed_utc_aware = last_analyzed_utc_naive.replace(tzinfo=timezone.utc)
                        if datetime.now(timezone.utc) - last_analyzed_utc_aware < timedelta(hours=12):
                            needs_analysis = False
                    
                    if needs_analysis:
                        logger.info(f"Brand ID {brand_obj.id} ('{brand_obj.name}') needs analysis (last analyzed over 12 hours ago or never).")
                        try:
                            await analyze_brand_for_digest_update(brand_obj, db, reddit_client)
                        except Exception as e:
                            logger.error(f"Error during conditional analysis for brand {brand_obj.id}: {e}", exc_info=True)
                    else:
                        logger.info(f"Brand ID {brand_obj.id} ('{brand_obj.name}') analyzed recently. Skipping conditional analysis.")
            else:
                logger.warning("Reddit client not available. Skipping conditional analysis for all brands.")

            # Fetch mentions for email (this part remains, using days_to_check for email content window)
            brand_ids = [brand.id for brand in user_brands]
            # Re-fetch user_brands in case analysis added new ones (though unlikely for this flow)
            # Or simply use the existing brand_ids for fetching mentions for the email
            recent_mentions = RedditMentionCRUD.get_recent_mentions_for_user_brands(db, brand_ids, since_datetime)
            
            brands_with_mentions: Dict[Brand, List[RedditMention]] = {brand: [] for brand in user_brands}
            for mention_obj in recent_mentions: # Renamed 'mention' to 'mention_obj' to avoid conflict
                # Find the brand object in user_brands that matches mention_obj.brand_id
                # This is safer than relying on the order or assuming brand_obj is still the same instance
                # if the list was somehow modified (though it's not in this specific code path)
                matching_brand_for_mention = next((b for b in user_brands if b.id == mention_obj.brand_id), None)
                if matching_brand_for_mention:
                    brands_with_mentions[matching_brand_for_mention].append(mention_obj)

            
            if not any(mentions for mentions in brands_with_mentions.values()):
                logger.info(f"No new mentions for {user.email} in the last {days_to_check} day(s). Sending 'no new mentions' digest.")
            
            html_content = generate_digest_html_content(user, brands_with_mentions, days_to_check)
            await send_digest_email_async(user.email, html_content, current_date_str)
            logger.info(f"Digest email sent to {user.email}")
            await asyncio.sleep(4.5) # 2 second delay to stay well under Resend's rate limit of 100 emails/minute

    except Exception as e:
        logger.error(f"Error in daily digest job: {e}", exc_info=True)
    finally:
        if reddit_client and hasattr(reddit_client, '_core') and hasattr(reddit_client._core, '_event_loop') and reddit_client._core._event_loop is not None:
             # Attempt graceful PRAW client shutdown only if it seems initialized
            try:
                if hasattr(reddit_client, 'close') and asyncio.iscoroutinefunction(reddit_client.close):
                    await reddit_client.close()
                    logger.info("Async PRAW Reddit client closed.")
            except Exception as e:
                logger.error(f"Error closing PRAW client: {e}", exc_info=True)
        if aiohttp_session and not aiohttp_session.closed:
            await aiohttp_session.close()
            logger.info("Aiohttp session closed.")
        db.close()
        logger.info("Daily digest job finished.")

async def run_manual_test_digest_for_user(db: Session, user_email: str, days_to_check: int):
    if not RESEND_API_KEY:
        logger.error("Cannot run test digest: RESEND_API_KEY is not set.")
        return
    logger.info(f"Starting manual test digest for user: {user_email} for the last {days_to_check} days.")
    user = UserCRUD.get_user_by_email(db, user_email)
    if not user:
        logger.error(f"Test user {user_email} not found.")
        return

    user_brands = BrandCRUD.get_user_brands(db, user_email=user.email)
    if not user_brands:
        logger.info(f"User {user_email} has no brands. Sending 'no brands' digest for test.")
        html_content_no_brands = generate_digest_html_content(user, {}, days_to_check)
        await send_digest_email_async(user.email, html_content_no_brands, datetime.now(timezone.utc).strftime('%Y-%m-%d'))
        return

    brand_ids = [brand.id for brand in user_brands]
    since_datetime = datetime.now(timezone.utc) - timedelta(days=days_to_check)
    recent_mentions = RedditMentionCRUD.get_recent_mentions_for_user_brands(db, brand_ids, since_datetime)
    
    brands_with_mentions: Dict[Brand, List[RedditMention]] = {brand: [] for brand in user_brands}
    for mention in recent_mentions:
        for brand in user_brands:
            if mention.brand_id == brand.id:
                brands_with_mentions[brand].append(mention)
                break
    
    html_content = generate_digest_html_content(user, brands_with_mentions, days_to_check)
    logger.info(f"Generated HTML for {user_email}. Attempting to send test email...")
    await send_digest_email_async(user.email, html_content, datetime.now(timezone.utc).strftime('%Y-%m-%d'))

if __name__ == "__main__":
    logger.info(f"Running {__file__} standalone to execute run_daily_digest_job().")
    try:
        asyncio.run(run_daily_digest_job())
        logger.info("Daily digest job completed successfully.")
    except Exception as e:
        logger.error(f"Error during standalone execution: {e}", exc_info=True)
