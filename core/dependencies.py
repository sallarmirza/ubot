# core/dependencies.py
# FastAPI dependency for protected routes.
# Flow: read cookie -> decode JWT -> load the User from DB -> hand it to the route.
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session
from core.security import COOKIE_NAME, decode_access_token
from db_manager import db_manager 
from db_model import User

def get_current_user(
    access_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: Session = Depends(db_manager.get_db),) -> User:
    # No cookie: the user never logged in (or logged out)
    if not access_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    # Bad signature or expired token
    user_id = decode_access_token(access_token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    # Token was valid but the user row no longer exists
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    return user