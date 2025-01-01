from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from database import get_db
from crud import UserCRUD
from . import config

router = APIRouter(prefix="/auth", tags=["authentication"])
security = HTTPBearer()

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
    return email

@router.post("/google-login", tags=["authentication"])
async def google_login(
    token: str,
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
        else:
            UserCRUD.update_last_login(db, email)
        
        # Create access token
        access_token = config.create_access_token(email)
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "email": email
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

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
        else:
            UserCRUD.update_last_login(db, email)
        
        # Create access token
        access_token = config.create_access_token(email)
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "email": email
        }
    
    except Exception as e:
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