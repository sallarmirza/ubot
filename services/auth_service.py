# services/auth_service.py
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from repositories import auth_repository as repo
from schema.oauth_schema import GoogleOAuthError
from services import google_oauth_service as google


# run the app flow logic
def login_with_google(db: Session, code: str) -> tuple[int, str]:
    """Exchange a Google code and return the local user and primary channel IDs."""
    # 1. Swap the code for tokens
    tokens = google.exchange_code_for_tokens(code)
    access_token = tokens.get("access_token")
    if not access_token:
        raise GoogleOAuthError("Token Exchange failed: missing access token")

    # 2. Ask Google who this account is (needs the 'openid' scope for "sub")
    profile = google.fetch_userinfo(access_token)
    google_sub = profile.get("sub")
    if not google_sub:
        raise GoogleOAuthError(
            "Google did not return a user id (is the 'openid' scope requested?)"
        )
    email = profile.get("email")

    # 3. Ask Google which channels this account owns
    channels = google.fetch_my_channels(access_token)
    if not channels:
        raise GoogleOAuthError("No YouTube channel found on this Google account")

    # 4. Returning user -> reuse them; new user -> create one
    user = repo.get_user_by_google_sub(db, google_sub)
    if user is None:
        user = repo.create_user(db, google_sub, email)
    elif email and user.email != email:
        user.email = email
    user_id = user.user_id

    # 5. Store tokens (timezone-aware UTC, matching DateTime(timezone=True))
    expires_at = datetime.now(timezone.utc) + timedelta(
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

    # 6. Store/refresh channels, then commit everything at once
    repo.upsert_channels(db, user_id, channels)
    db.commit()
    return user_id, channels[0]["youtube_channel_id"]