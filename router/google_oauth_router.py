import secrets
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
# import requests

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
    # TEMP debug: show what the callback request actually carries (remove later)
    print("HOST:", request.headers.get("host"))
    print("COOKIE HEADER:", request.headers.get("cookie"))
    print("URL:", request.url)

    frontend_page = settings.FRONTEND_URL

    def failed(reason: str) -> RedirectResponse:
        # Send the user back to the frontend with an error reason in the query string
        return RedirectResponse(f"{frontend_page}?error=oauth_failed&reason={reason}")

    # Validate the callback request before doing any token work
    saved_state = request.cookies.get(STATE_COOKIE)
    if error:
        return failed("provider_denied")
    if not code:
        return failed("missing_code")
    if not state:
        return failed("missing_state")
    if not saved_state:
        return failed("state_cookie_missing")
    if not secrets.compare_digest(state, saved_state):
        return failed("state_mismatch")

    # Exchange the code for tokens and save the user and channels
    try:
        user_id = auth_service.login_with_google(db, code)
    except GoogleOAuthError as exc:
        db.rollback()
        if str(exc).startswith("Token Exchange failed:"):
            return failed("token_exchange")
        if str(exc).startswith("Fetching channels failed:"):
            return failed("channel_fetch")
        return failed("no_youtube_channel")

    # Success: set the JWT on the returned response and clear the temporary state cookie
    response = RedirectResponse(frontend_page)
    set_auth_cookie(response, create_access_token(user_id))
    response.delete_cookie(STATE_COOKIE, path="/")
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