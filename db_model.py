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
    """One YouTube comment OR one reply, saved for a selected video.

    Top-level comments have parent_comment_id = None.
    Replies point to their parent comment through parent_comment_id.
    """

    __tablename__ = "comments"
    __table_args__ = (
        # The same YouTube comment can be saved once per selected video.
        # (Two users may select the same video, so youtube_comment_id alone
        # is NOT unique across the whole table.)
        UniqueConstraint(
            "selected_video_id",
            "youtube_comment_id",
            name="uq_comments_selected_video_youtube_comment",
        ),
    )

    # Our own internal ID for this comment.
    comment_id = Column(Integer, primary_key=True)

    # Which selected video this comment belongs to (target_video table).
    selected_video_id = Column(
        Integer, ForeignKey("target_video.selected_video_id"), nullable=False
    )

    # Self-reference: for a reply, this is the comment_id of the parent comment.
    # NULL means this row is a top-level comment.
    parent_comment_id = Column(Integer, ForeignKey("comments.comment_id"), nullable=True)

    # The comment's ID on YouTube (e.g. "UgxABC..."), used when posting replies.
    youtube_comment_id = Column(String(100), nullable=False)

    # The text written by the viewer (cut to 800 characters to fit the column).
    comment_text = Column(String(800), nullable=False)

    # The reply generated by the AI. NULL until a reply is generated.
    ai_reply = Column(String(800), nullable=True)

    # True once the AI reply has been posted on YouTube.
    is_replied = Column(Boolean, nullable=False, default=False)

    # Set by the database when the row is inserted / updated.
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # The selected video this comment belongs to.
    target_video = relationship("TargetVideo", back_populates="comment_list")

    # Many-to-one: the parent of this reply.
    # remote_side tells SQLAlchemy that comment_id is the "parent" side,
    # which is required for a table that points to itself.
    parent_comment = relationship(
        "Comments", remote_side=[comment_id], back_populates="replies"
    )

    # One-to-many: all replies of this comment.
    # cascade="all, delete-orphan": deleting a parent also deletes its replies,
    # and a reply removed from this list is deleted from the database too.
    replies = relationship(
        "Comments", back_populates="parent_comment", cascade="all, delete-orphan"
    )


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