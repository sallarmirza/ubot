from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.config import settings
from db_model import UserOAuth
from repositories import selection_video_repo as repo
from schema.selection_video_schema import SelectedVideosRequest, VideoResponse


# Base URL of the YouTube Data API v3.
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
# Google's URL where we exchange a refresh_token for a new access_token.
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_VIDEO_LIMIT = 5
MAX_VIDEO_LIMIT = 5 #if the user has more than 500 videos, they can select the most recent 500

# How the tables connect (quick reminder):
#   YoutubeChannel -> TargetChannel (channel the user chose to manage)
#   TargetChannel  -> Videos        (catalog: ALL videos of that channel)
#   Videos         -> TargetVideo   (only the videos the user SELECTED)


# ---------------------------------------------------------------
# Google token handling
# ---------------------------------------------------------------

def _get_access_token(db: Session, user_id: int) -> str:
	"""Return a valid Google access token for this user.

	Logic:
	  1. If the saved token is still valid, use it.
	  2. If it expired, use the refresh_token to get a new one from Google.
	  3. If we cannot refresh, the user must sign in with Google again.
	"""
	oauth = db.query(UserOAuth).filter_by(user_id=user_id).first()
	if oauth is None:
		raise HTTPException(status_code=401, detail="Google account is not connected")

	# We store times in the DB without timezone info, so we remove tzinfo here
	# to be able to compare them.
	now = datetime.now(timezone.utc).replace(tzinfo=None)

	# Case 1: token is still valid, so just return it.
	if oauth.expires_at and oauth.expires_at > now:
		return oauth.access_token
	# Case 2: we have no expiry info and no refresh token, so we can only try
	# the saved token as it is.
	if oauth.expires_at is None and not oauth.refresh_token:
		return oauth.access_token
	# Case 3: token expired and there is no refresh token, so login again.
	if not oauth.refresh_token:
		raise HTTPException(status_code=401, detail="Sign in to Google again")

	# Token expired but we have a refresh token: ask Google for a new access token.
	try:
		response = httpx.post(
			TOKEN_URL,
			data={
				"client_id": settings.GOOGLE_CLIENT_ID,
				"client_secret": settings.GOOGLE_CLIENT_SECRET,
				"refresh_token": oauth.refresh_token,
				"grant_type": "refresh_token",
			},
			timeout=15,
		)
	except httpx.RequestError as error:
		# Network problem (Google not reachable).
		raise HTTPException(status_code=502, detail="Could not refresh Google access") from error

	if response.status_code != 200:
		# Google rejected the refresh token (revoked or invalid).
		raise HTTPException(status_code=401, detail="Sign in to Google again")

	# Save the new token and its expiry time (Google gives seconds, default 1 hour).
	token_data = response.json()
	oauth.access_token = token_data["access_token"]
	oauth.expires_at = now + timedelta(seconds=token_data.get("expires_in", 3600))
	db.commit()
	return oauth.access_token


# ---------------------------------------------------------------
# YouTube API helpers
# ---------------------------------------------------------------

def _youtube_get(access_token: str, path: str, params: dict) -> dict:
	"""Make one GET request to the YouTube API and return the JSON result.

	`path` is the endpoint name, e.g. "videos", "channels", "playlistItems".
	Any failure is converted into a 502 error for our own API users.
	"""
	try:
		response = httpx.get(
			f"{YOUTUBE_API}/{path}",
			params=params,
			headers={"Authorization": f"Bearer {access_token}"},
			timeout=20,
		)
	except httpx.RequestError as error:
		raise HTTPException(status_code=502, detail="Could not reach YouTube") from error

	if response.status_code != 200:
		raise HTTPException(status_code=502, detail="YouTube API request failed")
	return response.json()


def _count(statistics: dict, name: str) -> int:
	"""Safely read a number (views/likes/comments) from YouTube statistics.

	YouTube sends numbers as strings (e.g. "120"), and a field can be missing
	(for example when likes are hidden). In any bad case we return 0.
	"""
	try:
		return max(0, int(statistics.get(name, 0)))
	except (TypeError, ValueError):
		return 0


def _video_details(access_token: str, video_ids: list[str]) -> dict[str, dict]:
	"""Fetch title, description and stats for many videos.

	Returns a dict: {youtube_video_id: {details}}.
	YouTube allows at most 50 ids per request, so we send them in batches of 50.
	"""
	details = {}
	for start in range(0, len(video_ids), 50):
		batch = video_ids[start : start + 50]
		response = _youtube_get(
			access_token,
			"videos",
			{"part": "snippet,statistics", "id": ",".join(batch)},
		)
		for item in response.get("items", []):
			snippet = item.get("snippet", {})
			statistics = item.get("statistics", {})
			details[item["id"]] = {
				"youtube_video_id": item["id"],
				# Cut the text to fit our DB column sizes (255 and 800 characters).
				"title": snippet.get("title", "")[:255],
				"description": snippet.get("description", "")[:800],
				"views": _count(statistics, "viewCount"),
				"likes": _count(statistics, "likeCount"),
				"comments": _count(statistics, "commentCount"),
			}
	return details


def _extract_channel_videos(
	access_token: str, channel_id: str, limit: int = DEFAULT_VIDEO_LIMIT
) -> list[dict]:
	"""Get up to `limit` uploaded videos of a channel, with their details.

	Steps:
	  1. Ask YouTube for the channel's "uploads" playlist id.
	  2. Read playlist pages until we reach the requested limit.
	  3. Fetch full details for all collected ids.
	"""
	# Step 1: every channel has a hidden "uploads" playlist holding all its videos.
	channel_data = _youtube_get(
		access_token,
		"channels",
		{"part": "contentDetails", "id": channel_id},
	)
	channel_items = channel_data.get("items", [])
	if not channel_items:
		raise HTTPException(status_code=404, detail="YouTube channel not found")

	uploads_id = channel_items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
	video_ids = []
	next_page_token = None

	# Step 2: keep reading pages until YouTube stops giving a nextPageToken.
	while len(video_ids) < limit:
		page_size = min(50, limit - len(video_ids))
		params = {"part": "snippet,contentDetails", "playlistId": uploads_id, "maxResults": page_size}
		if next_page_token:
			params["pageToken"] = next_page_token

		page = _youtube_get(access_token, "playlistItems", params)
		for item in page.get("items", []):
			video_id = item.get("contentDetails", {}).get("videoId")
			if video_id:
				video_ids.append(video_id)

		next_page_token = page.get("nextPageToken")
		if not next_page_token or len(video_ids) >= limit:
			break

	# Step 3: get details, and keep the original playlist order
	# (skipping any video that YouTube did not return details for).
	details = _video_details(access_token, video_ids)
	return [details[video_id] for video_id in video_ids if video_id in details]


# ---------------------------------------------------------------
# Public functions (used by the router)
# ---------------------------------------------------------------

def list_channel_videos(
	db: Session, user_id: int, channel_id: str, limit: int = DEFAULT_VIDEO_LIMIT
) -> list[VideoResponse]:
	"""Return all videos of a channel and mark which ones the user selected.

	Flow:
	  1. Check the channel belongs to the user.
	  2. Get a valid Google token and download all videos from YouTube.
	  3. Save them in our catalog (`videos` table).
	  4. Find which videos are already selected, and build the response.
	"""
	channel = repo.get_user_channel(db, user_id, channel_id)
	if channel is None:
		raise HTTPException(status_code=404, detail="Channel not found")
	access_token = _get_access_token(db, user_id)
	videos = _extract_channel_videos(access_token, channel.youtube_channel_id, limit)
	target = repo.get_or_create_target_channel(db, user_id, channel)
	repo.save_video_catalog(db, user_id, target, videos)
	db.commit()

	# Build {youtube_video_id: saved_description} for videos the user selected.
	# The join connects the catalog (Videos) with the selected list (TargetVideo).
	selected_descriptions = repo.get_selected_video_descriptions(db, user_id, target)
	result = []
	for video in videos:
		video_id = video["youtube_video_id"]
		# A video is "selected" if it exists in the dict above.
		selected = video_id in selected_descriptions
		# Prefer the description we saved earlier (it may be written by the user);
		# otherwise use the one from YouTube.
		description = selected_descriptions.get(video_id) or video["description"]
		result.append(
			VideoResponse(
				**{**video, "description": description},
				selected=selected,
				# If the description is empty, the frontend must ask the user to type one.
				description_required=not bool(description.strip()),
			)
		)
	return result


def save_selected_videos(
	db: Session, user_id: int, payload: SelectedVideosRequest
) -> list[VideoResponse]:
	"""Save the videos the user selected (into the `target_video` table).

	Flow:
	  1. Validate the channel, the target and that videos exist in our catalog.
	  2. Fetch fresh stats/descriptions from YouTube.
	  3. If YouTube has no description, require a manual one from the user.
	  4. Insert or update each selected video, then commit once.
	"""
	channel = repo.get_user_channel(db, user_id, payload.channel_id)
	if channel is None:
		raise HTTPException(status_code=404, detail="Channel not found")
	# Nothing selected, so nothing to save.
	if not payload.videos:
		return []
	# {youtube_video_id: request_item}, which also removes duplicate ids.
	requested_videos = {video.youtube_video_id: video for video in payload.videos}
	video_ids = list(requested_videos)

	# The target channel must already exist (it is created when videos are listed).
	target = repo.get_target_channel(db, user_id, channel)
	if target is None:
		raise HTTPException(status_code=400, detail="Load channel videos before selecting")

	# Every selected video must already be in our catalog. This stops users from
	# selecting video ids that do not belong to this channel.
	catalog = repo.get_video_catalog(db, user_id, target, video_ids)
	catalog_by_youtube_id = {video.youtube_video_id: video for video in catalog}
	if len(catalog_by_youtube_id) != len(video_ids):
		raise HTTPException(status_code=400, detail="Refresh videos before selecting")

	# Get the latest data from YouTube, so views/likes are up to date.
	access_token = _get_access_token(db, user_id)
	details = _video_details(access_token, video_ids)
	if len(details) != len(video_ids):
		raise HTTPException(status_code=404, detail="One or more YouTube videos were not found")

	# Save the submitted full text, or use YouTube's text when the field is blank.
	for video_id in video_ids:
		manual_description = requested_videos[video_id].description.strip()
		youtube_description = details[video_id]["description"].strip()
		description = manual_description or youtube_description
		if not description:
			raise HTTPException(
				status_code=422,
				detail=f"Add a description for video {video_id}",
			)
		details[video_id]["description"] = description[:800]

	# Upsert: update the row if the video was selected before, otherwise create it.
	saved_videos = []
	for youtube_video_id in video_ids:
		video = catalog_by_youtube_id[youtube_video_id]
		video_data = details[youtube_video_id]
		repo.save_selected_video(db, user_id, video, video_data)
		saved_videos.append(
			VideoResponse(**video_data, selected=True, description_required=False)
		)

	# One commit at the end, so either all videos are saved or none.
		# (If something fails above, nothing is half-saved.)
	db.commit()
	return saved_videos