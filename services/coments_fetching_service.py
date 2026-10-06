import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from repositories import ai_repo, coments_feching_repo
from services import ai_service
from services.selection_video_service import YOUTUBE_API, _get_access_token


# Maximum number of top-level comments to fetch from a single video.
DEFAULT_MAX_COMMENTS = 100
# Maximum number of replies to fetch for a single top-level comment.
DEFAULT_MAX_REPLIES = 50


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
		response = httpx.get(
			f"{YOUTUBE_API}/{endpoint}",
			auth=_BearerAuth(access_token),
			params=params,
			headers={"Authorization": f"Bearer {access_token}"},
			timeout=20,
		)
	except httpx.RequestError as error:
		# Network problem (DNS failure, timeout, connection refused, etc.).
		raise HTTPException(status_code=502, detail="Could not reach YouTube") from error

	if response.status_code != 200:
		# Try to extract YouTube's specific error reason from the response body,
		# e.g. "commentsDisabled". If the body isn't shaped as expected, ignore it.
		reason = ""
		try:
			reason = response.json()["error"]["errors"][0]["reason"]
		except (KeyError, IndexError, TypeError, ValueError):
			pass
		# Give a clearer error when the video owner has turned comments off.
		if reason == "commentsDisabled":
			raise HTTPException(status_code=422, detail="Comments are disabled for this video")
		# Any other YouTube failure becomes a generic 502.
		raise HTTPException(status_code=502, detail="YouTube could not return the comments")
	return response.json()


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
	"""Fetch top-level comments (and their replies) up to the given limits."""
	comments = []
	page_token = None

	# Keep requesting pages of comment threads until the limit is reached.
	while len(comments) < max_comments:
		remaining = max_comments - len(comments)
		params = {
			# "snippet" gives the top-level comment; "replies" gives a few
			# preview replies for each thread.
			"part": "snippet,replies",
			"videoId": video_id,
			# Only ask for as many as we still need (max 100 per page).
			"maxResults": min(100, remaining),
			"textFormat": "plainText",
			# Newest comments first.
			"order": "time",
		}
		if page_token:
			params["pageToken"] = page_token
		page = _youtube_get(access_token, "commentThreads", params)

		for thread in page.get("items", []):
			# Stop mid-page if we've already hit the limit.
			if len(comments) >= max_comments:
				break

			thread_snippet = thread.get("snippet", {})
			top_level = thread_snippet.get("topLevelComment", {})
			comment = _format_comment(top_level)

			parent_id = top_level.get("id", "")
			total_replies = thread_snippet.get("totalReplyCount", 0)

			# QUOTA SAVING: the commentThreads response already includes a few
			# replies (up to 5) for each thread, so reuse them for free.
			embedded = thread.get("replies", {}).get("comments", [])
			comment["replies"] = [_format_comment(r) for r in embedded][:max_replies]

			# Make the extra (quota-costing) replies request ONLY when:
			#  - we have a valid parent ID (an empty ID would make YouTube fail), and
			#  - the embedded replies are fewer than what we want and what exists.
			wanted = min(total_replies, max_replies)
			if parent_id and len(comment["replies"]) < wanted:
				comment["replies"] = _get_replies(
					access_token, parent_id, max_replies
				)
			comments.append(comment)

		# No next page token means there are no more comment threads.
		page_token = page.get("nextPageToken")
		if not page_token:
			break

	# Return only after the loop has finished, so every page is collected
	# (this was previously inside the loop and stopped after page one).
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

	# Save the fetched comments to the database. If the repository rejects the
	# data (ValueError), undo the transaction and return a 422 to the client.
	try:
		coments_feching_repo.save_fetched_comments(
			db, selected_video.selected_video_id, comments
		)
		ai_service.attach_saved_reply_state(
			db, selected_video.selected_video_id, comments
		)
		db.commit()
	except ValueError as error:
		db.rollback()
		raise HTTPException(status_code=422, detail=str(error)) from error

	return comments
