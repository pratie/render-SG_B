from fastapi import APIRouter, Depends, HTTPException, Body

from sqlalchemy.orm import Session
from typing import Dict, Optional
from datetime import datetime

import os
import logging
import requests
import asyncio
import aiohttp




# Database and models
from database import get_db
from models import User, Brand, UserPreferences, AlertSetting
from auth.router import get_current_user

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Get Telegram credentials from environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

async def send_telegram_alert(message: str, chat_id: str = None):
    """Send alert message to Telegram with retry logic and timeout."""
    max_retries = 3
    retry_delay = 5  # seconds
    timeout = 30  # seconds
    
    if not TELEGRAM_BOT_TOKEN or (not TELEGRAM_CHAT_ID and not chat_id):
        logger.error("Missing Telegram credentials for alert")
        return False

    target_chat_id = chat_id if chat_id else TELEGRAM_CHAT_ID
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        'chat_id': target_chat_id,
        'text': message,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(telegram_url, json=payload, timeout=timeout) as response:
                    if response.status == 200:
                        logger.info(f"Telegram alert sent successfully to chat {target_chat_id}")
                        return True
                    else:
                        logger.error(f"Failed to send Telegram alert. Status: {response.status}")
                        logger.error(f"Response: {await response.text()}")
        except asyncio.TimeoutError:
            logger.error(f"Timeout error on attempt {attempt + 1} for alert")
        except Exception as e:
            logger.error(f"Error sending alert on attempt {attempt + 1}: {str(e)}")
        
        if attempt < max_retries - 1:
            logger.info(f"Retrying alert in {retry_delay} seconds...")
            await asyncio.sleep(retry_delay)
    
    logger.error(f"Failed to send Telegram alert to {target_chat_id} after {max_retries} attempts")
    return False

@router.post("/settings")
async def set_alert_settings(
    settings: Dict,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Set or update user's alert preferences"""
    try:
        alert_settings = db.query(AlertSetting).filter(
            AlertSetting.user_email == current_user_email
        ).first()
        
        if not alert_settings:
            alert_settings = AlertSetting(
                user_email=current_user_email,
                telegram_chat_id=settings.get('telegram_chat_id', ''),
                enable_telegram_alerts=settings.get('enable_telegram_alerts', False),
                enable_email_alerts=settings.get('enable_email_alerts', False),
                alert_threshold_score=settings.get('alert_threshold_score', 2),
                alert_frequency=settings.get('alert_frequency', 'daily'),
                is_active=settings.get('is_active', True),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(alert_settings)
        else:
            alert_settings.telegram_chat_id = settings.get('telegram_chat_id', alert_settings.telegram_chat_id)
            alert_settings.enable_telegram_alerts = settings.get('enable_telegram_alerts', alert_settings.enable_telegram_alerts)
            alert_settings.enable_email_alerts = settings.get('enable_email_alerts', alert_settings.enable_email_alerts)
            alert_settings.alert_threshold_score = settings.get('alert_threshold_score', alert_settings.alert_threshold_score)
            alert_settings.alert_frequency = settings.get('alert_frequency', alert_settings.alert_frequency)
            alert_settings.is_active = settings.get('is_active', alert_settings.is_active)
            alert_settings.updated_at = datetime.utcnow()
        
        db.commit()
        return {"status": "success", "message": "Alert settings updated"}
    except Exception as e:
        logger.error(f"Error updating alert settings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/settings")
async def get_alert_settings(
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's alert preferences"""
    try:
        alert_settings = db.query(AlertSetting).filter(
            AlertSetting.user_email == current_user_email
        ).first()
        
        if not alert_settings:
            # Default settings if none exist
            return {
                "telegram_chat_id": "",
                "enable_telegram_alerts": False,
                "enable_email_alerts": False,
                "alert_threshold_score": 100,
                "alert_frequency": "daily",
                "is_active": True
            }
        
        return {
            "telegram_chat_id": alert_settings.telegram_chat_id,
            "enable_telegram_alerts": alert_settings.enable_telegram_alerts,
            "enable_email_alerts": alert_settings.enable_email_alerts,
            "alert_threshold_score": alert_settings.alert_threshold_score,
            "alert_frequency": alert_settings.alert_frequency,
            "is_active": alert_settings.is_active
        }
    except Exception as e:
        logger.error(f"Error getting alert settings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def send_brand_mention_alert(
    user_email: str, 
    brand_name: str, 
    post_title: str, 
    post_url: str, 
    score: int, 
    db: Session
):
    """Send alert when a brand is mentioned in a high-scoring post"""
    try:
        alert_settings = db.query(AlertSetting).filter(
            AlertSetting.user_email == user_email
        ).first()
        
        if not alert_settings or (not alert_settings.enable_telegram_alerts and not alert_settings.enable_email_alerts):
            return False  # Alerts disabled for this user
        
        if score < alert_settings.alert_threshold_score:
            return False  # Post score below threshold
        
        # Prepare alert message
        alert_message = (
            f"🚨 <b>Brand Mention Alert</b> 🚨\n"
            f"<b>Brand:</b> {brand_name}\n"
            f"<b>Post:</b> {post_title}\n"
            f"<b>Score:</b> {score}\n"
            f"<b>URL:</b> {post_url}\n"
        )
        
        if alert_settings.enable_telegram_alerts and alert_settings.telegram_chat_id:
            await send_telegram_alert(alert_message, alert_settings.telegram_chat_id)
            return True
        
        if alert_settings.enable_email_alerts:
            # Email alert logic can be implemented here when ready
            logger.info(f"Email alert would be sent for {brand_name} to {user_email}")
            return True
        
        return False
    except Exception as e:
        logger.error(f"Error sending brand mention alert: {str(e)}")
        return False

def get_all_active_alert_settings(db: Session):
    """Get all active alert settings for the real-time monitoring system.
    
    Returns a list of AlertSetting objects for all users who have enabled alerts.
    """
    try:
        # Query for all alert settings where alerts are enabled
        settings = db.query(AlertSetting).filter(
            (AlertSetting.enable_telegram_alerts == True) | 
            (AlertSetting.enable_email_alerts == True)
        ).all()
        
        logger.info(f"Found {len(settings)} active alert settings")
        return settings
    except Exception as e:
        logger.error(f"Error fetching active alert settings: {str(e)}")
        return []
