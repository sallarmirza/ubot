from urllib.parse import urlencode

import logging
import httpx

from core.config import settings
from schema.oauth_schema import GoogleOAuthError
from services.http_clients import get_sync_http_client

# talk to google only 

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
]
logger = logging.getLogger(__name__)


def _log_channel_fetch_error(response: httpx.Response) -> None:
    """Log useful Google diagnostics without ever logging request credentials."""
    error = {}
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error", {})
    except ValueError:
        pass

    if not isinstance(error, dict):
        error = {}
    errors = error.get("errors")
    reason = (
        errors[0].get("reason")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict)
        else None
    )
    logger.error(
        "YouTube channel fetch failed: status=%s google_code=%s google_message=%s "
        "google_reason=%s body=%s",
        response.status_code,
        error.get("code"),
        error.get("message"),
        reason,
        response.text,
    )

# user routed to google pages
def build_login_url(state:str)->str:
    """ URL of Google's consent page the user is redirected to"""
    params={
        "client_id":settings.GOOGLE_CLIENT_ID,
        "redirect_uri":settings.GOOGLE_REDIRECT_URI,
        "response_type":"code",
        "scope":" ".join(SCOPES),
        "access_type":"offline",
        "prompt":"consent",
        "include_granted_scopes": "true",
        "state":state,
    }
    
    return f"{AUTH_URL}?{urlencode(params)}"

# get long term token 
def exchange_code_for_tokens(code:str)->dict:
    """exchange the one-time code for access_token and refresh_token"""
    try:
        resp=get_sync_http_client().post(
            TOKEN_URL,
            data={
                "code":code,
                "client_id":settings.GOOGLE_CLIENT_ID,
                "client_secret":settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri":settings.GOOGLE_REDIRECT_URI,
                "grant_type":"authorization_code",
            },
            timeout=15,
        )
    except httpx.RequestError as exc:
        logger.error("Google token exchange request failed: %s", exc)
        raise GoogleOAuthError("Token Exchange failed: network error") from exc
    if resp.status_code!=200:
        logger.error("Google token exchange failed: status=%s body=%s", resp.status_code, resp.text)
        raise GoogleOAuthError(f"Token Exchange failed:{resp.text}")
    try:
        tokens = resp.json()
    except ValueError as exc:
        logger.error("Google token exchange returned invalid JSON")
        raise GoogleOAuthError("Token Exchange failed: invalid response") from exc
    if not isinstance(tokens, dict):
        logger.error("Google token exchange returned an unexpected response type")
        raise GoogleOAuthError("Token Exchange failed: invalid response")
    return tokens

# fetch all channels of user
def fetch_my_channels(access_token: str) -> list[dict]:
    """list the YouTube channels owned by the logged-in Google account."""
    try:
        resp = get_sync_http_client().get(
            CHANNELS_URL,
            params={"part": "snippet,statistics", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
    except httpx.RequestError as exc:
        logger.error("YouTube channel fetch request failed: %s", exc)
        raise GoogleOAuthError("Fetching channels failed: network error") from exc
    if resp.status_code != 200:
        _log_channel_fetch_error(resp)
        raise GoogleOAuthError(f"Fetching channels failed: {resp.text}")

    try:
        payload = resp.json()
    except ValueError as exc:
        logger.error("YouTube channel fetch returned invalid JSON")
        raise GoogleOAuthError("Fetching channels failed: invalid response") from exc
    if not isinstance(payload, dict):
        logger.error("YouTube channel fetch returned an unexpected response type")
        raise GoogleOAuthError("Fetching channels failed: invalid response")

    # Convert Google's response into plain dicts matching our youtube_channel columns
    channels = []
    try:
        for item in payload.get("items", []):
            stats = item.get("statistics", {})
            channels.append(
                {
                    "youtube_channel_id": item["id"],
                    "channel_name": item["snippet"]["title"],
                    "channel_subscribers": int(stats.get("subscriberCount", 0)),
                    "channel_views": int(stats.get("viewCount", 0)),
                }
            )
    except (KeyError, TypeError, ValueError) as exc:
        logger.error("YouTube channel fetch returned an invalid channel payload")
        raise GoogleOAuthError("Fetching channels failed: invalid response") from exc
    return channels
