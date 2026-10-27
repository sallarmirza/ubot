from urllib.parse import urlencode

from core.config import settings
from schema.oauth_schema import GoogleOAuthError
from services.http_clients import get_sync_http_client

# talk to google only 

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
]



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
        "state":state,
    }
    
    return f"{AUTH_URL}?{urlencode(params)}"



# get long term token 
def exchange_code_for_tokens(code:str)->dict:
    """exchange the one-time code for access_token and refresh_token"""
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
    if resp.status_code!=200:
        raise GoogleOAuthError(f"Token Exchange failed:{resp.text}")
    return resp.json()


def revoke_token(token: str) -> None:
    """Revoke a Google OAuth grant using either its refresh or access token."""
    response = get_sync_http_client().post(
        REVOKE_URL,
        data={"token": token},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if response.status_code == 200:
        return

    try:
        error_code = response.json().get("error")
    except (AttributeError, ValueError):
        error_code = None
    if response.status_code == 400 and error_code == "invalid_token":
        # The grant is already unusable at Google, so local disconnect can proceed.
        return
    raise GoogleOAuthError("Google token revocation failed")




def fetch_google_subject(access_token: str) -> str:
    """Return the authenticated Google account's stable OpenID identifier."""
    resp = get_sync_http_client().get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        raise GoogleOAuthError(f"Google account identity failed: {resp.text}")

    subject = resp.json().get("sub")
    if not isinstance(subject, str) or not subject:
        raise GoogleOAuthError(
            "Google account identity failed: response did not include a subject"
        )
    return subject




# fetch all channels of user
def fetch_my_channels(access_token: str) -> list[dict]:
    """list the YouTube channels owned by the logged-in Google account."""
    resp = get_sync_http_client().get(
        CHANNELS_URL,
        params={"part": "snippet,statistics", "mine": "true"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        raise GoogleOAuthError(f"Fetching channels failed: {resp.text}")

    # Convert Google's response into plain dicts matching our youtube_channel columns
    channels = []
    for item in resp.json().get("items", []):
        stats = item.get("statistics", {})
        channels.append(
            {
                "youtube_channel_id": item["id"],
                "channel_name": item["snippet"]["title"],
                "channel_subscribers": int(stats.get("subscriberCount", 0)),
                "channel_views": int(stats.get("viewCount", 0)),
            }
        )
    return channels