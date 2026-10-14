# db_model.py
# SQLAlchemy models (PostgreSQL). Chain: User -> YoutubeChannel -> TargetChannel -> BusinessSetup / Videos
# -> TargetVideo -> Comments / Analytics.
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    false,
)
from sqlalchemy.orm import declarative_base, relationship

# Shared base class; every model below inherits from it
Base = declarative_base()


def _ts():
    """Timezone-aware timestamp column set by the database on insert."""
    return Column(DateTime(timezone=True), server_default=func.now())


def _ts_updated():
    """Timezone-aware timestamp column refreshed on every update."""
    return Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    __tablename__ = "users"
    # user main entity, only created once, no need for updated_at for now
    user_id = Column(Integer, primary_key=True)
    # Google's stable user id ("sub"): how a returning user is recognized at login
    google_sub = Column(String(100), nullable=False, unique=True)
    email = Column(String(255), nullable=True)
    created_at = _ts()

    oauth = relationship("UserOAuth", back_populates="user", uselist=False)
    youtube_channels = relationship("YoutubeChannel", back_populates="user")
    target_channels = relationship("TargetChannel", back_populates="user")
    business_setups = relationship("BusinessSetup", back_populates="user")
    videos = relationship("Videos", back_populates="user")
    target_videos = relationship("TargetVideo", back_populates="user")
    analytics = relationship("Analytics", back_populates="user")


class UserOAuth(Base):
    """Google tokens, one row per user."""

    __tablename__ = "user_oauth"

    oauth_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, unique=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    # Timezone-aware: compare against datetime.now(timezone.utc)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    scopes = Column(Text, nullable=True)
    created_at = _ts()
    updated_at = _ts_updated()

    user = relationship("User", back_populates="oauth")


class YoutubeChannel(Base):
    """A YouTube channel the user selected (saved after /channels/select)."""

    __tablename__ = "youtube_channel"

    channel_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    youtube_channel_id = Column(String(100), nullable=False)
    channel_name = Column(String(255), nullable=False)
    # BigInteger: Postgres INTEGER is 32-bit (max ~2.1 billion)
    channel_subscribers = Column(BigInteger, nullable=False, default=0)
    channel_views = Column(BigInteger, nullable=False, default=0)
    created_at = _ts()
    updated_at = _ts_updated()

    # One row per channel per user (upsert_channel relies on this).
    # The unique constraint also indexes user_id.
    __table_args__ = (
        UniqueConstraint("user_id", "youtube_channel_id", name="uq_youtube_channel_user_channel"),
    )

    user = relationship("User", back_populates="youtube_channels")
    target_channels = relationship("TargetChannel", back_populates="channel")


class TargetChannel(Base):
    """The channel the user chose to manage with the bot."""

    __tablename__ = "target_channel"

    target_channel_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    channel_id = Column(
        Integer, ForeignKey("youtube_channel.channel_id"), nullable=False, index=True
    )
    created_at = _ts()
    updated_at = _ts_updated()

    # The unique constraint also indexes user_id.
    __table_args__ = (
        UniqueConstraint("user_id", "channel_id", name="uq_target_channel_user_channel"),
    )

    user = relationship("User", back_populates="target_channels")
    channel = relationship("YoutubeChannel", back_populates="target_channels")
    business_setups = relationship("BusinessSetup", back_populates="target_channel")
    videos = relationship("Videos", back_populates="target_channel")


class BusinessSetup(Base):
    """Business persona (name, services, rules, tone) for one target channel."""

    __tablename__ = "business_setup"

    business_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    target_channel_id = Column(
        Integer, ForeignKey("target_channel.target_channel_id"), nullable=False
    )
    business_name = Column(String(255), nullable=False)
    business_services = Column(String(800), nullable=False)
    business_rules = Column(String(300), nullable=True)
    tone = Column(String(50), nullable=True)
    created_at = _ts()
    updated_at = _ts_updated()

    # One persona per target channel (this also indexes target_channel_id)
    __table_args__ = (
        UniqueConstraint("target_channel_id", name="uq_business_setup_target_channel"),
    )

    user = relationship("User", back_populates="business_setups")
    target_channel = relationship("TargetChannel", back_populates="business_setups")


class Videos(Base):
    __tablename__ = "videos"

    video_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    target_channel_id = Column(
        Integer, ForeignKey("target_channel.target_channel_id"), nullable=False
    )
    youtube_video_id = Column(String(50), nullable=False)
    title = Column(String(255), nullable=True)
    created_at = _ts()
    updated_at = _ts_updated()

    # The unique constraint also indexes target_channel_id
    __table_args__ = (
        UniqueConstraint("target_channel_id", "youtube_video_id", name="uq_videos_channel_youtube_video"),
    )

    user = relationship("User", back_populates="videos")
    target_channel = relationship("TargetChannel", back_populates="videos")
    target_videos = relationship("TargetVideo", back_populates="video")


class TargetVideo(Base):
    """A video the user selected for auto-replies."""

    __tablename__ = "target_video"

    selected_video_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    video_id = Column(Integer, ForeignKey("videos.video_id"), nullable=False, index=True)
    likes = Column(BigInteger, nullable=False, default=0)
    comments = Column(BigInteger, nullable=False, default=0)
    views = Column(BigInteger, nullable=False, default=0)
    # Text: YouTube descriptions can be up to 5,000 characters
    description = Column(Text, nullable=True)
    prompt_context = Column(Text, nullable=True)
    created_at = _ts()
    updated_at = _ts_updated()

    # The unique constraint also indexes user_id
    __table_args__ = (
        UniqueConstraint("user_id", "video_id", name="uq_target_video_user_video"),
    )

    user = relationship("User", back_populates="target_videos")
    video = relationship("Videos", back_populates="target_videos")
    comment_list = relationship(
        "Comments", back_populates="target_video", cascade="all, delete-orphan"
    )
    analytics = relationship(
        "Analytics", back_populates="target_video", cascade="all, delete-orphan"
    )


class Comments(Base):
    """One YouTube comment OR one reply, saved for a selected video.

    Top-level comments have parent_comment_id = None.
    Replies point to their parent comment through parent_comment_id.
    """

    __tablename__ = "comments"
    __table_args__ = (
        # The same YouTube comment can be saved once per selected video.
        # (Two users may select the same video, so youtube_comment_id alone
        # is NOT unique across the whole table.) This also indexes selected_video_id.
        UniqueConstraint(
            "selected_video_id",
            "youtube_comment_id",
            name="uq_comments_selected_video_youtube_comment",
        ),
        # Speeds up "all drafts for this video" style queries
        Index("ix_comments_video_reply_status", "selected_video_id", "reply_status"),
    )

    # Our own internal ID for this comment.
    comment_id = Column(Integer, primary_key=True)

    # Which selected video this comment belongs to (target_video table).
    selected_video_id = Column(
        Integer,
        ForeignKey("target_video.selected_video_id", ondelete="CASCADE"),
        nullable=False,
    )

    # Self-reference: for a reply, this is the comment_id of the parent comment.
    # NULL means this row is a top-level comment.
    parent_comment_id = Column(
        Integer,
        ForeignKey("comments.comment_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # The comment's ID on YouTube (e.g. "UgxABC..."), used when posting replies.
    youtube_comment_id = Column(String(100), nullable=False)

    # The text written by the viewer. Postgres enforces the length, so cut to
    # 800 characters (and strip "\x00") before saving.
    comment_text = Column(String(800), nullable=False)

    # The reply generated by the AI. NULL until a reply is generated.
    # Also enforced at 800 characters: truncate before saving.
    ai_reply = Column(String(800), nullable=True)

    # True once the AI reply has been posted on YouTube.
    is_replied = Column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    youtube_reply_id = Column(String(100), nullable=True)
    reply_status = Column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    # Timezone-aware: compare against datetime.now(timezone.utc)
    reply_posting_started_at = Column(DateTime(timezone=True), nullable=True)

    # Set by the database when the row is inserted / updated.
    created_at = _ts()
    updated_at = _ts_updated()

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
    """Snapshot of a selected video's stats."""

    __tablename__ = "analytics"

    analytics_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    selected_video_id = Column(
        Integer,
        ForeignKey("target_video.selected_video_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    likes = Column(BigInteger, nullable=False, default=0)
    comments = Column(BigInteger, nullable=False, default=0)
    views = Column(BigInteger, nullable=False, default=0)
    created_at = _ts()
    updated_at = _ts_updated()

    user = relationship("User", back_populates="analytics")
    target_video = relationship("TargetVideo", back_populates="analytics")