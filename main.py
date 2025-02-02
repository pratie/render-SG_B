# main.py
from fastapi import FastAPI, Depends, HTTPException, Body,Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import json
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

from fastapi.responses import JSONResponse
from rate_limiter import limiter, rate_limit_exceeded_handler, get_analysis_rate_limit
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from database import get_db, init_db
from crud import UserCRUD, BrandCRUD, RedditMentionCRUD
from models import (
    User, Brand, RedditMention, UserBase, UserCreate, UserResponse,
    BrandInput, BrandResponse, AnalysisInput, AnalysisResponse,
    KeywordResponse, RedditMentionResponse, CommentInput, CommentResponse
)
from auth.router import router as auth_router, get_current_user
from routers.payment import router as payment_router

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)

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
# Include auth router
app.include_router(auth_router)
app.include_router(payment_router)

# Initialize clients
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Initialize Reddit client
reddit_config = {
    "client_id": os.getenv("REDDIT_CLIENT_ID"),
    "client_secret": os.getenv("REDDIT_CLIENT_SECRET"),
    "user_agent": "RedditAnalyzer/1.0"
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
        prompt = f"""Act as a senior SEO specialist and Reddit community analyst. Given a brand/project name : '{brand_name}' with description '{description}', 
        suggest 10-15 relevant keywords for finding related discussions. Return only the keywords, 
        one per line, without any additional text.
        
        Avoid very generic keywords like ai, technology,saas and reddit etc
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
    include_experience: bool,
    db: Session
) -> str:
    """Generate custom AI response with natural brand incorporation"""
    logging.info(f"Starting comment generation for brand_id: {brand_id}")
    logging.info(f"Post title: {post_title}")
    
    try:
        brand = db.query(Brand).filter(Brand.id == brand_id).first()
        if not brand:
            logging.error(f"Brand not found: {brand_id}")
            raise ValueError(f"Brand with id {brand_id} not found")
        
        brand_name = brand.name
        knowledge_base = brand.description
        
        logging.info(f"Found brand: {brand_name}")

        system_message = f"""
    You're a seasoned redditor sharing authentic experiences. Strict rules:
    
    1. Maximum 3 short paragraphs (5 sentences total)
    2. Use 50% sentence fragments
    3. Include 1-2 slang terms ("tbh", "imo")
    4. Mention {brand_name} exactly once through vague recall
    5. Add specific situational detail (fake subreddit, time frame)
    6. Include 1 mildly controversial opinion
    7. End with quick question
    8. Never use perfect grammar
    """

        prompt = f"""
    Post: {post_content}
    
    Craft response that:
    - Starts with blunt agreement
    - Shares 1 specific failure story
    - Mentions {brand_name} as afterthought
    - Includes minor self-deprecation
    - Ends with quick question
    - Max 120 words
    """
        logging.info("Sending request to Anthropic API")
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=70,
            temperature=0.9,  # Higher temp for more natural hesitation
            system=system_message,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        logging.info("Received response from Anthropic API")
        
        if not response or not response.content or len(response.content) == 0:
            logging.error("Empty response from Anthropic API")
            return "Sorry, I couldn't generate a response at this time."
            
        comment = response.content[0].text.strip()
        
        # Post-processing to ensure natural feel
        comment = re.sub(r"\b(Sneakyguy)\b", lambda m: m.group().lower(), comment)  # Ensure lowercase
        comment = re.sub(r"\!(?!\?)", ".", comment)  # Replace standalone exclamation marks
        logging.info(f"Final comment length: {len(comment)}")
        
        return comment
        
    except Exception as e:
        logging.error(f"Error in generate_custom_comment: {str(e)}", exc_info=True)
        return "Sorry, I'm having trouble generating a response right now."
def generate_relevance_score(post_title: str, post_content: str, brand_id: int, db: Session) -> int:
    """Generate relevance score between post and brand"""
    try:
        brand = db.query(Brand).filter(Brand.id == brand_id).first()
        if not brand:
            raise ValueError(f"Brand with id {brand_id} not found")

        system_message = """
        You are an expert content analyzer specializing in determining relevance between social media posts and brand offerings. Your task is to analyze the similarity between a given post and a brand's offering, providing a relevance score from 20-100.

        Scoring Guide:
        - 90-100: Exceptional match (direct need-solution fit)
        - 70-89: Strong match (clear alignment with some minor gaps)
        - 50-69: Moderate match (partial alignment)
        - 35-49: Basic match (some relevant elements)
        - 20-34: Minimal match (few overlapping elements)

        Your output must be in this exact format:
        Relevance Score: [20-100]
        Explanation: [2-3 sentences explaining the score]
        """

        prompt = f"""
        Analyze the relevance between this post and brand:

        Post Title: {post_title}
        Post Content: {post_content}
        Brand Name: {brand.name}
        Brand Description: {brand.description}
        """

        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1000,
            temperature=0.1,
            system=system_message,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = response.content[0].text
        
        # Extract just the score
        score_line = response_text.split('\n')[0]
        score = int(''.join(filter(str.isdigit, score_line)))
        
        # Ensure score is within 20-100 range
        return max(20, min(100, score))

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
    Requires authentication.
    """
    try:
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
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            reddit = asyncpraw.Reddit(
                **reddit_config,
                requestor_class=asyncprawcore.Requestor,
                requestor_kwargs={"session": session}
            )

            matching_posts = []
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
                        time_period = analysis_input.time_period or "month"
                        posts = subreddit.top(time_period, limit=analysis_input.limit)
                    except Exception as e:
                        logging.error(f"Error fetching posts from {clean_subreddit_name}: {str(e)}")
                        continue
                    
                    # Check each post for keyword matches
                    async for post in posts:
                        post_text = f"{post.title} {post.selftext}".lower()
                        matching_keywords = [
                            keyword for keyword in analysis_input.keywords 
                            if keyword.lower() in post_text
                        ]
                        
                        if matching_keywords:
                            # Generate AI suggested comment and relevance score
                            #test_comment, relevance_score = await generate_comment(post.title, post.selftext, brand.id, db)
                            relevance_score= generate_relevance_score(post.title, post.selftext, brand.id, db)
                            print("\n relavence score>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>:\n\n",relevance_score)
                            suggested_comment = "This feature will be live soon! Stay tuned!😊"
                            
                            post_data = {
                                "title": post.title,
                                "content": post.selftext[:5000],  # Limit content length
                                "url": f"https://reddit.com{post.permalink}",
                                "subreddit": clean_subreddit_name,
                                "created_utc": post.created_utc,
                                "score": post.score,
                                "num_comments": post.num_comments,
                                "relevance_score": relevance_score,
                                "suggested_comment": suggested_comment,
                                "matched_keywords": matching_keywords
                            }
                            matching_posts.append(post_data)

                            # Store the mention in the database
                            mention = RedditMention(
                                brand_id=brand.id,
                                title=post.title,
                                content=post.selftext[:500],  # Limit content length
                                url=f"https://reddit.com{post.permalink}",
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

            # Sort posts by relevance score
            matching_posts.sort(key=lambda x: x["relevance_score"], reverse=True)

            # Update brand's last_analyzed timestamp
            brand.last_analyzed = datetime.utcnow()
            db.commit()

            return AnalysisResponse(
                status="success",
                posts=matching_posts,
                matching_posts=matching_posts
            )

    except Exception as e:
        logging.error(f"Error analyzing Reddit content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/projects/{brand_id}", response_model=BrandResponse, tags=["brands"])
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
    limit: int = 50,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all Reddit mentions for a brand/project"""
    brand = BrandCRUD.get_brand(db, brand_id, current_user_email)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found or unauthorized access")
    
    try:
        mentions = RedditMentionCRUD.get_brand_mentions(db, brand_id, skip=skip, limit=limit)
        logging.info(f"Retrieved mentions: {[vars(m) for m in mentions]}")
        
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
        
        logging.info(f"Converted mentions: {mention_dicts}")
        return [RedditMentionResponse(**m) for m in mention_dicts]
    except Exception as e:
        logging.error(f"Error getting mentions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)

async def generate_custom_comment(
    post_title: str,
    post_content: str,
    brand_id: int,
    include_experience: bool,
    db: Session
) -> str:
    """Generate custom AI response with natural brand incorporation"""
    logging.info(f"Starting comment generation for brand_id: {brand_id}")
    logging.info(f"Post title: {post_title}")
    
    try:
        brand = db.query(Brand).filter(Brand.id == brand_id).first()
        if not brand:
            logging.error(f"Brand not found: {brand_id}")
            raise ValueError(f"Brand with id {brand_id} not found")
        
        brand_name = brand.name
        knowledge_base = brand.description
        
        logging.info(f"Found brand: {brand_name}")

        system_message = f"""
        You're a reddit user sharing authentic experiences. Strictly follow these rules:

        1. Only mention {brand_name} if relevant to OP's problem and through personal stories
        2. Use hesitation markers ("think it was...", "maybe called...") when naming tools
        3. Frame brand discovery as accidental ("stumbled upon", "saw mentioned")
        4. Always pair brand mentions with non-brand alternatives
        5. Use casual lowercase and natural speech patterns
        6. Include specific situational context (timeframe, source platform)
        7. Immediately pivot to methodology after any tool mention
        8. Add doubt about tool's role ("not sure if right for you")
        9. End with open-ended question to OP
        """

        prompt = f"""
        POST CONTEXT:
        Title: {post_title}
        Body: {post_content}

        YOUR TASK:
        Craft response that:
        1. Starts with empathy for OP's struggle
        2. Shares brief personal experience with prospecting
        3. Mentions discovering {brand_name} organically:
           - Through community discussion (don't specify subreddit)
           - With imperfect recall ("think it was...")
           - As example not recommendation
        4. Focuses on strategy over tools
        5. Ends with question inviting OP's experience
        """

        logging.info("Sending request to Anthropic API")
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=300,
            temperature=0.9,  # Higher temp for more natural hesitation
            system=system_message,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        logging.info("Received response from Anthropic API")
        
        if not response or not response.content or len(response.content) == 0:
            logging.error("Empty response from Anthropic API")
            return "Sorry, I couldn't generate a response at this time."
            
        comment = response.content[0].text.strip()
        
        # Post-processing to ensure natural feel
        comment = re.sub(r"\b(Sneakyguy)\b", lambda m: m.group().lower(), comment)  # Ensure lowercase
        comment = re.sub(r"\!(?!\?)", ".", comment)  # Replace standalone exclamation marks
        logging.info(f"Final comment length: {len(comment)}")
        
        return comment
        
    except Exception as e:
        logging.error(f"Error in generate_custom_comment: {str(e)}", exc_info=True)
        return "Sorry, I'm having trouble generating a response right now."
@app.post("/generate-custom-comment/", response_model=CommentResponse)
async def generate_comment_endpoint(
    comment_input: CommentInput,
    request: Request,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate a custom comment for a Reddit post.
    Requires authentication.
    """
    logging.info(f"Received comment generation request from user: {current_user_email}")
    
    try:
        comment = await generate_custom_comment(
            post_title=comment_input.post_title,
            post_content=comment_input.post_content,
            brand_id=comment_input.brand_id,
            include_experience=comment_input.include_experience,
            db=db
        )
        
        if not comment:
            logging.error("Empty comment generated")
            raise HTTPException(status_code=500, detail="Failed to generate comment")
            
        logging.info("Successfully generated comment")
        return CommentResponse(comment=comment)
        
    except ValueError as ve:
        logging.error(f"ValueError in generate_comment_endpoint: {str(ve)}")
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logging.error(f"Error in generate_comment_endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error generating comment")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)