import logging

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.config import settings
from repositories import ai_repo, coments_feching_repo
from services import ai_service
from services.http_clients import get_sync_http_client
from services.selection_video_service import YOUTUBE_API, _get_access_token


# Maximum number of top-level comments to fetch from a single video.
DEFAULT_MAX_COMMENTS = 50
# Initial Command Center loading never makes additional per-thread requests.
# commentThreads.list may include reply previews, but full reply pagination is
# deliberately deferred instead of blocking the primary comments response.
DEFAULT_MAX_REPLIES = 0
logger = logging.getLogger(__name__)


class _BearerAuth(httpx.Auth):
	def __init__(self, token: str):
		self.token = token

	def auth_flow(self, request: httpx.Request):
		request.headers["Authorization"] = f"Bearer {self.token}"
		yield request


def _youtube_get(access_token: str, endpoint: str, params: dict) -> dict:
	"""Call one YouTube endpoint and return its JSON response."""
	try:
		# Send a GET request to the YouTube Data API, authenticated with the
		# user's Google access token.
		response = get_sync_http_client().get(
			f"{YOUTUBE_API}/{endpoint}",
			auth=_BearerAuth(access_token),
			params=params,
			headers={"Authorization": f"Bearer {access_token}"},
			timeout=settings.YOUTUBE_REQUEST_TIMEOUT_SECONDS,
		)
	except httpx.RequestError as error:
		# Network problem (DNS failure, timeout, connection refused, etc.).
		logger.error("YouTube %s request failed: %s", endpoint, error)
		raise HTTPException(status_code=502, detail="Could not reach YouTube") from error

	if response.status_code != 200:
		# Extract diagnostics for server logs, while returning only safe messages.
		# The response body is from Google; no request credentials are logged.
		error_data = {}
		try:
			payload = response.json()
			if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
				error_data = payload["error"]
		except ValueError:
			pass
		errors = error_data.get("errors")
		reason = (
			errors[0].get("reason")
			if isinstance(errors, list) and errors and isinstance(errors[0], dict)
			else ""
		)
		logger.error(
			"YouTube %s failed: status=%s google_code=%s google_message=%s "
			"google_reason=%s body=%s",
			endpoint,
			response.status_code,
			error_data.get("code"),
			error_data.get("message"),
			reason,
			response.text[:1000],
		)

		# Give actionable client errors for known YouTube API outcomes.
		if reason == "commentsDisabled":
			raise HTTPException(status_code=422, detail="Comments are disabled for this video")
		if response.status_code == 401:
			raise HTTPException(status_code=401, detail="Sign in to Google again")
		if reason == "insufficientPermissions":
			raise HTTPException(
				status_code=403,
				detail="Google account lacks permission to read YouTube comments; sign in again and approve YouTube access",
			)
		if reason == "quotaExceeded":
			raise HTTPException(
				status_code=503,
				detail="YouTube quota is currently exhausted; try again later",
			)
		if reason == "videoNotFound":
			raise HTTPException(status_code=404, detail="YouTube video was not found")
		raise HTTPException(status_code=502, detail="YouTube could not return the comments")

	try:
		payload = response.json()
	except ValueError as error:
		logger.error("YouTube %s returned invalid JSON", endpoint)
		raise HTTPException(status_code=502, detail="YouTube returned an invalid response") from error
	if not isinstance(payload, dict):
		logger.error("YouTube %s returned an unexpected response type", endpoint)
		raise HTTPException(status_code=502, detail="YouTube returned an invalid response")
	return payload


def _format_comment(item: dict) -> dict:
	"""Keep the comment details needed by the test page."""
	snippet = item.get("snippet", {})

	# YouTube may return the like count as a string or omit it, so convert it
	# safely to a non-negative integer and fall back to 0 on bad data.
	try:
		like_count = max(0, int(snippet.get("likeCount", 0)))
	except (TypeError, ValueError):
		like_count = 0

	return {
		"youtube_comment_id": item.get("id", ""),
		"author_name": snippet.get("authorDisplayName", ""),
		# Truncate long comments to 800 characters (likely a DB column limit).
		"text": snippet.get("textDisplay", "")[:800],
		"published_at": snippet.get("publishedAt", ""),
		"like_count": like_count,
		# Replies are filled in later for top-level comments that have them.
		"replies": [],
	}


def _get_replies(access_token: str, parent_id: str, max_replies: int = DEFAULT_MAX_REPLIES) -> list[dict]:
	"""Fetch replies for one top-level comment, up to max_replies."""
	replies = []
	page_token = None

	# Keep requesting pages until we have enough replies or run out of pages.
	while len(replies) < max_replies:
		remaining = max_replies - len(replies)
		params = {
			"part": "snippet",
			"parentId": parent_id,
			# Only ask for as many as we still need (the API allows at most 100 per page).
			"maxResults": min(100, remaining),
			"textFormat": "plainText",
		}
		# On later pages, tell YouTube where to continue from.
		if page_token:
			params["pageToken"] = page_token

		page = _youtube_get(access_token, "comments", params)
		replies.extend(_format_comment(item) for item in page.get("items", []))

		# No next page token means there are no more replies to fetch.
		page_token = page.get("nextPageToken")
		if not page_token:
			break

	# Safety: never return more than the requested limit.
	return replies[:max_replies]


def _get_all_comments(
	access_token: str,
	video_id: str,
	max_comments: int = DEFAULT_MAX_COMMENTS,
	max_replies: int = DEFAULT_MAX_REPLIES,
) -> list[dict]:
	"""Fetch one bounded page of top-level comments for initial UI loading."""
	page = _youtube_get(
		access_token,
		"commentThreads",
		{
			"part": "snippet,replies",
			"videoId": video_id,
			"maxResults": min(100, max_comments),
			"textFormat": "plainText",
			"order": "time",
		},
	)
	comments = []
	for thread in page.get("items", [])[:max_comments]:
		if not isinstance(thread, dict):
			raise HTTPException(status_code=502, detail="YouTube returned an invalid comment response")
		thread_snippet = thread.get("snippet")
		if not isinstance(thread_snippet, dict):
			raise HTTPException(status_code=502, detail="YouTube returned an invalid comment response")
		top_level = thread_snippet.get("topLevelComment")
		if not isinstance(top_level, dict):
			raise HTTPException(status_code=502, detail="YouTube returned an invalid comment response")
		comment = _format_comment(top_level)

		# Reuse only the reply previews already supplied by commentThreads.list.
		# Do not issue one synchronous comments.list request per thread.
		replies_data = thread.get("replies")
		embedded = replies_data.get("comments", []) if isinstance(replies_data, dict) else []
		if not isinstance(embedded, list):
			embedded = []
		comment["replies"] = [
			_format_comment(reply)
			for reply in embedded[:max_replies]
			if isinstance(reply, dict)
		]
		comments.append(comment)
	return comments


def fetch_video_comments(
	db: Session,
	user_id: int,
	channel_id: str,
	video_id: str,
	max_comments: int = DEFAULT_MAX_COMMENTS,
	max_replies: int = DEFAULT_MAX_REPLIES,
) -> list[dict]:
	"""Fetch comments only for a video selected by this user's channel.

	max_comments: how many top-level comments to fetch (limit).
	max_replies: how many replies to fetch per comment (limit).
	"""
	try:
		# Verify ownership and selection before contacting YouTube. This ensures a
		# user can only fetch comments for videos they selected on their own channel.
		selected_video = ai_repo.get_selected_video(
			db, user_id, channel_id, video_id
		)
		if selected_video is None:
			raise HTTPException(status_code=404, detail="Selected video not found")

		# Get a valid Google access token (refreshed automatically if expired).
		access_token = _get_access_token(db, user_id)

		# Fetch first, then persist the complete top-level result for this selected video.
		comments = _get_all_comments(
			access_token,
			video_id,
			max_comments=max_comments,
			max_replies=max_replies,
		)

		coments_feching_repo.save_fetched_comments(
			db, selected_video.selected_video_id, comments
		)
		ai_service.attach_saved_reply_state(
			db, selected_video.selected_video_id, comments
		)
		db.commit()
		return comments
	except HTTPException:
		# Deliberate HTTP errors from auth, YouTube, ownership, and validation
		# retain their status/detail instead of being converted to a generic 500.
		raise
	except ValueError as error:
		db.rollback()
		raise HTTPException(status_code=422, detail=str(error)) from error
	except Exception as error:
		# This is intentionally the outer boundary: it records the complete
		# traceback server-side while never leaking database/provider internals.
		db.rollback()
		logger.exception(
			"Unexpected comments failure channel=%s video=%s",
			channel_id,
			video_id,
		)
		raise HTTPException(
			status_code=500,
			detail="Unable to load comments",
		) from error
