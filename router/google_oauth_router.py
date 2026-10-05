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
    failed = RedirectResponse(f"{settings.FRONTEND_URL}/login?error=oauth_failed")

    # Reject if the user denied access, or the state doesn't match our cookie
    saved_state = request.cookies.get(STATE_COOKIE)
    if error or not code or not state or state != saved_state:
        return failed

    try:
        user_id = auth_service.login_with_google(db, code)
    except GoogleOAuthError:
        db.rollback()
        return failed

    # Success: set the JWT on the same response we return, and clear the temporary state cookie
    response = RedirectResponse(f"{settings.FRONTEND_URL}/dashboard")
    set_auth_cookie(response, create_access_token(user_id))
    response.delete_cookie(STATE_COOKIE)
    return response

@router.get("/me")
def me(user: User = Depends(get_current_user)):
    """Front calls this on page load to check if the user is logged in."""
    return {"user_id": user.user_id}

@router.post("/logout")
def logout(response: Response):
    """Remove the JWT cookie."""
    clear_auth_cookie(response)
    return {"message": "logged out"}