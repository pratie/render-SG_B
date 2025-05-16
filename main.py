# main.py
from fastapi import FastAPI, Depends, HTTPException, Body, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from datetime import datetime, timezone
import json
import psycopg2
import os
import anthropic
import logging
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
    allow_origins=["http://localhost:3000","https://vercel-f-tau.vercel.app","https://www.sneakyguy.com"],  # Add your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()
    logging.info("Database initialized")

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

# Initialize Reddit client
reddit_config = {
    "client_id": os.getenv("REDDIT_CLIENT_ID"),
    "client_secret": os.getenv("REDDIT_CLIENT_SECRET"),
    "user_agent": "apptest"
}

# Utility functions
async def verify_subreddit(subreddit_name: str) -> bool:
    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            reddit = asyncpraw.Reddit(
                **reddit_config,
                requestor_class=asyncprawcore.Requestor,
                requestor_kwargs={"session": session}
            )
            subreddit = await reddit.subreddit(subreddit_name)
            await subreddit.load()
            await reddit.close()
            return True
    except (prawcore.exceptions.Redirect, prawcore.exceptions.NotFound):
        return False

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
            return ["technology", "artificial", "news"]
            
        return verified_subreddits
        
    except anthropic.APIError as e:
        print(f"Anthropic API error: {str(e)}")
        if "overloaded" in str(e).lower():
            print("AI service is overloaded, using default subreddits")
        return ["technology", "artificial", "news"]
    except Exception as e:
        print(f"Error in get_subreddits: {str(e)}")
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

        prompt = f"""
You are creating a helpful, authentic Reddit comment that provides genuine value while subtly mentioning {brand_name} if appropriate at last. Your goal is to create a comment that gets upvoted because it's genuinely helpful.

<context>
Post Title: {post_title}
Post Content: {post_content}
Brand: {brand_name}
What They Do: {brand_description}
</context>
<reddit_comment_rules>
1. Write in a clear, respectful, and non-promotional tone:
   - Be helpful first, never salesy
   - Use concise, plain language with minimal jargon
   - Avoid overexplaining or “trying to sell” anything

2. Acknowledge the user’s post genuinely:
   - Recognize their question, challenge, or frustration
   - Share a quick insight, tip, or idea that could help

3. Mention the brand only if directly relevant:
   - Mention {brand_name} only when it clearly fits the context
   - Never say “I’ve found,” “I’ve been using,” or any “I’ve” phrases
   - Briefly state how it solves the problem or what it’s good at
   - Place the mention toward the end, subtly and casually
   - Sound like someone who’s seen it work, not a promoter

4. Authenticity is key:
   - Write like a knowledgeable person on Reddit, not a bot or ad
   - 1–2 short paragraphs max, with natural flow and some imperfection
   - No greetings or sign-offs
   - End with a confident, neutral tone — like “take it or leave it”

5. Avoid red flags:
   - No buzzwords, no excessive punctuation
   - No rigid structures or lists
   - No AI-sounding phrasing
   - No greetings like “hey,” “hi,” or “hello”
</reddit_comment_rules>
"""

        if user_prefs:
            # Add tone customization based on user preferences
            if user_prefs.tone == 'friendly':
                prompt += "\n<tone>friendly</tone>"
            elif user_prefs.tone == 'professional':
                prompt += "\n<tone>professional</tone>"
            elif user_prefs.tone == 'technical':
                prompt += "\n<tone>technical</tone>"
            
            # Add any custom response style from user preferences
            if user_prefs.response_style:
                prompt += f"\n<custom_style>{user_prefs.response_style}</custom_style>"

        prompt += "\nGenerate ONLY the Reddit comment text between <response> tags.\nThe comment should be 1-2 sentences."

# API call
        response = anthropic_client.messages.create(
    model="claude-3-haiku-20240307",
    max_tokens=254,
    temperature=0.99,
    messages=[{"role": "user", "content": prompt}]
)

        #print("SYSTEM:------------------------------------", system_message)
        print("\n")
        print("PROMPT:------------------------------------", prompt)
        
        logging.info("Received response from Anthropic API")
        
        # Handle empty responses
        if not response or not response.content or len(response.content) == 0:
            logging.error("Empty response from Anthropic API")
            return "Sorry, I couldn't generate a response at this time."
            
        # Extract the comment from response
        comment = response.content[0].text.strip()
        
        # Extract content between response tags if present
        if "<response>" in comment:
            comment = comment.split("<response>")[1].split("</response>")[0].strip()
        
        # Basic cleanup and formatting
        comment = comment.replace("Hey there, ", "").replace("Hi there, ", "").strip()
        comment = comment.replace("-", " ").replace(":", "").replace("  ", "").strip()
        comment = comment.replace("  ", " ").replace("  ", " ").replace("That's a great question!", "").replace("Hey there!", "")
        
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
        return "Sorry, I'm having trouble generating a response right now."
# def generate_relevance_score(post_title: str, post_content: str, brand_id: int, db: Session) -> int:
#     """Generate relevance score between post and brand"""
#     try:
#         brand = db.query(Brand).filter(Brand.id == brand_id).first()
#         if not brand:
#             raise ValueError(f"Brand with id {brand_id} not found")

#         system_message = """
#         You are an expert content analyzer specializing in determining relevance between social media posts and brand offerings. Your task is to analyze the similarity between a given post and a brand's offering, providing a relevance score from 20-100.

#         Scoring Guide:
#         - 90-100: Exceptional match (direct need-solution fit)
#         - 70-89: Strong match (clear alignment with some minor gaps)
#         - 50-69: Moderate match (partial alignment)
#         - 35-49: Basic match (some relevant elements)
#         - 20-34: Minimal match (few overlapping elements)

#         Your output must be in this exact format:
#         Relevance Score: [20-100]
#         Explanation: [2-3 sentences explaining the score]
#         """

#         prompt = f"""
#         Analyze the relevance between this post and brand:

#         Post Title: {post_title}
#         Post Content: {post_content}
#         Brand Name: {brand.name}
#         Brand Description: {brand.description}
#         """

#         response = anthropic_client.messages.create(
#             model="claude-3-haiku-20240307",
#             max_tokens=200,
#             temperature=0.5,
#             system=system_message,
#             messages=[
#                 {"role": "user", "content": prompt}
#             ]
#         )

#         response_text = response.content[0].text
        
#         # Extract just the score
#         score_line = response_text.split('\n')[0]
#         score = int(''.join(filter(str.isdigit, score_line)))
        
#         # Ensure score is within 20-100 range
#         return max(20, min(100, score))

#     except Exception as e:
#         logging.error(f"Error generating relevance score: {str(e)}")
#         # Return a default score in case of error
#         return 20

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
    Uses both API calls and database queries to provide comprehensive results.
    Requires authentication.
    """
    try:
        print("\n analysis_input>>>>:\n", analysis_input)
        # Verify brand ownership and get latest data
        brand = BrandCRUD.get_brand(db, analysis_input.brand_id, current_user_email)
        if not brand:
            raise HTTPException(status_code=404, detail="Brand not found or unauthorized access")
            
        # Refresh brand data to ensure we have the latest keywords and subreddits
        brand = db.query(Brand).filter(Brand.id == analysis_input.brand_id).first()
        if not brand:
            raise HTTPException(status_code=404, detail="Brand not found")
            
        # Parse the latest keywords and subreddits from the brand
        try:
            current_keywords = json.loads(brand.keywords)
            current_subreddits = json.loads(brand.subreddits)
            
            # Update the analysis input with latest data
            analysis_input.keywords = current_keywords
            analysis_input.subreddits = current_subreddits
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Invalid keywords or subreddits format in database")

        # Get results from database first (do this before clearing existing mentions)
        logging.info("Querying database for existing Reddit posts...")
        

        # Clear existing mentions for this brand before adding new ones
        try:
            db.query(RedditMention).filter(RedditMention.brand_id == brand.id).delete()
            db.commit()
            logging.info(f"Cleared existing mentions for brand {brand.id}")
        except Exception as e:
            db.rollback()
            logging.error(f"Error clearing existing mentions: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to clear existing mentions")

        # Initialize Reddit client with async support
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        
        # Initialize set to track processed URLs
        processed_urls = set()
        
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            reddit = asyncpraw.Reddit(
                **reddit_config,
                requestor_class=asyncprawcore.Requestor,
                requestor_kwargs={"session": session}
            )

            api_matching_posts = []
            for subreddit_name in analysis_input.subreddits:
                try:
                    # Clean up subreddit name by removing 'r/' prefix if present
                    clean_subreddit_name = subreddit_name.replace('r/', '')
                    
                    # Try to access the subreddit
                    try:
                        subreddit = await reddit.subreddit(clean_subreddit_name)
                        # Verify the subreddit exists by trying to access its properties
                        await subreddit.load()
                    except (asyncprawcore.exceptions.NotFound, asyncprawcore.exceptions.Redirect):
                        logging.error(f"Subreddit {clean_subreddit_name} not found")
                        continue
                    except asyncprawcore.exceptions.Forbidden:
                        logging.error(f"Access to subreddit {clean_subreddit_name} is forbidden")
                        continue
                    except Exception as e:
                        logging.error(f"Error accessing subreddit {clean_subreddit_name}: {str(e)}")
                        continue
                    
                    # Get posts from the subreddit based on time period
                    try:
                        # Default to month if time_period is not specified
                        time_period = "month"
                        limit = 1000
                        posts = subreddit.top(time_period, limit=limit)
                        # print("limit>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>:\n", limit)
                        # print("time_period>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>:\n", time_period)
                    except Exception as e:
                        logging.error(f"Error fetching posts from {clean_subreddit_name}: {str(e)}")
                        continue
                    
                    # Check each post for keyword matches
                    async for post in posts:
                        # Skip if we already have this post from database
                        post_url = ""
                        if post.permalink:
                            # Clean up the permalink to handle various formats
                            permalink = post.permalink.strip()
                            if permalink.startswith(('http://', 'https://')):
                                # Already a full URL, use as is
                                post_url = permalink
                            elif permalink.startswith('//'):
                                # Protocol-relative URL
                                post_url = f"https:{permalink}"
                            elif permalink.startswith('/'):
                                # Relative URL starting with slash
                                post_url = f"https://reddit.com{permalink}"
                            else:
                                # Relative URL without slash
                                post_url = f"https://reddit.com/{permalink}"
                        
                        # Ensure URL is properly formatted
                        if post_url and '//' in post_url:
                            # Fix any double slashes in the path portion (after the domain)
                            parts = post_url.split('//', 2)
                            if len(parts) > 2:
                                # There's a third // which is incorrect
                                post_url = f"{parts[0]}//{parts[1]}/{parts[2].replace('//', '/')}"
                        
                        if post_url in processed_urls:
                            continue
                        
                        post_text = f"{post.title} {post.selftext}".lower()
                        matching_keywords = [
                            keyword for keyword in analysis_input.keywords 
                            if keyword.lower() in post_text
                        ]
                        
                        if matching_keywords:
                            # Generate relevance score
                            #relevance_score = generate_relevance_score(post.title, post.selftext, brand.id, db)
                            relevance_score=50
                            suggested_comment = "This feature will be live soon! Stay tuned!😊"
                            # print("\n Post found in API:\n", post.title, post.created_utc, post_url)
                            # print("create date in readble format:", datetime.fromtimestamp(post.created_utc))
                            
                            post_data = {
                                "title": post.title,
                                "content": post.selftext[:10000],  # Limit content length
                                "url": post_url,
                                "subreddit": clean_subreddit_name,
                                "created_utc": int(post.created_utc),
                                "score": post.score,
                                "num_comments": post.num_comments,
                                "relevance_score": relevance_score,
                                "suggested_comment": suggested_comment,
                                "matched_keywords": matching_keywords,
                                "source": "api"  # Mark as coming from Reddit API
                            }
                            api_matching_posts.append(post_data)
                            processed_urls.add(post_url)  # Mark as processed

                            # Store the mention in the database
                            mention = RedditMention(
                                brand_id=brand.id,
                                title=post.title,
                                content=post.selftext[:10000],  # Limit content length
                                url=post_url,
                                subreddit=clean_subreddit_name,
                                keyword=matching_keywords[0],  # Primary matching keyword
                                matching_keywords_list=matching_keywords,  # All matching keywords
                                score=post.score,
                                num_comments=post.num_comments,
                                relevance_score=relevance_score,
                                suggested_comment=suggested_comment,
                                created_utc=int(post.created_utc)
                            )
                            try:
                                logging.info(f"Saving mention for brand {brand.id}: {post.title}")
                                RedditMentionCRUD.create_mention(db, mention)
                                logging.info(f"Successfully saved mention for brand {brand.id}")
                            except Exception as e:
                                logging.error(f"Error saving mention: {str(e)}")
                                continue

                except Exception as e:
                    logging.error(f"Error processing subreddit {subreddit_name}: {str(e)}")
                    continue

            # Close the Reddit client
            await reddit.close()
            
            
            # Combine results from both sources
            all_matching_posts =  api_matching_posts
            logging.info(f"Total posts found: {len(all_matching_posts)} ({len(api_matching_posts)} from API)")

         
            brand.last_analyzed = datetime.utcnow()
            db.commit()

            return AnalysisResponse(
                status="success",
                posts=all_matching_posts,
                matching_posts=all_matching_posts,
                statistics={
                    "total_posts": len(all_matching_posts),
                    "api_posts": len(api_matching_posts),
                }
            )

    except Exception as e:
        logging.error(f"Error analyzing Reddit content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
# Database connection function
def connect_to_db():
    """Connect to the PostgreSQL database with Reddit data."""
    try:
        conn = psycopg2.connect(
            host=os.getenv("PG_HOST"),
            port=os.getenv("PG_PORT"),
            dbname=os.getenv("PG_DBNAME"),
            user=os.getenv("PG_USER"),
            password=os.getenv("PG_PASSWORD")
        )
        return conn
    except Exception as e:
        logging.error(f"Error connecting to Reddit database: {e}")
        return None

# Updated keyword search function 
def search_keywords(keywords, subreddit=None, limit=20, offset=0, table='submissions'):
    """Search for posts containing any of the specified keywords."""
    conn = connect_to_db()
    if not conn:
        return []
        
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