# app/crud.py
from sqlalchemy.orm import Session
from sqlalchemy import desc
import models
from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import HTTPException
import json

class UserCRUD:
    @staticmethod
    def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
        """Get user by email"""
        return db.query(models.User).filter(models.User.email == email).first()

    @staticmethod
    def create_user(db: Session, email: str) -> models.User:
        """Create new user if doesn't exist"""
        existing_user = UserCRUD.get_user_by_email(db, email)
        if existing_user:
            return existing_user
            
        db_user = models.User(email=email)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user

    @staticmethod
    def update_last_login(db: Session, email: str) -> models.User:
        """Update user's last login time"""
        db_user = UserCRUD.get_user_by_email(db, email)
        if db_user:
            db_user.last_login = datetime.utcnow()
            db.commit()
            db.refresh(db_user)
        return db_user

class BrandCRUD:
    @staticmethod
    def create_brand(
        db: Session,
        brand_input: dict,
        user_email: str
    ) -> models.Brand:
        """Create a new brand"""
        try:
            db_brand = models.Brand(
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
    def get_brand(db: Session, brand_id: int, user_email: str) -> Optional[models.Brand]:
        """Get a specific brand by ID and user email"""
        user = UserCRUD.get_user_by_email(db, user_email)
        if not user:
            return None
        return db.query(models.Brand).filter(models.Brand.id == brand_id, models.Brand.user_email == user_email).first()

    @staticmethod
    def get_user_brands(db: Session, user_email: str, skip: int = 0, limit: int = 50) -> List[models.Brand]:
        """Get all brands for a user"""
        return db.query(models.Brand).filter(models.Brand.user_email == user_email).offset(skip).limit(limit).all()

    @staticmethod
    def update_brand_keywords(db: Session, brand_id: int, keywords: List[str]) -> Optional[models.Brand]:
        """Update brand keywords"""
        brand = db.query(models.Brand).filter(models.Brand.id == brand_id).first()
        if not brand:
            return None
            
        brand.keywords = json.dumps(keywords)
        brand.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(brand)
        return brand

    @staticmethod
    def update_brand_subreddits(db: Session, brand_id: int, subreddits: List[str]) -> Optional[models.Brand]:
        """Update brand subreddits"""
        brand = db.query(models.Brand).filter(models.Brand.id == brand_id).first()
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
    ) -> Optional[models.Brand]:
        """Update brand details"""
        brand = db.query(models.Brand).filter(
            models.Brand.id == brand_id,
            models.Brand.user_email == user_email
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
        brand = db.query(models.Brand).filter(models.Brand.id == brand_id).first()
        if not brand:
            return False
        db.delete(brand)
        db.commit()
        return True

class RedditMentionCRUD:
    @staticmethod
    def create_mention(db: Session, mention: models.RedditMention) -> models.RedditMention:
        """Create a new Reddit mention"""
        db.add(mention)
        db.commit()
        db.refresh(mention)
        return mention

    @staticmethod
    def get_brand_mentions(
        db: Session,
        brand_id: int,
        skip: int = 0,
        limit: int = 500
    ) -> List[models.RedditMention]:
        """Get all mentions for a brand"""
        mentions = db.query(models.RedditMention).filter(
            models.RedditMention.brand_id == brand_id
        ).order_by(
            desc(models.RedditMention.created_at)
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