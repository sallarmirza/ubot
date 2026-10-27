# repositories/auth_repository.py
from sqlalchemy.orm import Session
from db_model import (
    Analytics,
    BusinessSetup,
    Comments,
    TargetChannel,
    TargetVideo,
    User,
    UserOAuth,
    Videos,
    YoutubeChannel,
)


def find_user_id_by_google_subject(db: Session, google_subject: str) -> int | None:
    """Return the user associated with this stable Google account identifier."""
    row = (
        db.query(UserOAuth.user_id)
        .filter(UserOAuth.google_subject == google_subject)
        .first()
    )
    return row[0] if row else None


def create_user(db: Session) -> User:
    """Insert a new user row for a first-time login."""
    user = User()
    db.add(user)
    db.flush()  # assigns user.user_id without committing
    return user


def upsert_oauth(
    db: Session,
    user_id: int,
    google_subject: str,
    access_token: str,
    refresh_token: str | None,
    expires_at,
    scopes: str | None,
) -> None:
    """Insert or update this user's Google tokens (one row per user)."""
    oauth = db.query(UserOAuth).filter(UserOAuth.user_id == user_id).first()
    if oauth is None:
        oauth = UserOAuth(user_id=user_id)
        db.add(oauth)
    oauth.google_subject = google_subject
    oauth.access_token = access_token
    if refresh_token:  # Google may omit it; keep the old one in that case
        oauth.refresh_token = refresh_token
    oauth.expires_at = expires_at
    oauth.scopes = scopes


def is_comment_monitoring_enabled(db: Session, user_id: int) -> bool:
    """Return whether this user's automatic comment monitoring is enabled."""
    enabled = (
        db.query(UserOAuth.comment_monitoring_enabled)
        .filter_by(user_id=user_id)
        .scalar()
    )
    return bool(enabled)


def set_comment_monitoring_enabled(
    db: Session, user_id: int, enabled: bool
) -> None:
    """Pause or resume background comment monitoring for one account."""
    oauth = db.query(UserOAuth).filter_by(user_id=user_id).first()
    if oauth is not None:
        oauth.comment_monitoring_enabled = enabled


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


def delete_google_connection(db: Session, user_id: int) -> None:
    """Clear OAuth credentials and all channel-owned application data."""
    _delete_channel_data(db, user_id)
    oauth = db.query(UserOAuth).filter(UserOAuth.user_id == user_id).first()
    if oauth is not None:
        # Retain the stable Google subject so a later reconnect reuses this user.
        oauth.access_token = ""
        oauth.refresh_token = None
        oauth.expires_at = None
        oauth.scopes = None
        oauth.comment_monitoring_enabled = False


def delete_user_account(db: Session, user_id: int) -> None:
    """Delete all persisted application data owned by one user."""
    _delete_channel_data(db, user_id)
    db.query(UserOAuth).filter(UserOAuth.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.user_id == user_id).delete(
        synchronize_session=False
    )


def _delete_channel_data(db: Session, user_id: int) -> None:
    """Delete dependent rows in foreign-key order for a user's channels."""
    channel_ids = [
        row[0]
        for row in db.query(YoutubeChannel.channel_id)
        .filter(YoutubeChannel.user_id == user_id)
        .all()
    ]
    target_channel_ids = {
        row[0]
        for row in db.query(TargetChannel.target_channel_id)
        .filter(TargetChannel.user_id == user_id)
        .all()
    }
    if channel_ids:
        target_channel_ids.update(
            row[0]
            for row in db.query(TargetChannel.target_channel_id)
            .filter(TargetChannel.channel_id.in_(channel_ids))
            .all()
        )

    video_ids = {
        row[0]
        for row in db.query(Videos.video_id)
        .filter(Videos.user_id == user_id)
        .all()
    }
    if target_channel_ids:
        video_ids.update(
            row[0]
            for row in db.query(Videos.video_id)
            .filter(Videos.target_channel_id.in_(target_channel_ids))
            .all()
        )

    selected_video_ids = {
        row[0]
        for row in db.query(TargetVideo.selected_video_id)
        .filter(TargetVideo.user_id == user_id)
        .all()
    }
    if video_ids:
        selected_video_ids.update(
            row[0]
            for row in db.query(TargetVideo.selected_video_id)
            .filter(TargetVideo.video_id.in_(video_ids))
            .all()
        )

    if selected_video_ids:
        db.query(Comments).filter(
            Comments.selected_video_id.in_(selected_video_ids)
        ).delete(synchronize_session=False)
        db.query(Analytics).filter(
            Analytics.selected_video_id.in_(selected_video_ids)
        ).delete(synchronize_session=False)
    db.query(Analytics).filter(Analytics.user_id == user_id).delete(
        synchronize_session=False
    )

    db.query(TargetVideo).filter(TargetVideo.user_id == user_id).delete(
        synchronize_session=False
    )
    if video_ids:
        db.query(TargetVideo).filter(
            TargetVideo.video_id.in_(video_ids)
        ).delete(synchronize_session=False)

    db.query(BusinessSetup).filter(BusinessSetup.user_id == user_id).delete(
        synchronize_session=False
    )
    if target_channel_ids:
        db.query(BusinessSetup).filter(
            BusinessSetup.target_channel_id.in_(target_channel_ids)
        ).delete(synchronize_session=False)

    if video_ids:
        db.query(Videos).filter(Videos.video_id.in_(video_ids)).delete(
            synchronize_session=False
        )
    if target_channel_ids:
        db.query(TargetChannel).filter(
            TargetChannel.target_channel_id.in_(target_channel_ids)
        ).delete(synchronize_session=False)
    if channel_ids:
        db.query(YoutubeChannel).filter(
            YoutubeChannel.channel_id.in_(channel_ids)
        ).delete(synchronize_session=False)