import secrets
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from core.config import settings
from core.dependencies import get_current_user
from core.security import clear_auth_cookie, create_access_token, set_auth_cookie
from db_manager import db_manager
from db_model import User
from schema.oauth_schema import GoogleOAuthError
from services import auth_service
from services import google_oauth_service as google

router=APIRouter(tags=["auth"])

STATE_COOKIE="oauth_state"

@router.get("/google/login")
def google_login():
    """login with google to give permission"""
    try:
        state=secrets.token_urlsafe(32)
        # redirect to google page
        response=RedirectResponse(google.build_login_url(state))
        response.set_cookie(
            STATE_COOKIE,
            state,
            max_age=600,
            httponly=True,
            samesite="lax",
            secure=settings.COOKIE_SECURE,
        )
        return response
    except:
        raise ValueError("Unable to perform action")

@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(db_manager.get_db),
):
    """Google sends the user back here: verify state, save tokens, set the JWT cookie."""
    frontend_url = settings.FRONTEND_URL.rstrip("/") if settings.FRONTEND_URL else str(request.base_url).rstrip("/")

    def failed(reason: str) -> RedirectResponse:
        return RedirectResponse(
            f"{frontend_url}/test-demo?{urlencode({'auth': 'failed', 'reason': reason})}"
        )

    saved_state = request.cookies.get(STATE_COOKIE)
    if error:
        return failed("access_denied" if error == "access_denied" else "provider_denied")
    if not code:
        return failed("missing_code")
    if not state:
        return failed("missing_state")
    if not saved_state:
        return failed("state_cookie_missing")
    if not secrets.compare_digest(state, saved_state):
        return failed("state_mismatch")

    try:
        user_id, channel_id = auth_service.login_with_google(db, code)
    except GoogleOAuthError as exc:
        db.rollback()
        if str(exc).startswith("Token Exchange failed:"):
            return failed("token_exchange")
        if str(exc).startswith("Fetching channels failed:"):
            return failed("channel_fetch")
        return failed("no_youtube_channel")

    # Success: set the JWT on the same response we return, and clear the temporary state cookie
    response = RedirectResponse(
        f"{frontend_url}/dashboard/{channel_id}?{urlencode({'auth': 'success'})}"
    )
    set_auth_cookie(response, create_access_token(user_id))
    response.delete_cookie(STATE_COOKIE)
    return response

@router.get("/me")
def me(user: User = Depends(get_current_user)):
    """Front calls this on page load to check if the user is logged in."""
    return {"user_id": user.user_id}

@router.get("/channels")
def channels(user: User = Depends(get_current_user)):
    """Return the signed-in user's saved YouTube channels."""
    return [
        {
            "youtube_channel_id": channel.youtube_channel_id,
            "channel_name": channel.channel_name,
            "channel_subscribers": channel.channel_subscribers,
            "channel_views": channel.channel_views,
        }
        for channel in user.youtube_channels
    ]

@router.post("/logout")
def logout(response: Response):
    """Remove the JWT cookie."""
    clear_auth_cookie(response)
    return {"message": "logged out"}
