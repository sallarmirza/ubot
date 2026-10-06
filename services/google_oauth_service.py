from urllib.parse import urlencode
import httpx
from core.config import settings
from schema.oauth_schema import GoogleOAuthError

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
    resp=httpx.post(
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

# fetch all channels of user
def fetch_my_channels(access_token: str) -> list[dict]:
    """list the YouTube channels owned by the logged-in Google account."""
    resp = httpx.get(
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