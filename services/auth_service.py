# services/auth_service.py
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from repositories import auth_repository as repo
from schema.oauth_schema import GoogleOAuthError
from services import google_oauth_service as google

# run the app flow logic 
def login_with_google(db: Session, code: str) -> tuple[int, str]:
    """Exchange a Google code and return the local user and primary channel IDs."""
    # 1. Swap the code for tokens, then ask Google which channels this account owns
    tokens = google.exchange_code_for_tokens(code)
    access_token = tokens.get("access_token")
    if not access_token:
        raise GoogleOAuthError("Token Exchange failed: missing access token")

    channels = google.fetch_my_channels(access_token)
    if not channels:
        raise GoogleOAuthError("No YouTube channel found on this Google account")

    # 2. Returning user -> reuse their user_id; new user -> create one
    user_id = repo.find_user_id_by_channel_ids(
        db, [c["youtube_channel_id"] for c in channels]
    )
    if user_id is None:
        user_id = repo.create_user(db).user_id

    # 3. Store tokens (expires_at as naive UTC, since SQLite DateTime has no timezone)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        seconds=tokens.get("expires_in", 3600)
    )
    repo.upsert_oauth(
        db,
        user_id=user_id,
        access_token=access_token,
        refresh_token=tokens.get("refresh_token"),
        expires_at=expires_at,
        scopes=tokens.get("scope"),
    )

    # 4. Store/refresh channels, then commit everything at once
    repo.upsert_channels(db, user_id, channels)
    db.commit()
    return user_id, channels[0]["youtube_channel_id"]
