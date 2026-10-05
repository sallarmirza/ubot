# repositories/auth_repository.py
from sqlalchemy.orm import Session
from db_model import User, UserOAuth, YoutubeChannel


def find_user_id_by_channel_ids(db: Session, youtube_channel_ids: list[str]) -> int | None:
    """Recognise a returning user: have we stored any of these channels before?
    (Swap this for a google_id lookup later if you add that column.)"""
    row = (
        db.query(YoutubeChannel.user_id)
        .filter(YoutubeChannel.youtube_channel_id.in_(youtube_channel_ids))
        .first()
    )
    return row[0] if row else None


def create_user(db: Session) -> User:
    """Insert a new user row for a first-time login."""
    user = User()
    db.add(user)
    db.flush()  # assigns user.user_id without committing
    return user


def upsert_oauth(db: Session, user_id, access_token, refresh_token, expires_at, scopes) -> None:
    """Insert or update this user's Google tokens (one row per user)."""
    oauth = db.query(UserOAuth).filter(UserOAuth.user_id == user_id).first()
    if oauth is None:
        oauth = UserOAuth(user_id=user_id)
        db.add(oauth)
    oauth.access_token = access_token
    if refresh_token:  # Google may omit it; keep the old one in that case
        oauth.refresh_token = refresh_token
    oauth.expires_at = expires_at
    oauth.scopes = scopes


def upsert_channels(db: Session, user_id: int, channels: list[dict]) -> None:
    """Insert new channels and refresh name/subscriber/view counts for existing ones."""
    for ch in channels:
        row = (
            db.query(YoutubeChannel)
            .filter_by(user_id=user_id, youtube_channel_id=ch["youtube_channel_id"])
            .first()
        )
        if row is None:
            row = YoutubeChannel(user_id=user_id, youtube_channel_id=ch["youtube_channel_id"])
            db.add(row)
        row.channel_name = ch["channel_name"]
        row.channel_subscribers = ch["channel_subscribers"]
        row.channel_views = ch["channel_views"]