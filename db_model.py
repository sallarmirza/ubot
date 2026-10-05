from datetime import datetime, timezone
from sqlalchemy.orm import declarative_base
from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric,
    String, Boolean, Text, UniqueConstraint, false,
)
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    user_id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class youtubechannel (Base):
    __tablename__ = 'channel'
    channel_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    channel_name = Column(String(255), nullable=False, unique=False)
    channel_subscribers = Column(Integer, nullable=False, default=0)
    channel_views = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class target_channel (Base):
    __tablename__ = 'selected_channel'
    selected_channel_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    channel_id = Column(Integer, ForeignKey('channel.channel_id'), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    __table_args__ = (
    UniqueConstraint("user_id", "channel_id", name="uq_user_channel"),
)
    
class business_setup (Base):
    __tablename__ = 'business_setup'
    business_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    selected_channel_id = Column(Integer, ForeignKey('selected_channel.selected_channel_id'), nullable=False)
    business_name = Column(String(255), nullable=False)
    business_services = Column(String(800), nullable=False, unique=False)
    business_rules = Column(String(300), nullable=True)
    tone = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class videos (Base):
    __tablename__ = 'videos'
    video_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    selected_channel_id = Column(Integer, ForeignKey('selected_channel.selected_channel_id'), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class selected_video (Base):
    __tablename__ = 'selected_video'
    selected_video_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    channel_id = Column(Integer, ForeignKey('youtubechannel.channel_id'), nullable=False)
    video_id = Column(Integer, ForeignKey('videos.video_id'), nullable=False)
    likes = Column(Integer, nullable=False, default=0)
    comments = Column(Integer, nullable=False, default=0)
    views = Column(Integer, nullable=False, default=0)
    description = Column(String(800), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    __table_args__ = (
    UniqueConstraint("user_id", "channel_id", name="uq_user_channel"),
)

class coments (Base):
    __tablename__ = 'comments'
    comment_id = Column(Integer, primary_key=True)
    selected_video_id = Column(Integer, ForeignKey('selected_video.selected_video_id'), nullable=False)
    comment_text = Column(String(800), nullable=False)
    ai_reply = Column(String(800), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

class anaalytics (Base):
    __tablename__ = 'analytics'
    analytics_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    selected_video_id = Column(Integer, ForeignKey('selected_video.selected_video_id'), nullable=False)
    likes = Column(Integer, nullable=False, default=0)
    comments = Column(Integer, nullable=False, default=0)
    views = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))