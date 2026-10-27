from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from db_model import Analytics, TargetVideo
from repositories import analytics_repo
from schema.analytics_schema import (
	AnalyticsComment,
	AnalyticsSnapshot,
	SelectedVideoAnalytics,
)
from services import selection_video_service


def _is_awaiting_reply(comment, channel_id: str) -> bool:
	return (
		bool(comment.author_channel_id)
		and comment.author_channel_id != channel_id
		and not comment.is_replied
		and comment.reply_status in {"draft", "failed"}
		and getattr(comment, "can_reply", None) is not False
		and any(
			character.isalnum()
			for character in (getattr(comment, "comment_text", "") or "")
		)
	)


def _refresh_selected_statistics(
	db: Session, user_id: int, selected_videos: list[TargetVideo]
) -> None:
	if not selected_videos:
		return

	# This fetch runs only when an analytics endpoint is requested.
	video_ids = [selected_video.video.youtube_video_id for selected_video in selected_videos]
	statistics_by_video_id = selection_video_service.fetch_video_statistics(
		db, user_id, video_ids
	)
	channels_by_id = {
		selected_video.video.target_channel.channel.youtube_channel_id:
		selected_video.video.target_channel.channel
		for selected_video in selected_videos
	}
	channel_statistics = selection_video_service.fetch_channel_statistics(
		db, user_id, list(channels_by_id)
	)
	selected_video_ids = [
		selected_video.selected_video_id for selected_video in selected_videos
	]
	latest_snapshots = analytics_repo.get_latest_analytics_snapshots(
		db, selected_video_ids
	)
	missing_video_ids = set(video_ids) - statistics_by_video_id.keys()
	if missing_video_ids:
		raise HTTPException(
			status_code=502,
			detail="YouTube did not return statistics for every selected video",
		)
	missing_channel_ids = channels_by_id.keys() - channel_statistics.keys()
	if missing_channel_ids:
		raise HTTPException(
			status_code=502,
			detail="YouTube did not return statistics for every selected channel",
		)

	refreshed_at = datetime.now(timezone.utc).replace(tzinfo=None)
	for channel_id, channel in channels_by_id.items():
		current_channel_stats = channel_statistics[channel_id]
		channel.channel_name = current_channel_stats["channel_name"]
		channel.channel_subscribers = current_channel_stats["channel_subscribers"]
		channel.channel_views = current_channel_stats["channel_views"]
		channel.updated_at = refreshed_at

	for selected_video in selected_videos:
		video_id = selected_video.video.youtube_video_id
		channel_id = selected_video.video.target_channel.channel.youtube_channel_id
		statistics = statistics_by_video_id[video_id]
		views = statistics["views"]
		likes = statistics["likes"]
		comments = statistics["comments"]
		selected_video.channel_name = channels_by_id[channel_id].channel_name
		selected_video.views = views
		selected_video.likes = likes
		selected_video.comments = comments
		selected_video.updated_at = refreshed_at

		previous_snapshot = latest_snapshots.get(selected_video.selected_video_id)
		if previous_snapshot is None:
			db.add(
				Analytics(
					user_id=user_id,
					selected_video_id=selected_video.selected_video_id,
					views=views,
					likes=likes,
					comments=comments,
				)
			)
		else:
			previous_snapshot.views = views
			previous_snapshot.likes = likes
			previous_snapshot.comments = comments

	db.commit()


def _build_video_analytics(db: Session, selected_video: TargetVideo) -> SelectedVideoAnalytics:
	video = selected_video.video
	target_channel = video.target_channel
	channel = target_channel.channel
	comments = analytics_repo.get_video_comments(db, selected_video.selected_video_id)
	history = analytics_repo.get_video_analytics(db, selected_video.selected_video_id)
	youtube_comment_ids = {
		comment.comment_id: comment.youtube_comment_id for comment in comments
	}
	awaiting_comments = [
		comment for comment in comments
		if _is_awaiting_reply(comment, channel.youtube_channel_id)
	]

	comment_rows = [
		AnalyticsComment(
			comment_id=comment.comment_id,
			youtube_comment_id=comment.youtube_comment_id,
			video_name=comment.video_name,
			parent_youtube_comment_id=youtube_comment_ids.get(
				comment.parent_comment_id
			),
			comment_text=comment.comment_text,
			ai_reply=comment.ai_reply,
			awaiting_reply=_is_awaiting_reply(
				comment, channel.youtube_channel_id
			),
			is_replied=comment.is_replied,
			youtube_reply_id=comment.youtube_reply_id,
			reply_status=comment.reply_status,
			created_at=comment.created_at,
			updated_at=comment.updated_at,
		)
		for comment in comments
	]
	top_level_comments = [
		comment for comment in comments if comment.parent_comment_id is None
	]

	return SelectedVideoAnalytics(
		selected_video_id=selected_video.selected_video_id,
		youtube_channel_id=channel.youtube_channel_id,
		channel_name=selected_video.channel_name or channel.channel_name,
		youtube_video_id=video.youtube_video_id,
		title=video.title,
		description=selected_video.description,
		prompt_context=selected_video.prompt_context,
		channel_subscribers=channel.channel_subscribers,
		channel_views=channel.channel_views,
		views=selected_video.views,
		likes=selected_video.likes,
		youtube_comment_count=selected_video.comments,
		saved_top_level_comments=len(top_level_comments),
		saved_replies=len(comments) - len(top_level_comments),
		awaiting_replies=len(awaiting_comments),
		generated_drafts=sum(bool(comment.ai_reply) for comment in comments),
		posted_replies=sum(comment.is_replied for comment in comments),
		uncertain_replies=sum(comment.reply_status == "unknown" for comment in comments),
		created_at=selected_video.created_at,
		updated_at=selected_video.updated_at,
		comments=comment_rows,
		history=[
			AnalyticsSnapshot(
				analytics_id=snapshot.analytics_id,
				views=snapshot.views,
				likes=snapshot.likes,
				comments=snapshot.comments,
				created_at=snapshot.created_at,
				updated_at=snapshot.updated_at,
			)
			for snapshot in history
		],
	)


def get_selected_video_analytics(
	db: Session, user_id: int
) -> list[SelectedVideoAnalytics]:
	"""Refresh and return detailed analytics for every video selected by this user."""
	selected_videos = analytics_repo.get_selected_videos(db, user_id)
	try:
		_refresh_selected_statistics(db, user_id, selected_videos)
	except Exception:
		db.rollback()
		raise
	return [_build_video_analytics(db, video) for video in selected_videos]


def get_video_analytics(
	db: Session, user_id: int, channel_id: str, video_id: str
) -> SelectedVideoAnalytics:
	"""Refresh and return analytics for one video selected by this user."""
	selected_video = analytics_repo.get_selected_video(
		db, user_id, channel_id, video_id
	)
	if selected_video is None:
		raise HTTPException(status_code=404, detail="Selected video not found")
	try:
		_refresh_selected_statistics(db, user_id, [selected_video])
	except Exception:
		db.rollback()
		raise
	return _build_video_analytics(db, selected_video)
