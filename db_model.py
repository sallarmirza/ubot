# app/models.py
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
)
from sqlalchemy.orm import relationship
from db_manager import Base





class User(Base):
    __tablename__ = "users"
    # user main entity, only created once, no need for updated_at for now
    user_id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, server_default=func.now())

    oauth = relationship("UserOAuth", back_populates="user", uselist=False)
    youtube_channels = relationship("YoutubeChannel", back_populates="user")
    target_channels = relationship("TargetChannel", back_populates="user")
    business_setups = relationship("BusinessSetup", back_populates="user")
    videos = relationship("Videos", back_populates="user")
    target_videos = relationship("TargetVideo", back_populates="user")
    analytics = relationship("Analytics", back_populates="user")


class UserOAuth(Base):
    __tablename__ = "user_oauth"

    oauth_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, unique=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    scopes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="oauth")


class YoutubeChannel(Base):
    __tablename__ = "youtube_channel"

    channel_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    youtube_channel_id = Column(String(100), nullable=False)
    channel_name = Column(String(255), nullable=False)
    channel_subscribers = Column(Integer, nullable=False, default=0)
    channel_views = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="youtube_channels")
    target_channels = relationship("TargetChannel", back_populates="channel")


class TargetChannel(Base):
    __tablename__ = "target_channel"

    target_channel_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    channel_id = Column(Integer, ForeignKey("youtube_channel.channel_id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "channel_id", name="uq_target_channel_user_channel"),
    )

    user = relationship("User", back_populates="target_channels")
    channel = relationship("YoutubeChannel", back_populates="target_channels")
    business_setups = relationship("BusinessSetup", back_populates="target_channel")
    videos = relationship("Videos", back_populates="target_channel")


class BusinessSetup(Base):
    __tablename__ = "business_setup"

    business_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    target_channel_id = Column(
        Integer, ForeignKey("target_channel.target_channel_id"), nullable=False
    )
    business_name = Column(String(255), nullable=False)
    business_services = Column(String(800), nullable=False)
    business_rules = Column(String(300), nullable=True)
    tone = Column(String(50), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="business_setups")
    target_channel = relationship("TargetChannel", back_populates="business_setups")


class Videos(Base):
    __tablename__ = "videos"

    video_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    target_channel_id = Column(
        Integer, ForeignKey("target_channel.target_channel_id"), nullable=False
    )
    youtube_video_id = Column(String(50), nullable=False)
    title = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("target_channel_id", "youtube_video_id", name="uq_videos_channel_youtube_video"),
    )

    user = relationship("User", back_populates="videos")
    target_channel = relationship("TargetChannel", back_populates="videos")
    target_videos = relationship("TargetVideo", back_populates="video")


class TargetVideo(Base):
    __tablename__ = "target_video"

    selected_video_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    video_id = Column(Integer, ForeignKey("videos.video_id"), nullable=False)
    likes = Column(Integer, nullable=False, default=0)
    comments = Column(Integer, nullable=False, default=0)
    views = Column(Integer, nullable=False, default=0)
    description = Column(String(800), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "video_id", name="uq_target_video_user_video"),
    )

    user = relationship("User", back_populates="target_videos")
    video = relationship("Videos", back_populates="target_videos")
    comment_list = relationship("Comments", back_populates="target_video")
    analytics = relationship("Analytics", back_populates="target_video")


class Comments(Base):
    __tablename__ = "comments"

    comment_id = Column(Integer, primary_key=True)
    selected_video_id = Column(
        Integer, ForeignKey("target_video.selected_video_id"), nullable=False
    )
    youtube_comment_id = Column(String(100), nullable=False, unique=True)
    comment_text = Column(String(800), nullable=False)
    ai_reply = Column(String(800), nullable=True)
    is_replied = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    target_video = relationship("TargetVideo", back_populates="comment_list")


class Analytics(Base):
    __tablename__ = "analytics"

    analytics_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    selected_video_id = Column(
        Integer, ForeignKey("target_video.selected_video_id"), nullable=False
    )
    likes = Column(Integer, nullable=False, default=0)
    comments = Column(Integer, nullable=False, default=0)
    views = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="analytics")
    target_video = relationship("TargetVideo", back_populates="analytics")