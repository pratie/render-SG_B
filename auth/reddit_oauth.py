"""
Reddit OAuth implementation for the Reddit Analysis API.
This module handles the OAuth flow for Reddit authentication.
"""
import os
import secrets
import time
from typing import Dict, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
import requests
from pydantic import BaseModel
import logging
from datetime import datetime, timedelta

from database import get_db
from models import User, RedditToken, RedditOAuthState
from auth.router import get_current_user

# Create router
router = APIRouter(
    prefix="/api/reddit-auth",
    tags=["reddit-auth"],
    responses={404: {"description": "Not found"}},
)

# Models
class RedditTokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    scope: str

class RedditAuthStatus(BaseModel):
    is_authenticated: bool
    username: Optional[str] = None
    expires_at: Optional[int] = None

# Constants
REDDIT_OAUTH_URL = "https://www.reddit.com/api/v1/authorize"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "python:reddit-analysis-api:v1.0.0 (by /u/snaplearn2earn)")
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")

# Get the base URL from environment variable with a default for local development
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
REDDIT_REDIRECT_URI = f"{BASE_URL}/api/reddit-auth/callback"

# Debug print to verify the correct value is being used
print(f"REDDIT_REDIRECT_URI loaded as: {REDDIT_REDIRECT_URI}")
logging.info(f"REDDIT_REDIRECT_URI loaded as: {REDDIT_REDIRECT_URI}")

REDDIT_SCOPES = ["identity", "read", "submit"]

def get_auth_headers() -> Dict[str, str]:
    """Get headers for Reddit API authentication"""
    return {
        "User-Agent": REDDIT_USER_AGENT
    }

def get_token_auth() -> Tuple[str, str]:
    """Get client credentials for token requests"""
    return (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET)

def save_reddit_token(db: Session, user_email: str, token_data: RedditTokenResponse) -> RedditToken:
    """Save or update Reddit token in database"""
    # Calculate expiration time
    expires_at = int(time.time()) + token_data.expires_in
    
    # Check if token exists
    token = db.query(RedditToken).filter(RedditToken.user_email == user_email).first()
    
    if token:
        # Update existing token
        token.access_token = token_data.access_token
        token.refresh_token = token_data.refresh_token
        token.token_type = token_data.token_type
        token.scope = token_data.scope
        token.expires_at = expires_at
    else:
        # Create new token
        token = RedditToken(
            user_email=user_email,
            access_token=token_data.access_token,
            refresh_token=token_data.refresh_token,
            token_type=token_data.token_type,
            scope=token_data.scope,
            expires_at=expires_at
        )
        db.add(token)
    
    db.commit()
    db.refresh(token)
    return token

async def get_reddit_token(db: Session, user_email: str) -> Optional[RedditToken]:
    """Get valid Reddit token for user, refreshing if needed"""
    token = db.query(RedditToken).filter(RedditToken.user_email == user_email).first()
    
    if not token:
        return None
    
    # Check if token is expired or about to expire (within 5 minutes)
    current_time = int(time.time())
    if token.expires_at - current_time < 300:
        # Token needs refresh
        try:
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token
            }
            
            response = requests.post(
                REDDIT_TOKEN_URL,
                auth=get_token_auth(),
                headers=get_auth_headers(),
                data=refresh_data
            )
            
            if response.status_code == 200:
                token_data = RedditTokenResponse(**response.json())
                token = save_reddit_token(db, user_email, token_data)
            else:
                # If refresh fails, return None to trigger re-authentication
                logging.error(f"Failed to refresh Reddit token: {response.text}")
                return None
                
        except Exception as e:
            logging.error(f"Error refreshing Reddit token: {str(e)}")
            return None
    
    return token

def save_oauth_state(db: Session, state: str, user_email: str) -> RedditOAuthState:
    """Save OAuth state to database"""
    try:
        # Delete any existing expired states for this user
        db.query(RedditOAuthState).filter(
            RedditOAuthState.user_email == user_email,
            RedditOAuthState.expires_at <= datetime.utcnow()
        ).delete()
        
        oauth_state = RedditOAuthState(
            state=state,
            user_email=user_email,
            expires_at=datetime.utcnow() + timedelta(minutes=10)
        )
        db.add(oauth_state)
        db.commit()
        logging.info(f"Saved OAuth state {state} for user {user_email}")
        return oauth_state
    except Exception as e:
        logging.error(f"Error saving OAuth state: {str(e)}")
        db.rollback()
        raise

def get_oauth_state(db: Session, state: str) -> Optional[RedditOAuthState]:
    """Get OAuth state from database if valid"""
    try:
        logging.info(f"Looking for OAuth state: {state}")
        oauth_state = db.query(RedditOAuthState).filter(
            RedditOAuthState.state == state,
            RedditOAuthState.expires_at > datetime.utcnow()
        ).first()
        
        if oauth_state:
            logging.info(f"Found valid OAuth state for user {oauth_state.user_email}")
            # Clean up the used state
            db.delete(oauth_state)
            db.commit()
            return oauth_state
        else:
            # Check if state exists but is expired
            expired_state = db.query(RedditOAuthState).filter(
                RedditOAuthState.state == state
            ).first()
            if expired_state:
                logging.error(f"Found expired OAuth state for user {expired_state.user_email}")
                db.delete(expired_state)
                db.commit()
            else:
                logging.error("OAuth state not found in database")
        return None
    except Exception as e:
        logging.error(f"Error getting OAuth state: {str(e)}")
        return None

@router.get("/login")
async def reddit_login(
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Initiate Reddit OAuth flow"""
    try:
        # Generate state parameter to prevent CSRF
        state = secrets.token_urlsafe(32)
        logging.info(f"Generated new state {state} for user {current_user_email}")
        
        # Save state to database
        save_oauth_state(db, state, current_user_email)
        
        # Build authorization URL
        params = {
            "client_id": REDDIT_CLIENT_ID,
            "response_type": "code",
            "state": state,
            "redirect_uri": REDDIT_REDIRECT_URI,
            "duration": "permanent",
            "scope": " ".join(REDDIT_SCOPES)
        }
        
        auth_url = f"{REDDIT_OAUTH_URL}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
        logging.info(f"Generated Reddit auth URL with state {state}")
        return {"auth_url": auth_url}
    except Exception as e:
        logging.error(f"Error in reddit_login: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/callback")
async def reddit_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    db: Session = Depends(get_db)
):
    """Handle Reddit OAuth callback"""
    # Handle errors
    if error:
        logging.error(f"Reddit OAuth error: {error}")
        html_content = f"""
        <html>
            <body>
                <script>
                    window.opener.postMessage({{ error: '{error}' }}, '*');
                    window.close();
                </script>
                <p>Authentication failed. You can close this window.</p>
            </body>
        </html>
        """
        return Response(content=html_content, media_type="text/html")
    
    # Validate state to prevent CSRF
    oauth_state = get_oauth_state(db, state) if state else None
    if not oauth_state:
        logging.error("Invalid state parameter in Reddit OAuth callback")
        html_content = """
        <html>
            <body>
                <script>
                    window.opener.postMessage({ error: 'Invalid state parameter' }, '*');
                    window.close();
                </script>
                <p>Authentication failed. You can close this window.</p>
            </body>
        </html>
        """
        return Response(content=html_content, media_type="text/html")
    
    try:
        # Get user email from state
        user_email = oauth_state.user_email
        
        # Exchange code for token
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDDIT_REDIRECT_URI
        }
        
        response = requests.post(
            REDDIT_TOKEN_URL,
            auth=get_token_auth(),
            headers=get_auth_headers(),
            data=token_data
        )
        
        if response.status_code != 200:
            logging.error(f"Error getting Reddit token: {response.text}")
            html_content = """
            <html>
                <body>
                    <script>
                        window.opener.postMessage({ error: 'Failed to get Reddit token' }, '*');
                        window.close();
                    </script>
                    <p>Authentication failed. You can close this window.</p>
                </body>
            </html>
            """
            return Response(content=html_content, media_type="text/html")
        
        # Parse token response
        token_data = RedditTokenResponse(**response.json())
        
        # Get Reddit username
        user_response = requests.get(
            "https://oauth.reddit.com/api/v1/me",
            headers={
                **get_auth_headers(),
                "Authorization": f"Bearer {token_data.access_token}"
            }
        )
        
        if user_response.status_code != 200:
            logging.error(f"Error getting Reddit user info: {user_response.text}")
            html_content = """
            <html>
                <body>
                    <script>
                        window.opener.postMessage({ error: 'Failed to get Reddit user info' }, '*');
                        window.close();
                    </script>
                    <p>Authentication failed. You can close this window.</p>
                </body>
            </html>
            """
            return Response(content=html_content, media_type="text/html")
        
        username = user_response.json().get("name")
        
        # Save token to database
        token = save_reddit_token(db, user_email, token_data)
        
        # Update username if available
        if username and token:
            token.reddit_username = username
            db.commit()
        
        # Return success HTML that closes the window and notifies the parent
        html_content = """
        <html>
            <body>
                <script>
                    window.opener.postMessage({ success: true }, '*');
                    window.close();
                </script>
                <p>Authentication successful! You can close this window.</p>
            </body>
        </html>
        """
        return Response(content=html_content, media_type="text/html")
        
    except Exception as e:
        logging.error(f"Error in Reddit OAuth callback: {str(e)}", exc_info=True)
        html_content = f"""
        <html>
            <body>
                <script>
                    window.opener.postMessage({{ error: '{str(e)}' }}, '*');
                    window.close();
                </script>
                <p>Authentication failed. You can close this window.</p>
            </body>
        </html>
        """
        return Response(content=html_content, media_type="text/html")

@router.get("/status")
async def reddit_auth_status(
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Check if user is authenticated with Reddit"""
    token = db.query(RedditToken).filter(RedditToken.user_email == current_user_email).first()
    
    if not token:
        return RedditAuthStatus(is_authenticated=False)
    
    return RedditAuthStatus(
        is_authenticated=True,
        username=token.reddit_username,
        expires_at=token.expires_at
    )

@router.post("/logout")
async def reddit_logout(
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Revoke Reddit token and remove from database"""
    token = db.query(RedditToken).filter(RedditToken.user_email == current_user_email).first()
    
    if token:
        try:
            # Revoke token with Reddit
            revoke_data = {
                "token": token.access_token,
                "token_type_hint": "access_token"
            }
            
            requests.post(
                "https://www.reddit.com/api/v1/revoke_token",
                auth=get_token_auth(),
                headers=get_auth_headers(),
                data=revoke_data
            )
            
            # Delete token from database
            db.delete(token)
            db.commit()
            
        except Exception as e:
            logging.error(f"Error revoking Reddit token: {str(e)}")
            # Still delete from database even if revoke fails
            db.delete(token)
            db.commit()
    
    return {"success": True}

# Test endpoint for Reddit OAuth
@router.get("/test")
async def test_reddit_auth(
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Test endpoint for Reddit OAuth"""
    token = await get_reddit_token(db, current_user_email)
    
    if not token:
        return {
            "authenticated": False,
            "message": "Not authenticated with Reddit"
        }
    
    try:
        # Test API call to verify token works
        response = requests.get(
            "https://oauth.reddit.com/api/v1/me",
            headers={
                **get_auth_headers(),
                "Authorization": f"Bearer {token.access_token}"
            }
        )
        
        if response.status_code == 200:
            user_data = response.json()
            return {
                "authenticated": True,
                "username": user_data.get("name"),
                "karma": user_data.get("total_karma"),
                "created_utc": user_data.get("created_utc")
            }
        else:
            return {
                "authenticated": False,
                "message": f"API error: {response.status_code} - {response.text}"
            }
    except Exception as e:
        return {
            "authenticated": False,
            "message": f"Error: {str(e)}"
        }
