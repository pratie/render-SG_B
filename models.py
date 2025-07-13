# app/models.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pydantic import BaseModel, EmailStr, validator, Field
from typing import List, Optional
from datetime import datetime, timedelta
import json

from database import Base

# SQLAlchemy Models
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, default=datetime.utcnow)
    has_paid = Column(Boolean, default=False, nullable=False)
    payment_date = Column(DateTime, nullable=True)
    stripe_payment_id = Column(String, nullable=True)
    dodo_payment_id = Column(String, nullable=True)
    subscription_plan = Column(String, default="none", nullable=False)  # "none", "monthly", "6month", "annual"
    plan_expires_at = Column(DateTime, nullable=True)

    # Relationships
    brands = relationship("Brand", back_populates="user", foreign_keys="Brand.user_email")
    reddit_oauth_states = relationship("RedditOAuthState", back_populates="user", cascade="all, delete-orphan")

class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, ForeignKey("users.email"))
    name = Column(String)
    description = Column(String)
    keywords = Column(String, default="[]")  # JSON string
    subreddits = Column(String, default="[]")  # JSON string
    last_analyzed = Column(DateTime, nullable=True)
    subreddit_last_analyzed = Column(String, default="{}")  # JSON dict of subreddit -> timestamp
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="brands")
    mentions = relationship("RedditMention", back_populates="brand", cascade="all, delete-orphan")
    comments = relationship("RedditComment", back_populates="brand", cascade="all, delete-orphan")

    @property
    def keywords_list(self) -> List[str]:
        """Get keywords as a list"""
        try:
            return json.loads(self.keywords or "[]")
        except json.JSONDecodeError:
            return []

    @keywords_list.setter
    def keywords_list(self, value: List[str]):
        """Set keywords from a list"""
        self.keywords = json.dumps(value)

    @property
    def subreddits_list(self) -> List[str]:
        """Get subreddits as a list"""
        try:
            return json.loads(self.subreddits or "[]")
        except json.JSONDecodeError:
            return []

    @subreddits_list.setter
    def subreddits_list(self, value: List[str]):
        """Set subreddits from a list"""
        self.subreddits = json.dumps(value)

    @property
    def subreddit_last_analyzed_dict(self) -> dict:
        """Get subreddit last analyzed times as a dictionary"""
        try:
            return json.loads(self.subreddit_last_analyzed or "{}")
        except json.JSONDecodeError:
            return {}
    
    @subreddit_last_analyzed_dict.setter
    def subreddit_last_analyzed_dict(self, value: dict):
        """Store subreddit last analyzed times as JSON"""
        self.subreddit_last_analyzed = json.dumps(value)

class RedditMention(Base):
    __tablename__ = "reddit_mentions"

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"))
    title = Column(String)
    content = Column(Text)
    url = Column(String)
    subreddit = Column(String)
    keyword = Column(String)  # Primary matching keyword
    matching_keywords = Column(String, default="[]")  # All matching keywords as JSON
    score = Column(Integer, default=0)
    num_comments = Column(Integer, default=0)
    relevance_score = Column(Integer, default=0)
    suggested_comment = Column(Text, default="")
    intent = Column(String, nullable=True)  # Added intent column
    created_at = Column(DateTime, default=datetime.utcnow)
    created_utc = Column(Integer, default=lambda: int(datetime.utcnow().timestamp()))

    # Relationships
    brand = relationship("Brand", back_populates="mentions")

    def __init__(self, **kwargs):
        # Convert lists to JSON strings for storage
        if 'matching_keywords' in kwargs:
            if isinstance(kwargs['matching_keywords'], list):
                kwargs['matching_keywords'] = json.dumps(kwargs['matching_keywords'])
            elif isinstance(kwargs['matching_keywords'], str):
                try:
                    parsed = json.loads(kwargs['matching_keywords'])
                    if not isinstance(parsed, list):
                        kwargs['matching_keywords'] = "[]"
                except json.JSONDecodeError:
                    kwargs['matching_keywords'] = "[]"
        
        # Ensure numeric fields have defaults
        kwargs.setdefault('score', 0)
        kwargs.setdefault('num_comments', 0)
        kwargs.setdefault('relevance_score', 0)
        kwargs.setdefault('suggested_comment', "")
        kwargs.setdefault('intent', None) # Default intent to None
        kwargs.setdefault('created_utc', int(datetime.utcnow().timestamp()))
        
        super().__init__(**kwargs)

    @property
    def matching_keywords_list(self) -> List[str]:
        """Get keywords as a Python list"""
        try:
            return json.loads(self.matching_keywords) if self.matching_keywords else []
        except json.JSONDecodeError:
            return []

    @matching_keywords_list.setter
    def matching_keywords_list(self, value: List[str]) -> None:
        """Store keywords as a JSON string"""
        self.matching_keywords = json.dumps(value) if value else "[]"

class RedditComment(Base):
    __tablename__ = "reddit_comments"

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"))
    post_id = Column(String, index=True)  # Reddit post ID
    post_url = Column(String)
    comment_text = Column(Text)
    comment_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    brand = relationship("Brand", back_populates="comments")

    class Config:
        from_attributes = True


class RedditToken(Base):
    __tablename__ = "reddit_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, ForeignKey("users.email"), unique=True)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=False)
    token_type = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    expires_at = Column(Integer, nullable=False)  # Unix timestamp
    reddit_username = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = relationship("User", backref="reddit_token")

class RedditOAuthState(Base):
    __tablename__ = "reddit_oauth_states"

    state = Column(String, primary_key=True)
    user_email = Column(String, ForeignKey("users.email"))
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(minutes=10))

    user = relationship("User", back_populates="reddit_oauth_states")

class MagicToken(Base):
    __tablename__ = "magic_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, index=True)
    token = Column(String, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class AlertSetting(Base):
    __tablename__ = "alert_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, unique=True, index=True)
    telegram_chat_id = Column(String, nullable=True)
    enable_telegram_alerts = Column(Boolean, default=False)
    enable_email_alerts = Column(Boolean, default=False)
    alert_threshold_score = Column(Integer, default=100)  # Minimum Reddit score to trigger alert
    alert_frequency = Column(String, default="daily")  # daily, hourly, immediate
    is_active = Column(Boolean, default=True)  # Whether alerts are active for this user
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# User Preferences Models
class UserPreferences(Base):
    __tablename__ = "user_preferences"
    
    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, unique=True, index=True)
    tone = Column(String, nullable=True)  # friendly, professional, technical
    response_style = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class UserPreferencesInput(BaseModel):
    tone: str = Field(description="Communication tone preference (friendly, professional, technical)")
    response_style: Optional[str] = Field(None, description="Custom response style template")

class UserPreferencesResponse(BaseModel):
    tone: str
    response_style: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Pydantic Models for API
class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    id: int
    created_at: datetime
    last_login: Optional[datetime]
    has_paid: bool = False
    payment_date: Optional[datetime] = None
    stripe_payment_id: Optional[str] = None
    dodo_payment_id: Optional[str] = None
    subscription_plan: str = "none"
    plan_expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class PlanSelectionInput(BaseModel):
    plan: str = Field(..., description="Subscription plan: 'monthly', '6month', or 'annual'")

class PlanSelectionResponse(BaseModel):
    checkout_url: str
    plan: str
    price: str

class AlertSettingInput(BaseModel):
    telegram_chat_id: Optional[str] = Field('', description="Telegram chat ID for alerts")
    enable_telegram_alerts: Optional[bool] = Field(False, description="Enable Telegram alerts")
    enable_email_alerts: Optional[bool] = Field(False, description="Enable email alerts")
    alert_threshold_score: Optional[int] = Field(100, description="Minimum Reddit post score to trigger alerts")
    alert_frequency: Optional[str] = Field("daily", description="Frequency of alerts (daily, hourly, immediate)")
    is_active: Optional[bool] = Field(True, description="Whether alerts are active for this user")

class AlertSettingResponse(BaseModel):
    telegram_chat_id: str
    enable_telegram_alerts: bool
    enable_email_alerts: bool
    alert_threshold_score: int
    alert_frequency: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class BrandInput(BaseModel):
    name: str
    description: str
    keywords: Optional[List[str]] = []
    subreddits: Optional[List[str]] = []

class AnalysisInput(BaseModel):
    brand_id: int
    keywords: List[str]
    subreddits: List[str]
    time_period: Optional[str] = "month"  # week, month, year
    limit: Optional[int] = 1000

class KeywordResponse(BaseModel):
    keywords: List[str]
    subreddits: List[str]

class RedditMentionResponse(BaseModel):
    id: int
    brand_id: int
    title: str
    content: str
    url: str
    subreddit: str
    keyword: str
    matching_keywords: List[str]
    matched_keywords: List[str] = []  # Alias for frontend compatibility
    score: int = 0
    num_comments: int = 0
    relevance_score: int = 0
    suggested_comment: str = ""
    intent: str = "unknown"
    created_at: datetime
    created_utc: int
    formatted_date: str = ""

    @validator('matching_keywords', pre=True)
    def parse_matching_keywords(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return v or []

    @validator('matched_keywords', always=True)
    def set_matched_keywords(cls, v, values):
        return values.get('matching_keywords', [])

    @validator('created_utc', pre=True)
    def ensure_created_utc(cls, v, values):
        if v is None and 'created_at' in values:
            return int(values['created_at'].timestamp())
        return v or int(datetime.utcnow().timestamp())

    @validator('formatted_date', always=True)
    def format_date(cls, v, values):
        if 'created_at' in values:
            return values['created_at'].strftime('%Y-%m-%d %H:%M:%S')
        return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    class Config:
        orm_mode = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    @classmethod
    def from_orm(cls, obj):
        if not hasattr(obj, '__dict__'):
            return super().from_orm(obj)
        
        # Create a copy of the dict to avoid modifying the original
        data = obj.__dict__.copy()
        
        # Remove SQLAlchemy internal state
        data.pop('_sa_instance_state', None)
        
        # Handle the matching_keywords field
        if isinstance(data.get('matching_keywords'), str):
            try:
                data['matching_keywords'] = json.loads(data['matching_keywords'])
            except json.JSONDecodeError:
                data['matching_keywords'] = []
        
        # Set default values for optional fields
        data.setdefault('score', 0)
        data.setdefault('num_comments', 0)
        data.setdefault('relevance_score', 0)
        data.setdefault('suggested_comment', "")
        data.setdefault('created_utc', int(datetime.utcnow().timestamp()))
        # Ensure intent is a string, default to 'unknown' if None or missing
        if not data.get('intent'):
            data['intent'] = 'unknown'
        return cls(**data)

class AnalysisResponse(BaseModel):
    status: str = "success"
    posts: List[dict]
    matching_posts: List[dict]

    @validator('posts', 'matching_posts', pre=True)
    def validate_posts(cls, v):
        # Ensure each post has the required fields
        required_fields = {'title', 'url', 'subreddit', 'created_utc', 'score', 'num_comments', 'relevance_score', 'suggested_comment'}
        for post in v:
            missing_fields = required_fields - set(post.keys())
            if missing_fields:
                raise ValueError(f"Missing required fields in post: {missing_fields}")
        return v

    class Config:
        orm_mode = True

    @validator('matching_posts', pre=True, always=True)
    def set_matching_posts(cls, v, values):
        # For backward compatibility, if matching_posts is not provided, use posts
        return v or values.get('posts', [])

class BrandResponse(BaseModel):
    id: int
    name: str
    description: str
    keywords: List[str]
    subreddits: List[str]
    created_at: datetime
    updated_at: datetime
    user_email: str
    last_analyzed: Optional[datetime]

    class Config:
        orm_mode = True

    @validator('keywords', 'subreddits', pre=True)
    def parse_json_list(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

    @classmethod
    def from_orm(cls, obj):
        if hasattr(obj, '__dict__'):
            # Create a copy of the dict to avoid modifying the original
            data = obj.__dict__.copy()
            
            # Remove SQLAlchemy internal state
            data.pop('_sa_instance_state', None)
            
            # Handle keywords and subreddits
            data['keywords'] = obj.keywords_list if hasattr(obj, 'keywords_list') else obj.keywords
            data['subreddits'] = obj.subreddits_list if hasattr(obj, 'subreddits_list') else obj.subreddits
            
            return cls(**data)
        return cls(**obj)

class CommentInput(BaseModel):
    post_title: str
    post_content: str
    brand_id: int

class CommentResponse(BaseModel):
    comment: str

class PostCommentInput(BaseModel):
    post_title: str
    post_content: Optional[str] = ""
    brand_id: int
    post_url: str
    comment_text: str

class PostCommentResponse(BaseModel):
    comment: str
    comment_url: str
    status: str = "success"

class PostSearchResult(BaseModel):
    id: str
    author: Optional[str]
    title: str
    score: int
    created_utc: datetime
    subreddit: str
    num_comments: int
    permalink: str

    class Config:
        from_attributes = True