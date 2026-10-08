from datetime import datetime, timedelta, timezone
import logging

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.config import settings
from db_model import TargetChannel, TargetVideo, UserOAuth, Videos, YoutubeChannel
from schema.selection_video_schema import SelectedVideosRequest, VideoResponse
from services.http_clients import get_sync_http_client


YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_VIDEO_LIMIT = 5
MAX_VIDEO_LIMIT = 500
logger = logging.getLogger(__name__)

# Refresh the Google token this long BEFORE it actually expires, so a token
# that is about to expire is never used for a request.
TOKEN_EXPIRY_MARGIN = timedelta(minutes=1)


def _get_channel(db: Session, user_id: int, channel_id: str) -> YoutubeChannel:
	channel = (
		db.query(YoutubeChannel)
		.filter_by(user_id=user_id, youtube_channel_id=channel_id)
		.first()
	)
	if channel is None:
		raise HTTPException(status_code=404, detail="Channel not found")
	return channel


def _get_target_channel(
	db: Session, user_id: int, channel: YoutubeChannel
) -> TargetChannel:
	# Get-or-create: return the tracked channel, creating it on first use.
	target = (
		db.query(TargetChannel)
		.filter_by(user_id=user_id, channel_id=channel.channel_id)
		.first()
	)
	if target is None:
		target = TargetChannel(user_id=user_id, channel_id=channel.channel_id)
		db.add(target)
		# flush() assigns the new row an ID without committing the transaction.
		db.flush()
	return target


def _get_access_token(db: Session, user_id: int) -> str:
	oauth = db.query(UserOAuth).filter_by(user_id=user_id).first()
	if oauth is None:
		raise HTTPException(status_code=401, detail="Google account is not connected")

	# The DB stores naive UTC datetimes, so compare against a naive UTC "now".
	now = datetime.now(timezone.utc).replace(tzinfo=None)

	# Token is still valid for at least the safety margin: use it as is.
	if oauth.expires_at and oauth.expires_at > now + TOKEN_EXPIRY_MARGIN:
		return oauth.access_token
	# No expiry info and no way to refresh: nothing else we can do.
	if oauth.expires_at is None and not oauth.refresh_token:
		return oauth.access_token
	if not oauth.refresh_token:
		# We can't refresh, but the token may still be valid for a few seconds.
		if oauth.expires_at and oauth.expires_at > now:
			return oauth.access_token
		raise HTTPException(status_code=401, detail="Sign in to Google again")

	# Exchange the refresh token for a new access token.
	try:
		response = get_sync_http_client().post(
			TOKEN_URL,
			data={
				"client_id": settings.GOOGLE_CLIENT_ID,
				"client_secret": settings.GOOGLE_CLIENT_SECRET,
				"refresh_token": oauth.refresh_token,
				"grant_type": "refresh_token",
			},
			timeout=settings.YOUTUBE_REQUEST_TIMEOUT_SECONDS,
		)
	except httpx.RequestError as error:
		raise HTTPException(status_code=502, detail="Could not refresh Google access") from error

	if response.status_code != 200:
		raise HTTPException(status_code=401, detail="Sign in to Google again")

	token_data = response.json()
	oauth.access_token = token_data["access_token"]
	oauth.expires_at = now + timedelta(seconds=token_data.get("expires_in", 3600))
	db.commit()
	return oauth.access_token


def _youtube_get(access_token: str, path: str, params: dict) -> dict:
	try:
		response = get_sync_http_client().get(
			f"{YOUTUBE_API}/{path}",
			params=params,
			headers={"Authorization": f"Bearer {access_token}"},
			timeout=settings.YOUTUBE_REQUEST_TIMEOUT_SECONDS,
		)
	except httpx.RequestError as error:
		raise HTTPException(status_code=502, detail="Could not reach YouTube") from error

	if response.status_code != 200:
		raise HTTPException(status_code=502, detail="YouTube API request failed")
	return response.json()


def _count(statistics: dict, name: str) -> int:
	# YouTube returns counts as strings and omits some (e.g. hidden likes),
	# so convert safely and fall back to 0.
	try:
		return max(0, int(statistics.get(name, 0)))
	except (TypeError, ValueError):
		return 0


def _video_details(access_token: str, video_ids: list[str]) -> dict[str, dict]:
	details = {}
	# The videos endpoint accepts at most 50 IDs per request.
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
			description = snippet.get("description") or ""
			details[item["id"]] = {
				"youtube_video_id": item["id"],
				"title": snippet.get("title", "")[:255],
				"description": description[:800],
				"description_required": not description.strip(),
				"views": _count(statistics, "viewCount"),
				"likes": _count(statistics, "likeCount"),
				"comments": _count(statistics, "commentCount"),
			}
	return details


def _extract_channel_videos(
	access_token: str, channel_id: str, limit: int
) -> list[dict]:
	# Every channel has a hidden "uploads" playlist containing all its videos.
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

	# Stop paging once the requested number of uploads has been collected.
	while len(video_ids) < limit:
		params = {
			"part": "snippet,contentDetails",
			"playlistId": uploads_id,
			"maxResults": min(50, limit - len(video_ids)),
		}
		if next_page_token:
			params["pageToken"] = next_page_token

		page = _youtube_get(access_token, "playlistItems", params)
		for item in page.get("items", []):
			if len(video_ids) >= limit:
				break
			video_id = item.get("contentDetails", {}).get("videoId")
			if video_id:
				video_ids.append(video_id)

		next_page_token = page.get("nextPageToken")
		if not next_page_token or len(video_ids) >= limit:
			break

	details = _video_details(access_token, video_ids)
	# Keep the original playlist order, skipping videos with no details.
	return [details[video_id] for video_id in video_ids if video_id in details]


def _save_video_catalog(
	db: Session, user_id: int, target: TargetChannel, videos: list[dict]
) -> None:
	# Manual upsert: update the title if the video exists, otherwise create it.
	for video_data in videos:
		video = (
			db.query(Videos)
			.filter_by(
				user_id=user_id,
				target_channel_id=target.target_channel_id,
				youtube_video_id=video_data["youtube_video_id"],
			)
			.first()
		)
		if video is None:
			video = Videos(
				user_id=user_id,
				target_channel_id=target.target_channel_id,
				youtube_video_id=video_data["youtube_video_id"],
			)
			db.add(video)
		video.title = video_data["title"]


def _remove_deselected_videos(
	db: Session, user_id: int, target: TargetChannel, keep_youtube_ids: list[str]
) -> None:
	"""Delete selections for this channel that are NOT in keep_youtube_ids."""
	query = (
		db.query(TargetVideo)
		.join(Videos, TargetVideo.video_id == Videos.video_id)
		.filter(
			TargetVideo.user_id == user_id,
			Videos.target_channel_id == target.target_channel_id,
		)
	)
	# An empty keep-list means "deselect everything" for this channel.
	if keep_youtube_ids:
		query = query.filter(Videos.youtube_video_id.notin_(keep_youtube_ids))

	# Delete row by row (not a bulk delete) so ORM cascades still run.
	for selection in query.all():
		db.delete(selection)


def _cached_channel_videos(
	db: Session, user_id: int, channel: YoutubeChannel, limit: int
) -> list[VideoResponse]:
	"""Return an existing catalog without making the page render wait on Google."""
	target = (
		db.query(TargetChannel)
		.filter_by(user_id=user_id, channel_id=channel.channel_id)
		.first()
	)
	if target is None:
		return []

	videos = (
		db.query(Videos)
		.filter_by(user_id=user_id, target_channel_id=target.target_channel_id)
		.order_by(Videos.updated_at.desc(), Videos.video_id.desc())
		.limit(limit)
		.all()
	)
	if not videos:
		return []

	selected_by_video_id = {
		selection.video_id: selection
		for selection in db.query(TargetVideo)
		.filter_by(user_id=user_id)
		.filter(TargetVideo.video_id.in_([video.video_id for video in videos]))
		.all()
	}
	return [
		VideoResponse(
			youtube_video_id=video.youtube_video_id,
			title=video.title or "",
			description=(selected_by_video_id.get(video.video_id).description or "")
			if video.video_id in selected_by_video_id
			else "",
			views=(selected_by_video_id.get(video.video_id).views or 0)
			if video.video_id in selected_by_video_id
			else 0,
			likes=(selected_by_video_id.get(video.video_id).likes or 0)
			if video.video_id in selected_by_video_id
			else 0,
			comments=(selected_by_video_id.get(video.video_id).comments or 0)
			if video.video_id in selected_by_video_id
			else 0,
			selected=video.video_id in selected_by_video_id,
			description_required=False,
		)
		for video in videos
	]


def list_channel_videos(
	db: Session, user_id: int, channel_id: str, limit: int = DEFAULT_VIDEO_LIMIT
) -> list[VideoResponse]:
	channel = _get_channel(db, user_id, channel_id)
	cached_videos = _cached_channel_videos(db, user_id, channel, limit)
	if cached_videos:
		return cached_videos

	access_token = _get_access_token(db, user_id)
	videos = _extract_channel_videos(access_token, channel.youtube_channel_id, limit)
	target = _get_target_channel(db, user_id, channel)
	_save_video_catalog(db, user_id, target, videos)
	db.commit()

	# Find which of this channel's videos the user has already selected.
	selected_descriptions = {
		row.youtube_video_id: row.description
		for row in (
			db.query(Videos.youtube_video_id, TargetVideo.description)
			.join(TargetVideo, TargetVideo.video_id == Videos.video_id)
			.filter(
				Videos.target_channel_id == target.target_channel_id,
				TargetVideo.user_id == user_id,
			)
			.all()
		)
	}
	return [
		VideoResponse(
			**{
				**video,
				"description": (
					selected_descriptions[video["youtube_video_id"]]
					if video["youtube_video_id"] in selected_descriptions
					else video["description"]
				),
				"description_required": (
					not selected_descriptions[video["youtube_video_id"]]
					if video["youtube_video_id"] in selected_descriptions
					else video["description_required"]
				),
			},
			selected=video["youtube_video_id"] in selected_descriptions,
		)
		for video in videos
	]


def save_selected_videos(
	db: Session, user_id: int, payload: SelectedVideosRequest
) -> list[VideoResponse]:
	"""Replace this channel's monitored video with exactly one catalog video."""
	channel = _get_channel(db, user_id, payload.channel_id)

	youtube_ids = [video.youtube_video_id for video in payload.videos]
	if len(youtube_ids) != 1:
		raise HTTPException(
			status_code=422,
			detail="Select exactly one monitored video",
		)
	descriptions = {
		video.youtube_video_id: video.description for video in payload.videos
	}

	target = (
		db.query(TargetChannel)
		.filter_by(user_id=user_id, channel_id=channel.channel_id)
		.first()
	)
	if target is None:
		# Nothing was ever loaded, so there is nothing to select or deselect.
		if not youtube_ids:
			return []
		raise HTTPException(status_code=400, detail="Load channel videos before selecting")

	# Every requested video must already be in the local catalog.
	catalog = (
		db.query(Videos)
		.filter(
			Videos.user_id == user_id,
			Videos.target_channel_id == target.target_channel_id,
			Videos.youtube_video_id.in_(youtube_ids),
		)
		.all()
	)
	catalog_by_youtube_id = {video.youtube_video_id: video for video in catalog}
	if len(catalog_by_youtube_id) != len(youtube_ids):
		raise HTTPException(status_code=400, detail="Refresh videos before selecting")

	# The catalog was created by GET /selection-videos/{channel_id}.  Saving a
	# selection must remain a local database operation: calling YouTube again
	# here can delay the request or fail after the user has already chosen a
	# catalog video.
	_remove_deselected_videos(db, user_id, target, youtube_ids)

	saved_videos = []
	for youtube_video_id in youtube_ids:
		video = catalog_by_youtube_id[youtube_video_id]

		# Get-or-create the selection row. Existing metadata is preserved until
		# the next catalog/monitor refresh; a new selection starts at zero.
		selected = (
			db.query(TargetVideo)
			.filter_by(user_id=user_id, video_id=video.video_id)
			.first()
		)
		if selected is None:
			selected = TargetVideo(user_id=user_id, video_id=video.video_id)
			db.add(selected)

		description = descriptions[youtube_video_id]
		if description:
			selected.description = description
		elif selected.description is None:
			selected.description = ""

		saved_videos.append(
			VideoResponse(
				youtube_video_id=video.youtube_video_id,
				title=video.title or "",
				description=selected.description or "",
				views=selected.views or 0,
				likes=selected.likes or 0,
				comments=selected.comments or 0,
				selected=True,
				description_required=False,
			)
		)

	db.commit()
	logger.info(
		"Monitored video selected: user_id=%s youtube_channel_id=%s "
		"youtube_video_id=%s",
		user_id,
		channel.youtube_channel_id,
		youtube_ids[0],
	)
	return saved_videos
