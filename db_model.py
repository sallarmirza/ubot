"""
models.py
=========

SQLAlchemy ORM models for the YouTube channel / video / comment AI-reply system.

Data hierarchy (parent -> child):

    User
     ├── Channel                (channels that belong to the user)
     │     └── SelectedChannel  (channels the user chose to automate)
     │           ├── PersonaSetup   (1:1 - business persona for AI replies)
     │           └── Video          (videos fetched for that channel)
     │                 └── SelectedVideo   (videos the user chose to track)
     │                       ├── Comment   (comments + AI replies)
     │                       └── Analytics (likes / comments / views snapshots)

Deletion strategy
-----------------
* The DATABASE enforces cascade deletes through `ondelete="CASCADE"` on every
  foreign key.
* The ORM relationships use `cascade="all, delete"` + `passive_deletes=True`,
  which tells SQLAlchemy to trust the database to remove child rows instead of
  loading every child into memory first (much faster for big tables).
"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship


# ============================================================
# BASE
# ============================================================

# Every model below inherits from this Base so SQLAlchemy can track
# them in one metadata object (used for create_all() and migrations).
Base = declarative_base()


# ============================================================
# HELPERS
# ============================================================

def utcnow() -> datetime:
    """
    Return the current time as a timezone-aware UTC datetime.

    FIX: the original code repeated `lambda: datetime.now(timezone.utc)`
    in every table. A single named function is cleaner and easier to test.
    """
    return datetime.now(timezone.utc)


class TimestampMixin:
    """
    Adds `created_at` and `updated_at` columns to any model that inherits it.

    * created_at -> set once, when the row is first inserted.
    * updated_at -> set on insert and refreshed automatically on every UPDATE
                    (through SQLAlchemy's `onupdate`).

    FIX: the original code copy-pasted these two columns into every class.
    A mixin removes the duplication (DRY) and guarantees every table
    uses exactly the same definition.
    """

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


# ============================================================
# USER
# ============================================================

class User(TimestampMixin, Base):
    """
    An application user. Root of the whole hierarchy: deleting a user
    removes all of their channels, videos, comments and analytics.
    """

    __tablename__ = "users"

    user_id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------
    # NOTE: `passive_deletes=True` lets the DB's ON DELETE CASCADE do the work.

    channels = relationship(
        "Channel",
        back_populates="user",
        cascade="all, delete",
        passive_deletes=True,
    )

    selected_channels = relationship(
        "SelectedChannel",
        back_populates="user",
        cascade="all, delete",
        passive_deletes=True,
    )

    persona_setups = relationship(
        "PersonaSetup",
        back_populates="user",
        cascade="all, delete",
        passive_deletes=True,
    )

    videos = relationship(
        "Video",
        back_populates="user",
        cascade="all, delete",
        passive_deletes=True,
    )

    selected_videos = relationship(
        "SelectedVideo",
        back_populates="user",
        cascade="all, delete",
        passive_deletes=True,
    )

    comments = relationship(
        "Comment",
        back_populates="user",
        cascade="all, delete",
        passive_deletes=True,
    )

    analytics = relationship(
        "Analytics",
        back_populates="user",
        cascade="all, delete",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<User user_id={self.user_id}>"


# ============================================================
# CHANNEL
# ============================================================

class Channel(TimestampMixin, Base):
    """
    A channel that belongs to a user, with its basic public stats.
    A user cannot have two channels with the same name.
    """

    __tablename__ = "channel"

    channel_id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # Owner of the channel. Indexed because we filter by user very often.
    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    channel_name = Column(
        String(255),
        nullable=False,
    )

    # FIX: BigInteger instead of Integer. A normal 32-bit Integer overflows
    # at ~2.1 billion, and big channels' total views can exceed that.
    # `server_default` also makes raw SQL inserts safe (not only ORM inserts).
    channel_subscribers = Column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    channel_views = Column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

    user = relationship(
        "User",
        back_populates="channels",
    )

    selected_channels = relationship(
        "SelectedChannel",
        back_populates="channel",
        cascade="all, delete",
        passive_deletes=True,
    )

    # --------------------------------------------------------
    # Constraints
    # --------------------------------------------------------

    __table_args__ = (
        # One user cannot register the same channel name twice.
        UniqueConstraint(
            "user_id",
            "channel_name",
            name="uq_user_channel_name",
        ),
        # Counters can never be negative.
        CheckConstraint(
            "channel_subscribers >= 0",
            name="ck_channel_subscribers_non_negative",
        ),
        CheckConstraint(
            "channel_views >= 0",
            name="ck_channel_views_non_negative",
        ),
    )

    def __repr__(self) -> str:
        return f"<Channel channel_id={self.channel_id} name={self.channel_name!r}>"


# ============================================================
# SELECTED CHANNEL
# ============================================================

class SelectedChannel(TimestampMixin, Base):
    """
    A channel the user has chosen to activate (e.g. for AI auto-replies).
    Each (user, channel) pair can be selected only once.
    """

    __tablename__ = "selected_channel"

    selected_channel_id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    channel_id = Column(
        Integer,
        ForeignKey("channel.channel_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

    user = relationship(
        "User",
        back_populates="selected_channels",
    )

    channel = relationship(
        "Channel",
        back_populates="selected_channels",
    )

    # One-to-one: a selected channel has at most one persona.
    # `uselist=False` makes this a single object instead of a list.
    persona_setup = relationship(
        "PersonaSetup",
        back_populates="selected_channel",
        uselist=False,
        cascade="all, delete",
        passive_deletes=True,
    )

    videos = relationship(
        "Video",
        back_populates="selected_channel",
        cascade="all, delete",
        passive_deletes=True,
    )

    # --------------------------------------------------------
    # Constraints
    # --------------------------------------------------------

    __table_args__ = (
        # The same user cannot select the same channel twice.
        UniqueConstraint(
            "user_id",
            "channel_id",
            name="uq_user_selected_channel",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SelectedChannel id={self.selected_channel_id} "
            f"user_id={self.user_id} channel_id={self.channel_id}>"
        )


# ============================================================
# PERSONA SETUP
# ============================================================

class PersonaSetup(TimestampMixin, Base):
    """
    Business persona used by the AI when replying on a selected channel
    (business name, services, rules and tone). One persona per selected channel.
    """

    __tablename__ = "persona_setup"

    persona_id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # `unique=True` enforces the one-to-one relationship at DB level.
    # FIX: removed the extra `index=True`. A unique constraint already
    # creates an index, so having both created a duplicate, wasteful index.
    selected_channel_id = Column(
        Integer,
        ForeignKey(
            "selected_channel.selected_channel_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        unique=True,
    )

    business_name = Column(
        String(255),
        nullable=False,
    )

    business_services = Column(
        String(800),
        nullable=False,
    )

    # Optional rules the AI must follow (e.g. "never promise refunds").
    business_rules = Column(
        String(300),
        nullable=True,
    )

    # Optional reply tone (e.g. "friendly", "professional").
    tone = Column(
        String(50),
        nullable=True,
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

    user = relationship(
        "User",
        back_populates="persona_setups",
    )

    selected_channel = relationship(
        "SelectedChannel",
        back_populates="persona_setup",
    )

    def __repr__(self) -> str:
        return f"<PersonaSetup persona_id={self.persona_id} business={self.business_name!r}>"


# ============================================================
# VIDEO
# ============================================================

class Video(TimestampMixin, Base):
    """
    A video that belongs to a selected channel.

    FIX (important): the original used `delete-orphan` on this table, which
    has TWO parents (User and SelectedChannel). With two delete-orphan parents,
    SQLAlchemy raises "is an orphan" errors when a Video is created while only
    one parent is attached through a relationship. Using plain
    `cascade="all, delete"` (+ DB-level ON DELETE CASCADE) avoids that bug.
    """

    __tablename__ = "videos"

    video_id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    selected_channel_id = Column(
        Integer,
        ForeignKey(
            "selected_channel.selected_channel_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

    user = relationship(
        "User",
        back_populates="videos",
    )

    selected_channel = relationship(
        "SelectedChannel",
        back_populates="videos",
    )

    selected_videos = relationship(
        "SelectedVideo",
        back_populates="video",
        cascade="all, delete",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Video video_id={self.video_id} selected_channel_id={self.selected_channel_id}>"


# ============================================================
# SELECTED VIDEO
# ============================================================

class SelectedVideo(TimestampMixin, Base):
    """
    A video the user chose to track. Stores the latest engagement numbers
    plus a description. Each (user, video) pair can be selected only once.
    """

    __tablename__ = "selected_video"

    selected_video_id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    video_id = Column(
        Integer,
        ForeignKey("videos.video_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Latest engagement counters (BigInteger: popular videos can exceed 2.1B views).
    likes = Column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    # NOTE: this is the comment COUNT (a number). The actual Comment rows
    # are available through the `comments_list` relationship below.
    comments = Column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    views = Column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    description = Column(
        String(800),
        nullable=True,
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

    user = relationship(
        "User",
        back_populates="selected_videos",
    )

    video = relationship(
        "Video",
        back_populates="selected_videos",
    )

    # Named `comments_list` to avoid clashing with the `comments` count column.
    comments_list = relationship(
        "Comment",
        back_populates="selected_video",
        cascade="all, delete",
        passive_deletes=True,
    )

    analytics = relationship(
        "Analytics",
        back_populates="selected_video",
        cascade="all, delete",
        passive_deletes=True,
    )

    # --------------------------------------------------------
    # Constraints
    # --------------------------------------------------------

    __table_args__ = (
        # The same user cannot select the same video twice.
        UniqueConstraint(
            "user_id",
            "video_id",
            name="uq_user_selected_video",
        ),
        # Engagement counters can never be negative.
        CheckConstraint("likes >= 0", name="ck_selected_video_likes_non_negative"),
        CheckConstraint("comments >= 0", name="ck_selected_video_comments_non_negative"),
        CheckConstraint("views >= 0", name="ck_selected_video_views_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<SelectedVideo id={self.selected_video_id} video_id={self.video_id}>"


# ============================================================
# COMMENT
# ============================================================

class Comment(TimestampMixin, Base):
    """
    A viewer comment on a selected video, together with the AI-generated
    reply (if one has been produced yet).
    """

    __tablename__ = "comments"

    comment_id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    selected_video_id = Column(
        Integer,
        ForeignKey(
            "selected_video.selected_video_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # The original viewer comment.
    comment_text = Column(
        String(800),
        nullable=False,
    )

    # The AI's reply. NULL means "no reply generated yet".
    ai_reply = Column(
        String(800),
        nullable=True,
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

    user = relationship(
        "User",
        back_populates="comments",
    )

    selected_video = relationship(
        "SelectedVideo",
        back_populates="comments_list",
    )

    def __repr__(self) -> str:
        return f"<Comment comment_id={self.comment_id} selected_video_id={self.selected_video_id}>"


# ============================================================
# ANALYTICS
# ============================================================

class Analytics(TimestampMixin, Base):
    """
    Engagement snapshot (likes / comments / views) of a selected video.
    Multiple rows per video are allowed so you can track growth over time
    (use `created_at` as the snapshot time).
    """

    __tablename__ = "analytics"

    analytics_id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    selected_video_id = Column(
        Integer,
        ForeignKey(
            "selected_video.selected_video_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    likes = Column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    comments = Column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    views = Column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

    user = relationship(
        "User",
        back_populates="analytics",
    )

    selected_video = relationship(
        "SelectedVideo",
        back_populates="analytics",
    )

    # --------------------------------------------------------
    # Constraints
    # --------------------------------------------------------

    __table_args__ = (
        CheckConstraint("likes >= 0", name="ck_analytics_likes_non_negative"),
        CheckConstraint("comments >= 0", name="ck_analytics_comments_non_negative"),
        CheckConstraint("views >= 0", name="ck_analytics_views_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<Analytics analytics_id={self.analytics_id} selected_video_id={self.selected_video_id}>"