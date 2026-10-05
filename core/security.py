
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Response

from core.config import settings

ALGORITHM = "HS256"
COOKIE_NAME = "access_token"


def create_access_token(user_id: int) -> str:
    """Sign a token holding only the user_id (sub) and an expiry time."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(days=settings.JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Return the user_id if the signature and expiry are valid, otherwise None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None


def set_auth_cookie(response: Response, token: str) -> None:
    """Store the JWT in an httpOnly cookie so React JS can't read or steal it."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.JWT_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Logout: remove the cookie from the browser."""
    response.delete_cookie(key=COOKIE_NAME, path="/")