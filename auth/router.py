from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from utils import send_magic_link_email

from database import get_db, DATABASE_URL
from crud import UserCRUD, MagicTokenCRUD
from . import config

router = APIRouter(prefix="/auth", tags=["authentication"])
security = HTTPBearer()

class EmailSchema(BaseModel):
    email: EmailStr

class MagicTokenSchema(BaseModel):
    token: str

def get_db_path():
    """Extract database path from DATABASE_URL"""
    if DATABASE_URL.startswith('sqlite:////'):
        return DATABASE_URL[10:].split('?')[0]
    return DATABASE_URL[9:].split('?')[0]

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> str:
    """Dependency to get current user's email from JWT token"""
    email = config.verify_token(credentials.credentials)
    user = UserCRUD.get_user_by_email(db, email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    print("\n=== User Authenticated ===")
    print(f"Email: {email}")
    print(f"Database: {get_db_path()}")
    print("=========================\n")
    return email

@router.post("/google-login", tags=["authentication"])
async def google_login(
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """Login or register user with Google OAuth token"""
    try:
        # Verify Google token and get email
        email = config.verify_google_token(token)
        
        # Get or create user
        user = UserCRUD.get_user_by_email(db, email)
        if not user:
            user = UserCRUD.create_user(db, email)
            print("\n=== New User Created ===")
            print(f"Email: {email}")
            print(f"Database: {get_db_path()}")
            print("=====================\n")
        else:
            UserCRUD.update_last_login(db, email)
            print("\n=== User Login ===")
            print(f"Email: {email}")
            print(f"Database: {get_db_path()}")
            print("=================\n")
        
        # Create access token
        access_token = config.create_access_token(email)
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "email": email
        }
    
    except Exception as e:
        print(f"\n=== Login Error ===")
        print(f"Error: {str(e)}")
        print("=================\n")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

@router.post("/request-login-link", tags=["authentication"])
async def request_login_link(
    data: EmailSchema,
    db: Session = Depends(get_db)
):
    """Request a magic login link to be sent by email."""
    # We don't reveal if the user exists to prevent email enumeration
    # We can create the user here if they don't exist, or do it upon verification
    user = UserCRUD.get_user_by_email(db, data.email)
    if not user:
        # Optionally create the user now
        user = UserCRUD.create_user(db, data.email)

    magic_token = MagicTokenCRUD.create_magic_token(db, data.email)
    send_magic_link_email(email=data.email, token=magic_token.token)
    return {"message": "If an account with that email exists, a login link has been sent."}


@router.post("/verify-magic-token", tags=["authentication"])
async def verify_magic_token(
    data: MagicTokenSchema,
    db: Session = Depends(get_db)
):
    """Verify a magic token and log the user in."""
    db_token = MagicTokenCRUD.get_magic_token(db, data.token)

    if not db_token or db_token.used or db_token.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired login link."
        )

    # Mark token as used
    MagicTokenCRUD.use_magic_token(db, db_token)

    # Get or create user
    user = UserCRUD.get_user_by_email(db, db_token.user_email)
    if not user:
        # This case is unlikely if we create the user on request, but as a fallback
        user = UserCRUD.create_user(db, db_token.user_email)
    else:
        UserCRUD.update_last_login(db, db_token.user_email)

    # Create access token
    access_token = config.create_access_token(user.email)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "email": user.email
    }


@router.get("/google-login", tags=["authentication"]) 
async def google_login_get(
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """Login or register user with Google OAuth token (GET method)"""
    return await google_login(token, db)

@router.post("/test-login", tags=["authentication"])
async def test_login(
    email: str,
    db: Session = Depends(get_db)
):
    """Development only: Create a test user and return access token"""
    try:
        # Get or create user
        user = UserCRUD.get_user_by_email(db, email)
        if not user:
            user = UserCRUD.create_user(db, email)
            print("\n=== New Test User Created ===")
            print(f"Email: {email}")
            print(f"Database: {get_db_path()}")
            print("=========================\n")
        else:
            UserCRUD.update_last_login(db, email)
            print("\n=== Test User Login ===")
            print(f"Email: {email}")
            print(f"Database: {get_db_path()}")
            print("====================\n")
        
        # Create access token
        access_token = config.create_access_token(email)
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "email": email
        }
    
    except Exception as e:
        print(f"\n=== Test Login Error ===")
        print(f"Error: {str(e)}")
        print("=====================\n")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

@router.get("/me", tags=["authentication"])
async def get_current_user_info(
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user information"""
    user = UserCRUD.get_user_by_email(db, current_user_email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return {
        "email": user.email,
        "created_at": user.created_at,
        "last_login": user.last_login
    }

@router.post("/check-token", tags=["authentication"])
async def check_token_validity(
    current_user_email: str = Depends(get_current_user)
):
    """Check if the current token is valid"""
    return {"valid": True, "email": current_user_email}