from fastapi import HTTPException
from sqlalchemy.orm import Session

from db_model import PinnedVideo
from repositories import analytics_repo
from schema.pinned_analytics_schema import (
	PinnedAnalyticsResponse,
	PinnedComment,
	PinnedReply,
)
from services import coments_fetching_service, selection_video_service


def _reply(item: dict) -> PinnedReply:
	return PinnedReply(
		comment_id=item.get("youtube_comment_id", ""),
		author_name=item.get("author_name", ""),
		author_channel_id=item.get("author_channel_id"),
		text=item.get("text", ""),
		published_at=item.get("published_at", ""),
		like_count=item.get("like_count", 0),
	)


def _comment(item: dict) -> PinnedComment:
	return PinnedComment(
		**_reply(item).model_dump(),
		replies=[
			_reply(reply)
			for reply in item.get("replies", [])
			if isinstance(reply, dict)
		],
	)


def _has_channel_reply(comment: dict, channel_id: str) -> bool:
	return any(
		reply.get("author_channel_id") == channel_id
		for reply in comment.get("replies", [])
		if isinstance(reply, dict)
	)


def get_pin_status(db: Session, user_id: int) -> dict:
	pin = analytics_repo.get_pinned_video(db, user_id)
	if pin is None:
		return {
			"configured": False,
			"enabled": False,
			"channel_id": None,
			"video_id": None,
		}
	return {
		"configured": True,
		"enabled": pin.enabled,
		"channel_id": pin.youtube_channel_id,
		"video_id": pin.youtube_video_id,
	}


def configure_pin(
	db: Session, user_id: int, channel_id: str, video_id: str
) -> dict:
	"""Pin only a video already selected by this user."""
	selected_video = analytics_repo.get_selected_video(
		db, user_id, channel_id, video_id
	)
	if selected_video is None:
		raise HTTPException(status_code=404, detail="Selected video not found")
	pin = analytics_repo.save_pinned_video(db, user_id, channel_id, video_id)
	return {
		"configured": True,
		"enabled": pin.enabled,
		"channel_id": pin.youtube_channel_id,
		"video_id": pin.youtube_video_id,
	}


def set_pin_enabled(db: Session, user_id: int, enabled: bool) -> dict:
	pin = analytics_repo.get_pinned_video(db, user_id)
	if pin is None:
		raise HTTPException(status_code=404, detail="No pinned video is configured")
	pin = analytics_repo.set_pinned_video_enabled(db, pin, enabled)
	return {
		"configured": True,
		"enabled": pin.enabled,
		"channel_id": pin.youtube_channel_id,
		"video_id": pin.youtube_video_id,
	}


def get_pinned_analytics(
	db: Session,
	user_id: int,
	max_comments: int,
	max_replies: int,
) -> PinnedAnalyticsResponse:
	pin = analytics_repo.get_pinned_video(db, user_id)
	if pin is None or not pin.enabled:
		raise HTTPException(status_code=409, detail="No enabled pinned video")
	return _load_pinned_analytics(db, user_id, pin, max_comments, max_replies)


def get_public_pinned_analytics(
	db: Session, max_comments: int, max_replies: int
) -> PinnedAnalyticsResponse:
	pin = analytics_repo.get_latest_enabled_pinned_video(db)
	if pin is None:
		raise HTTPException(status_code=404, detail="No enabled pinned video")
	return _load_pinned_analytics(
		db, pin.user_id, pin, max_comments, max_replies
	)


def _load_pinned_analytics(
	db: Session,
	user_id: int,
	pin: PinnedVideo,
	max_comments: int,
	max_replies: int,
) -> PinnedAnalyticsResponse:
	selected_video = analytics_repo.get_selected_video(
		db, user_id, pin.youtube_channel_id, pin.youtube_video_id
	)
	if selected_video is None:
		raise HTTPException(
			status_code=404,
			detail="Pinned video is no longer selected; configure a selected video",
		)

	video = selected_video.video
	video_stats = selection_video_service.fetch_video_statistics(
		db, user_id, [pin.youtube_video_id]
	).get(pin.youtube_video_id)
	channel_stats = selection_video_service.fetch_channel_statistics(
		db, user_id, [pin.youtube_channel_id]
	).get(pin.youtube_channel_id)
	if video_stats is None:
		raise HTTPException(
			status_code=502, detail="YouTube did not return pinned-video statistics"
		)
	if channel_stats is None:
		raise HTTPException(
			status_code=502, detail="YouTube did not return pinned-channel statistics"
		)

	comments = coments_fetching_service.fetch_video_comments(
		db,
		user_id,
		pin.youtube_channel_id,
		pin.youtube_video_id,
		max_comments=max_comments,
		max_replies=max_replies,
	)
	top_level_comments = [
		comment for comment in comments
		if comment.get("author_channel_id") != pin.youtube_channel_id
	]
	replied_comments = [
		_comment(comment)
		for comment in top_level_comments
		if _has_channel_reply(comment, pin.youtube_channel_id)
	]
	unanswered_comments = [
		_comment(comment)
		for comment in top_level_comments
		if not _has_channel_reply(comment, pin.youtube_channel_id)
	]

	return PinnedAnalyticsResponse(
		channel_id=pin.youtube_channel_id,
		channel_name=channel_stats["channel_name"],
		channel_subscribers=channel_stats["channel_subscribers"],
		channel_total_videos=channel_stats["channel_video_count"],
		video_id=pin.youtube_video_id,
		video_title=video_stats["title"] or video.title,
		video_views=video_stats["views"],
		video_likes=video_stats["likes"],
		video_comment_count=video_stats["comments"],
		comments_fetched=len(top_level_comments),
		max_comments=max_comments,
		max_replies_per_comment=max_replies,
		replied_comments=replied_comments,
		unanswered_comments=unanswered_comments,
	)
