# main.py
import logging
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Depends, HTTPException, Body, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from datetime import datetime, timezone
import json
import psycopg2
import os
import anthropic
from openai import OpenAI
from typing import List, Optional
import asyncio
import asyncpraw
import asyncprawcore
import prawcore
import praw
import re
from dotenv import load_dotenv
import time
from tenacity import retry, stop_after_attempt, wait_exponential
import certifi
import ssl
import aiohttp
import random
from fastapi.staticfiles import StaticFiles

import logging

from fastapi.responses import JSONResponse
from rate_limiter import limiter, rate_limit_exceeded_handler, get_analysis_rate_limit
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from database import get_db, init_db
from crud import UserCRUD, BrandCRUD, RedditMentionCRUD, RedditCommentCRUD
from models import (
    User, Brand, RedditMention, RedditComment, RedditToken, UserBase, UserCreate, UserResponse,
    BrandInput, BrandResponse, AnalysisInput, AnalysisResponse,
    KeywordResponse, RedditMentionResponse, CommentInput, CommentResponse,
    PostCommentInput, PostCommentResponse, PostSearchResult, UserPreferences, AlertSetting
)
from auth.router import router as auth_router, get_current_user
from auth.reddit_oauth import router as reddit_oauth_router, get_reddit_token
from routers.payment import router as payment_router
from routers.preferences import router as preferences_router
from routers.alerts import router as alerts_router

# Load environment variables
load_dotenv()

# Configure logging
#logging.basicConfig(level=logging.INFO)

# Detect if running on Render (Render sets specific environment variables)
IS_RENDER = os.getenv("RENDER") is not None or os.getenv("RENDER_SERVICE_NAME") is not None
IS_PRODUCTION = os.getenv("ENV") == "production" or IS_RENDER

logger.info(f"Running environment - ENV: {os.getenv('ENV')}, RENDER: {IS_RENDER}, PRODUCTION: {IS_PRODUCTION}")

# Initialize FastAPI app
app = FastAPI(
    title="Reddit Analysis API", 
    description="API for analyzing Reddit content based on brand/project keywords",
    version="1.0.0",
    openapi_tags=[
        {
            "name": "authentication",
            "description": "Operations with user authentication"
        },
        {
            "name": "analysis",
            "description": "Reddit content analysis operations"
        },
        {
            "name": "brands",
            "description": "Brand management operations"
        },
        {
            "name": "reddit",
            "description": "Reddit interaction operations"
        }
    ]
)

# Add security scheme for Swagger UI

# Add rate limiter middleware
# Add rate limiter to app
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://vercel-f-tau.vercel.app","https://www.sneakyguy.com","http://localhost:3000"],  # Production frontend URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup

@app.on_event("startup")
async def startup_event():
    init_db()
    logging.info("Database initialized") # Use your existing logger if preferred

@app.get(
    "/projects/", 
    response_model=List[BrandResponse],
    tags=["brands"],
    summary="Get all projects",
    description="Get all projects for the current user"
)
async def get_user_brands(
    skip: int = 0,
    limit: int = 80,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all brands/projects for the current user"""
    try:
        brands = BrandCRUD.get_user_brands(db, current_user_email, skip=skip, limit=limit)
        return [BrandResponse.from_orm(brand) for brand in brands]
    except Exception as e:
        logging.error(f"Error getting brands: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
# Include auth router
app.include_router(auth_router)
app.include_router(reddit_oauth_router)
app.include_router(payment_router)
app.include_router(preferences_router)
app.include_router(alerts_router)

# Initialize clients
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize Reddit client
reddit_config = {
    "client_id": os.getenv("REDDIT_CLIENT_ID"),
    "client_secret": os.getenv("REDDIT_CLIENT_SECRET"),
    "user_agent": "python:reddit-analysis-api:v1.0.0 (by /u/Overall-Poem-9764)"
}

# Utility functions
async def verify_subreddit(subreddit_name: str) -> bool:
    """Skip subreddit verification on production to avoid 403 errors"""
    if IS_PRODUCTION:
        # On production (Render), skip verification to avoid IP blocking
        logging.info(f"Production environment: Assuming subreddit r/{subreddit_name} is valid")
        return True
    
    try:
        # Use simple HTTP request to check subreddit existence (dev only)
        url = f"https://www.reddit.com/r/{subreddit_name}/about.json"
        headers = {
            'User-Agent': 'python:reddit-analysis-api:v1.0.0 (by /u/Overall-Poem-9764)',
            'Accept': 'application/json'
        }
        
        # Add delay to avoid rate limiting
        await asyncio.sleep(0.5)
        
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(url, headers=headers, allow_redirects=True) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Check if the subreddit data is valid
                        if 'data' in data and data['data'] and 'display_name' in data['data']:
                            logging.info(f"Verified subreddit r/{subreddit_name} exists")
                            return True
                    elif response.status == 403:
                        logging.warning(f"Subreddit r/{subreddit_name} may be private, treating as valid")
                        return True
                    elif response.status == 404:
                        logging.warning(f"Subreddit r/{subreddit_name} does not exist")
                        return False
                    else:
                        logging.warning(f"Unexpected response {response.status} for subreddit r/{subreddit_name}, treating as valid")
                        return True
            except asyncio.TimeoutError:
                logging.warning(f"Timeout verifying subreddit r/{subreddit_name}, assuming valid")
                return True
    except Exception as e:
        logging.error(f"Error verifying subreddit r/{subreddit_name}: {str(e)}")
        return True

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
def get_keywords(brand_name: str, description: str) -> list[str]:
    """Generate 5-10 relevant keywords for finding Reddit posts"""
    try:
        prompt = f"""Act as a senior SEO specialist and Reddit community analyst. Given a brand/project name: '{brand_name}' with description '{description}', 
suggest 10-15 relevant keywords for finding related discussions. Each keyword should consist of TWO WORDS ONLY (not longer phrases or single words).

Return only the keywords, one per line, without any additional text.
        
Avoid very generic keywords like 'ai technology', 'saas platform', etc.
NOTE: Please avoid "-" (hyphens) in keywords
"""
        
        response = anthropic_client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        
        keywords = [
            line.strip().lower() for line in response.content[0].text.split('\n')
            if line.strip()
        ]
        
        if not keywords:
            print("No keywords were suggested by AI, using default")
            return [brand_name.lower()]
            
        return keywords
        
    except anthropic.APIError as e:
        print(f"Anthropic API error in get_keywords: {str(e)}")
        return [brand_name.lower()]
    except Exception as e:
        print(f"Error in get_keywords: {str(e)}")
        return [brand_name.lower()]

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
async def get_subreddits(brand_name: str, description: str, keywords: list[str]) -> list[str]:
    """Generate and verify relevant subreddits"""
    try:
        prompt = f"""Given a brand/project named '{brand_name}' with description '{description}' 
        and keywords {keywords}, suggest 5-10 relevant subreddits where discussions about this 
        topic might occur. Only include the subreddit names without 'r/' prefix, one per line."""
        
        response = anthropic_client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        
        suggested_subreddits = [
            line.strip().lower() for line in response.content[0].text.split('\n')
            if line.strip() and not line.strip().startswith('r/')
        ]
        
        if not suggested_subreddits:
            print("No subreddits were suggested by AI, using default")
            if IS_PRODUCTION:
                return ["AskReddit", "todayilearned", "explainlikeimfive", "LifeProTips", "YouShouldKnow"]
            else:
                return ["technology", "artificial", "news"]
            
        # Verify each subreddit exists
        verified_subreddits = []
        for subreddit in suggested_subreddits:
            try:
                if await verify_subreddit(subreddit):
                    verified_subreddits.append(subreddit)
                else:
                    print(f"Subreddit '{subreddit}' does not exist or is not accessible")
            except Exception as e:
                print(f"Error verifying subreddit '{subreddit}': {str(e)}")
                continue
        
        if not verified_subreddits:
            print("No valid subreddits found, using default")
            # Environment-specific fallback subreddits
            if IS_PRODUCTION:
                # More general subreddits for production to avoid IP blocking
                return ["AskReddit", "todayilearned", "explainlikeimfive", "LifeProTips", "YouShouldKnow"] 
            else:
                # Original defaults for development
                return ["technology", "artificial", "news"]
            
        return verified_subreddits
        
    except anthropic.APIError as e:
        print(f"Anthropic API error: {str(e)}")
        if "overloaded" in str(e).lower():
            print("AI service is overloaded, using default subreddits")
        if IS_PRODUCTION:
            return ["AskReddit", "todayilearned", "explainlikeimfive", "LifeProTips", "YouShouldKnow"]
        else:
            return ["technology", "artificial", "news"]
    except Exception as e:
        print(f"Error in get_subreddits: {str(e)}")
        if IS_PRODUCTION:
            return ["AskReddit", "todayilearned", "explainlikeimfive", "LifeProTips", "YouShouldKnow"]
        else:
            return ["technology", "artificial", "news"]

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)


async def generate_custom_comment(
    post_title: str,
    post_content: str,
    brand_id: int,
    db: Session,
    user_email: str = None
) -> str:
    """Generate custom AI response with natural brand incorporation"""
    logging.info(f"Starting comment generation for brand_id: {brand_id}")
    logging.info(f"Post title: {post_title}")
    
    try:
        # Get brand information from database
        brand = db.query(Brand).filter(Brand.id == brand_id).first()
        if not brand:
            logging.error(f"Brand not found: {brand_id}")
            raise ValueError(f"Brand with id {brand_id} not found")
        
        brand_name = brand.name
        brand_description = brand.description
        
        logging.info(f"Found brand: {brand_name}")

        # Get user preferences if available
        user_prefs = None
        if user_email:
            user_prefs = db.query(UserPreferences).filter(
                UserPreferences.user_email == user_email
            ).first()

        # Define system message based on user preferences
#         system_message = """
# You are an expert Reddit user who knows how to engage with people in reddit discussions naturally and authentically.
# Your responses should be helpful, conversational, and never end with generic questions like "let me know if you have questions" or "hope this helps".
# """

        prompt = f"""You're browsing Reddit and see this post:

"{post_title}"
{post_content}

You know about {brand_name} ({brand_description}).

Write a short, natural comment. Keep it 1-2 sentences max. Be casual and direct. No dashes, no fancy punctuation, no long explanations, no corporate speak.

Only mention {brand_name} if it's genuinely relevant and fits naturally. Most of the time don't mention it at all. Just be helpful first. Sound like how people actually talk on Reddit."""

        if user_prefs:
            # Add tone customization based on user preferences
            if user_prefs.tone == 'friendly':
                prompt += "\n\nBe a bit more friendly and warm in your tone."
            elif user_prefs.tone == 'professional':
                prompt += "\n\nKeep it professional but still casual."
            elif user_prefs.tone == 'technical':
                prompt += "\n\nFeel free to get technical if it helps."
            
            # Add any custom response style from user preferences
            if user_prefs.response_style:
                prompt += f"\n\nAdditional style note: {user_prefs.response_style}"

        # Removed XML instructions for more natural output

        # Comment out Claude API call for testing
        # response = anthropic_client.messages.create(
        #     model="claude-3-haiku-20240307",
        #     max_tokens=254,
        #     temperature=0.99,
        #     messages=[{"role": "user", "content": prompt}]
        # )

        # GPT-4.1 API call
        response = openai_client.responses.create(
            model="gpt-4.1",
            input=prompt
        )

        print("\n")
        print("PROMPT:------------------------------------", prompt)
        
        logging.info("Received response from OpenAI GPT-4.1 API")
        
        # Handle empty responses
        if not response or not response.output_text:
            logging.error("Empty response from OpenAI API")
            return "Sorry, I couldn't generate a response at this time."
            
        # Extract the comment from response
        comment = response.output_text.strip()
        
        # Remove any structured tags that might leak through
        comment = comment.replace("<response>", "").replace("</response>", "").strip()
        
        # Remove AI tells and fix formatting
        comment = comment.replace("Hope this helps!", "").replace("Let me know if you have questions!", "")
        comment = comment.replace("I hope this helps", "").replace("Feel free to ask", "")
        
        # Remove all dashes and replace with natural alternatives
        comment = comment.replace("—", ". ").replace("–", ". ").replace(" - ", ". ")
        comment = comment.replace("-", " ")
        
        # Clean up extra spaces
        comment = re.sub(r'\s+', ' ', comment).strip()
        
        # Ensure proper capitalization of brand name
        if brand_name:
            comment = re.sub(
                rf'\b{re.escape(brand_name.lower())}\b',
                brand_name,
                comment,
                flags=re.IGNORECASE
            )
        
        logging.info(f"Generated comment: {comment}")
        logging.info(f"Comment length: {len(comment)}")
        
        return comment
        
    except Exception as e:
        logging.error(f"Error in generate_custom_comment: {str(e)}", exc_info=True)
        if "openai" in str(e).lower():
            return "Sorry, I'm having trouble with the AI service right now."
        return "Sorry, I'm having trouble generating a response right now."
def generate_relevance_score(post_title: str, post_content: str, brand_id: int, db: Session) -> int:
    """Generate relevance score between post and brand"""
    try:
        brand = db.query(Brand).filter(Brand.id == brand_id).first()
        if not brand:
            raise ValueError(f"Brand with id {brand_id} not found")

        system_message = """
        You are an expert Reddit post analyzer specializing in determining relevance between social media posts and brand offerings.
        Your task is to analyze the similarity between a given Reddit post and a brand’s offering.

        Return your answer strictly in this JSON format:
        {
          "relevance_score": [20-100],
          "explanation": "[2-3 sentence explanation of the score]",
          "intent": "[purchase_intent | solution_seeking | recommendation_request | comparison | complaint | feature_request | product_feedback | general_interest | unaware_prospect | other]"
        }

        Scoring Guide:
        - 90-100: Exceptional match (direct need-solution fit)
        - 70-89: Strong match (clear alignment with some minor gaps)
        - 50-69: Moderate match (partial alignment)
        - 35-49: Basic match (some relevant elements)
        - 20-34: Minimal match (few overlapping elements)

        Example Output:
        {
          "relevance_score": 85,
          "explanation": "The post discusses pain points that align closely with the brand's core offerings, suggesting strong potential interest. Minor mismatch in use case keeps it from scoring higher.",
          "intent": "solution_seeking"
        }
        """

        prompt = f"""
        Analyze the relevance between this Reddit post and the brand.

        Post Title: {post_title}
        Post Content: {post_content}

        Brand Name: {brand.name}
        Brand Description: {brand.description}
        """

        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=300,
            temperature=0.3,
            system=system_message,
            messages=[{"role": "user", "content": prompt}]
        )

        raw_output = response.content[0].text.strip()
        print("Raw Claude Output:", raw_output)

        try:
            parsed = json.loads(raw_output)
            score = parsed.get("relevance_score", 20)
            explanation = parsed.get("explanation", "")
            intent = parsed.get("intent", "other")
        except json.JSONDecodeError:
            print("Failed to parse Claude response as JSON.")
            return 20, "Failed to parse response", "other"

        score = max(20, min(100, int(score)))
        print(f"Post Title: {post_title}\nScore: {score}\nExplanation: {explanation}\nIntent: {intent}")
        return score, explanation, intent

    except Exception as e:
        print(f"Error generating relevance score: {e}")
        return 20, "Error during scoring", "other"
    except Exception as e:
        logging.error(f"Error generating relevance score: {str(e)}")
        # Return a default score in case of error
        return 20

@app.post("/analyze/initial", response_model=KeywordResponse, tags=["analysis"])
@get_analysis_rate_limit() 
async def get_initial_analysis(
    brand_input: BrandInput,
    request: Request,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get initial keywords and subreddits based on brand/project information.
    Requires authentication.
    """
    try:
        keywords = get_keywords(brand_input.name, brand_input.description)
        subreddits = await get_subreddits(brand_input.name, brand_input.description, keywords)
        
        return KeywordResponse(
            keywords=keywords,
            subreddits=subreddits
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from typing import Tuple, List, Dict

async def _perform_brand_reddit_analysis(brand_id: int, db: Session) -> Tuple[List[Dict], int, int]:
    """
    Core logic to analyze Reddit posts for a given brand.
    Fetches posts, matches keywords, saves/updates mentions, and updates brand timestamps.
    Returns a list of all mention data for the brand, new mentions count, and updated mentions count.
    """
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        logger.error(f"_perform_brand_reddit_analysis: Brand with ID {brand_id} not found.")
        return [], 0, 0 
            
    try:
        current_keywords = json.loads(brand.keywords)
        current_subreddits = json.loads(brand.subreddits)
    except json.JSONDecodeError:
        logger.error(f"_perform_brand_reddit_analysis: Invalid keywords or subreddits format for brand {brand_id}.")
        return [], 0, 0

    existing_mentions_db = {m.url: m for m in db.query(RedditMention).filter(RedditMention.brand_id == brand.id).all()}
    subreddit_last_analyzed = brand.subreddit_last_analyzed_dict
    
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    processed_urls_in_session = set()
    
    new_mentions_count = 0
    updated_mentions_count = 0
    
    # Get Reddit client credentials for OAuth
    reddit_client_id = os.getenv("REDDIT_CLIENT_ID")
    reddit_client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    
    if not reddit_client_id or not reddit_client_secret:
        logger.error("Reddit API credentials not found in environment variables")
        return [], 0, 0
    
    # Get app-only OAuth token for API access
    auth_data = {
        'grant_type': 'client_credentials'
    }
    
    auth_headers = {
        'User-Agent': 'python:reddit-analysis-api:v1.0.0 (by /u/Overall-Poem-9764)'
    }
    
    # Get OAuth token
    auth_response = None
    access_token = None
    
    try:
        import requests
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as auth_session:
            auth_url = 'https://www.reddit.com/api/v1/access_token'
            auth_response = requests.post(
                auth_url,
                auth=(reddit_client_id, reddit_client_secret),
                data=auth_data,
                headers=auth_headers,
                timeout=10
            )
            
            if auth_response.status_code == 200:
                token_data = auth_response.json()
                access_token = token_data.get('access_token')
                logger.info("Successfully obtained Reddit OAuth token")
            else:
                logger.error(f"Failed to get Reddit OAuth token: {auth_response.status_code} - {auth_response.text}")
                return [], 0, 0
    except Exception as e:
        logger.error(f"Error getting Reddit OAuth token: {str(e)}")
        return [], 0, 0
    
    if not access_token:
        logger.error("No access token obtained from Reddit")
        return [], 0, 0
    
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        headers = {
            'User-Agent': 'python:reddit-analysis-api:v1.0.0 (by /u/Overall-Poem-9764)',
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Connection': 'keep-alive'
        }

        for subreddit_name in current_subreddits:
            is_initial_scan_for_subreddit = False
            try:
                clean_subreddit_name = subreddit_name.replace('r/', '')
                last_analyzed_ts = subreddit_last_analyzed.get(clean_subreddit_name, 0)
                last_analyzed_str = datetime.utcfromtimestamp(last_analyzed_ts).strftime('%Y-%m-%d %H:%M:%S UTC') if last_analyzed_ts else 'Never'
                
                logger.info("\n=== Analyzing r/%s for Brand ID %s ===", clean_subreddit_name, brand_id)
                logger.info("Last analyzed: %s", last_analyzed_str)

                # Determine URL and parameters based on scan type
                if last_analyzed_ts == 0:
                    is_initial_scan_for_subreddit = True
                    effective_limit = 250
                    effective_time_period = "month"
                    logger.info(f"Performing initial scan for r/{clean_subreddit_name}. Time period: '{effective_time_period}', Limit: {effective_limit} posts")
                    url = f"https://oauth.reddit.com/r/{clean_subreddit_name}/top?limit={effective_limit}&t={effective_time_period}"
                else: 
                    is_initial_scan_for_subreddit = False
                    effective_limit = 300
                    logger.info(f"Fetching up to: {effective_limit} new posts for r/{clean_subreddit_name} since {last_analyzed_str}")
                    url = f"https://oauth.reddit.com/r/{clean_subreddit_name}/new?limit={effective_limit}"

                # Add delay between requests to avoid rate limiting (increased for production)
                delay = 3.0 if IS_PRODUCTION else 1.0
                await asyncio.sleep(delay)
                
                # Fetch posts from Reddit API
                try:
                    timeout = aiohttp.ClientTimeout(total=30)
                    async with session.get(url, headers=headers, timeout=timeout, allow_redirects=True) as response:
                        if response.status == 403:
                            logging.warning(f"Access denied to r/{clean_subreddit_name} (403) - may be private or IP blocked")
                            # Try with fallback default subreddits for this brand
                            continue
                        elif response.status == 429:
                            logging.warning(f"Rate limited on r/{clean_subreddit_name} - waiting longer")
                            backoff_delay = 10.0 if IS_PRODUCTION else 5.0
                            await asyncio.sleep(backoff_delay)
                            continue
                        elif response.status == 401:
                            logging.error(f"OAuth token invalid or expired for r/{clean_subreddit_name}")
                            continue
                        elif response.status != 200:
                            logging.error(f"Error fetching posts from r/{clean_subreddit_name}: HTTP {response.status}")
                            continue
                        
                        data = await response.json()
                        if 'data' not in data or 'children' not in data['data']:
                            logging.error(f"Invalid response format from r/{clean_subreddit_name}")
                            continue
                        
                        posts = data['data']['children']
                        logging.info(f"Fetched {len(posts)} posts from r/{clean_subreddit_name}")
                
                except asyncio.TimeoutError:
                    logging.error(f"Timeout fetching posts from r/{clean_subreddit_name}")
                    continue
                except Exception as e:
                    logging.error(f"Error fetching posts from r/{clean_subreddit_name}: {str(e)}")
                    continue
                
                processed_count_in_subreddit = 0
                for post_data in posts:
                    post = post_data['data']
                    processed_count_in_subreddit += 1
                    if not is_initial_scan_for_subreddit and post['created_utc'] <= last_analyzed_ts:
                        logger.info(f"Stopping at post older than last analysis for r/{clean_subreddit_name}: '{post['title']}'")
                        break

                    post_url = f"https://reddit.com{post['permalink']}"
                    if post_url in processed_urls_in_session:
                        continue
                    processed_urls_in_session.add(post_url)
                    
                    post_text = f"{post['title']} {post.get('selftext', '') or ''}".lower()
                    matching_keywords = [kw for kw in current_keywords if kw.lower() in post_text]
                    
                    if matching_keywords:
                        existing_mention_from_db = existing_mentions_db.get(post_url)
                        
                        # For existing posts, only update dynamic fields
                        if existing_mention_from_db:
                            changed = False
                            if existing_mention_from_db.num_comments != post['num_comments']:
                                existing_mention_from_db.num_comments = post['num_comments']
                                changed = True
                            if changed:
                                db.commit()
                                updated_mentions_count += 1
                            continue  # Skip to next post as we've updated what we needed
                            
                        # For new posts, calculate all fields including relevance score and intent
                        relevance_score, explanation_line, intent_line = generate_relevance_score(post['title'], post.get('selftext', '') or '', brand_id, db)
                        suggested_comment = explanation_line
                        intent = intent_line


                        # Create new mention
                        new_mention = RedditMention(
                            brand_id=brand.id,
                            title=post['title'],
                            content=post.get('selftext', '') or "",
                            url=post_url,
                            subreddit=clean_subreddit_name,
                            keyword=matching_keywords[0] if matching_keywords else "",
                            matching_keywords=json.dumps(matching_keywords),
                            score=post['score'],
                            num_comments=post['num_comments'],
                            relevance_score=relevance_score,
                            suggested_comment=suggested_comment,
                            intent=intent,
                            created_utc=int(post['created_utc'])
                        )
                        db.add(new_mention)
                        new_mentions_count += 1
                        logger.info(f"Added new mention for Brand ID {brand_id}, Post: {post['title'][:50]}... URL: {post_url}")
                
                if processed_count_in_subreddit > 0 or is_initial_scan_for_subreddit:
                    subreddit_last_analyzed[clean_subreddit_name] = int(datetime.utcnow().timestamp())
                logger.info(f"Finished r/{clean_subreddit_name} for Brand ID {brand_id}, processed {processed_count_in_subreddit} posts from API call.")

            except Exception as e:
                logging.error(f"Error processing subreddit {subreddit_name} for Brand ID {brand_id}: {str(e)}", exc_info=True)
                continue

        
        current_time_utc = datetime.utcnow()
        brand.subreddit_last_analyzed = json.dumps(subreddit_last_analyzed)
        brand.last_analyzed = current_time_utc
        db.commit()
        
        logger.info("\n=== Analysis Summary for Brand ID %s ===", brand_id)
        logger.info("Analysis completed at: %s", current_time_utc.strftime('%Y-%m-%d %H:%M:%S UTC'))
        logger.info("New mentions found: %s", new_mentions_count)
        logger.info("Existing mentions updated: %s", updated_mentions_count)
        logger.info("Subreddit analysis timestamps updated as follows:")
        for sub_name, ts in subreddit_last_analyzed.items():
            last_analyzed_dt = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S UTC')
            logger.info("  - r/%s: Last analysis timestamp set to %s", sub_name, last_analyzed_dt)
        logger.info("======================\n")

        all_mentions_from_db = db.query(RedditMention).filter(RedditMention.brand_id == brand.id).order_by(RedditMention.created_utc.desc()).all()
        
        comprehensive_mentions_list_for_response = []
        for mention_orm_object in all_mentions_from_db:
            mention_pydantic_object = RedditMentionResponse.from_orm(mention_orm_object)
            comprehensive_mentions_list_for_response.append(mention_pydantic_object.dict())

        return comprehensive_mentions_list_for_response, new_mentions_count, updated_mentions_count

@app.post("/analyze/reddit", response_model=AnalysisResponse, tags=["analysis"])
@get_analysis_rate_limit() 
async def analyze_reddit_content(
    analysis_input: AnalysisInput,
    request: Request,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Analyze Reddit posts based on approved keywords and subreddits.
    Uses incremental analysis: broader search for initial scan, .new() for updates.
    Requires authentication.
    Triggers core analysis logic and returns results.
    """
    try:
        brand_check = BrandCRUD.get_brand(db, analysis_input.brand_id, current_user_email)
        if not brand_check:
            raise HTTPException(status_code=404, detail="Brand not found or unauthorized access")

        comprehensive_mentions_list, new_mentions_found, updated_mentions_found = await _perform_brand_reddit_analysis(
            brand_id=analysis_input.brand_id, 
            db=db
        )
        
        logger.info(f"Endpoint analyze_reddit_content for Brand ID {analysis_input.brand_id} completed. "
                    f"New: {new_mentions_found}, Updated: {updated_mentions_found}.")

        return AnalysisResponse(
            status="success",
            posts=comprehensive_mentions_list,
            matching_posts=comprehensive_mentions_list
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Unexpected error in analyze_reddit_content endpoint for Brand ID {analysis_input.brand_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
        
    try:
        with conn.cursor() as cur:
            # Check if the table exists
            cur.execute(
                f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = '{table}')"
            )
            if not cur.fetchone()[0]:
                logging.error(f"Table '{table}' does not exist")
                return []
            
            # Determine which fields to search based on the table
            if table == 'submissions':
                search_fields = ['title', 'selftext']
                display_fields = [
                    'id', 'author', 'title', 'selftext', 'score', 
                    'created_utc', 'subreddit', 'num_comments', 'permalink'
                ]
            else:  # comments
                search_fields = ['body']
                display_fields = [
                    'id', 'author', 'body', 'score', 'created_utc', 'subreddit', 'link_id'
                ]
            
            # Handle keywords list properly
            if isinstance(keywords, str):
                keyword_list = [k.strip() for k in keywords.split(',')]
            elif isinstance(keywords, list):
                keyword_list = keywords
            else:
                keyword_list = list(keywords)
            
            # Build the WHERE clause to match any of the keywords
            keyword_conditions = []
            params = []
            for keyword in keyword_list:
                field_conditions = []
                for field in search_fields:
                    field_conditions.append(f"{field} ILIKE %s")
                    params.append(f"%{keyword}%")
                # Each keyword can match in any field
                keyword_conditions.append(f"({' OR '.join(field_conditions)})")
            
            # Join all keyword conditions with OR to capture any match
            where_clause = ' OR '.join(keyword_conditions)
            
            # Add subreddit filter if specified
            if subreddit:
                where_clause = f"({where_clause}) AND subreddit = %s"
                params.append(subreddit)
            
            sql_query = f"""
                SELECT {', '.join(display_fields)}
                FROM {table}
                WHERE {where_clause}
                ORDER BY score DESC
                LIMIT %s OFFSET %s
            """
            params.extend([limit, offset])
            
            logging.info(f"Executing SQL: {sql_query} with params: {params}")
            cur.execute(sql_query, params)
            results = cur.fetchall()
            logging.info(f"Found {len(results)} results from database")
            
            # Convert results to a list of dictionaries
            posts = []
            for result in results:
                post = {}
                for i, field in enumerate(display_fields):
                    post[field] = result[i]
                posts.append(post)
            
            return posts
    except Exception as e:
        logging.error(f"Error searching keywords: {e}")
        return []
    finally:
        conn.close()


@app.put(
    "/projects/{brand_id}", 
    response_model=BrandResponse,
    tags=["brands"],
    summary="Update a project",
    description="Update a project"
)
async def update_brand(
    brand_id: int,
    brand_input: BrandInput,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a brand/project"""
    brand = BrandCRUD.get_brand(db, brand_id, current_user_email)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    
    try:
        # Update the brand fields
        brand.name = brand_input.name
        brand.description = brand_input.description
        brand.keywords = json.dumps(brand_input.keywords) if hasattr(brand_input, 'keywords') else brand.keywords
        brand.subreddits = json.dumps(brand_input.subreddits) if hasattr(brand_input, 'subreddits') else brand.subreddits
        brand.updated_at = datetime.utcnow()
        
        # Save the changes
        db.commit()
        db.refresh(brand)
        
        return BrandResponse.from_orm(brand)
    except Exception as e:
        db.rollback()
        logging.error(f"Error updating brand: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post(
    "/projects/", 
    response_model=BrandResponse,
    tags=["brands"],
    summary="Create a new project",
    description="Create a new project for the current user"
)
async def create_brand(
    brand_input: BrandInput,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new brand/project"""
    try:
        # Get initial keywords and subreddits
        try:
            keywords = get_keywords(brand_input.name, brand_input.description)
        except Exception as e:
            logging.error(f"Error getting keywords: {str(e)}")
            keywords = [brand_input.name.lower()]
            
        try:
            subreddits = await get_subreddits(brand_input.name, brand_input.description, keywords)
        except Exception as e:
            logging.error(f"Error getting subreddits: {str(e)}")
            if IS_PRODUCTION:
                subreddits = ["AskReddit", "todayilearned", "explainlikeimfive", "LifeProTips", "YouShouldKnow"]
            else:
                subreddits = ["technology", "artificial", "news"]

        # Create brand with initial data
        brand_data = {
            "name": brand_input.name,
            "description": brand_input.description,
            "keywords": keywords,
            "subreddits": subreddits
        }
        
        brand = BrandCRUD.create_brand(
            db=db,
            brand_input=brand_data,
            user_email=current_user_email
        )
        
        return brand
    except Exception as e:
        logging.error(f"Error creating brand: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get(
    "/projects/", 
    response_model=List[BrandResponse],
    tags=["brands"],
    summary="Get all projects",
    description="Get all projects for the current user"
)
async def get_user_brands(
    skip: int = 0,
    limit: int = 50,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all brands/projects for the current user"""
    try:
        brands = BrandCRUD.get_user_brands(db, current_user_email, skip=skip, limit=limit)
        return [BrandResponse.from_orm(brand) for brand in brands]
    except Exception as e:
        logging.error(f"Error getting brands: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get(
    "/projects/{brand_id}", 
    response_model=BrandResponse,
    tags=["brands"],
    summary="Get a specific project",
    description="Get a specific project by ID"
)
async def get_brand(
    brand_id: int,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific brand/project"""
    brand = BrandCRUD.get_brand(db, brand_id, current_user_email)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found or unauthorized access")
    return brand

@app.delete(
    "/projects/{brand_id}",
    tags=["brands"],
    summary="Delete a project",
    description="Delete a project by ID"
)
async def delete_brand(
    brand_id: int,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a brand/project"""
    brand = BrandCRUD.get_brand(db, brand_id, current_user_email)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found or unauthorized access")
    BrandCRUD.delete_brand(db, brand_id)
    return {"message": "Project deleted successfully"}

@app.put(
    "/projects/{brand_id}/keywords",
    response_model=BrandResponse,
    tags=["brands"],
    summary="Update project keywords",
    description="Update keywords for a specific project"
)
async def update_brand_keywords(
    brand_id: int,
    keywords: List[str] = Body(..., embed=True),
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update keywords for a brand/project"""
    brand = BrandCRUD.get_brand(db, brand_id, current_user_email)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found or unauthorized access")
    return BrandCRUD.update_brand_keywords(db, brand_id, keywords)

@app.put(
    "/projects/{brand_id}/subreddits",
    response_model=BrandResponse,
    tags=["brands"],
    summary="Update project subreddits",
    description="Update subreddits for a specific project"
)
async def update_brand_subreddits(
    brand_id: int,
    subreddits: List[str] = Body(..., embed=True),
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update subreddits for a brand/project"""
    brand = BrandCRUD.get_brand(db, brand_id, current_user_email)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found or unauthorized access")
    return BrandCRUD.update_brand_subreddits(db, brand_id, subreddits)

@app.get(
    "/mentions/{brand_id}/",
    response_model=List[RedditMentionResponse],
    tags=["mentions"],
    summary="Get project mentions",
    description="Get all Reddit mentions for a project"
)
async def get_brand_mentions(
    brand_id: int,
    skip: int = 0,
    limit: int = 5000,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all Reddit mentions for a brand/project"""
    brand = BrandCRUD.get_brand(db, brand_id, current_user_email)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found or unauthorized access")
    
    try:
        mentions = RedditMentionCRUD.get_brand_mentions(db, brand_id, skip=skip, limit=limit)
        #logging.info(f"Retrieved mentions: {[vars(m) for m in mentions]}")
        
        # Convert each mention to a dict and validate required fields
        mention_dicts = []
        for mention in mentions:
            mention_dict = {
                "id": mention.id,
                "brand_id": mention.brand_id,
                "title": mention.title or "",
                "content": mention.content or "",
                "url": mention.url or "",
                "subreddit": mention.subreddit or "",
                "keyword": mention.keyword or "",
                "matching_keywords": json.loads(mention.matching_keywords) if mention.matching_keywords else [],
                "matched_keywords": json.loads(mention.matching_keywords) if mention.matching_keywords else [],
                "score": mention.score or 0,
                "num_comments": mention.num_comments or 0,
                "relevance_score": mention.relevance_score or 0,
                "intent": mention.intent or "",
                "suggested_comment": mention.suggested_comment or "",
                "created_at": mention.created_at or datetime.utcnow(),
                "created_utc": mention.created_utc or int(datetime.utcnow().timestamp()),
                "formatted_date": mention.created_at.strftime('%Y-%m-%d %H:%M:%S') if mention.created_at else datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }
            mention_dicts.append(mention_dict)
        
        #logging.info(f"Converted mentions: {mention_dicts}")
        return [RedditMentionResponse(**m) for m in mention_dicts]
    except Exception as e:
        logging.error(f"Error getting mentions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

class RedditCommentError(Exception):
    """Custom exception for Reddit comment errors"""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)

@app.post("/api/reddit/comment/", response_model=PostCommentResponse, tags=["reddit"])
async def post_reddit_comment(
    comment_input: PostCommentInput,
    request: Request,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Post a comment to Reddit.
    Requires authentication and proper Reddit API credentials.
    Rate limited to 5 comments per user per 24 hours.
    """
    logging.info(f"Starting comment posting request from user: {current_user_email}")

    print('post comment input*50', comment_input)
    
    try:
        # Check rate limit
        logging.info(f"Checking rate limit for user: {current_user_email}")
        comment_count = RedditCommentCRUD.get_user_comment_count_last_24h(db, current_user_email)
        logging.info(f"Current comment count for user {current_user_email}: {comment_count}/5")
        
        if comment_count >= 10:  
            logging.warning(f"Rate limit exceeded for user {current_user_email}. Count: {comment_count}")
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. You can only post 5 comments per 24 hours."
            )

        # Verify brand ownership
        logging.info(f"Verifying brand ownership for brand_id: {comment_input.brand_id}")
        brand = BrandCRUD.get_brand(db, comment_input.brand_id, current_user_email)
        if not brand:
            raise HTTPException(
                status_code=404,
                detail="Brand not found or unauthorized access"
            )
        
        # Extract post ID from URL
        match = re.search(r'comments/([a-z0-9]+)/', comment_input.post_url, re.I)
        if not match:
            raise HTTPException(
                status_code=400,
                detail="Invalid Reddit post URL"
            )
        
        post_id = match.group(1)
        
        # Check if we've already commented on this post
        existing_comment = db.query(RedditComment).filter(
            RedditComment.brand_id == comment_input.brand_id,
            RedditComment.post_id == post_id
        ).first()
        
        if existing_comment:
            return PostCommentResponse(
                comment=existing_comment.comment_text,
                comment_url=existing_comment.comment_url,
                status="already_exists"
            )

        # Get Reddit token
        token = await get_reddit_token(db, current_user_email)
        if not token:
            raise HTTPException(
                status_code=401,
                detail="Reddit authentication required. Please connect your Reddit account first."
            )

        # Generate AI comment
        # comment = await generate_custom_comment(
        #     post_title=comment_input.post_title,
        #     post_content=comment_input.post_content,
        #     brand_id=comment_input.brand_id,
        #     db=db,
        #     user_email=current_user_email
        # )
        # instead of generating comment we want to use the one that coming from the api call, we comment text option 
        comment = comment_input.comment_text

        # Run the Reddit operations in a thread pool
        def post_to_reddit():
            try:
                logging.info("Initializing Reddit client...")
                reddit_client_id = os.getenv("REDDIT_CLIENT_ID")
                reddit_client_secret = os.getenv("REDDIT_CLIENT_SECRET")
                reddit_user_agent = os.getenv("REDDIT_USER_AGENT", "python:reddit-analysis-api:v1.0.0 (by /u/snaplearn2earn)")

                # Initialize Reddit client with OAuth token
                reddit = praw.Reddit(
                    client_id=reddit_client_id,
                    client_secret=reddit_client_secret,
                    user_agent=reddit_user_agent,
                    refresh_token=token.refresh_token
                )

                # Verify authentication
                try:
                    logging.info("Verifying Reddit authentication...")
                    reddit_user = reddit.user.me()
                    logging.info(f"Reddit authentication successful as user: {reddit_user.name}")
                except Exception as auth_error:
                    logging.error(f"Reddit authentication verification failed: {str(auth_error)}")
                    raise

                logging.info(f"Fetching submission with ID: {post_id}")
                submission = reddit.submission(id=post_id)
                
                if not submission:
                    logging.error("Submission not found")
                    raise prawcore.exceptions.NotFound("Submission not found")
                
                if submission.title != comment_input.post_title:
                    logging.error(f"Title mismatch. Expected: {comment_input.post_title}, Got: {submission.title}")
                    raise ValueError("Reddit post title mismatch")
                
                logging.info("Posting comment to submission...")
                return submission.reply(comment)
                
            except prawcore.exceptions.OAuthException as oauth_error:
                logging.error(f"Reddit OAuth error: {str(oauth_error)}")
                raise
            except Exception as e:
                logging.error(f"Error in post_to_reddit: {str(e)}")
                raise

        try:
            loop = asyncio.get_event_loop()
            logging.info("Attempting to post comment to Reddit...")
            comment = await loop.run_in_executor(None, post_to_reddit)
            logging.info("Successfully posted comment to Reddit")
            
            # Save the comment to our database
            try:
                logging.info("Saving comment to database...")
                reddit_comment = RedditComment(
                    brand_id=comment_input.brand_id,
                    post_id=post_id,
                    post_url=comment_input.post_url,
                    comment_text=comment_input.comment_text,
                    comment_url=f"https://reddit.com{comment.permalink}"
                )
                db.add(reddit_comment)
                db.commit()
                logging.info("Successfully saved comment to database")
            except Exception as db_error:
                logging.error(f"Database error while saving comment: {str(db_error)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to save comment to database: {str(db_error)}"
                )

            return PostCommentResponse(
                comment=comment_input.comment_text,
                comment_url=f"https://reddit.com{comment.permalink}",
                status="success"
            )

        except prawcore.exceptions.Forbidden as e:
            logging.error(f"Reddit authentication error: {str(e)}")
            raise HTTPException(
                status_code=403,
                detail=f"Reddit authentication failed or insufficient permissions: {str(e)}"
            )
        except prawcore.exceptions.NotFound as e:
            logging.error(f"Reddit post not found error: {str(e)}")
            raise HTTPException(
                status_code=404,
                detail=f"Reddit post not found: {str(e)}"
            )
        except prawcore.exceptions.ServerError as e:
            logging.error(f"Reddit server error: {str(e)}")
            raise HTTPException(
                status_code=502,
                detail=f"Reddit server error: {str(e)}"
            )
        except prawcore.exceptions.TooLarge as e:
            logging.error(f"Comment too long error: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"Comment is too long for Reddit: {str(e)}"
            )
        except Exception as e:
            logging.error(f"Unexpected error while posting comment: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to post comment: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error in post_reddit_comment: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred"
        )

@app.post("/generate-comment/", response_model=CommentResponse, tags=["reddit"])
async def generate_comment_endpoint(
    comment_input: CommentInput,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """
    Generate a custom comment for a Reddit post.
    Requires authentication.
    """
    try:
        # Generate the comment
        comment = await generate_custom_comment(
            post_title=comment_input.post_title,
            post_content=comment_input.post_content,
            brand_id=comment_input.brand_id,
            db=db,
            user_email=current_user  # current_user is already the email string
        )
        
        return {"comment": comment}
    except Exception as e:
        logging.error(f"Error in generate_comment_endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get(
    "/explore/posts/",
    response_model=List[PostSearchResult],
    tags=["reddit"],
    summary="Explore Reddit Posts",
    description="Search and explore posts in the database with optimized full-text search capabilities."
)
async def explore_posts(
    query: str = Query(..., description="Search term for post titles"),
    subreddit: Optional[str] = Query(None, description="Filter by specific subreddit"),
    limit: int = Query(500, ge=1, le=500, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """
    Explores Reddit submissions using optimized search:
    - Uses full-text search when available for multi-word queries
    - Falls back to ILIKE for simple searches
    - Can filter by subreddit
    - Returns paginated results sorted by score
    """
    conn = connect_to_db()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    try:
        with conn.cursor() as cur:
            # Check if the table exists
            cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'submissions')")
            if not cur.fetchone()[0]:
                raise HTTPException(status_code=404, detail="Submissions table does not exist")
            
            # Check if we have full text search index
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_indexes 
                    WHERE tablename = 'submissions'
                    AND indexdef LIKE '%to_tsvector%title%'
                )
            """)
            has_fts = cur.fetchone()[0]
            
            # Define display fields
            display_fields = ['id', 'author', 'title', 'score', 'created_utc', 'subreddit', 'num_comments', 'permalink']
            
            # Build the WHERE clause
            where_clauses = []
            params = []
            
            # Use full text search if available, otherwise use ILIKE
            if has_fts and ' ' in query.strip():
                # Convert query to tsquery format (replace spaces with & for AND search)
                ts_query = ' & '.join(query.split())
                where_clauses.append("to_tsvector('english', title) @@ to_tsquery('english', %s)")
                params.append(ts_query)
            else:
                # Fall back to ILIKE for simple searches
                where_clauses.append("title ILIKE %s")
                params.append(f"%{query}%")
            
            # Add subreddit filter if specified
            if subreddit:
                where_clauses.append("subreddit = %s")
                params.append(subreddit)
            
            # Build the final query
            sql_query = f"""
                SELECT {', '.join(display_fields)}
                FROM submissions
                WHERE {' AND '.join(where_clauses)}
                ORDER BY score DESC
                LIMIT %s OFFSET %s
            """
            params.extend([limit, offset])
            
            cur.execute(sql_query, params)
            results = cur.fetchall()
            
            # Convert to list of dicts and handle datetime conversion
            posts = []
            for result in results:
                post = {}
                for i, field in enumerate(display_fields):
                    value = result[i]
                    # Convert created_utc from Unix timestamp to datetime
                    if field == 'created_utc' and isinstance(value, (int, float)):
                        value = datetime.fromtimestamp(value)
                    post[field] = value
                posts.append(post)
            
            return posts

    except Exception as e:
        logging.error(f"Error in /explore/posts/ endpoint: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during post exploration"
        )
    finally:
        conn.close()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "10000"))  # Use PORT from env or default to 10000 for Render
    uvicorn.run(app, host="0.0.0.0", port=port)