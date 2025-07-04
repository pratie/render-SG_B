# app/crud.py
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta
import json
from typing import List, Optional, Dict, Any
import logging
import secrets

from models import User, Brand, RedditMention, RedditComment, AlertSetting, MagicToken # Added AlertSetting and MagicToken
from fastapi import HTTPException

class UserCRUD:
    @staticmethod
    def get_user_by_email(db: Session, email: str) -> Optional[User]:
        """Get user by email"""
        return db.query(User).filter(User.email == email).first()

    @staticmethod
    def create_user(db: Session, email: str) -> User:
        """Create new user if doesn't exist"""
        existing_user = UserCRUD.get_user_by_email(db, email)
        if existing_user:
            return existing_user
            
        db_user = User(email=email)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user

    @staticmethod
    def update_last_login(db: Session, email: str) -> User:
        """Update user's last login time"""
        db_user = UserCRUD.get_user_by_email(db, email)
        if db_user:
            db_user.last_login = datetime.utcnow()
            db.commit()
            db.refresh(db_user)
        return db_user

# ... (end of UserCRUD class) ...

class MagicTokenCRUD:
    @staticmethod
    def create_magic_token(db: Session, email: str) -> MagicToken:
        """Create a new magic token for a user."""
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(minutes=15)  # Token valid for 15 minutes
        db_token = MagicToken(
            user_email=email,
            token=token,
            expires_at=expires_at
        )
        db.add(db_token)
        db.commit()
        db.refresh(db_token)
        return db_token

    @staticmethod
    def get_magic_token(db: Session, token: str) -> Optional[MagicToken]:
        """Get a magic token by its value."""
        return db.query(MagicToken).filter(MagicToken.token == token).first()

    @staticmethod
    def use_magic_token(db: Session, db_token: MagicToken) -> MagicToken:
        """Mark a magic token as used."""
        db_token.used = True
        db.commit()
        db.refresh(db_token)
        return db_token


class AlertSettingCRUD:
    @staticmethod
    def get_users_for_daily_digest(db: Session) -> List[User]:
        """Get all users who have opted in for daily email digests (based on enable_email_alerts only)."""
        return (
            db.query(User)
            .join(AlertSetting, User.email == AlertSetting.user_email)
            .filter(AlertSetting.enable_email_alerts == True)
            .all()
        )

    @staticmethod
    def get_alert_setting(db: Session, user_email: str) -> Optional[AlertSetting]:
        """Get alert settings for a specific user."""
        return db.query(AlertSetting).filter(AlertSetting.user_email == user_email).first()

    @staticmethod
    def update_or_create_alert_setting(db: Session, user_email: str, settings_data: Dict[str, Any]) -> AlertSetting:
        """Update or create alert settings for a user."""
        setting = db.query(AlertSetting).filter(AlertSetting.user_email == user_email).first()
        if not setting:
            defaults = {
                'telegram_chat_id': None,
                'enable_telegram_alerts': False,
                'enable_email_alerts': False, 
                'alert_threshold_score': 100,
                'alert_frequency': 'daily',
                'is_active': True
            }
            final_settings = {**defaults, **settings_data}
            setting = AlertSetting(user_email=user_email, **final_settings)
            db.add(setting)
        else:
            for key, value in settings_data.items():
                setattr(setting, key, value)
            setting.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(setting)
        return setting

class BrandCRUD:
    @staticmethod
    def create_brand(
        db: Session,
        brand_input: dict,
        user_email: str
    ) -> Brand:
        """Create a new brand"""
        try:
            db_brand = Brand(
                user_email=user_email,
                name=brand_input["name"],
                description=brand_input["description"],
                keywords=json.dumps(brand_input.get("keywords", [])),
                subreddits=json.dumps(brand_input.get("subreddits", []))
            )
            
            db.add(db_brand)
            db.commit()
            db.refresh(db_brand)
            return db_brand
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    @staticmethod
    def get_brand(db: Session, brand_id: int, user_email: str) -> Optional[Brand]:
        """Get a specific brand by ID and user email"""
        user = UserCRUD.get_user_by_email(db, user_email)
        if not user:
            return None
        return db.query(Brand).filter(Brand.id == brand_id, Brand.user_email == user_email).first()

    @staticmethod
    def get_user_brands(db: Session, user_email: str, skip: int = 0, limit: int = 50) -> List[Brand]:
        """Get all brands for a user"""
        return db.query(Brand).filter(Brand.user_email == user_email).offset(skip).limit(limit).all()

    @staticmethod
    def update_brand_keywords(db: Session, brand_id: int, keywords: List[str]) -> Optional[Brand]:
        """Update brand keywords"""
        brand = db.query(Brand).filter(Brand.id == brand_id).first()
        if not brand:
            return None
            
        brand.keywords = json.dumps(keywords)
        brand.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(brand)
        return brand

    @staticmethod
    def update_brand_subreddits(db: Session, brand_id: int, subreddits: List[str]) -> Optional[Brand]:
        """Update brand subreddits"""
        brand = db.query(Brand).filter(Brand.id == brand_id).first()
        if not brand:
            return None
            
        brand.subreddits = json.dumps(subreddits)
        brand.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(brand)
        return brand

    @staticmethod
    def update_brand(
        db: Session,
        brand_id: int,
        brand_input: dict,
        user_email: str
    ) -> Optional[Brand]:
        """Update brand details"""
        brand = db.query(Brand).filter(
            Brand.id == brand_id,
            Brand.user_email == user_email
        ).first()
        
        if not brand:
            return None
            
        brand.name = brand_input["name"]
        brand.description = brand_input["description"]
        brand.keywords = json.dumps(brand_input.get("keywords", []))
        brand.subreddits = json.dumps(brand_input.get("subreddits", []))
        brand.updated_at = datetime.utcnow()
        
        try:
            db.commit()
            db.refresh(brand)
            return brand
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    @staticmethod
    def delete_brand(db: Session, brand_id: int) -> bool:
        """Delete a brand"""
        brand = db.query(Brand).filter(Brand.id == brand_id).first()
        if not brand:
            return False
        db.delete(brand)
        db.commit()
        return True

class RedditMentionCRUD:
    @staticmethod
    def create_mention(db: Session, mention: RedditMention) -> RedditMention:
        """Create a new Reddit mention"""
        db.add(mention)
        db.commit()
        db.refresh(mention)
        return mention

    @staticmethod
    def get_recent_mentions_for_user_brands(
        db: Session, brand_ids: List[int], since_datetime: datetime
    ) -> List[RedditMention]:
        """Get mentions for specified brand_ids created after since_datetime."""
        if not brand_ids:
            return []
        # First get all mentions
        mentions = (
            db.query(RedditMention)
            .filter(
                RedditMention.brand_id.in_(brand_ids),
                RedditMention.created_at >= since_datetime,
            )
            .order_by(desc(RedditMention.created_at))
            .all()
        )
        
        # Deduplicate by URL, keeping the latest version of each mention
        seen_urls = set()
        unique_mentions = []
        for mention in mentions:
            if mention.url not in seen_urls:
                seen_urls.add(mention.url)
                unique_mentions.append(mention)
        
        return unique_mentions

    @staticmethod
    def get_brand_mentions(
        db: Session,
        brand_id: int,
        skip: int = 0,
        limit: int = 500
    ) -> List[RedditMention]:
        """Get all mentions for a brand"""
        mentions = db.query(RedditMention).filter(
            RedditMention.brand_id == brand_id
        ).order_by(
            desc(RedditMention.created_at)
        ).offset(skip).limit(limit).all()
        
        # Ensure all mentions have required fields with defaults
        for mention in mentions:
            # Handle matching_keywords
            if mention.matching_keywords is None or mention.matching_keywords == "":
                mention.matching_keywords = "[]"
            try:
                json.loads(mention.matching_keywords)
            except json.JSONDecodeError:
                mention.matching_keywords = "[]"
            
            # Set default values for numeric fields
            mention.num_comments = mention.num_comments or 0
            mention.relevance_score = mention.relevance_score or 0
            mention.score = mention.score or 0
            
            # Handle timestamps
            if not mention.created_at:
                mention.created_at = datetime.utcnow()
            mention.created_utc = mention.created_utc or int(mention.created_at.timestamp())
            
            # Handle text fields
            mention.suggested_comment = mention.suggested_comment or ""
            mention.keyword = mention.keyword or ""
            
            # Commit changes
            db.add(mention)
        
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            raise e
        
        return mentions

class RedditCommentCRUD:
    @staticmethod
    def create_comment(db: Session, brand_id: int, post_id: str, post_url: str, comment_text: str, comment_url: str) -> RedditComment:
        """Create a new Reddit comment record"""
        comment = RedditComment(
            brand_id=brand_id,
            post_id=post_id,
            post_url=post_url,
            comment_text=comment_text,
            comment_url=comment_url
        )
        db.add(comment)
        db.commit()
        db.refresh(comment)
        return comment

    @staticmethod
    def get_comment_by_post_id(db: Session, brand_id: int, post_id: str) -> Optional[RedditComment]:
        """Get a comment by post ID and brand ID"""
        return db.query(RedditComment).filter(
            RedditComment.brand_id == brand_id,
            RedditComment.post_id == post_id
        ).first()

    @staticmethod
    def get_brand_comments(db: Session, brand_id: int, skip: int = 0, limit: int = 100) -> List[RedditComment]:
        """Get all comments for a brand"""
        return db.query(RedditComment).filter(
            RedditComment.brand_id == brand_id
        ).offset(skip).limit(limit).all()

    @staticmethod
    def get_user_comment_count_last_24h(db: Session, user_email: str) -> int:
        """Get the number of successful comments (with comment URLs) made by a user in the last 24 hours"""
        yesterday = datetime.utcnow() - timedelta(days=1)
        # Print all comments for debugging
        comments = (
            db.query(RedditComment)
            .join(Brand)
            .filter(Brand.user_email == user_email)
            .filter(RedditComment.created_at >= yesterday)
            .filter(RedditComment.comment_url.isnot(None))  # Only count comments with URLs
            .filter(RedditComment.comment_url != '')  # Ensure URL is not empty
            .all()
        )
        
        # Print comments for debugging
        for comment in comments:
            print(f"Comment ID: {comment.id}, URL: {comment.comment_url}, Created At: {comment.created_at}")
            
        return len(comments)