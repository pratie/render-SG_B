from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from database import get_db
from models import UserPreferences, UserPreferencesInput, UserPreferencesResponse
from auth.router import get_current_user

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

@router.get("", response_model=UserPreferencesResponse)
async def get_user_preferences(
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the current user's AI communication preferences"""
    prefs = db.query(UserPreferences).filter(
        UserPreferences.user_email == current_user_email
    ).first()
    
    if not prefs:
        # Return default preferences if none set
        return {
            "tone": "friendly",
            "response_style": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
    
    return {
        "tone": prefs.tone,
        "response_style": prefs.response_style,
        "created_at": prefs.created_at,
        "updated_at": prefs.updated_at
    }

@router.post("", response_model=UserPreferencesResponse)
async def set_user_preferences(
    preferences: UserPreferencesInput,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Set or update the user's AI communication preferences"""
    prefs = db.query(UserPreferences).filter(
        UserPreferences.user_email == current_user_email
    ).first()
    
    if not prefs:
        prefs = UserPreferences(
            user_email=current_user_email,
            tone=preferences.tone,
            response_style=preferences.response_style
        )
        db.add(prefs)
    else:
        prefs.tone = preferences.tone
        prefs.response_style = preferences.response_style
        prefs.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(prefs)
    
    return {
        "tone": prefs.tone,
        "response_style": prefs.response_style,
        "created_at": prefs.created_at,
        "updated_at": prefs.updated_at
    }
